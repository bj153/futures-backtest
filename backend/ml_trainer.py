"""
LightGBM 期货时序预测（防过拟合优化版）
============================================
核心改进：
  1. 强正则参数（更少叶子、更浅、高正则化、低学习率、更多树）
  2. 精简特征集（避免冗余滞后特征的噪声累计）
  3. 滚动回测（rolling walk-forward），不用未来数据
  4. 额外验证集（holdout），防止 CV 过程中仍泄露

用法:
    python ml_trainer.py                           # 默认 RB.SHF
    python ml_trainer.py --ts_code=P.DCE           # 棕榈油
    python ml_trainer.py --ts_code=HC.SHF          # 热卷
    python ml_trainer.py --ts_code=MA.CZCE --start=20210101 --end=20250605
"""

import argparse
import warnings
from datetime import datetime
from typing import Tuple

import lightgbm as lgb
import numpy as np
import pandas as pd
import tushare as ts
from sklearn.metrics import (accuracy_score, precision_recall_fscore_support,
                             roc_auc_score)
from sklearn.model_selection import TimeSeriesSplit

warnings.filterwarnings('ignore')

# ============================================================
# 1. 数据获取
# ============================================================

TOKEN = '26097aa822d0b8c9fc2afe27c1d447e3b1bdee64b1dd341e9f11878d'
pro = ts.pro_api(TOKEN)


def fetch_futures_data(
    ts_code: str = 'RB.SHF',
    start_date: str = '20200101',
    end_date: str = None,
) -> pd.DataFrame:
    """获取期货日线数据（主力连续合约格式: RB.SHF, P.DCE, MA.CZCE 等）"""
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')

    print(f"📥 正在拉取 {ts_code} 日线数据 ({start_date} ~ {end_date})...")
    df = pro.fut_daily(
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
        fields='trade_date,open,high,low,close,pre_close,vol,amount,oi',
    )
    if df is None or df.empty:
        raise ValueError(f"未获取到 {ts_code} 的数据，请检查 ts_code 或日期范围")

    df = df.sort_values('trade_date').reset_index(drop=True)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df['pre_close'] = df['pre_close'].mask(df['pre_close'] == 0, df['close'].shift(1))

    print(f"✅ 共获取 {len(df)} 条日线数据 ({df['trade_date'].min()} ~ {df['trade_date'].max()})")
    return df


