"""
统一实验入口 run_experiment.py
================================
整合 backend/ 下 7 个一次性实验脚本（run_ma_hourly*.py / run_i2609_hourly*.py /
run_palm_hourly.py / run_ma_month.py）为单一 CLI 入口。

各原脚本对应策略变体（--strategy / 子命令）:
  cls1      ← run_ma_hourly.py            二分类(未来1根K线涨跌), 单模型+早停
  cls2      ← run_ma_hourly_v2.py         二分类(未来3根均价方向), 增强特征/参数
  reg3      ← run_ma_hourly_v3.py         回归(未来5根收益率) + 收益率阈值扫描
  ens-dir   ← run_i2609_hourly.py         5种子集成 分类概率+回归幅度, 概率阈值扫描
  ens-dir-f ← run_i2609_hourly_filter.py  同上 + MA20动量过滤
  vol       ← run_palm_hourly.py          波动率回归(|未来5根收益|) + 百分位评估
  quick     ← run_ma_month.py             80/20 切分 + 5种子集成回归 + 阈值扫描

所有策略的计算逻辑与原脚本逐一对应，仅把合约/周期/数据量/窗口/阈值等
抽为命令行参数；不改任何默认参数的语义（默认值即原脚本硬编码值）。

用法示例:
  python run_experiment.py cls1
  python run_experiment.py cls2 --symbol KQ.m@CZCE.MA --bars 10000
  python run_experiment.py ens-dir --symbol KQ.m@DCE.i --recent-days 30
  python run_experiment.py ens-dir-f --symbol KQ.m@DCE.i
  python run_experiment.py vol --symbol KQ.m@DCE.p
  python run_experiment.py quick --symbol KQ.m@CZCE.MA
"""

import argparse
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd

ANNUALIZE = 244 * 6  # 小时线近似年化因子（各原脚本一致）


# ============================================================
# 公共工具
# ============================================================

def fetch_klines(symbol, duration, bars, auth):
    """拉取K线并按时间排序（所有原脚本一致的数据获取逻辑）"""
    from tqsdk import TqApi
    print(f"📥 拉取 {symbol} {duration}s K线 x{bars}...")
    api = TqApi(auth=auth)
    df = api.get_kline_serial(symbol, duration, bars)
    api.close()
    print(f"✅ 获取 {len(df)} 根K线")
    df['time'] = pd.to_datetime(df['datetime'], unit='ns', utc=True).dt.tz_convert('Asia/Shanghai')
    df = df.sort_values('time').reset_index(drop=True)
    print(f"   时间范围: {df['time'].min()} ~ {df['time'].max()}")
    return df


def parse_seeds(s):
    return [int(x) for x in s.split(',')]


def parse_floats(s):
    return [float(x) for x in s.split(',')]


def make_auth(args):
    from tqsdk import TqAuth
    return TqAuth(args.tq_user, args.tq_pass)


def pick_features(df, exclude):
    return [c for c in df.columns if c not in exclude and df[c].dtype in ('float64', 'int64')]


def sweep_threshold_rows(result_df, prob_col, ret_col, thresholds, annualize=ANNUALIZE):
    """概率阈值扫描（ens-dir 风格），打印表格行"""
    for th in thresholds:
        pred = np.where(result_df[prob_col] > th, 1,
                np.where(result_df[prob_col] < (1 - th), 0, np.nan))
        mask = ~np.isnan(pred)
        if mask.sum() < 5:
            continue
        p = pred[mask].astype(int)
        rets = result_df[ret_col].values[mask]
        strat = np.where(p == 1, rets, -rets)
        total = float((1 + np.nan_to_num(strat)).prod() - 1)
        sharpe = strat.mean() / strat.std() * np.sqrt(annualize) if strat.std() > 1e-10 else 0
        win = (strat > 0).mean()
        cum = (1 + strat).cumprod()
        dd = float((cum / np.maximum.accumulate(cum) - 1).min()) if len(cum) > 1 else 0
        switches = int(np.sum(np.diff(p) != 0))
        longs = int((p == 1).sum())
        shorts = int((p == 0).sum())
        print(f"{th:>7.2f} {int(mask.sum()):>6} {longs:>5} {shorts:>5} {switches:>5} "
              f"{total:>9.2%} {sharpe:>6.2f} {win:>5.2%} {dd:>7.2%}")


def print_benchmark(result_df, ret_col):
    """基准输出（ens-dir / ens-dir-f 共用）"""
    bm_ret_vals = result_df[ret_col].values
    bm_long = float((1 + np.nan_to_num(bm_ret_vals)).prod() - 1)
    bm_short = float((1 - np.nan_to_num(bm_ret_vals)).prod() - 1)
    print(f"\n📊 基准:")
    start_p = result_df['close'].iloc[0]
    end_p = result_df['close'].iloc[-1]
    print(f"   起始价: {start_p:.0f} → 结束价: {end_p:.0f} ({(end_p-start_p)/start_p:.2%})")
    print(f"   做多持有: {bm_long:.2%}")
    print(f"   做空持有: {bm_short:.2%}")
    half = len(bm_ret_vals) // 2
    if half > 0:
        h_long = float((1 + np.nan_to_num(bm_ret_vals[:half])).prod() - 1)
        h_short = float((1 - np.nan_to_num(bm_ret_vals[half:])).prod() - 1)
        print(f"   半多半空: {((1+h_long)*(1+h_short)-1):.2%}")


# ============================================================
# 特征工程（按原脚本逐版保留）
# ============================================================

