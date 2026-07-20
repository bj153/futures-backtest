"""
甲醇 MA 1小时线 — 模型训练+保存+预测模块
==========================================
用法:
    # 训练并保存模型
    python ma_model.py --train

    # 用已保存模型预测
    python ma_model.py --predict

    # 训练后直接预测
    python ma_model.py --train --predict
"""

import warnings, os, sys, json
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from tqsdk import TqApi, TqAuth
import lightgbm as lgb
import joblib
from datetime import datetime

# ============================================================
# 配置
# ============================================================

SYMBOL = 'KQ.m@CZCE.MA'
AUTH = TqAuth('bj153', 'baijing153')
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

MODEL_PATH = os.path.join(MODEL_DIR, 'ma_hourly_v3.pkl')
FEATURES_PATH = os.path.join(MODEL_DIR, 'ma_hourly_features.json')
THRESHOLD_PCTILE = 70  # 取预测值前30%才出信号（自适应）
THRESHOLD_FIXED = 0.001  # 固定阈值备选

SEEDS = [42, 73, 101, 257, 500]
LGB_PARAMS = {
    'n_estimators': 800,
    'learning_rate': 0.02,
    'num_leaves': 12,
    'max_depth': 5,
    'min_child_samples': 30,
    'subsample': 0.7,
    'colsample_bytree': 0.6,
    'reg_alpha': 0.2,
    'reg_lambda': 0.3,
    'min_split_gain': 0.003,
}

# ============================================================
# 特征工程
# ============================================================


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """构造特征 + 标签"""
    df = df.copy()

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

    # 标签：未来5根K线的绝对波动幅度（不赌方向）
    df['label_ret'] = df['close'].pct_change(5).shift(-5).abs()

    return df


def get_feature_cols(df: pd.DataFrame) -> list:
    """获取特征列列表"""
    exclude = ['time', 'datetime', 'id', 'label_ret', 'close', 'open', 'high', 'low',
               'volume', 'close_oi', 'open_oi', 'symbol', 'duration', 'ret_1']
    return [c for c in df.columns if c not in exclude and df[c].dtype in ('float64', 'int64')]


# ============================================================
# 训练
# ============================================================


