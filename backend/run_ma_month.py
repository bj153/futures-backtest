"""
甲醇 MA 1小时线 — 最近1个月快速回测
==========================================
只用最近约30天的数据训练+回测
评估在近期行情中的实际表现
"""

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from tqsdk import TqApi, TqAuth
import lightgbm as lgb
from datetime import datetime, timedelta

AUTH = TqAuth('bj153', 'baijing153')

print("🦞 甲醇 MA — 最近1个月小时线回测")
print("=" * 50)

# 要拉 2 个月的数据保证有足够训练集
print("📥 拉取近2个月数据...")
api = TqApi(auth=AUTH)
df = api.get_kline_serial('KQ.m@CZCE.MA', 3600, 1500)
api.close()

df['time'] = pd.to_datetime(df['datetime'], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
df = df.sort_values('time').reset_index(drop=True)
print(f"✅ {len(df)} 根K线, {df['time'].min().strftime('%Y-%m-%d')} ~ {df['time'].max().strftime('%Y-%m-%d')}")

# === 特征 ===
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

# 持仓量
df['oi_change_5'] = df['close_oi'].pct_change(5)
df['oi_ratio'] = df['close_oi'] / df['close_oi'].rolling(20).mean().replace(0, np.nan)

# 标签
df['label_ret'] = df['close'].pct_change(5).shift(-5)

exclude = ['time', 'datetime', 'id', 'label_ret', 'close', 'open', 'high', 'low',
           'volume', 'close_oi', 'open_oi', 'symbol', 'duration', 'ret_1']
feature_cols = [c for c in df.columns if c not in exclude and df[c].dtype in ('float64', 'int64')]

df = df.dropna(subset=feature_cols + ['label_ret']).reset_index(drop=True)
print(f"可用行: {len(df)}, 特征: {len(feature_cols)}")

# === 划分: 前80%训练, 后20%测试(约最后1周) ===
mid = int(len(df) * 0.8)
train = df.iloc[:mid]
test = df.iloc[mid:]

print(f"\n📅 训练: {train['time'].min().strftime('%m/%d')} ~ {train['time'].max().strftime('%m/%d')} ({len(train)}根)")
print(f"📅 测试: {test['time'].min().strftime('%m/%d')} ~ {test['time'].max().strftime('%m/%d')} ({len(test)}根)")

X_train, y_train = train[feature_cols].values, train['label_ret'].values
X_test, y_test = test[feature_cols].values, test['label_ret'].values

# === 训练 5 个模型做集成 ===
print("\n🔧 训练5个模型做集成...")
models = []
for seed in [42, 73, 101, 257, 500]:
    model = lgb.LGBMRegressor(
        n_estimators=500, learning_rate=0.02, num_leaves=10, max_depth=4,
        min_child_samples=30, subsample=0.7, colsample_bytree=0.6,
        reg_alpha=0.3, reg_lambda=0.5, min_split_gain=0.005,
        random_state=seed, verbosity=-1,
    )
    model.fit(X_train, y_train)
    models.append(model)

# 集成预测（均值）
test_preds = np.mean([m.predict(X_test) for m in models], axis=0)
train_preds = np.mean([m.predict(X_train) for m in models], axis=0)

# === 评估 ===
print("\n📊 回测结果:")
print(f"{'阈值':>8} {'信号':>6} {'做多':>5} {'做空':>5} {'切换':>5} {'收益':>10} {'夏普':>7} {'胜率':>6} {'回撤':>8}")
print("-" * 65)

rets = test['close'].values
ret_1k = np.diff(rets) / rets[:-1]

for th in [0.0, 0.0005, 0.001, 0.0015, 0.002, 0.0025, 0.003]:
    pred = np.where(test_preds[:-1] > th, 1, np.where(test_preds[:-1] < -th, 0, np.nan))
    mask = ~np.isnan(pred)
    if mask.sum() < 5:
        continue
    p_clean = pred[mask].astype(int)
    r_clean = ret_1k[mask]
    strat = np.where(p_clean == 1, r_clean, -r_clean)
    total = float((1 + np.nan_to_num(strat)).prod() - 1)
    sharpe = strat.mean() / strat.std() * np.sqrt(244*6) if strat.std() > 1e-10 else 0
    win = (strat > 0).mean()
    cum = (1 + strat).cumprod()
    dd = float((cum / np.maximum.accumulate(cum) - 1).min()) if len(cum) > 1 else 0
    switches = int(np.sum(np.diff(p_clean) != 0))
    longs = int((p_clean == 1).sum())
    shorts = int((p_clean == 0).sum())
    print(f"{th:>7.4f} {int(mask.sum()):>6} {longs:>5} {shorts:>5} {switches:>5} {total:>9.2%} {sharpe:>6.2f} {win:>5.2%} {dd:>7.2%}")

# === 基准对比 ===
# 买入持有
bm_rets = ret_1k
bm_total = float((1 + bm_rets).prod() - 1)
bm_sharpe = bm_rets.mean() / bm_rets.std() * np.sqrt(244*6) if bm_rets.std() > 1e-10 else 0
print(f"\n📊 基准(买入持有): 收益={bm_total:.2%}  夏普={bm_sharpe:.2f}")

# 打印实际走势
start_price = test['close'].iloc[0]
end_price = test['close'].iloc[-1]
print(f"   起始价: {start_price:.0f} → 结束价: {end_price:.0f} ({(end_price-start_price)/start_price:.2%})")

print("\n✅ 完成！")
