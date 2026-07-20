"""
甲醇(MA) 1小时线 LightGBM 回测 v3 — 回归+阈值版
==============================================
思路: 用回归预测未来收益率，再设阈值过滤出信号
这样信号数天然可控，且置信度更直接
"""

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from tqsdk import TqApi, TqAuth
from sklearn.metrics import mean_absolute_error, r2_score
import lightgbm as lgb

# ============================================================
# 1. 数据
# ============================================================

SYMBOL = 'KQ.m@CZCE.MA'
AUTH = TqAuth('bj153', 'baijing153')

print("🦞 甲醇 MA 1小时线 LightGBM v3（回归+阈值）")
print("=" * 55)

print(f"📥 拉取 {SYMBOL} 1小时线数据...")
api = TqApi(auth=AUTH)
df = api.get_kline_serial(SYMBOL, 3600, 10000)
api.close()
print(f"✅ 获取 {len(df)} 根1小时K线")

df['time'] = pd.to_datetime(df['datetime'], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
df = df.sort_values('time').reset_index(drop=True)
print(f"   时间: {df['time'].min()} ~ {df['time'].max()}")

# ============================================================
# 2. 特征 + 标签（回归）
# ============================================================

print("🔧 构造特征...")

df['ret_1'] = df['close'].pct_change()
df['ret_3'] = df['close'].pct_change(3)
df['ret_5'] = df['close'].pct_change(5)
df['ret_10'] = df['close'].pct_change(10)
df['ret_20'] = df['close'].pct_change(20)
df['accel'] = df['ret_1'].diff()
df['hl_pct'] = (df['high'] - df['low']) / df['close']

for lag in [1, 2, 3, 5, 10, 20]:
    df[f'close_lag{lag}'] = df['close'].shift(lag)
for lag in [1, 3, 5, 10, 20]:
    df[f'vol_lag{lag}'] = df['volume'].shift(lag)

df['vol_ma10'] = df['volume'].rolling(10).mean()
df['vol_ma20'] = df['volume'].rolling(20).mean()
df['vol_ratio'] = df['volume'] / df['vol_ma10'].replace(0, np.nan)

for w in [5, 10, 20, 40, 80, 120]:
    ma = df['close'].rolling(w).mean()
    df[f'ma{w}_ratio'] = df['close'] / ma - 1
    df[f'ma{w}_slope'] = ma.pct_change(5)

for w in [5, 10, 20]:
    df[f'volatility_{w}'] = df['ret_1'].rolling(w).std()
    df[f'hl_ratio_{w}'] = (df['high'] - df['low']).rolling(w).mean() / df['close']

delta = df['close'].diff()
gain = delta.clip(lower=0).rolling(14).mean()
loss = (-delta.clip(upper=0)).rolling(14).mean()
rs = gain / loss.replace(0, np.nan)
df['rsi_14'] = 100 - (100 / (1 + rs))
df['rsi_14_slope'] = df['rsi_14'].diff(5)

ema12 = df['close'].ewm(span=12, adjust=False).mean()
ema26 = df['close'].ewm(span=26, adjust=False).mean()
df['macd'] = ema12 - ema26
df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
df['macd_hist'] = df['macd'] - df['macd_signal']
df['macd_hist_slope'] = df['macd_hist'].diff(5)

bb_mid = df['close'].rolling(20).mean()
bb_std = df['close'].rolling(20).std()
df['bb_width'] = (bb_mid + 2 * bb_std - (bb_mid - 2 * bb_std)) / bb_mid
df['bb_position'] = (df['close'] - (bb_mid - 2 * bb_std)) / (4 * bb_std + 1e-10)
df['bb_width_slope'] = df['bb_width'].diff(5)

df['hour'] = df['time'].dt.hour
df['weekday'] = df['time'].dt.weekday
df['session'] = np.where(df['hour'].between(21, 23), 4,
                np.where(df['hour'].between(0, 2), 5,
                np.where(df['hour'].between(9, 11), 1,
                np.where(df['hour'].between(13, 15), 2, 0))))

df['oi_change_5'] = df['close_oi'].pct_change(5)
df['oi_change_10'] = df['close_oi'].pct_change(10)
df['oi_ratio'] = df['close_oi'] / df['close_oi'].rolling(20).mean().replace(0, np.nan)

# --- 标签: 未来5根K线收益率（回归）---
df['label_ret'] = df['close'].pct_change(5).shift(-5)

# 同时也做二分类标签用于对比
df['label_cls'] = (df['label_ret'] > 0).astype(int)

exclude = ['time', 'datetime', 'id', 'label_ret', 'label_cls',
           'close', 'open', 'high', 'low', 'volume', 'close_oi', 'open_oi',
           'symbol', 'duration', 'ret_1']
feature_cols = [c for c in df.columns if c not in exclude and df[c].dtype in ('float64', 'int64')]

print(f"   特征数: {len(feature_cols)}, 标签: 未来5K线收益率")

# ============================================================
# 3. 滚动回测（回归 + 阈值过滤）
# ============================================================

print("\n📊 滚动回测 (回归+阈值, walk-forward)")

TRAIN_SIZE = 4000
TEST_SIZE = 100
THRESHOLD = 0.0015  # 收益率阈值: |预测收益| > 0.15% 才交易

results = []
feat_imps = []

df = df.dropna(subset=feature_cols + ['label_ret']).reset_index(drop=True)

params = {
    'objective': 'regression',
    'metric': 'mae',
    'boosting_type': 'gbdt',
    'n_estimators': 2000,
    'learning_rate': 0.01,
    'num_leaves': 12,
    'max_depth': 5,
    'min_child_samples': 50,
    'subsample': 0.7,
    'colsample_bytree': 0.6,
    'reg_alpha': 0.3,
    'reg_lambda': 0.5,
    'min_split_gain': 0.005,
    'random_state': 42,
    'verbosity': -1,
}

start = TRAIN_SIZE
while start + TEST_SIZE <= len(df):
    train = df.iloc[start - TRAIN_SIZE:start]
    test = df.iloc[start:start + TEST_SIZE]

    X_train = train[feature_cols].values
    y_train = train['label_ret'].values
    X_test = test[feature_cols].values

    model = lgb.LGBMRegressor(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_train, y_train), (X_test, test['label_ret'].values)],
        callbacks=[lgb.early_stopping(20), lgb.log_evaluation(0)],
    )

    y_pred = model.predict(X_test)

    for i in range(len(test)):
        results.append({
            'time': test['time'].iloc[i],
            'close': test['close'].iloc[i],
            'actual_ret': test['label_ret'].iloc[i],
            'pred_ret': y_pred[i],
        })

    feat_imps.append(model.feature_importances_)

    if len(results) % 500 == 0:
        print(f"   已预测 {len(results)} 根K线...")

    start += TEST_SIZE

