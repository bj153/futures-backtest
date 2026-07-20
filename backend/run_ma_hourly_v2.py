"""
甲醇(MA) 1小时线 LightGBM 回测 v2 — 优化版
==============================================
优化点:
  1. 更低学习率(0.01) + 更多树(2000) + 更耐心早停(30)
  2. 预测未来3根K线均价方向（降噪）
  3. 加入夜盘/早盘时段特征
  4. 加入价格加速度(二阶导数)
  5. 加入更大周期均线(120, 240)
  6. 加入多空成交量比
"""

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from tqsdk import TqApi, TqAuth
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, roc_auc_score
import lightgbm as lgb

# ============================================================
# 1. 拉取数据
# ============================================================

SYMBOL = 'KQ.m@CZCE.MA'
AUTH = TqAuth('bj153', 'baijing153')

print("🦞 甲醇 MA 1小时线 LightGBM v2（优化版）")
print("=" * 55)

print(f"📥 拉取 {SYMBOL} 1小时线数据...")
api = TqApi(auth=AUTH)
df = api.get_kline_serial(SYMBOL, 3600, 10000)  # 更多数据
api.close()

print(f"✅ 获取 {len(df)} 根1小时K线")

df['time'] = pd.to_datetime(df['datetime'], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
df = df.sort_values('time').reset_index(drop=True)
print(f"   时间范围: {df['time'].min()} ~ {df['time'].max()}")

# ============================================================
# 2. 特征工程 v2
# ============================================================

print("🔧 构造特征 v2...")

# --- 基础收益率 ---
df['ret_1'] = df['close'].pct_change()
df['ret_3'] = df['close'].pct_change(3)
df['ret_5'] = df['close'].pct_change(5)
df['ret_10'] = df['close'].pct_change(10)
df['ret_20'] = df['close'].pct_change(20)

# --- 价格加速度(二阶导) ---
df['accel'] = df['ret_1'].diff()

# --- 多空波动比 ---
df['hl_pct'] = (df['high'] - df['low']) / df['close']

# --- 滞后价格(更多步长) ---
for lag in [1, 2, 3, 5, 10, 20]:
    df[f'close_lag{lag}'] = df['close'].shift(lag)

# --- 滞后成交量 ---
for lag in [1, 2, 3, 5, 10, 20]:
    df[f'vol_lag{lag}'] = df['volume'].shift(lag)

# --- 成交量比 & 多空量 ---
df['vol_ma10'] = df['volume'].rolling(10).mean()
df['vol_ma20'] = df['volume'].rolling(20).mean()
df['vol_ratio'] = df['volume'] / df['vol_ma10'].replace(0, np.nan)
df['vol_ratio_20'] = df['volume'] / df['vol_ma20'].replace(0, np.nan)

# 缩量/放量信号
df['vol_expand'] = (df['volume'] > df['vol_ma10'] * 1.5).astype(float)
df['vol_shrink'] = (df['volume'] < df['vol_ma10'] * 0.5).astype(float)

# --- 均线偏离(含大周期) ---
for w in [5, 10, 20, 40, 80, 120, 240]:
    ma = df['close'].rolling(w).mean()
    df[f'ma{w}_ratio'] = df['close'] / ma - 1

# 均线斜率
for w in [5, 10, 20, 60]:
    ma = df['close'].rolling(w).mean()
    df[f'ma{w}_slope'] = ma.pct_change(5)

# --- 波动率(多周期) ---
for w in [3, 5, 10, 20]:
    df[f'volatility_{w}'] = df['ret_1'].rolling(w).std()
    df[f'hl_ratio_{w}'] = (df['high'] - df['low']).rolling(w).mean() / df['close']

# --- RSI(周期多元) ---
for period in [7, 14, 21]:
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    df[f'rsi_{period}'] = 100 - (100 / (1 + rs))

# RSI 背离信号
df['rsi_14_slope'] = df['rsi_14'].diff(3)

# --- MACD ---
ema12 = df['close'].ewm(span=12, adjust=False).mean()
ema26 = df['close'].ewm(span=26, adjust=False).mean()
df['macd'] = ema12 - ema26
df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
df['macd_hist'] = df['macd'] - df['macd_signal']
df['macd_hist_slope'] = df['macd_hist'].diff(3)

# --- 布林带 ---
bb_mid = df['close'].rolling(20).mean()
bb_std = df['close'].rolling(20).std()
df['bb_width'] = (bb_mid + 2 * bb_std - (bb_mid - 2 * bb_std)) / bb_mid
df['bb_position'] = (df['close'] - (bb_mid - 2 * bb_std)) / (4 * bb_std + 1e-10)
df['bb_width_slope'] = df['bb_width'].diff(5)

# --- 时间特征(小时线精细版) ---
df['hour'] = df['time'].dt.hour
df['minute'] = df['time'].dt.minute
df['weekday'] = df['time'].dt.weekday
df['month'] = df['time'].dt.month

# 交易时段标识
# 夜盘: 21-23点, 早盘: 9-11:30, 午盘: 13:30-15点
df['session'] = 0  # 默认
df.loc[df['hour'].between(9, 11), 'session'] = 1      # 早盘
df.loc[df['hour'].between(13, 14), 'session'] = 2      # 午盘前
df.loc[(df['hour'] == 14) & (df['minute'] >= 30), 'session'] = 2  # 午盘后
# 15点是收盘
df.loc[df['hour'] == 15, 'session'] = 3                # 收盘
df.loc[df['hour'].between(21, 23), 'session'] = 4      # 夜盘
df.loc[df['hour'] == 23, 'session'] = 4                # 夜盘
# 0点凌晨那根归入夜盘尾巴
df.loc[df['hour'].between(0, 2), 'session'] = 5        # 凌晨

# 离收盘/开盘的K线数
df['session_progress'] = df.groupby(
    (df['session'] != df['session'].shift(1)).cumsum()
).cumcount() / 12  # 归一化，每12根K线约一个时段

# session one-hot
for s in range(1, 6):
    df[f'session_{s}'] = (df['session'] == s).astype(float)

# --- 持仓量 ---
df['oi_change_1'] = df['close_oi'].pct_change()
df['oi_change_5'] = df['close_oi'].pct_change(5)
df['oi_change_10'] = df['close_oi'].pct_change(10)
df['oi_ma20'] = df['close_oi'].rolling(20).mean()
df['oi_ratio'] = df['close_oi'] / df['oi_ma20'].replace(0, np.nan)

# --- 量价关系 ---
df['vp_corr'] = (
    df['ret_1'].rolling(20).corr(df['volume'])
)

# --- 标签: 未来3根均价方向(降噪) ---
df['label'] = (df['close'].shift(-3).rolling(3).mean() > df['close'].rolling(3).mean().shift(-1)).astype(int)

# 特征列
exclude = ['time', 'datetime', 'id', 'label', 'close', 'open', 'high', 'low',
           'volume', 'open_oi', 'close_oi', 'symbol', 'duration', 'ret_1']
feature_cols = [c for c in df.columns if c not in exclude and df[c].dtype in ('float64', 'int64')]

print(f"   特征数: {len(feature_cols)}")

# ============================================================
# 3. 滚动回测
# ============================================================

print("\n📊 滚动回测 (walk-forward, v2 优化参数)...")

LGB_PARAMS = {
    'objective': 'binary',
    'metric': 'binary_logloss',
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

TRAIN_SIZE = 4000
TEST_SIZE = 100

results = []
feat_imps = []

df = df.dropna(subset=feature_cols + ['label']).reset_index(drop=True)
print(f"   可用数据: {len(df)} 行")

start = TRAIN_SIZE
while start + TEST_SIZE <= len(df):
    train = df.iloc[start - TRAIN_SIZE:start]
    test = df.iloc[start:start + TEST_SIZE]

    X_train = train[feature_cols].values
    y_train = train['label'].values
    X_test = test[feature_cols].values
    y_test = test['label'].values

    pos_w = (len(y_train) - y_train.sum()) / (y_train.sum() + 1e-10)

    model = lgb.LGBMClassifier(**LGB_PARAMS, class_weight={0: 1.0, 1: pos_w})
    model.fit(
        X_train, y_train,
        eval_set=[(X_train, y_train), (X_test, y_test)],
        callbacks=[lgb.early_stopping(30), lgb.log_evaluation(0)],
    )

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    for i in range(len(test)):
        results.append({
            'time': test['time'].iloc[i],
            'close': test['close'].iloc[i],
            'actual': y_test[i],
            'pred': y_pred[i],
            'prob': y_prob[i],
        })

    feat_imps.append(model.feature_importances_)

    if len(results) % 500 == 0:
        best = model.best_iteration_
        print(f"   已预测 {len(results)} 根K线... (best_iter≈{best})")

    start += TEST_SIZE

print(f"   完成！共预测 {len(results)} 根K线")

# ============================================================
# 4. 评估
# ============================================================

print("\n📊 评估结果:")
print("=" * 55)

result_df = pd.DataFrame(results)
y_true = result_df['actual'].values
y_pred = result_df['pred'].values
y_prob = result_df['prob'].values

acc = accuracy_score(y_true, y_pred)
prec, rec, f1, _ = precision_recall_fscore_support(y_true, y_pred, average='binary')
auc = roc_auc_score(y_true, y_prob) if len(np.unique(y_true)) > 1 else 0.5

print(f"   准确率:     {acc:.4f}")
print(f"   精确率(涨): {prec:.4f}")
print(f"   召回率(涨): {rec:.4f}")
print(f"   F1:         {f1:.4f}")
print(f"   AUC:        {auc:.4f}")

# 模拟交易
result_df['daily_ret'] = result_df['close'].pct_change().shift(-1)
result_df['strat_ret'] = np.where(
    result_df['pred'] == 1,
    result_df['daily_ret'],
    np.where(result_df['pred'] == 0, -result_df['daily_ret'], 0),
)
result_df = result_df.dropna(subset=['daily_ret', 'strat_ret'])

cum_bm = (1 + result_df['daily_ret']).cumprod()
cum_strat = (1 + result_df['strat_ret']).cumprod()

total_ret = cum_strat.iloc[-1] - 1
bm_ret = cum_bm.iloc[-1] - 1
avg_trades_per_year = len(result_df) / ((result_df['time'].iloc[-1] - result_df['time'].iloc[0]).days / 365)

sharpe = (result_df['strat_ret'].mean() / result_df['strat_ret'].std() * np.sqrt(244 * 6)
          if result_df['strat_ret'].std() > 0 else 0)
win_rate = (result_df['strat_ret'] > 0).mean()
max_dd = (cum_strat / cum_strat.cummax() - 1).min()

print(f"\n   策略总收益:     {total_ret:.2%}")
print(f"   基准收益(持多): {bm_ret:.2%}")
print(f"   超额收益:       {total_ret - bm_ret:.2%}")
print(f"   夏普比率:       {sharpe:.3f}")
print(f"   胜率(每K线):   {win_rate:.2%}")
print(f"   最大回撤:       {max_dd:.2%}")

longs = (result_df['pred'] == 1).sum()
shorts = (result_df['pred'] == 0).sum()
signals = result_df['pred'].diff().fillna(0).abs().sum() / 2
print(f"   做多/做空:      {longs} / {shorts}")
print(f"   信号切换次数:   {int(signals)}")

# --- 分时段表现 ---
result_df['hour'] = result_df['time'].dt.hour
result_df['is_night'] = result_df['hour'].between(21, 23) | (result_df['hour'] <= 2)
night = result_df[result_df['is_night']]
day = result_df[~result_df['is_night']]

if len(night) > 0:
    print(f"\n📊 分时段:")
    print(f"   夜盘 胜率: { (night['pred'] == night['actual']).mean():.2%}  ({len(night)} 根)")
    print(f"   日盘 胜率: { (day['pred'] == day['actual']).mean():.2%}  ({len(day)} 根)")

# ============================================================
# 5. 特征重要性
# ============================================================

if feat_imps:
    avg_imp = np.mean(feat_imps, axis=0)
    imp_df = pd.DataFrame({'feature': feature_cols, 'importance': avg_imp})
    imp_df = imp_df.sort_values('importance', ascending=False)

    print(f"\n🔝 Top 25 特征重要性:")
    for _, row in imp_df.head(25).iterrows():
        print(f"   {row['feature']}: {row['importance']:.0f}")

print("\n✅ 完成！")