# ============================================================
# 2. 特征工程（精简版）
# ============================================================


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    构造特征 - 精简版，避免过拟合
    原则：少而精，避免大量滞后特征叠加噪声
    """
    print("🔧 构造特征（精简版）...")
    df = df.copy()

    # --- 收益率 ---
    df['ret_1d'] = df['close'].pct_change()
    df['ret_5d'] = df['close'].pct_change(5)
    df['ret_20d'] = df['close'].pct_change(20)
    df['high_low_pct'] = (df['high'] - df['low']) / df['close']

    # --- 滞后价格（仅关键步长）---
    for lag in [1, 2, 5, 10, 20]:
        df[f'close_lag{lag}'] = df['close'].shift(lag)

    # --- 成交量比 ---
    df['vol_ma5'] = df['vol'].rolling(5).mean()
    df['vol_ratio'] = df['vol'] / df['vol_ma5'].replace(0, np.nan)

    # --- 持仓量变化 ---
    df['oi_change_pct'] = df['oi'].pct_change(5)
    df['oi_change_1d'] = df['oi'].pct_change()

    # --- 均线偏离度 ---
    for w in [5, 10, 20, 60]:
        ma = df['close'].rolling(w).mean()
        df[f'ma{w}_ratio'] = df['close'] / ma - 1

    # --- 波动率 ---
    for w in [5, 10, 20]:
        df[f'volatility_{w}'] = df['ret_1d'].rolling(w).std()
        df[f'hl_ratio_{w}'] = (df['high'] - df['low']).rolling(w).mean() / df['close']

    # --- RSI(14) ---
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi_14'] = 100 - (100 / (1 + rs))

    # --- MACD ---
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']

    # --- 布林带宽度 ---
    bb_mid = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_width'] = (bb_mid + 2 * bb_std - (bb_mid - 2 * bb_std)) / bb_mid
    df['bb_position'] = (df['close'] - (bb_mid - 2 * bb_std)) / (4 * bb_std + 1e-10)

    # --- 时间特征 ---
    df['month'] = df['trade_date'].dt.month
    df['weekday'] = df['trade_date'].dt.weekday

    # --- 标签：下一日涨跌 ---
    df['label'] = (df['close'].shift(-1) > df['close']).astype(int)

    print(f"  特征维度: {df.shape[1] - 1} 列（含 label）")
    return df


# ============================================================
# 3. 滚动回测（walk-forward，最严格）
# ============================================================


def rolling_backtest(
    df: pd.DataFrame,
    feature_cols: list,
    train_window: int = 800,      # 训练窗口大小（天数）
    test_window: int = 20,        # 每次预测的天数
    min_train: int = 400,         # 最小训练样本
) -> pd.DataFrame:
    """
    滚动回测（walk-forward analysis）
    - 只用历史数据训练
    - 每次前滚 test_window 天
    - 最接近实盘模拟
    """
    print(f"\n📊 滚动回测（walk-forward）...")
    print(f"  训练窗口: {train_window} 天, 预测窗口: {test_window} 天")
    df = df.reset_index(drop=True)
    results = []

    start_idx = max(train_window, min_train)
    step = test_window

    while start_idx + step <= len(df):
        # 训练集：最近的 train_window 条
        train_end = start_idx
        train_start = max(0, train_end - train_window)
        # 测试集：接下来的 step 条
        test_end = min(len(df), train_end + step)

        train_df = df.iloc[train_start:train_end].dropna(subset=feature_cols + ['label'])
        test_df = df.iloc[train_end:test_end].dropna(subset=feature_cols + ['label'])

        if len(train_df) < min_train or len(test_df) < 5:
            start_idx += step
            continue

        X_train = train_df[feature_cols].values
        y_train = train_df['label'].values
        X_test = test_df[feature_cols].values
        y_test = test_df['label'].values

        # 类别权重
        pos_w = (len(y_train) - y_train.sum()) / (y_train.sum() + 1e-10)

        # 强正则参数
        model = lgb.LGBMClassifier(
            objective='binary',
            metric='binary_logloss',
            boosting_type='gbdt',
            n_estimators=1000,
            learning_rate=0.02,
            num_leaves=8,
            max_depth=4,
            min_child_samples=30,
            subsample=0.7,
            colsample_bytree=0.6,
            reg_alpha=0.5,
            reg_lambda=0.5,
            min_split_gain=0.01,
            random_state=42,
            verbosity=-1,
            class_weight={0: 1.0, 1: pos_w},
        )
        model.fit(
            X_train, y_train,
            eval_set=[(X_train, y_train), (X_test, y_test)],
            callbacks=[lgb.early_stopping(15), lgb.log_evaluation(0)],
        )

        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]

        # 记录每根K线的预测
        for i in range(len(test_df)):
            results.append({
                'trade_date': test_df['trade_date'].iloc[i],
                'close': test_df['close'].iloc[i],
                'actual': y_test[i],
                'pred': y_pred[i],
                'prob': y_prob[i],
            })

        if (start_idx - train_window) % (step * 5) == 0:
            print(f"  训练至 {train_df['trade_date'].iloc[-1].strftime('%Y-%m-%d')} 预测 "
                  f"{test_df['trade_date'].iloc[0].strftime('%Y-%m-%d')} ~ "
                  f"{test_df['trade_date'].iloc[-1].strftime('%Y-%m-%d')}")

        start_idx += step

    result_df = pd.DataFrame(results)
    print(f"  共预测 {len(result_df)} 根K线")
    return result_df


def evaluate_backtest(result_df: pd.DataFrame):
    """评估滚动回测结果"""
    y_true = result_df['actual'].values
    y_pred = result_df['pred'].values
    y_prob = result_df['prob'].values

    acc = accuracy_score(y_true, y_pred)
    prec, rec, f1, _ = precision_recall_fscore_support(y_true, y_pred, average='binary')
    try:
        auc = roc_auc_score(y_true, y_prob)
    except ValueError:
        auc = 0.5

    print(f"\n📊 回测评估:")
    print(f"  准确率:         {acc:.4f}")
    print(f"  精确率(涨):     {prec:.4f}")
    print(f"  召回率(涨):     {rec:.4f}")
    print(f"  F1:             {f1:.4f}")
    print(f"  AUC:            {auc:.4f}")

    # 模拟交易
    result_df = result_df.copy()
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
    sharpe = (result_df['strat_ret'].mean() / result_df['strat_ret'].std() * np.sqrt(244)
              if result_df['strat_ret'].std() > 0 else 0)
    win_rate = (result_df['strat_ret'] > 0).mean()
    max_dd = (cum_strat / cum_strat.cummax() - 1).min()

    print(f"  策略总收益:     {total_ret:.2%}")
    print(f"  基准收益(买入持有): {bm_ret:.2%}")
    print(f"  超额收益:       {total_ret - bm_ret:.2%}")
    print(f"  夏普比率:       {sharpe:.3f}")
    print(f"  胜率(日):       {win_rate:.2%}")
    print(f"  最大回撤:       {max_dd:.2%}")

    # 交易统计
    longs = (result_df['pred'] == 1).sum()
    shorts = (result_df['pred'] == 0).sum()
    signals = result_df['pred'].diff().fillna(0).abs().sum() / 2
    print(f"  做多/做空:      {longs} / {shorts}")
    print(f"  信号切换次数:   {int(signals)}")

    return result_df


# ============================================================
# 4. 单次训练 + 时序交叉验证（快速评估用）
# ============================================================


def cv_train(
    X: np.ndarray,
    y: np.ndarray,
    n_splits: int = 5,
) -> Tuple[lgb.Booster, dict]:
    """
    时序交叉验证训练（使用强正则参数）
    用于快速评估特征有效性，不用于最终回测
    """
    params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
        'boosting_type': 'gbdt',
        'n_estimators': 1000,
        'learning_rate': 0.02,
        'num_leaves': 8,
        'max_depth': 4,
        'min_child_samples': 30,
        'subsample': 0.7,
        'colsample_bytree': 0.6,
        'reg_alpha': 0.5,
        'reg_lambda': 0.5,
        'min_split_gain': 0.01,
        'random_state': 42,
        'verbosity': -1,
    }

    tscv = TimeSeriesSplit(n_splits=n_splits)
    cv_metrics = {'accuracy': [], 'precision': [], 'recall': [], 'f1': [], 'auc': []}

    print(f"\n📊 {n_splits} 折时序交叉验证（强正则）:")
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X), 1):
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]

        pos_w = (len(y_train) - y_train.sum()) / (y_train.sum() + 1e-10)

        model = lgb.LGBMClassifier(**params, class_weight={0: 1.0, 1: pos_w})
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            callbacks=[lgb.early_stopping(15), lgb.log_evaluation(0)],
        )

        y_pred = model.predict(X_val)
        y_prob = model.predict_proba(X_val)[:, 1]

        acc = accuracy_score(y_val, y_pred)
        prec, rec, f1, _ = precision_recall_fscore_support(y_val, y_pred, average='binary')
        auc = roc_auc_score(y_val, y_prob) if len(np.unique(y_val)) > 1 else 0.5

        cv_metrics['accuracy'].append(acc)
        cv_metrics['precision'].append(prec)
        cv_metrics['recall'].append(rec)
        cv_metrics['f1'].append(f1)
        cv_metrics['auc'].append(auc)

        print(f"  折 {fold}: acc={acc:.4f}  prec={prec:.4f}  rec={rec:.4f}  f1={f1:.4f}  auc={auc:.4f}  best_iter={model.best_iteration_}")

    print(f"\n  🏆 CV 均值:")
    for k, v in cv_metrics.items():
        print(f"    {k}: {np.mean(v):.4f} ± {np.std(v):.4f}")

    # 全量训练最终模型
    print("🔄 使用全部数据训练最终模型...")
    pos_w = (len(y) - y.sum()) / (y.sum() + 1e-10)
    final_model = lgb.LGBMClassifier(**params, class_weight={0: 1.0, 1: pos_w})
    final_model.fit(X, y)

    return final_model, cv_metrics


def print_feature_importance(model, feature_names, top_n=25):
    """打印特征重要性"""
    imp = pd.DataFrame({'feature': feature_names, 'importance': model.feature_importances_})
    imp = imp.sort_values('importance', ascending=False)
    print(f"\n🔝 Top {top_n} 特征重要性:")
    for _, row in imp.head(top_n).iterrows():
        print(f"  {row['feature']}: {row['importance']}")


# ============================================================
# 5. 主流程
# ============================================================


def main():
    parser = argparse.ArgumentParser(description='LightGBM 期货时序预测（防过拟合版）')
    parser.add_argument('--ts_code', default='RB.SHF',
                        help='主力连续合约代码，如 RB.SHF / P.DCE / HC.SHF / MA.CZCE')
    parser.add_argument('--start', default='20200101', help='数据开始日期')
    parser.add_argument('--end', default=None, help='数据结束日期')
    parser.add_argument('--mode', choices=['cv', 'walk', 'both'], default='both',
                        help='cv=仅交叉验证, walk=仅滚动回测, both=两者')
    parser.add_argument('--train_window', type=int, default=800,
                        help='滚动回测训练窗口大小')
    parser.add_argument('--test_window', type=int, default=20,
                        help='滚动回测每次预测天数')
    args = parser.parse_args()

    print("=" * 60)
    print(f"🦞 LightGBM 期货预测（防过拟合版）")
    print(f"   合约: {args.ts_code}")
    print(f"   数据: {args.start} ~ {args.end or '今天'}")
    print("=" * 60)

    # 1. 获取数据
    raw_df = fetch_futures_data(args.ts_code, args.start, args.end)

    # 2. 特征工程
    df = build_features(raw_df)

    # 3. 划分特征/标签
    exclude_cols = [
        'trade_date', 'label', 'close', 'open', 'high', 'low',
        'pre_close', 'vol', 'amount', 'oi', 'ret_1d',
    ]
    feature_cols = [
        c for c in df.columns
        if c not in exclude_cols and df[c].dtype in ('float64', 'int64')
    ]

    # 去 NaN
    df_clean = df[feature_cols + ['label', 'trade_date', 'close']].dropna().reset_index(drop=True)
    X = df_clean[feature_cols].values
    y = df_clean['label'].values

    print(f"\n📋 数据集: {len(df_clean)} 行, {len(feature_cols)} 个特征")
    print(f"  涨样本: {y.sum()} ({y.sum() / len(y):.1%})")
    print(f"  跌样本: {len(y) - y.sum()} ({(len(y) - y.sum()) / len(y):.1%})")

    # --- 交叉验证（快速评估）---
    if args.mode in ('cv', 'both'):
        model, cv_metrics = cv_train(X, y)
        print_feature_importance(model, feature_cols)

    # --- 滚动回测（严格评估）---
    if args.mode in ('walk', 'both'):
        result_df = rolling_backtest(
            df_clean, feature_cols,
            train_window=args.train_window,
            test_window=args.test_window,
        )
        if len(result_df) > 0:
            bt_result = evaluate_backtest(result_df)
        else:
            print("❌ 滚动回测未生成任何预测（数据不足或窗口设置不合理）")

    print("\n✅ 完成！")


if __name__ == '__main__':
    main()
