"""
甲醇(MA) 1小时线 LightGBM 回测
=================================
数据源: 天勤 TQSdk (KQ.m@CZCE.MA)
周期: 1小时
策略: LightGBM 二分类预测未来1根K线涨跌
回测: 严格 walk-forward
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

print("🦞 甲醇 MA 1小时线 LightGBM 回测")
print("=" * 50)

print(f"📥 拉取 {SYMBOL} 1小时线数据...")
api = TqApi(auth=AUTH)
df = api.get_kline_serial(SYMBOL, 3600, 8000)  # 8000根1小时线 ≈ 2年+
api.close()

print(f"✅ 获取 {len(df)} 根1小时K线")

# 处理时间戳
import datetime
df['time'] = pd.to_datetime(df['datetime'], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
df = df.sort_values('time').reset_index(drop=True)

print(f"   时间范围: {df['time'].min()} ~ {df['time'].max()}")

# ============================================================
# 2. 特征工程
# ============================================================

print("🔧 构造特征...")

# 收益率
df['ret_1'] = df['close'].pct_change()
df['ret_5'] = df['close'].pct_change(5)
df['ret_10'] = df['close'].pct_change(10)

# 多空比
df['hl_pct'] = (df['high'] - df['low']) / df['close']

# 滞后价格
for lag in [1, 2, 3, 5, 10]:
    df[f'close_lag{lag}'] = df['close'].shift(lag)

# 滞后成交量
for lag in [1, 2, 3, 5, 10]:
    df[f'vol_lag{lag}'] = df['volume'].shift(lag)

# 成交量比
df['vol_ma10'] = df['volume'].rolling(10).mean()
df['vol_ratio'] = df['volume'] / df['vol_ma10'].replace(0, np.nan)

# 均线偏离
for w in [5, 10, 20, 40, 80]:
    ma = df['close'].rolling(w).mean()
    df[f'ma{w}_ratio'] = df['close'] / ma - 1

# 波动率
for w in [5, 10, 20]:
    df[f'volatility_{w}'] = df['ret_1'].rolling(w).std()

# RSI(14)
delta = df['close'].diff()
gain = delta.clip(lower=0).rolling(14).mean()
loss = (-delta.clip(upper=0)).rolling(14).mean()
rs = gain / loss.replace(0, np.nan)
df['rsi_14'] = 100 - (100 / (1 + rs))

# MACD
ema12 = df['close'].ewm(span=12, adjust=False).mean()
ema26 = df['close'].ewm(span=26, adjust=False).mean()
df['macd'] = ema12 - ema26
df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
df['macd_hist'] = df['macd'] - df['macd_signal']

# 布林带
bb_mid = df['close'].rolling(20).mean()
bb_std = df['close'].rolling(20).std()
df['bb_width'] = (bb_mid + 2 * bb_std - (bb_mid - 2 * bb_std)) / bb_mid
df['bb_position'] = (df['close'] - (bb_mid - 2 * bb_std)) / (4 * bb_std + 1e-10)

# 时间特征
df['hour'] = df['time'].dt.hour
df['weekday'] = df['time'].dt.weekday
df['month'] = df['time'].dt.month

# 持仓量
df['oi_change'] = df['close_oi'].pct_change(5)
df['oi_ratio'] = df['close_oi'] / df['close_oi'].rolling(20).mean()

# 标签：未来1根K线涨
df['label'] = (df['close'].shift(-1) > df['close']).astype(int)

# 特征列
exclude = ['time', 'datetime', 'id', 'label', 'close', 'open', 'high', 'low',
           'volume', 'open_oi', 'close_oi', 'symbol', 'duration', 'ret_1']
feature_cols = [c for c in df.columns if c not in exclude and df[c].dtype in ('float64', 'int64')]

print(f"   特征数: {len(feature_cols)}")

# ============================================================
# 3. 滚动回测
# ============================================================

print("\n📊 滚动回测 (walk-forward)...")

LGB_PARAMS = {
    'objective': 'binary',
    'metric': 'binary_logloss',
    'boosting_type': 'gbdt',
    'n_estimators': 1000,
    'learning_rate': 0.02,
    'num_leaves': 8,
    'max_depth': 4,
    'min_child_samples': 50,
    'subsample': 0.7,
    'colsample_bytree': 0.6,
    'reg_alpha': 0.5,
    'reg_lambda': 0.5,
    'min_split_gain': 0.01,
    'random_state': 42,
    'verbosity': -1,
}

TRAIN_SIZE = 3000   # 3000根K线训练
TEST_SIZE = 100     # 每次预测100根

results = []
feat_imps = []

df = df.dropna(subset=feature_cols + ['label']).reset_index(drop=True)

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
        callbacks=[lgb.early_stopping(15), lgb.log_evaluation(0)],
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

    # 累积特征重要性
    feat_imps.append(model.feature_importances_)

    if len(results) % 500 == 0:
        print(f"   已预测 {len(results)} 根K线...")

    start += TEST_SIZE

print(f"   完成！共预测 {len(results)} 根K线")

# ============================================================
# 4. 评估
# ============================================================

print("\n📊 评估结果:")
print("=" * 50)

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
sharpe = (result_df['strat_ret'].mean() / result_df['strat_ret'].std() * np.sqrt(244 * 6)
          if result_df['strat_ret'].std() > 0 else 0)  # 小时线，近似年化
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

# ============================================================
# 5. 特征重要性
# ============================================================

if feat_imps:
    avg_imp = np.mean(feat_imps, axis=0)
    imp_df = pd.DataFrame({'feature': feature_cols, 'importance': avg_imp})
    imp_df = imp_df.sort_values('importance', ascending=False)

    print(f"\n🔝 Top 20 特征重要性:")
    for _, row in imp_df.head(20).iterrows():
        print(f"   {row['feature']}: {row['importance']:.0f}")

print("\n✅ 完成！")
