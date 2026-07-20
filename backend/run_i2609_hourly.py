"""
i2609 铁矿石 近1月小时线回测（方向预测）
==========================================
回测目标: LightGBM 预测小时线涨跌方向
"""

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from tqsdk import TqApi, TqAuth
from sklearn.metrics import accuracy_score, roc_auc_score
import lightgbm as lgb

AUTH = TqAuth('bj153', 'baijing153')

print("🦞 i2609 铁矿石 近1月小时线方向回测")
print("=" * 55)

# 1. 拉数据
SYMBOL = 'KQ.m@DCE.i'
api = TqApi(auth=AUTH)
df = api.get_kline_serial(SYMBOL, 3600, 1500)
api.close()

df['time'] = pd.to_datetime(df['datetime'], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
df = df.sort_values('time').reset_index(drop=True)
print(f"📥 共 {len(df)} 根1小时K线")
print(f"   {df['time'].min().strftime('%Y-%m-%d')} ~ {df['time'].max().strftime('%Y-%m-%d')}")

# 2. 特征
df['ret_1'] = df['close'].pct_change()
df['ret_3'] = df['close'].pct_change(3)
df['ret_5'] = df['close'].pct_change(5)
df['ret_10'] = df['close'].pct_change(10)
df['hl_pct'] = (df['high'] - df['low']) / df['close']
df['accel'] = df['ret_1'].diff()

for lag in [1, 2, 3, 5, 10]:
    df[f'close_lag{lag}'] = df['close'].shift(lag)
for lag in [1, 3, 5, 10]:
    df[f'vol_lag{lag}'] = df['volume'].shift(lag)

df['vol_ma10'] = df['volume'].rolling(10).mean()
df['vol_ratio'] = df['volume'] / df['vol_ma10'].replace(0, np.nan)

for w in [5, 10, 20, 40]:
    ma = df['close'].rolling(w).mean()
    df[f'ma{w}_ratio'] = df['close'] / ma - 1
    df[f'ma{w}_slope'] = ma.pct_change(5)

for w in [5, 10, 20]:
    df[f'volatility_{w}'] = df['ret_1'].rolling(w).std()
    df[f'hl_ratio_{w}'] = (df['high'] - df['low']).rolling(w).mean() / df['close']

delta = df['close'].diff()
gain = delta.clip(lower=0).rolling(14).mean()
loss = (-delta.clip(upper=0)).rolling(14).mean()
df['rsi_14'] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

ema12 = df['close'].ewm(span=12, adjust=False).mean()
ema26 = df['close'].ewm(span=26, adjust=False).mean()
df['macd'] = ema12 - ema26
df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
df['macd_hist'] = df['macd'] - df['macd_signal']

bb_mid = df['close'].rolling(20).mean()
bb_std = df['close'].rolling(20).std()
df['bb_width'] = (bb_mid + 2 * bb_std - (bb_mid - 2 * bb_std)) / bb_mid
df['bb_position'] = (df['close'] - (bb_mid - 2 * bb_std)) / (4 * bb_std + 1e-10)

df['hour'] = df['time'].dt.hour
df['weekday'] = df['time'].dt.weekday

df['oi_change_5'] = df['close_oi'].pct_change(5)
df['oi_ratio'] = df['close_oi'] / df['close_oi'].rolling(20).mean().replace(0, np.nan)

# 标签：回归（未来5根收益率）+ 分类（方向）
df['label_ret'] = df['close'].pct_change(5).shift(-5)
df['label_dir'] = (df['label_ret'] > 0).astype(int)

exclude = ['time', 'datetime', 'id', 'label_ret', 'label_dir', 'close', 'open', 'high', 'low',
           'volume', 'close_oi', 'open_oi', 'symbol', 'duration', 'ret_1']
feature_cols = [c for c in df.columns if c not in exclude and df[c].dtype in ('float64', 'int64')]

df = df.dropna(subset=feature_cols + ['label_dir', 'label_ret']).reset_index(drop=True)
print(f"   特征: {len(feature_cols)} 个, 可用: {len(df)} 行")

# 3. 滚动回测
TRAIN_SIZE = 800
TEST_SIZE = 50
SEEDS = [42, 73, 101, 257, 500]

print(f"\n📊 walk-forward 方向回测...")

results = []

i = TRAIN_SIZE
while i + TEST_SIZE <= len(df):
    train = df.iloc[i - TRAIN_SIZE:i]
    test = df.iloc[i:i + TEST_SIZE]

    # 方向分类
    Xtr_c, ytr_c = train[feature_cols].values, train['label_dir'].values
    Xte = test[feature_cols].values

    pw = (len(ytr_c) - ytr_c.sum()) / (ytr_c.sum() + 1e-10)

    # 分类模型（方向）
    preds_list = []
    for seed in SEEDS:
        m = lgb.LGBMClassifier(
            n_estimators=500, learning_rate=0.02, num_leaves=8, max_depth=4,
            min_child_samples=30, subsample=0.7, colsample_bytree=0.6,
            reg_alpha=0.3, reg_lambda=0.5, min_split_gain=0.005,
            random_state=seed, verbosity=-1,
            class_weight={0: 1.0, 1: pw},
        )
        m.fit(Xtr_c, ytr_c)
        preds_list.append(m.predict_proba(Xte)[:, 1])

    prob = np.mean(preds_list, axis=0)

    # 回归模型（幅度）
    Xtr_r, ytr_r = train[feature_cols].values, train['label_ret'].values
    preds_r = []
    for seed in SEEDS:
        m = lgb.LGBMRegressor(
            n_estimators=500, learning_rate=0.02, num_leaves=8, max_depth=4,
            min_child_samples=30, subsample=0.7, colsample_bytree=0.6,
            reg_alpha=0.3, reg_lambda=0.5, min_split_gain=0.005,
            random_state=seed, verbosity=-1,
        )
        m.fit(Xtr_r, ytr_r)
        preds_r.append(m.predict(Xte))
    pred_ret = np.mean(preds_r, axis=0)

    for j in range(len(test)):
        results.append({
            'time': test['time'].iloc[j],
            'close': test['close'].iloc[j],
            'actual_dir': test['label_dir'].iloc[j],
            'prob': prob[j],
            'pred_ret': pred_ret[j],
            'actual_ret': test['label_ret'].iloc[j],
        })

    i += TEST_SIZE

result_df = pd.DataFrame(results)

# 只取最近1个月（约400根）
one_month_ago = result_df['time'].max() - pd.Timedelta(days=30)
result_df = result_df[result_df['time'] >= one_month_ago].reset_index(drop=True)
print(f"\n📅 严格近1个月: {result_df['time'].min().strftime('%Y-%m-%d')} ~ {result_df['time'].max().strftime('%Y-%m-%d')} ({len(result_df)}根K线)")

y_true = result_df['actual_dir'].values
y_prob = result_df['prob'].values
y_pred = (y_prob > 0.5).astype(int)

print(f"\n📊 分类评估:")
acc = accuracy_score(y_true, y_pred)
auc = roc_auc_score(y_true, y_prob) if len(np.unique(y_true)) > 1 else 0.5
print(f"   准确率: {acc:.4f}")
print(f"   AUC:    {auc:.4f}")

# 不同阈值测试
print(f"\n{'阈值':>8} {'信号数':>6} {'做多':>5} {'做空':>5} {'切换':>5} {'总收益':>10} {'夏普':>7} {'胜率':>6} {'回撤':>8}")
print("-" * 66)

for th in [0.0, 0.55, 0.58, 0.60, 0.62, 0.65]:
    pred = np.where(result_df['prob'] > th, 1,
            np.where(result_df['prob'] < (1 - th), 0, np.nan))
    mask = ~np.isnan(pred)
    if mask.sum() < 5:
        continue
    p = pred[mask].astype(int)

    # 用实际收益率算收益
    test_ret_vals = result_df['actual_ret'].values[mask]
    strat = np.where(p == 1, test_ret_vals, -test_ret_vals)

    total = float((1 + np.nan_to_num(strat)).prod() - 1)
    sharpe = strat.mean() / strat.std() * np.sqrt(244*6) if strat.std() > 1e-10 else 0
    win = (strat > 0).mean()
    cum = (1 + strat).cumprod()
    dd = float((cum / np.maximum.accumulate(cum) - 1).min()) if len(cum) > 1 else 0
    switches = int(np.sum(np.diff(p) != 0))
    longs = int((p == 1).sum())
    shorts = int((p == 0).sum())

    print(f"{th:>7.2f} {int(mask.sum()):>6} {longs:>5} {shorts:>5} {switches:>5} {total:>9.2%} {sharpe:>6.2f} {win:>5.2%} {dd:>7.2%}")

# 基准（双向）
bm_ret_vals = result_df['actual_ret'].values
bm_long = float((1 + np.nan_to_num(bm_ret_vals)).prod() - 1)
bm_short = float((1 - np.nan_to_num(bm_ret_vals)).prod() - 1)
print(f"\n📊 基准:")
start_p = result_df['close'].iloc[0]
end_p = result_df['close'].iloc[-1]
print(f"   起始价: {start_p:.0f} → 结束价: {end_p:.0f} ({(end_p-start_p)/start_p:.2%})")
print(f"   做多持有: {bm_long:.2%}")
print(f"   做空持有: {bm_short:.2%}")
print(f"   最佳单向: {max(bm_long, bm_short):.2%}")

# 看涨跌各半
half = len(bm_ret_vals) // 2
if half > 0:
    h_long = float((1 + np.nan_to_num(bm_ret_vals[:half])).prod() - 1)
    h_short = float((1 - np.nan_to_num(bm_ret_vals[half:])).prod() - 1)
    print(f"   半多半空: {((1+h_long)*(1+h_short)-1):.2%}")

print("\n✅ 完成！")