def features_v1(df):
    """run_ma_hourly.py 的特征"""
    df['ret_1'] = df['close'].pct_change()
    df['ret_5'] = df['close'].pct_change(5)
    df['ret_10'] = df['close'].pct_change(10)
    df['hl_pct'] = (df['high'] - df['low']) / df['close']
    for lag in [1, 2, 3, 5, 10]:
        df[f'close_lag{lag}'] = df['close'].shift(lag)
    for lag in [1, 2, 3, 5, 10]:
        df[f'vol_lag{lag}'] = df['volume'].shift(lag)
    df['vol_ma10'] = df['volume'].rolling(10).mean()
    df['vol_ratio'] = df['volume'] / df['vol_ma10'].replace(0, np.nan)
    for w in [5, 10, 20, 40, 80]:
        ma = df['close'].rolling(w).mean()
        df[f'ma{w}_ratio'] = df['close'] / ma - 1
    for w in [5, 10, 20]:
        df[f'volatility_{w}'] = df['ret_1'].rolling(w).std()
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi_14'] = 100 - (100 / (1 + rs))
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
    df['month'] = df['time'].dt.month
    df['oi_change'] = df['close_oi'].pct_change(5)
    df['oi_ratio'] = df['close_oi'] / df['close_oi'].rolling(20).mean()
    return df


def features_v2(df):
    """run_ma_hourly_v2.py 的特征（增强版）"""
    df['ret_1'] = df['close'].pct_change()
    df['ret_3'] = df['close'].pct_change(3)
    df['ret_5'] = df['close'].pct_change(5)
    df['ret_10'] = df['close'].pct_change(10)
    df['ret_20'] = df['close'].pct_change(20)
    df['accel'] = df['ret_1'].diff()
    df['hl_pct'] = (df['high'] - df['low']) / df['close']
    for lag in [1, 2, 3, 5, 10, 20]:
        df[f'close_lag{lag}'] = df['close'].shift(lag)
    for lag in [1, 2, 3, 5, 10, 20]:
        df[f'vol_lag{lag}'] = df['volume'].shift(lag)
    df['vol_ma10'] = df['volume'].rolling(10).mean()
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    df['vol_ratio'] = df['volume'] / df['vol_ma10'].replace(0, np.nan)
    df['vol_ratio_20'] = df['volume'] / df['vol_ma20'].replace(0, np.nan)
    df['vol_expand'] = (df['volume'] > df['vol_ma10'] * 1.5).astype(float)
    df['vol_shrink'] = (df['volume'] < df['vol_ma10'] * 0.5).astype(float)
    for w in [5, 10, 20, 40, 80, 120, 240]:
        ma = df['close'].rolling(w).mean()
        df[f'ma{w}_ratio'] = df['close'] / ma - 1
    for w in [5, 10, 20, 60]:
        ma = df['close'].rolling(w).mean()
        df[f'ma{w}_slope'] = ma.pct_change(5)
    for w in [3, 5, 10, 20]:
        df[f'volatility_{w}'] = df['ret_1'].rolling(w).std()
        df[f'hl_ratio_{w}'] = (df['high'] - df['low']).rolling(w).mean() / df['close']
    for period in [7, 14, 21]:
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        df[f'rsi_{period}'] = 100 - (100 / (1 + rs))
    df['rsi_14_slope'] = df['rsi_14'].diff(3)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    df['macd_hist_slope'] = df['macd_hist'].diff(3)
    bb_mid = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_width'] = (bb_mid + 2 * bb_std - (bb_mid - 2 * bb_std)) / bb_mid
    df['bb_position'] = (df['close'] - (bb_mid - 2 * bb_std)) / (4 * bb_std + 1e-10)
    df['bb_width_slope'] = df['bb_width'].diff(5)
    df['hour'] = df['time'].dt.hour
    df['minute'] = df['time'].dt.minute
    df['weekday'] = df['time'].dt.weekday
    df['month'] = df['time'].dt.month
    df['session'] = 0
    df.loc[df['hour'].between(9, 11), 'session'] = 1
    df.loc[df['hour'].between(13, 14), 'session'] = 2
    df.loc[(df['hour'] == 14) & (df['minute'] >= 30), 'session'] = 2
    df.loc[df['hour'] == 15, 'session'] = 3
    df.loc[df['hour'].between(21, 23), 'session'] = 4
    df.loc[df['hour'] == 23, 'session'] = 4
    df.loc[df['hour'].between(0, 2), 'session'] = 5
    df['session_progress'] = df.groupby(
        (df['session'] != df['session'].shift(1)).cumsum()
    ).cumcount() / 12
    for s in range(1, 6):
        df[f'session_{s}'] = (df['session'] == s).astype(float)
    df['oi_change_1'] = df['close_oi'].pct_change()
    df['oi_change_5'] = df['close_oi'].pct_change(5)
    df['oi_change_10'] = df['close_oi'].pct_change(10)
    df['oi_ma20'] = df['close_oi'].rolling(20).mean()
    df['oi_ratio'] = df['close_oi'] / df['oi_ma20'].replace(0, np.nan)
    df['vp_corr'] = df['ret_1'].rolling(20).corr(df['volume'])
    return df


def features_v3(df):
    """run_ma_hourly_v3.py 的特征（回归版）"""
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
    return df


def features_i2609(df, with_momentum=False):
    """run_i2609_hourly(_filter).py 的特征；with_momentum=True 时附加 MA20 趋势列"""
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
    if with_momentum:
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma20_direction'] = np.sign(df['ma20'].diff(5))  # 1=向上, -1=向下, 0=走平
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
    return df