def train():
    """拉数据 → 训练 → 保存模型"""
    print("📥 拉取数据...")
    api = TqApi(auth=AUTH)
    df = api.get_kline_serial(SYMBOL, 3600, 5000)
    api.close()

    df['time'] = pd.to_datetime(df['datetime'], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
    df = df.sort_values('time').reset_index(drop=True)
    print(f"   {len(df)} 根K线, {df['time'].min().strftime('%Y-%m-%d')} ~ {df['time'].max().strftime('%Y-%m-%d')}")

    print("🔧 构造特征...")
    df = build_features(df)
    feature_cols = get_feature_cols(df)

    df = df.dropna(subset=feature_cols + ['label_ret']).reset_index(drop=True)
    X = df[feature_cols].values
    y = df['label_ret'].values
    print(f"   训练集: {len(df)} 行, {len(feature_cols)} 个特征")

    print("🔧 训练集成模型...")
    models = []
    for seed in SEEDS:
        model = lgb.LGBMRegressor(
            **LGB_PARAMS, random_state=seed, verbosity=-1,
        )
        model.fit(X, y)
        models.append(model)

    joblib.dump({'models': models, 'feature_cols': feature_cols, 'seeds': SEEDS}, MODEL_PATH)
    with open(FEATURES_PATH, 'w') as f:
        json.dump(feature_cols, f)

    # 回测评估
    preds = np.mean([m.predict(X) for m in models], axis=0)
    mae = np.mean(np.abs(preds - y))
    direction_acc = ((preds > 0) == (y > 0)).mean()

    print(f"\n✅ 模型已保存: {MODEL_PATH}")
    print(f"   训练MAE: {mae:.6f}")
    print(f"   方向准确率: {direction_acc:.2%}")

    return models, feature_cols


# ============================================================
# 预测
# ============================================================


def get_adaptive_threshold(models, feature_cols):
    """动态计算阈值：基于最近1000根K线的预测值百分位"""
    api = TqApi(auth=AUTH)
    df = api.get_kline_serial(SYMBOL, 3600, 1200)
    api.close()
    
    df['time'] = pd.to_datetime(df['datetime'], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
    df = df.sort_values('time').reset_index(drop=True)
    df = build_features(df)
    df = df.dropna(subset=feature_cols).tail(1000)
    
    X = df[feature_cols].values
    preds = np.mean([m.predict(X) for m in models], axis=0)
    
    threshold = np.percentile(np.abs(preds), THRESHOLD_PCTILE)
    bias = np.median(preds)  # 偏多/偏空修正
    
    return threshold, bias


def predict():
    """加载模型 → 拉最新数据 → 输出信号"""
    if not os.path.exists(MODEL_PATH):
        print(f"❌ 模型不存在，请先运行 --train")
        return

    print("📦 加载模型...")
    data = joblib.load(MODEL_PATH)
    models = data['models']
    feature_cols = data['feature_cols']

    print("📥 拉取最新数据...")
    api = TqApi(auth=AUTH)
    df = api.get_kline_serial(SYMBOL, 3600, 100)
    api.close()

    df['time'] = pd.to_datetime(df['datetime'], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
    df = df.sort_values('time').reset_index(drop=True)

    df = build_features(df)
    df_latest = df.dropna(subset=feature_cols).tail(1)

    if df_latest.empty:
        print("❌ 最新K线特征不完整（数据不足）")
        return

    # 计算自适应阈值
    threshold, bias = get_adaptive_threshold(models, feature_cols)
    actual_threshold = max(threshold, THRESHOLD_FIXED)

    X = df_latest[feature_cols].values
    preds = np.mean([m.predict(X) for m in models], axis=0)
    pred_ret = preds[0]
    # 减去bias修正模型偏多/偏空倾向
    pred_ret_adj = pred_ret - bias

    current_time = df_latest['time'].iloc[0]
    current_price = df_latest['close'].iloc[0]

    print(f"\n{'='*55}")
    print(f"📊 甲醇 MA 波动预测 ({current_time.strftime('%Y-%m-%d %H:%M')})")
    print(f"{'='*55}")
    print(f"   当前价: {current_price:.0f}")
    print(f"   预测未来5K线波动: {pred_ret:.4%}")
    print(f"   历史波动中位数:   {bias:.4%}")
    print(f"   判定阈值:         {actual_threshold:.4%}")

    if pred_ret > actual_threshold:
        level = "🔥 高波动"
        confidence = min(pred_ret / actual_threshold, 3.0)
    else:
        level = "❄️ 低波动"
        confidence = 0

    print(f"   波动信号: {level}")
    print(f"   置信度:   {confidence:.2f}x")
    print(f"{'='*55}")

    return pred_ret, level, confidence


# ============================================================
# 批量预测（回放最近N根K线，看信号表现）
# ============================================================


def playback(n=100):
    """回放最近的K线，逐个预测看表现"""
    if not os.path.exists(MODEL_PATH):
        print(f"❌ 模型不存在")
        return

    data = joblib.load(MODEL_PATH)
    models = data['models']
    feature_cols = data['feature_cols']

    print(f"📥 拉取数据回放最近{n}根K线...")
    api = TqApi(auth=AUTH)
    df = api.get_kline_serial(SYMBOL, 3600, n + 200)
    api.close()

    df['time'] = pd.to_datetime(df['datetime'], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
    df = df.sort_values('time').reset_index(drop=True)
    df = build_features(df)
    df = df.dropna(subset=feature_cols).reset_index(drop=True)

    if len(df) < n:
        n = len(df)

    threshold, bias = get_adaptive_threshold(models, feature_cols)
    actual_threshold = max(threshold, THRESHOLD_FIXED)

    df_test = df.tail(n)
    X = df_test[feature_cols].values
    preds = np.mean([m.predict(X) for m in models], axis=0)
    preds_adj = preds - bias

    df_test = df_test.copy()
    df_test['pred_ret'] = preds
    df_test['pred_ret_adj'] = preds_adj

    print(f"\n📋 最近10根K线波动预测: (阈值: {actual_threshold:.4%})")
    print(f"{'时间':>16} {'收盘':>6} {'预测波动':>10} {'实际波动(后5K)':>14} {'判定':>6}")
    print("-" * 56)
    
    # 实际波动率（后5根K线的收益率绝对值）
    df_test['actual_future_vol'] = abs(df_test['close'].pct_change(5).shift(-5))
    
    for _, row in df_test.tail(10).iterrows():
        signal = '🔥' if row['pred_ret'] > actual_threshold else '❄️'
        print(f"{row['time'].strftime('%m/%d %H:%M'):>16} {row['close']:>6.0f} {row['pred_ret']:>9.2%} {row['actual_future_vol']:>13.2%} {signal}")

    signals = np.where(preds > actual_threshold, '高', '低')
    n_high = (signals == '高').sum()
    n_low = (signals == '低').sum()
    print(f"\n📊 最近{n}根K线分布:")
    print(f"   高波动预测: {n_high} ({n_high/len(signals):.1%})")
    print(f"   低波动预测: {n_low} ({n_low/len(signals):.1%})")

    return df_test


# ============================================================
# CLI
# ============================================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='甲醇MA 1小时线 模型')
    parser.add_argument('--train', action='store_true', help='训练模型')
    parser.add_argument('--predict', action='store_true', help='用已保存模型预测')
    parser.add_argument('--playback', type=int, default=0, help='回放最近N根K线')
    args = parser.parse_args()

    if args.train:
        train()
    if args.predict:
        predict()
    if args.playback:
        playback(args.playback)

    if not args.train and not args.predict and not args.playback:
        parser.print_help()
