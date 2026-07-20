"""
棕榈油 i2609 近1个月小时线回测
====================================
数据源: 天勤 TQSdk
用当前的波动率预测模型测试效果
"""

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from tqsdk import TqApi, TqAuth
import lightgbm as lgb

AUTH = TqAuth('bj153', 'baijing153')

print("🦞 i2609 棕榈油 近1月小时线回测")
print("=" * 55)

# 1. 拉数据
SYMBOL = 'KQ.m@DCE.p'  # 棕榈油主力连续（天勤代码小写p）
api = TqApi(auth=AUTH)
df = api.get_kline_serial(SYMBOL, 3600, 1500)
api.close()

df['time'] = pd.to_datetime(df['datetime'], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
df = df.sort_values('time').reset_index(drop=True)
print(f"📥 共 {len(df)} 根1小时K线")
print(f"   {df['time'].min().strftime('%Y-%m-%d')} ~ {df['time'].max().strftime('%Y-%m-%d')}")

# 2. 特征
df['ret_1'] = df['close'].pct_change()
df['ret_5'] = df['close'].pct_change(5)
df['hl_pct'] = (df['high'] - df['low']) / df['close']

for lag in [1, 2, 3, 5, 10]:
    df[f'close_lag{lag}'] = df['close'].shift(lag)
for lag in [1, 3, 5, 10]:
    df[f'vol_lag{lag}'] = df['volume'].shift(lag)

df['vol_ma10'] = df['volume'].rolling(10).mean()
df['vol_ratio'] = df['volume'] / df['vol_ma10'].replace(0, np.nan)

for w in [5, 10, 20]:
    ma = df['close'].rolling(w).mean()
    df[f'ma{w}_ratio'] = df['close'] / ma - 1
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

# 波动率标签
df['label'] = df['close'].pct_change(5).shift(-5).abs()

exclude = ['time', 'datetime', 'id', 'label', 'close', 'open', 'high', 'low',
           'volume', 'close_oi', 'open_oi', 'symbol', 'duration', 'ret_1']
feature_cols = [c for c in df.columns if c not in exclude and df[c].dtype in ('float64', 'int64')]

df = df.dropna(subset=feature_cols + ['label']).reset_index(drop=True)
print(f"   特征: {len(feature_cols)} 个, 可用: {len(df)} 行")

# 3. 滚动回测
TRAIN_SIZE = 800
TEST_SIZE = 50
SEEDS = [42, 73, 101, 257, 500]

print(f"\n📊 walk-forward 回测 (训练{len(df)}行中的最后{len(df)-TRAIN_SIZE}行)...")

results = []
pred_vols = []

i = TRAIN_SIZE
while i + TEST_SIZE <= len(df):
    train = df.iloc[i - TRAIN_SIZE:i]
    test = df.iloc[i:i + TEST_SIZE]

    Xtr, ytr = train[feature_cols].values, train['label'].values
    Xte = test[feature_cols].values

    p = (len(ytr) - ytr.sum()) / (ytr.sum() + 1e-10)
    preds_list = []
    for seed in SEEDS:
        m = lgb.LGBMRegressor(
            n_estimators=500, learning_rate=0.02, num_leaves=10, max_depth=4,
            min_child_samples=30, subsample=0.7, colsample_bytree=0.6,
            reg_alpha=0.2, reg_lambda=0.3, min_split_gain=0.003,
            random_state=seed, verbosity=-1,
        )
        m.fit(Xtr, ytr)
        preds_list.append(m.predict(Xte))

    pred = np.mean(preds_list, axis=0)
    pred_vols.extend(pred.tolist())

    for j in range(len(test)):
        results.append({
            'time': test['time'].iloc[j],
            'close': test['close'].iloc[j],
            'actual_vol': test['label'].iloc[j],
        })

    i += TEST_SIZE

result_df = pd.DataFrame(results)
result_df['pred_vol'] = pred_vols

# 4. 评估
actuals = result_df['actual_vol'].values
preds = result_df['pred_vol'].values
mae = np.mean(np.abs(preds - actuals))
median_vol = np.median(actuals)

print(f"\n📊 波动率预测评估:")
print(f"   MAE:           {mae:.4%}")
print(f"   预测均值:      {np.mean(preds):.4%}")
print(f"   实际波动均值:  {np.mean(actuals):.4%}")
print(f"   实际波动中位数: {median_vol:.4%}")
print(f"   R²:            {1 - np.sum((preds-actuals)**2)/np.sum((actuals-np.mean(actuals))**2):.4f}")

# 多阈值测试高波动预测准确率
print(f"\n{'阈值百分位':>8} {'阈值':>8} {'高波信号':>8} {'实际高波占比':>12} {'准确率':>8}")
print("-" * 48)
for pctile in [50, 60, 70, 80, 90]:
    th = np.percentile(preds, pctile)
    high_signal = preds >= th
    if high_signal.sum() == 0:
        continue
    actual_high = actuals >= np.percentile(actuals, pctile)
    acc = (high_signal == actual_high).mean()
    hit_rate = (actuals[high_signal] >= np.percentile(actuals, pctile)).mean()
    print(f"   P{pctile:>3}     {th:>7.4f} {high_signal.sum():>8} {actuals[high_signal].mean():>11.4%} {hit_rate:>7.2%}")

# 基准: 买入持有
ret_1k = result_df['close'].pct_change().values
bm_total = (1 + np.nan_to_num(ret_1k)).prod() - 1
print(f"\n📈 基准(买入持有): {bm_total:.2%}")

# 高波动时段做方向策略（用模型预测的涨跌方向）
result_df['ret_1k'] = ret_1k
th_pctile = np.percentile(preds, 70)
result_df['signal'] = np.where(preds >= th_pctile, 1, 0)
result_df['strat_ret'] = result_df['signal'] * result_df['ret_1k']
strat_total = (1 + np.nan_to_num(result_df['strat_ret'].values)).prod() - 1
print(f"   高波动做多策略: {strat_total:.2%}")

# 展示实际vs预测
print(f"\n📋 最近20根K线 预测波动 vs 实际波动:")
print(f"{'时间':>12} {'收盘':>6} {'预测波动':>10} {'实际波动':>10} {'判定':>6}")
print("-" * 48)
for _, row in result_df.tail(20).iterrows():
    label = '🔥高' if row['pred_vol'] >= th_pctile else '❄️低'
    print(f"{row['time'].strftime('%m/%d %H:%M'):>12} {row['close']:>6.0f} {row['pred_vol']:>9.2%} {row['actual_vol']:>9.2%} {label}")

print("\n✅ 完成！")