print(f"   完成！共预测 {len(results)} 根K线")

# ============================================================
# 4. 评估（不同阈值对比）
# ============================================================

result_df = pd.DataFrame(results)

# 回归指标
mae = mean_absolute_error(result_df['actual_ret'], result_df['pred_ret'])
r2 = r2_score(result_df['actual_ret'], result_df['pred_ret'])
print(f"\n📊 回归评估:")
print(f"   MAE:      {mae:.6f}")
print(f"   R²:       {r2:.4f}")
print(f"   预测均值: {result_df['pred_ret'].mean():.4%}")
print(f"   实际均值: {result_df['actual_ret'].mean():.4%}")

# 模拟交易
result_df['ret_1k'] = result_df['close'].pct_change().shift(-1)  # 单K线收益率

print(f"\n{'阈值':>10} {'信号数':>8} {'切换':>8} {'总收益':>12} {'夏普':>8} {'胜率':>8} {'最大回撤':>10}")
print("-" * 66)

best_threshold = 0
best_sharpe = -999
best_result = None

# 多阈值测试
for threshold in [0.0, 0.0005, 0.001, 0.0015, 0.002, 0.0025, 0.003, 0.004, 0.005]:
    preds = np.where(result_df['pred_ret'] > threshold, 1,
            np.where(result_df['pred_ret'] < -threshold, 0, np.nan))
    mask = ~np.isnan(preds)
    if mask.sum() < 20:
        continue

    preds_clean = preds[mask].astype(int)
    rets_clean = result_df['ret_1k'].values[mask]

    strat = np.where(preds_clean == 1, rets_clean, -rets_clean)

    total = float(np.nan_to_num((1 + np.nan_to_num(strat)).prod(), nan=1)) - 1
    sharpe = strat.mean() / strat.std() * np.sqrt(244*6) if strat.std() > 1e-10 else 0
    win = (strat > 0).mean()
    cum = (1 + strat).cumprod()
    dd = (cum / np.maximum.accumulate(cum) - 1).min()
    switches = int(np.sum(np.diff(preds_clean) != 0))

    print(f"{threshold:>9.4f} {int(mask.sum()):>8} {switches:>8} {total:>11.2%} {sharpe:>7.2f} {win:>7.2%} {dd:>9.2%}")

    if sharpe > best_sharpe:
        best_sharpe = sharpe
        best_threshold = threshold
        best_result = (total, sharpe, win, dd, int(mask.sum()), switches)

if best_result:
    print(f"\n🏆 最佳阈值: {best_threshold:.4f}")
    print(f"   信号数: {best_result[4]}, 切换: {best_result[5]}")
    print(f"   总收益: {best_result[0]:.2%}, 夏普: {best_result[1]:.2f}")
    print(f"   胜率: {best_result[2]:.2%}, 最大回撤: {best_result[3]:.2%}")

# --- 特征重要性 ---
if feat_imps:
    avg_imp = np.mean(feat_imps, axis=0)
    imp_df = pd.DataFrame({'feature': feature_cols, 'importance': avg_imp})
    imp_df = imp_df.sort_values('importance', ascending=False)
    print(f"\n🔝 Top 20 特征重要性:")
    for _, row in imp_df.head(20).iterrows():
        print(f"   {row['feature']}: {row['importance']:.0f}")

print("\n✅ 完成！")