def features_lite(df):
    """run_palm_hourly.py / run_ma_month.py 的精简特征（两者一致）"""
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
    return df


def print_feature_importance(feat_imps, feature_cols, top_n):
    if feat_imps:
        avg_imp = np.mean(feat_imps, axis=0)
        imp_df = pd.DataFrame({'feature': feature_cols, 'importance': avg_imp})
        imp_df = imp_df.sort_values('importance', ascending=False)
        print(f"\n🔝 Top {top_n} 特征重要性:")
        for _, row in imp_df.head(top_n).iterrows():
            print(f"   {row['feature']}: {row['importance']:.0f}")


# ============================================================
# 策略 1: cls1  ← run_ma_hourly.py
# ============================================================

def run_cls1(args):
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support, roc_auc_score
    import lightgbm as lgb

    print("🦞 [cls1] 二分类(未来1根K线涨跌) walk-forward 回测")
    print("=" * 50)

    df = fetch_klines(args.symbol, args.duration, args.bars, make_auth(args))

    print("🔧 构造特征...")
    df = features_v1(df)
    df['label'] = (df['close'].shift(-1) > df['close']).astype(int)

    exclude = ['time', 'datetime', 'id', 'label', 'close', 'open', 'high', 'low',
               'volume', 'open_oi', 'close_oi', 'symbol', 'duration', 'ret_1']
    feature_cols = pick_features(df, exclude)
    print(f"   特征数: {len(feature_cols)}")

    print("\n📊 滚动回测 (walk-forward)...")
    LGB_PARAMS = {
        'objective': 'binary', 'metric': 'binary_logloss', 'boosting_type': 'gbdt',
        'n_estimators': 1000, 'learning_rate': 0.02, 'num_leaves': 8, 'max_depth': 4,
        'min_child_samples': 50, 'subsample': 0.7, 'colsample_bytree': 0.6,
        'reg_alpha': 0.5, 'reg_lambda': 0.5, 'min_split_gain': 0.01,
        'random_state': 42, 'verbosity': -1,
    }

    results, feat_imps = [], []
    df = df.dropna(subset=feature_cols + ['label']).reset_index(drop=True)

    start = args.train_size
    while start + args.test_size <= len(df):
        train = df.iloc[start - args.train_size:start]
        test = df.iloc[start:start + args.test_size]
        X_train = train[feature_cols].values
        y_train = train['label'].values
        X_test = test[feature_cols].values
        y_test = test['label'].values
        pos_w = (len(y_train) - y_train.sum()) / (y_train.sum() + 1e-10)
        model = lgb.LGBMClassifier(**LGB_PARAMS, class_weight={0: 1.0, 1: pos_w})
        model.fit(X_train, y_train,
                  eval_set=[(X_train, y_train), (X_test, y_test)],
                  callbacks=[lgb.early_stopping(15), lgb.log_evaluation(0)])
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]
        for i in range(len(test)):
            results.append({'time': test['time'].iloc[i], 'close': test['close'].iloc[i],
                            'actual': y_test[i], 'pred': y_pred[i], 'prob': y_prob[i]})
        feat_imps.append(model.feature_importances_)
        if len(results) % 500 == 0:
            print(f"   已预测 {len(results)} 根K线...")
        start += args.test_size

    print(f"   完成！共预测 {len(results)} 根K线")

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

    result_df['daily_ret'] = result_df['close'].pct_change().shift(-1)
    result_df['strat_ret'] = np.where(result_df['pred'] == 1, result_df['daily_ret'],
                                      np.where(result_df['pred'] == 0, -result_df['daily_ret'], 0))
    result_df = result_df.dropna(subset=['daily_ret', 'strat_ret'])
    cum_bm = (1 + result_df['daily_ret']).cumprod()
    cum_strat = (1 + result_df['strat_ret']).cumprod()
    total_ret = cum_strat.iloc[-1] - 1
    bm_ret = cum_bm.iloc[-1] - 1
    sharpe = (result_df['strat_ret'].mean() / result_df['strat_ret'].std() * np.sqrt(ANNUALIZE)
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

    print_feature_importance(feat_imps, feature_cols, 20)
    print("\n✅ 完成！")


# ============================================================
# 策略 2: cls2  ← run_ma_hourly_v2.py
# ============================================================

def run_cls2(args):
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support, roc_auc_score
    import lightgbm as lgb

    print("🦞 [cls2] 二分类(未来3根均价方向) 优化版 walk-forward 回测")
    print("=" * 55)

    df = fetch_klines(args.symbol, args.duration, args.bars, make_auth(args))

    print("🔧 构造特征 v2...")
    df = features_v2(df)
    # 标签: 未来3根均价方向(降噪)
    df['label'] = (df['close'].shift(-3).rolling(3).mean() > df['close'].rolling(3).mean().shift(-1)).astype(int)

    exclude = ['time', 'datetime', 'id', 'label', 'close', 'open', 'high', 'low',
               'volume', 'open_oi', 'close_oi', 'symbol', 'duration', 'ret_1']
    feature_cols = pick_features(df, exclude)
    print(f"   特征数: {len(feature_cols)}")

    print("\n📊 滚动回测 (walk-forward, v2 优化参数)...")
    LGB_PARAMS = {
        'objective': 'binary', 'metric': 'binary_logloss', 'boosting_type': 'gbdt',
        'n_estimators': 2000, 'learning_rate': 0.01, 'num_leaves': 12, 'max_depth': 5,
        'min_child_samples': 50, 'subsample': 0.7, 'colsample_bytree': 0.6,
        'reg_alpha': 0.3, 'reg_lambda': 0.5, 'min_split_gain': 0.005,
        'random_state': 42, 'verbosity': -1,
    }

    results, feat_imps = [], []
    df = df.dropna(subset=feature_cols + ['label']).reset_index(drop=True)
    print(f"   可用数据: {len(df)} 行")

    start = args.train_size
    while start + args.test_size <= len(df):
        train = df.iloc[start - args.train_size:start]
        test = df.iloc[start:start + args.test_size]
        X_train = train[feature_cols].values
        y_train = train['label'].values
        X_test = test[feature_cols].values
        y_test = test['label'].values
        pos_w = (len(y_train) - y_train.sum()) / (y_train.sum() + 1e-10)
        model = lgb.LGBMClassifier(**LGB_PARAMS, class_weight={0: 1.0, 1: pos_w})
        model.fit(X_train, y_train,
                  eval_set=[(X_train, y_train), (X_test, y_test)],
                  callbacks=[lgb.early_stopping(30), lgb.log_evaluation(0)])
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]
        for i in range(len(test)):
            results.append({'time': test['time'].iloc[i], 'close': test['close'].iloc[i],
                            'actual': y_test[i], 'pred': y_pred[i], 'prob': y_prob[i]})
        feat_imps.append(model.feature_importances_)
        if len(results) % 500 == 0:
            print(f"   已预测 {len(results)} 根K线... (best_iter≈{model.best_iteration_})")
        start += args.test_size

    print(f"   完成！共预测 {len(results)} 根K线")

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

    result_df['daily_ret'] = result_df['close'].pct_change().shift(-1)
    result_df['strat_ret'] = np.where(result_df['pred'] == 1, result_df['daily_ret'],
                                      np.where(result_df['pred'] == 0, -result_df['daily_ret'], 0))
    result_df = result_df.dropna(subset=['daily_ret', 'strat_ret'])
    cum_bm = (1 + result_df['daily_ret']).cumprod()
    cum_strat = (1 + result_df['strat_ret']).cumprod()
    total_ret = cum_strat.iloc[-1] - 1
    bm_ret = cum_bm.iloc[-1] - 1
    sharpe = (result_df['strat_ret'].mean() / result_df['strat_ret'].std() * np.sqrt(ANNUALIZE)
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

    result_df['hour'] = result_df['time'].dt.hour
    result_df['is_night'] = result_df['hour'].between(21, 23) | (result_df['hour'] <= 2)
    night = result_df[result_df['is_night']]
    day = result_df[~result_df['is_night']]
    if len(night) > 0:
        print(f"\n📊 分时段:")
        print(f"   夜盘 胜率: {(night['pred'] == night['actual']).mean():.2%}  ({len(night)} 根)")
        print(f"   日盘 胜率: {(day['pred'] == day['actual']).mean():.2%}  ({len(day)} 根)")

    print_feature_importance(feat_imps, feature_cols, 25)
    print("\n✅ 完成！")


# ============================================================
# 策略 3: reg3  ← run_ma_hourly_v3.py
# ============================================================

def run_reg3(args):
    from sklearn.metrics import mean_absolute_error, r2_score
    import lightgbm as lgb

    print("🦞 [reg3] 回归(未来5根收益率)+阈值过滤 walk-forward 回测")
    print("=" * 55)

    df = fetch_klines(args.symbol, args.duration, args.bars, make_auth(args))

    print("🔧 构造特征...")
    df = features_v3(df)
    df['label_ret'] = df['close'].pct_change(5).shift(-5)
    df['label_cls'] = (df['label_ret'] > 0).astype(int)

    exclude = ['time', 'datetime', 'id', 'label_ret', 'label_cls',
               'close', 'open', 'high', 'low', 'volume', 'close_oi', 'open_oi',
               'symbol', 'duration', 'ret_1']
    feature_cols = pick_features(df, exclude)
    print(f"   特征数: {len(feature_cols)}, 标签: 未来5K线收益率")

    print("\n📊 滚动回测 (回归+阈值, walk-forward)")
    results, feat_imps = [], []
    df = df.dropna(subset=feature_cols + ['label_ret']).reset_index(drop=True)

    params = {
        'objective': 'regression', 'metric': 'mae', 'boosting_type': 'gbdt',
        'n_estimators': 2000, 'learning_rate': 0.01, 'num_leaves': 12, 'max_depth': 5,
        'min_child_samples': 50, 'subsample': 0.7, 'colsample_bytree': 0.6,
        'reg_alpha': 0.3, 'reg_lambda': 0.5, 'min_split_gain': 0.005,
        'random_state': 42, 'verbosity': -1,
    }

    start = args.train_size
    while start + args.test_size <= len(df):
        train = df.iloc[start - args.train_size:start]
        test = df.iloc[start:start + args.test_size]
        X_train = train[feature_cols].values
        y_train = train['label_ret'].values
        X_test = test[feature_cols].values
        model = lgb.LGBMRegressor(**params)
        model.fit(X_train, y_train,
                  eval_set=[(X_train, y_train), (X_test, test['label_ret'].values)],
                  callbacks=[lgb.early_stopping(20), lgb.log_evaluation(0)])
        y_pred = model.predict(X_test)
        for i in range(len(test)):
            results.append({'time': test['time'].iloc[i], 'close': test['close'].iloc[i],
                            'actual_ret': test['label_ret'].iloc[i], 'pred_ret': y_pred[i]})
        feat_imps.append(model.feature_importances_)
        if len(results) % 500 == 0:
            print(f"   已预测 {len(results)} 根K线...")
        start += args.test_size

    print(f"   完成！共预测 {len(results)} 根K线")

    result_df = pd.DataFrame(results)
    mae = mean_absolute_error(result_df['actual_ret'], result_df['pred_ret'])
    r2 = r2_score(result_df['actual_ret'], result_df['pred_ret'])
    print(f"\n📊 回归评估:")
    print(f"   MAE:      {mae:.6f}")
    print(f"   R²:       {r2:.4f}")
    print(f"   预测均值: {result_df['pred_ret'].mean():.4%}")
    print(f"   实际均值: {result_df['actual_ret'].mean():.4%}")

    result_df['ret_1k'] = result_df['close'].pct_change().shift(-1)

    print(f"\n{'阈值':>10} {'信号数':>8} {'切换':>8} {'总收益':>12} {'夏普':>8} {'胜率':>8} {'最大回撤':>10}")
    print("-" * 66)
    best_threshold = 0
    best_sharpe = -999
    best_result = None
    for threshold in args.thresholds:
        preds = np.where(result_df['pred_ret'] > threshold, 1,
                np.where(result_df['pred_ret'] < -threshold, 0, np.nan))
        mask = ~np.isnan(preds)
        if mask.sum() < 20:
            continue
        preds_clean = preds[mask].astype(int)
        rets_clean = result_df['ret_1k'].values[mask]
        strat = np.where(preds_clean == 1, rets_clean, -rets_clean)
        total = float(np.nan_to_num((1 + np.nan_to_num(strat)).prod(), nan=1)) - 1
        sharpe = strat.mean() / strat.std() * np.sqrt(ANNUALIZE) if strat.std() > 1e-10 else 0
        win = (strat > 0).mean()
        cum = (1 + strat).cumprod()
        dd = (cum / np.maximum.accumulate(cum) - 1).min()
        switches = int(np.sum(np.diff(preds_clean) != 0))
        print(f"{threshold:>9.4f} {int(mask.sum()):>8} {switches:>8} {total:>11.2%} "
              f"{sharpe:>7.2f} {win:>7.2%} {dd:>9.2%}")
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_threshold = threshold
            best_result = (total, sharpe, win, dd, int(mask.sum()), switches)

    if best_result:
        print(f"\n🏆 最佳阈值: {best_threshold:.4f}")
        print(f"   信号数: {best_result[4]}, 切换: {best_result[5]}")
        print(f"   总收益: {best_result[0]:.2%}, 夏普: {best_result[1]:.2f}")
        print(f"   胜率: {best_result[2]:.2%}, 最大回撤: {best_result[3]:.2%}")

    print_feature_importance(feat_imps, feature_cols, 20)
    print("\n✅ 完成！")


# ============================================================
# 策略 4/5: ens-dir / ens-dir-f  ← run_i2609_hourly(_filter).py
# ============================================================

def run_ens_dir(args, with_filter=False):
    from sklearn.metrics import accuracy_score, roc_auc_score
    import lightgbm as lgb

    tag = 'ens-dir-f 动量过滤版' if with_filter else 'ens-dir'
    print(f"🦞 [{tag}] 5种子集成 方向回测 ({args.symbol})")
    print("=" * 60)

    seeds = parse_seeds(args.seeds)
    df = fetch_klines(args.symbol, args.duration, args.bars, make_auth(args))

    df = features_i2609(df, with_momentum=with_filter)
    df['label_ret'] = df['close'].pct_change(5).shift(-5)
    df['label_dir'] = (df['label_ret'] > 0).astype(int)

    exclude = ['time', 'datetime', 'id', 'label_ret', 'label_dir', 'close', 'open', 'high', 'low',
               'volume', 'close_oi', 'open_oi', 'symbol', 'duration', 'ret_1']
    if with_filter:
        exclude = exclude + ['ma20']
    feature_cols = pick_features(df, exclude)

    subset = feature_cols + ['label_dir', 'label_ret'] + (['ma20_direction'] if with_filter else [])
    df = df.dropna(subset=subset).reset_index(drop=True)
    print(f"   特征: {len(feature_cols)} 个, 可用: {len(df)} 行")

    print(f"\n📊 walk-forward 方向回测{'（含动量过滤）' if with_filter else ''}...")
    results = []
    i = args.train_size
    while i + args.test_size <= len(df):
        train = df.iloc[i - args.train_size:i]
        test = df.iloc[i:i + args.test_size]
        Xtr_c, ytr_c = train[feature_cols].values, train['label_dir'].values
        Xte = test[feature_cols].values
        pw = (len(ytr_c) - ytr_c.sum()) / (ytr_c.sum() + 1e-10)

        preds_list = []
        for seed in seeds:
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

        if not with_filter:
            # 回归模型（幅度）— 仅 run_i2609_hourly.py 有
            Xtr_r, ytr_r = train[feature_cols].values, train['label_ret'].values
            preds_r = []
            for seed in seeds:
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
            row = {'time': test['time'].iloc[j], 'close': test['close'].iloc[j],
                   'actual_dir': test['label_dir'].iloc[j], 'prob': prob[j],
                   'actual_ret': test['label_ret'].iloc[j]}
            if with_filter:
                row['ma20_dir'] = test['ma20_direction'].iloc[j]
            else:
                row['pred_ret'] = pred_ret[j]
            results.append(row)
        i += args.test_size

    result_df = pd.DataFrame(results)

    # 严格近 N 天
    cutoff = result_df['time'].max() - pd.Timedelta(days=args.recent_days)
    result_df = result_df[result_df['time'] >= cutoff].reset_index(drop=True)
    print(f"\n📅 严格近{args.recent_days}天: {result_df['time'].min().strftime('%Y-%m-%d')} ~ "
          f"{result_df['time'].max().strftime('%Y-%m-%d')} ({len(result_df)}根K线)")

    y_true = result_df['actual_dir'].values
    y_prob = result_df['prob'].values
    y_pred = (y_prob > 0.5).astype(int)
    print(f"\n📊 分类评估:")
    acc = accuracy_score(y_true, y_pred)
    auc = roc_auc_score(y_true, y_prob) if len(np.unique(y_true)) > 1 else 0.5
    print(f"   准确率: {acc:.4f}")
    print(f"   AUC:    {auc:.4f}")

    if not with_filter:
        print(f"\n{'阈值':>8} {'信号数':>6} {'做多':>5} {'做空':>5} {'切换':>5} {'总收益':>10} {'夏普':>7} {'胜率':>6} {'回撤':>8}")
        print("-" * 66)
        sweep_threshold_rows(result_df, 'prob', 'actual_ret', args.prob_thresholds)
        print_benchmark(result_df, 'actual_ret')
    else:
        print(f"\n{'='*60}")
        print(f"📊 对比：原始策略 vs 动量过滤版")
        print(f"{'='*60}")
        for use_filter, label in [(False, '原始'), (True, '+动量过滤')]:
            print(f"\n--- {label} ---")
            print(f"{'阈值':>8} {'信号数':>6} {'做多':>5} {'做空':>5} {'切换':>5} {'收益':>10} {'夏普':>7} {'胜率':>6} {'回撤':>8}")
            print("-" * 66)
            for th in args.prob_thresholds:
                pred = np.where(result_df['prob'] > th, 1,
                        np.where(result_df['prob'] < (1 - th), 0, np.nan))
                mask = ~np.isnan(pred)
                if mask.sum() < 5:
                    continue
                if use_filter:
                    p_temp = pred[mask].astype(int)
                    ma20_dirs = result_df['ma20_dir'].values[mask]
                    # 趋势向下时不做多，趋势向上时不做空
                    filter_mask = ~((p_temp == 1) & (ma20_dirs < 0)) & ~((p_temp == 0) & (ma20_dirs > 0))
                    final_mask = mask.copy()
                    final_mask[mask] = filter_mask
                    if final_mask.sum() < 5:
                        continue
                    p = pred[final_mask].astype(int)
                    rets = result_df['actual_ret'].values[final_mask]
                else:
                    p = pred[mask].astype(int)
                    rets = result_df['actual_ret'].values[mask]
                strat = np.where(p == 1, rets, -rets)
                total = float((1 + np.nan_to_num(strat)).prod() - 1)
                sharpe = strat.mean() / strat.std() * np.sqrt(ANNUALIZE) if strat.std() > 1e-10 else 0
                win = (strat > 0).mean()
                cum = (1 + strat).cumprod()
                dd = float((cum / np.maximum.accumulate(cum) - 1).min()) if len(cum) > 1 else 0
                switches = int(np.sum(np.diff(p) != 0))
                longs = int((p == 1).sum())
                shorts = int((p == 0).sum())
                print(f"{th:>7.2f} {int(len(p)):>6} {longs:>5} {shorts:>5} {switches:>5} "
                      f"{total:>9.2%} {sharpe:>6.2f} {win:>5.2%} {dd:>7.2%}")
        print_benchmark(result_df, 'actual_ret')

    print("\n✅ 完成！")


# ============================================================
# 策略 6: vol  ← run_palm_hourly.py
# ============================================================

def run_vol(args):
    import lightgbm as lgb

    print(f"🦞 [vol] 波动率回归回测 ({args.symbol})")
    print("=" * 55)

    seeds = parse_seeds(args.seeds)
    df = fetch_klines(args.symbol, args.duration, args.bars, make_auth(args))

    df = features_lite(df)
    # 波动率标签: 未来5根收益率绝对值
    df['label'] = df['close'].pct_change(5).shift(-5).abs()

    exclude = ['time', 'datetime', 'id', 'label', 'close', 'open', 'high', 'low',
               'volume', 'close_oi', 'open_oi', 'symbol', 'duration', 'ret_1']
    feature_cols = pick_features(df, exclude)
    df = df.dropna(subset=feature_cols + ['label']).reset_index(drop=True)
    print(f"   特征: {len(feature_cols)} 个, 可用: {len(df)} 行")

    print(f"\n📊 walk-forward 回测 (训练{len(df)}行中的最后{len(df)-args.train_size}行)...")
    results, pred_vols = [], []
    i = args.train_size
    while i + args.test_size <= len(df):
        train = df.iloc[i - args.train_size:i]
        test = df.iloc[i:i + args.test_size]
        Xtr, ytr = train[feature_cols].values, train['label'].values
        Xte = test[feature_cols].values
        preds_list = []
        for seed in seeds:
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
            results.append({'time': test['time'].iloc[j], 'close': test['close'].iloc[j],
                            'actual_vol': test['label'].iloc[j]})
        i += args.test_size

    result_df = pd.DataFrame(results)
    result_df['pred_vol'] = pred_vols

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

    print(f"\n{'阈值百分位':>8} {'阈值':>8} {'高波信号':>8} {'实际高波占比':>12} {'准确率':>8}")
    print("-" * 48)
    for pctile in [50, 60, 70, 80, 90]:
        th = np.percentile(preds, pctile)
        high_signal = preds >= th
        if high_signal.sum() == 0:
            continue
        actual_high = actuals >= np.percentile(actuals, pctile)
        hit_rate = (actuals[high_signal] >= np.percentile(actuals, pctile)).mean()
        print(f"   P{pctile:>3}     {th:>7.4f} {high_signal.sum():>8} "
              f"{actuals[high_signal].mean():>11.4%} {hit_rate:>7.2%}")

    ret_1k = result_df['close'].pct_change().values
    bm_total = (1 + np.nan_to_num(ret_1k)).prod() - 1
    print(f"\n📈 基准(买入持有): {bm_total:.2%}")

    result_df['ret_1k'] = ret_1k
    th_pctile = np.percentile(preds, 70)
    result_df['signal'] = np.where(preds >= th_pctile, 1, 0)
    result_df['strat_ret'] = result_df['signal'] * result_df['ret_1k']
    strat_total = (1 + np.nan_to_num(result_df['strat_ret'].values)).prod() - 1
    print(f"   高波动做多策略: {strat_total:.2%}")

    print(f"\n📋 最近20根K线 预测波动 vs 实际波动:")
    print(f"{'时间':>12} {'收盘':>6} {'预测波动':>10} {'实际波动':>10} {'判定':>6}")
    print("-" * 48)
    for _, row in result_df.tail(20).iterrows():
        label = '🔥高' if row['pred_vol'] >= th_pctile else '❄️低'
        print(f"{row['time'].strftime('%m/%d %H:%M'):>12} {row['close']:>6.0f} "
              f"{row['pred_vol']:>9.2%} {row['actual_vol']:>9.2%} {label}")

    print("\n✅ 完成！")


# ============================================================
# 策略 7: quick  ← run_ma_month.py
# ============================================================

def run_quick(args):
    import lightgbm as lgb

    print(f"🦞 [quick] 80/20 切分 5种子集成回归 ({args.symbol})")
    print("=" * 50)

    seeds = parse_seeds(args.seeds)
    df = fetch_klines(args.symbol, args.duration, args.bars, make_auth(args))

    df = features_lite(df)
    df['label_ret'] = df['close'].pct_change(5).shift(-5)

    exclude = ['time', 'datetime', 'id', 'label_ret', 'close', 'open', 'high', 'low',
               'volume', 'close_oi', 'open_oi', 'symbol', 'duration', 'ret_1']
    feature_cols = pick_features(df, exclude)
    df = df.dropna(subset=feature_cols + ['label_ret']).reset_index(drop=True)
    print(f"可用行: {len(df)}, 特征: {len(feature_cols)}")

    mid = int(len(df) * args.train_ratio)
    train = df.iloc[:mid]
    test = df.iloc[mid:]
    print(f"\n📅 训练: {train['time'].min().strftime('%m/%d')} ~ {train['time'].max().strftime('%m/%d')} ({len(train)}根)")
    print(f"📅 测试: {test['time'].min().strftime('%m/%d')} ~ {test['time'].max().strftime('%m/%d')} ({len(test)}根)")

    X_train, y_train = train[feature_cols].values, train['label_ret'].values
    X_test, y_test = test[feature_cols].values, test['label_ret'].values

    print(f"\n🔧 训练{len(seeds)}个模型做集成...")
    models = []
    for seed in seeds:
        model = lgb.LGBMRegressor(
            n_estimators=500, learning_rate=0.02, num_leaves=10, max_depth=4,
            min_child_samples=30, subsample=0.7, colsample_bytree=0.6,
            reg_alpha=0.3, reg_lambda=0.5, min_split_gain=0.005,
            random_state=seed, verbosity=-1,
        )
        model.fit(X_train, y_train)
        models.append(model)

    test_preds = np.mean([m.predict(X_test) for m in models], axis=0)

    print("\n📊 回测结果:")
    print(f"{'阈值':>8} {'信号':>6} {'做多':>5} {'做空':>5} {'切换':>5} {'收益':>10} {'夏普':>7} {'胜率':>6} {'回撤':>8}")
    print("-" * 65)
    rets = test['close'].values
    ret_1k = np.diff(rets) / rets[:-1]
    for th in args.thresholds:
        pred = np.where(test_preds[:-1] > th, 1, np.where(test_preds[:-1] < -th, 0, np.nan))
        mask = ~np.isnan(pred)
        if mask.sum() < 5:
            continue
        p_clean = pred[mask].astype(int)
        r_clean = ret_1k[mask]
        strat = np.where(p_clean == 1, r_clean, -r_clean)
        total = float((1 + np.nan_to_num(strat)).prod() - 1)
        sharpe = strat.mean() / strat.std() * np.sqrt(ANNUALIZE) if strat.std() > 1e-10 else 0
        win = (strat > 0).mean()
        cum = (1 + strat).cumprod()
        dd = float((cum / np.maximum.accumulate(cum) - 1).min()) if len(cum) > 1 else 0
        switches = int(np.sum(np.diff(p_clean) != 0))
        longs = int((p_clean == 1).sum())
        shorts = int((p_clean == 0).sum())
        print(f"{th:>7.4f} {int(mask.sum()):>6} {longs:>5} {shorts:>5} {switches:>5} "
              f"{total:>9.2%} {sharpe:>6.2f} {win:>5.2%} {dd:>7.2%}")

    bm_rets = ret_1k
    bm_total = float((1 + bm_rets).prod() - 1)
    bm_sharpe = bm_rets.mean() / bm_rets.std() * np.sqrt(ANNUALIZE) if bm_rets.std() > 1e-10 else 0
    print(f"\n📊 基准(买入持有): 收益={bm_total:.2%}  夏普={bm_sharpe:.2f}")
    start_price = test['close'].iloc[0]
    end_price = test['close'].iloc[-1]
    print(f"   起始价: {start_price:.0f} → 结束价: {end_price:.0f} ({(end_price-start_price)/start_price:.2%})")

    print("\n✅ 完成！")


# ============================================================
# CLI
# ============================================================

def build_parser():
    p = argparse.ArgumentParser(
        prog='run_experiment.py',
        description='期货 LightGBM 实验统一入口（整合原 7 个 run_*.py 脚本）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('--tq-user', default='bj153', help='天勤账号（默认沿用原脚本）')
    p.add_argument('--tq-pass', default='baijing153', help='天勤密码（默认沿用原脚本）')

    sub = p.add_subparsers(dest='strategy', required=True, metavar='STRATEGY')

    def add_common(sp, symbol, bars, train_size, test_size):
        sp.add_argument('--symbol', default=symbol, help=f'天勤合约代码 (默认 {symbol})')
        sp.add_argument('--duration', type=int, default=3600, help='K线周期(秒) (默认 3600)')
        sp.add_argument('--bars', type=int, default=bars, help=f'拉取K线根数 (默认 {bars})')
        sp.add_argument('--train-size', type=int, default=train_size, help=f'训练窗口K线数 (默认 {train_size})')
        sp.add_argument('--test-size', type=int, default=test_size, help=f'每步预测K线数 (默认 {test_size})')

    sp = sub.add_parser('cls1', help='二分类(未来1根K线涨跌) ← run_ma_hourly.py')
    add_common(sp, 'KQ.m@CZCE.MA', 8000, 3000, 100)

    sp = sub.add_parser('cls2', help='二分类(未来3根均价方向) 优化版 ← run_ma_hourly_v2.py')
    add_common(sp, 'KQ.m@CZCE.MA', 10000, 4000, 100)

    sp = sub.add_parser('reg3', help='回归(未来5根收益率)+阈值 ← run_ma_hourly_v3.py')
    add_common(sp, 'KQ.m@CZCE.MA', 10000, 4000, 100)
    sp.add_argument('--thresholds', type=parse_floats,
                    default=[0.0, 0.0005, 0.001, 0.0015, 0.002, 0.0025, 0.003, 0.004, 0.005],
                    help='收益率阈值列表，逗号分隔')

    sp = sub.add_parser('ens-dir', help='5种子集成 方向+幅度 ← run_i2609_hourly.py')
    add_common(sp, 'KQ.m@DCE.i', 1500, 800, 50)
    sp.add_argument('--seeds', default='42,73,101,257,500', help='集成种子，逗号分隔')
    sp.add_argument('--recent-days', type=int, default=30, help='只评估最近N天 (默认 30)')
    sp.add_argument('--prob-thresholds', type=parse_floats,
                    default=[0.0, 0.55, 0.58, 0.60, 0.62, 0.65],
                    help='概率阈值列表，逗号分隔')

    sp = sub.add_parser('ens-dir-f', help='5种子集成 方向+MA20动量过滤 ← run_i2609_hourly_filter.py')
    add_common(sp, 'KQ.m@DCE.i', 1500, 800, 50)
    sp.add_argument('--seeds', default='42,73,101,257,500', help='集成种子，逗号分隔')
    sp.add_argument('--recent-days', type=int, default=30, help='只评估最近N天 (默认 30)')
    sp.add_argument('--prob-thresholds', type=parse_floats,
                    default=[0.0, 0.55, 0.58, 0.60, 0.62, 0.65],
                    help='概率阈值列表，逗号分隔')

    sp = sub.add_parser('vol', help='波动率回归 ← run_palm_hourly.py')
    add_common(sp, 'KQ.m@DCE.p', 1500, 800, 50)
    sp.add_argument('--seeds', default='42,73,101,257,500', help='集成种子，逗号分隔')

    sp = sub.add_parser('quick', help='80/20切分 集成回归 ← run_ma_month.py')
    add_common(sp, 'KQ.m@CZCE.MA', 1500, None, None)
    sp.add_argument('--seeds', default='42,73,101,257,500', help='集成种子，逗号分隔')
    sp.add_argument('--train-ratio', type=float, default=0.8, help='训练集占比 (默认 0.8)')
    sp.add_argument('--thresholds', type=parse_floats,
                    default=[0.0, 0.0005, 0.001, 0.0015, 0.002, 0.0025, 0.003],
                    help='收益率阈值列表，逗号分隔')
    return p


def main():
    args = build_parser().parse_args()
    if args.strategy == 'cls1':
        run_cls1(args)
    elif args.strategy == 'cls2':
        run_cls2(args)
    elif args.strategy == 'reg3':
        run_reg3(args)
    elif args.strategy == 'ens-dir':
        run_ens_dir(args, with_filter=False)
    elif args.strategy == 'ens-dir-f':
        run_ens_dir(args, with_filter=True)
    elif args.strategy == 'vol':
        run_vol(args)
    elif args.strategy == 'quick':
        run_quick(args)


if __name__ == '__main__':
    main()
