import os, hashlib
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import lightgbm as lgb

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Tuple, Optional

import logging
logger = logging.getLogger('ml_api')

router = APIRouter()

import warnings
warnings.filterwarnings('ignore')


# ============================================================
# ML 预测 API v2 — 训练/回测分离
# ============================================================

ML_MODEL_DIR = Path(__file__).parent / "models"
ML_MODEL_DIR.mkdir(exist_ok=True)

# 合约乘数映射（根据合约代码前缀匹配）
CONTRACT_MULTIPLIERS = {
    # 大商所
    'jm': 60, 'j': 100, 'i': 100, 'rb': 10, 'hc': 10,
    'p': 10, 'm': 10, 'y': 10, 'a': 10, 'b': 10, 'c': 10,
    'cs': 10, 'l': 5, 'v': 5, 'pp': 5, 'eg': 10, 'eb': 5,
    'pg': 20, 'rr': 10, 'fb': 10, 'bb': 10, 'jd': 5,
    # 上期所
    'cu': 5, 'al': 5, 'zn': 5, 'ni': 1, 'sn': 1, 'pb': 5,
    'au': 1000, 'ag': 15, 'ss': 5, 'ao': 20,
    'rb': 10, 'hc': 10, 'ru': 10, 'bu': 10, 'fu': 10,
    'sp': 10, 'wr': 10,
    # 郑商所
    'ta': 5, 'ma': 5, 'sa': 20, 'ur': 20, 'fg': 20, 'zc': 100,
    'rm': 10, 'oi': 10, 'cf': 5, 'sr': 10, 'ap': 10, 'cj': 5,
    'pk': 5, 'pf': 5, 'cy': 1, 'jr': 10, 'lr': 10, 'ri': 10,
    'sm': 5, 'sf': 5,
    # 中金所
    'if': 300, 'ic': 200, 'ih': 300, 'im': 200,
    't': 10000, 'tf': 10000, 'ts': 10000,
    # 能源中心
    'sc': 1000, 'nr': 10, 'lu': 10, 'bc': 5,
}

def get_multiplier(contract_code: str) -> int:
    """根据合约代码获取乘数"""
    code = contract_code.lower().replace('\d', '')
    prefix = ''.join(c for c in code if not c.isdigit())
    # 从长到短匹配前缀
    for i in range(len(prefix), 0, -1):
        key = prefix[:i]
        if key in CONTRACT_MULTIPLIERS:
            return CONTRACT_MULTIPLIERS[key]
    return 10  # 默认


def build_ml_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, list]:
    """构造 ML 特征
    - 标签: 未来N根K线收益方向（去前视偏差，只用 future close 不用 max/min）
    - 持仓量变化特征
    """
    df = df.copy()
    df = df.sort_values('time').reset_index(drop=True)
    if 'close' not in df.columns:
        return df, []

    # ---- 价格特征 ----
    df['ret_1'] = df['close'].pct_change()
    df['ret_3'] = df['close'].pct_change(3)
    df['ret_5'] = df['close'].pct_change(5)
    df['ret_10'] = df['close'].pct_change(10)
    df['hl_pct'] = (df['high'] - df['low']) / df['close'].replace(0, np.nan)
    df['hl_amp'] = (df['high'] - df['low']) / (df['high'] + df['low']) * 200
    df['accel'] = df['ret_1'].diff()

    for lag in [1, 2, 3, 5, 10]:
        df[f'close_lag{lag}'] = df['close'].shift(lag)
    for lag in [1, 3, 5, 10]:
        df[f'vol_lag{lag}'] = df['volume'].shift(lag)

    # ---- 持仓量特征 ----
    if 'hold' in df.columns:
        df['hold_chg'] = df['hold'].diff()
        df['hold_chg_pct'] = df['hold'].pct_change()
        df['hold_ma5'] = df['hold'].rolling(5).mean()
        df['hold_ratio'] = df['hold'] / df['hold_ma5'].replace(0, np.nan)
        df['hold_vol_ratio'] = df['hold_chg'].abs() / df['volume'].replace(0, np.nan)
        df['hold_trend'] = df['hold'].rolling(5).mean().diff(3)
        for lag in [1, 3, 5]:
            df[f'hold_lag{lag}'] = df['hold'].shift(lag)
            df[f'hold_chg_lag{lag}'] = df['hold_chg'].shift(lag)

    # ---- 成交量特征 ----
    df['vol_ma10'] = df['volume'].rolling(10).mean()
    df['vol_ratio'] = df['volume'] / df['vol_ma10'].replace(0, np.nan)

    # ---- 均线特征 ----
    for w in [5, 10, 20, 40]:
        ma = df['close'].rolling(w).mean()
        df[f'ma{w}_ratio'] = df['close'] / ma - 1
        df[f'ma{w}_slope'] = ma.pct_change(5)

    df['ma20'] = df['close'].rolling(20).mean()
    df['ma20_direction'] = np.sign(df['ma20'].diff(5))

    # ---- 波动率特征 ----
    for w in [5, 10, 20]:
        df[f'volatility_{w}'] = df['ret_1'].rolling(w).std()
        df[f'hl_ratio_{w}'] = (df['high'] - df['low']).rolling(w).mean() / df['close'].replace(0, np.nan)

    # ---- 技术指标 ----
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

    # ---- 标签: 未来N根K线收益方向（去前视偏差） ----
    n_forward = 12  # 未来12根K线的收益（小时线 ≈ 半天）
    # 用 future close / current close - 1，不用 max/min（减少前视偏差）
    df['fwd_ret'] = df['close'].shift(-n_forward) / df['close'] - 1
    # 3 分类标签：涨幅超过阈值=做多，跌幅超过阈值=做空，否则观望
    thresh = 0.003  # 0.3% 方向性阈值（比原来的0.2%略高，过滤噪声）
    df['label_dir'] = 0  # 0=观望
    df.loc[df['fwd_ret'] >= thresh, 'label_dir'] = 2   # LONG
    df.loc[df['fwd_ret'] <= -thresh, 'label_dir'] = 1  # SHORT
    # 保留最大收益方向用于回测盈亏计算
    df['label_ret'] = df['fwd_ret'].abs()

    # 排除不需要的特征列
    exclude = ['time', 'label_ret', 'label_dir', 'fwd_ret',
               'close', 'open', 'high', 'low', 'volume', 'hold',
               'ret_1', 'ma20', 'datetime', 'id', 'close_oi', 'open_oi',
               'symbol', 'duration']
    feature_cols = [c for c in df.columns if c not in exclude and df[c].dtype in ('float64', 'int64')]

    return df, feature_cols


class MLTrainRequest(BaseModel):
    kline_data: List[dict] = Field(..., description="K线数据 [{time, open, high, low, close, volume}]")
    contract: str = Field('', description="合约代码，用于命名模型文件")
    overwrite: str = Field('', description="覆盖已有模型的文件名，不为空则使用此文件名保存")


class MLTrainResponse(BaseModel):
    status: str
    model_file: str
    train_samples: int
    feature_count: int
    accuracy: float
    auc: float
    message: str


class MLBacktestRequest(BaseModel):
    kline_data: List[dict] = Field(..., description="K线数据")
    model_file: Optional[str] = Field(None, description="指定模型文件名，留空用最新的")
    threshold: float = Field(0.60, description="预测阈值(0.5~0.8)")
    use_filter: bool = Field(True, description="是否启用动量过滤")
    contract: Optional[str] = Field(None, description="合约代码，用于获取乘数")


class MLSignalItem(BaseModel):
    time: str
    price: float
    signal: str
    confidence: float
    prob: float


class MLBacktestResponse(BaseModel):
    status: str
    total_samples: int
    signal_samples: int = 0
    signal_count: int
    accuracy: float
    auc: float
    strategy_return: float
    strategy_sharpe: float
    strategy_max_dd: float
    benchmark_long: float
    benchmark_short: float
    latest_signal: str
    latest_price: float
    signals: List[MLSignalItem]
    trades: List[dict] = []
    equity_curve: List[dict] = []


class MLModelInfo(BaseModel):
    model_file: str
    trained_at: str
    accuracy: float
    auc: float
    train_samples: int
    feature_count: int
    contract: str = ''


@router.get("/api/ml/models", response_model=List[MLModelInfo])
async def ml_list_models():
    """列出所有已训练的模型"""
    models_list = []
    for mp in sorted(ML_MODEL_DIR.glob("*.pkl"), key=os.path.getmtime, reverse=True):
        try:
            import joblib
            data = joblib.load(mp)
            models_list.append(MLModelInfo(
                model_file=mp.name,
                trained_at=data.get('trained_at', '未知'),
                accuracy=data.get('accuracy', 0.0),
                auc=data.get('auc', 0.0),
                train_samples=data.get('train_samples', 0),
                feature_count=len(data.get('feature_cols', [])),
            ))
        except Exception:
            pass
    return models_list




@router.delete("/api/ml/models/{model_file}")
async def ml_delete_model(model_file: str):
    """删除指定模型文件"""
    import os
    model_path = ML_MODEL_DIR / model_file
    if not model_path.exists():
        raise HTTPException(status_code=404, detail=f"模型文件不存在: {model_file}")
    os.remove(model_path)
    logger.info(f"ML模型已删除: {model_file}")
    return {"status": "ok", "message": f"模型 {model_file} 已删除"}


@router.post("/api/ml/train", response_model=MLTrainResponse)
async def ml_train(req: MLTrainRequest):
    """用已加载的K线数据训练模型并保存 — walk-forward 验证"""
    try:
        if not req.kline_data or len(req.kline_data) < 300:
            raise HTTPException(status_code=400, detail=f"K线数据不足，至少300条，当前{len(req.kline_data)}条")

        df = pd.DataFrame(req.kline_data)
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'])

        df, feature_cols = build_ml_features(df)
        df = df.dropna(subset=feature_cols + ['label_dir']).reset_index(drop=True)

        if len(df) < 200:
            raise HTTPException(status_code=400, detail=f"特征构造后数据不足: {len(df)} 行（需要≥200）")

        n = len(df)
        seeds = [42, 73, 101]
        models = []

        # ---- Walk-Forward 验证（3折 expanding window） ----
        # fold 1: [0, 60%] → train, [60%, 75%] → val
        # fold 2: [0, 70%] → train, [70%, 85%] → val
        # fold 3: [0, 80%] → train, [80%, 100%] → val
        splits = [
            (int(n * 0.60), int(n * 0.75)),
            (int(n * 0.70), int(n * 0.85)),
            (int(n * 0.80), n),
        ]

        fold_metrics = []
        for fold_i, (train_end, val_end) in enumerate(splits):
            train_df = df.iloc[:train_end]
            val_df = df.iloc[train_end:val_end]

            if len(val_df) < 20:
                continue

            Xtr, ytr = train_df[feature_cols].values, train_df['label_dir'].values
            Xva, yva = val_df[feature_cols].values, val_df['label_dir'].values

            n0, n1, n2 = (ytr == 0).sum(), (ytr == 1).sum(), (ytr == 2).sum()
            class_weight = {}
            if 0 in set(ytr): class_weight[0] = 1.0
            if 1 in set(ytr): class_weight[1] = n0 / max(n1, 1)
            if 2 in set(ytr): class_weight[2] = n0 / max(n2, 1)

            fold_models = []
            fold_probs = []
            for seed in seeds:
                m = lgb.LGBMClassifier(
                    n_estimators=800, learning_rate=0.02, num_leaves=8, max_depth=4,
                    min_child_samples=20, subsample=0.7, colsample_bytree=0.6,
                    reg_alpha=0.3, reg_lambda=0.5, min_split_gain=0.005,
                    random_state=seed, verbosity=-1,
                    class_weight=class_weight,
                )
                m.fit(
                    Xtr, ytr,
                    eval_set=[(Xva, yva)],
                    eval_metric='multi_logloss',
                    callbacks=[lgb.early_stopping(20), lgb.log_evaluation(0)],
                )
                fold_models.append(m)
                fold_probs.append(m.predict_proba(Xva))

            # 平均概率
            probs_val = np.mean(fold_probs, axis=0)
            y_pred = np.argmax(probs_val, axis=1)

            from sklearn.metrics import accuracy_score
            acc = float(accuracy_score(yva, y_pred))
            try:
                from sklearn.metrics import roc_auc_score
                auc = float(roc_auc_score(yva, probs_val, multi_class='ovr', average='macro')) if len(np.unique(yva)) > 1 else 0.5
            except:
                auc = 0.5

            fold_metrics.append({'acc': acc, 'auc': auc, 'samples': len(val_df)})
            models.extend(fold_models)

        if not fold_metrics:
            raise HTTPException(status_code=400, detail="验证集数据不足，无法训练")

        # 用加权平均计算最终指标
        total_samples = sum(m['samples'] for m in fold_metrics)
        avg_acc = sum(m['acc'] * m['samples'] for m in fold_metrics) / total_samples
        avg_auc = sum(m['auc'] * m['samples'] for m in fold_metrics) / total_samples

        # ---- 最终模型：用全部数据再训练一次（提高部署稳定性） ----
        Xall, yall = df[feature_cols].values, df['label_dir'].values
        n0, n1, n2 = (yall == 0).sum(), (yall == 1).sum(), (yall == 2).sum()
        final_class_weight = {}
        if 0 in set(yall): final_class_weight[0] = 1.0
        if 1 in set(yall): final_class_weight[1] = n0 / max(n1, 1)
        if 2 in set(yall): final_class_weight[2] = n0 / max(n2, 1)

        final_models = []
        for seed in seeds:
            m = lgb.LGBMClassifier(
                n_estimators=500, learning_rate=0.02, num_leaves=8, max_depth=4,
                min_child_samples=20, subsample=0.7, colsample_bytree=0.6,
                reg_alpha=0.3, reg_lambda=0.5, min_split_gain=0.005,
                random_state=seed, verbosity=-1,
                class_weight=final_class_weight,
            )
            m.fit(Xall, yall)
            final_models.append(m)

        # 保存模型和特征
        now = datetime.now()
        dt_str = now.strftime('%Y%m%d_%H%M%S')
        contract_str = (req.contract or 'unknown').replace('/', '_') if req.contract else 'unknown'

        if req.overwrite:
            model_file = req.overwrite
        else:
            model_file = f"{contract_str}_{dt_str}.pkl"
        model_path = ML_MODEL_DIR / model_file

        import joblib
        joblib.dump({
            'models': final_models,
            'feature_cols': feature_cols,
            'seeds': seeds,
            'accuracy': avg_acc,
            'auc': avg_auc,
            'train_samples': len(df),
            'contract': req.contract or '',
            'trained_at': now.isoformat(),
            'fold_metrics': fold_metrics,
        }, model_path)

        logger.info(f"ML模型已保存: {model_file} (acc={avg_acc:.4f}, auc={avg_auc:.4f}, folds={len(fold_metrics)})")

        return MLTrainResponse(
            status='ok',
            model_file=model_file,
            train_samples=len(df),
            feature_count=len(feature_cols),
            accuracy=avg_acc,
            auc=avg_auc,
            message=f'模型训练完成（{len(fold_metrics)}折验证），准确率{avg_acc:.2%}，AUC={avg_auc:.4f}',
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ML训练失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/ml/backtest", response_model=MLBacktestResponse)
async def ml_backtest(req: MLBacktestRequest):
    """用已保存的模型回测K线数据"""
    try:
        if not req.kline_data or len(req.kline_data) < 100:
            raise HTTPException(status_code=400, detail=f"K线数据不足")

        # 选择模型：指定文件或用最新的
        model_path = None
        if req.model_file:
            mp = ML_MODEL_DIR / req.model_file
            if mp.exists():
                model_path = mp
            else:
                raise HTTPException(status_code=400, detail=f"模型文件不存在: {req.model_file}")
        else:
            model_files = sorted(ML_MODEL_DIR.glob("*.pkl"), key=os.path.getmtime, reverse=True)
            if not model_files:
                raise HTTPException(status_code=400, detail="没有已训练的模型，请先训练")
            model_path = model_files[0]

        import joblib
        model_data = joblib.load(model_path)
        models = model_data['models']
        feature_cols = model_data['feature_cols']

        df = pd.DataFrame(req.kline_data)
        raw_count = len(df)
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'])

        df, _ = build_ml_features(df)
        df = df.dropna(subset=feature_cols + ['label_dir', 'ma20_direction']).reset_index(drop=True)
        # 预测全部（3分类概率）
        X = df[feature_cols].values
        # 每个模型的预测都是 [样本数, 3] 概率
        all_probs = np.mean([m.predict_proba(X) for m in models], axis=0)  # [样本数, n_classes]
        # 兼容旧版二分类模型: [P_0, P_1] -> [1-P_1, P_1*0.3, P_1*0.7]
        if all_probs.shape[1] == 2:
            p0 = 1 - all_probs[:, 1]
            p1 = all_probs[:, 1] * 0.3
            p2 = all_probs[:, 1] * 0.7
            all_probs = np.column_stack([p0, p1, p2])
        
        y_true = df["label_dir"].values
        y_pred = np.argmax(all_probs, axis=1)

        from sklearn.metrics import accuracy_score
        acc = float(accuracy_score(y_true, y_pred))
        try:
            from sklearn.metrics import roc_auc_score
            auc = float(roc_auc_score(y_true, all_probs, multi_class="ovr", average="macro")) if len(np.unique(y_true)) > 1 else 0.5
        except:
            auc = 0.5

        # 生成信号：P2(做多概率) - P0,  P1(做空概率) - P0
        # 差值 > conf_thresh 才出手
        conf_thresh = 0.15
        test_rets = df["label_ret"].values
        ma_dirs = df["ma20_direction"].values

        signals_list = []
        strat_rets = []

        for i in range(len(df)):
            p0, p1, p2 = all_probs[i]
            long_conf = p2 - p0  # 做多置信度
            short_conf = p1 - p0  # 做空置信度
            
            raw_signal = None
            if long_conf > conf_thresh and long_conf > short_conf:
                raw_signal = 2  # LONG
            elif short_conf > conf_thresh and short_conf > long_conf:
                raw_signal = 1  # SHORT
            else:
                raw_signal = 0  # WAIT
            
            if raw_signal == 0:
                signals_list.append(MLSignalItem(
                    time=df["time"].iloc[i].strftime("%Y-%m-%d %H:%M") if "time" in df.columns else "",
                    price=float(df["close"].iloc[i]),
                    signal="WAIT", confidence=0.0, prob=float(max(p1, p2)),
                ))
                continue

            if req.use_filter:
                if raw_signal == 2 and ma_dirs[i] < 0:
                    signals_list.append(MLSignalItem(
                        time=df["time"].iloc[i].strftime("%Y-%m-%d %H:%M") if "time" in df.columns else "",
                        price=float(df["close"].iloc[i]),
                        signal="WAIT", confidence=0.0, prob=float(max(p1, p2)),
                    ))
                    continue
                if raw_signal == 1 and ma_dirs[i] > 0:
                    signals_list.append(MLSignalItem(
                        time=df["time"].iloc[i].strftime("%Y-%m-%d %H:%M") if "time" in df.columns else "",
                        price=float(df["close"].iloc[i]),
                        signal="WAIT", confidence=0.0, prob=float(max(p1, p2)),
                    ))
                    continue

            ret = test_rets[i]
            strat_ret = ret if raw_signal == 2 else -ret
            strat_rets.append(strat_ret)

            signals_list.append(MLSignalItem(
                time=df["time"].iloc[i].strftime("%Y-%m-%d %H:%M") if "time" in df.columns else "",
                price=float(df["close"].iloc[i]),
                signal="LONG" if raw_signal == 2 else "SHORT",
                confidence=float(abs(long_conf if raw_signal == 2 else short_conf)),
                prob=float(max(p1, p2)),
            ))
        multiplier = get_multiplier(req.contract or '')
        commission_rate = 0.0001
        trades_list = []
        pos = 0  # 1=做多, -1=做空, 0=空仓
        entry_price = 0
        entry_equity = 100000  # 开仓时的权益
        equity = 100000
        prev_signal = None
        for s in signals_list:
            if s.signal == 'WAIT':
                continue
            signal_changed = s.signal != prev_signal
            if not signal_changed:
                continue  # 方向不变时不开新仓
            
            if pos == 0:
                # 空仓开新仓
                entry_price = s.price
                entry_equity = equity
                com = s.price * multiplier * commission_rate
                equity -= com
                action = '买开' if s.signal == 'LONG' else '卖开'
                trades_list.append({'time': s.time, 'action': action, 'price': s.price, 'quantity': 1, 'equity': round(equity, 2), 'pnl': 0, 'reason': 'ML信号'})
                pos = 1 if s.signal == 'LONG' else -1
            else:
                # 平仓：先平旧仓（有盈亏），再开新仓
                if pos == 1:
                    # 平多仓
                    pnl = (s.price - entry_price) * multiplier
                else:
                    # 平空仓
                    pnl = (entry_price - s.price) * multiplier
                com = s.price * multiplier * commission_rate
                equity += pnl - com
                close_action = '卖平' if pos == 1 else '买平'
                trades_list.append({'time': s.time, 'action': close_action, 'price': s.price, 'quantity': 1, 'equity': round(equity, 2), 'pnl': round(pnl - com, 2), 'reason': 'ML信号平' + ('多' if pos == 1 else '空')})
                # 开新仓
                entry_price = s.price
                entry_equity = equity
                com2 = s.price * multiplier * commission_rate
                equity -= com2
                open_action = '买开' if s.signal == 'LONG' else '卖开'
                trades_list.append({'time': s.time, 'action': open_action, 'price': s.price, 'quantity': 1, 'equity': round(equity, 2), 'pnl': 0, 'reason': 'ML信号开' + ('多' if s.signal == 'LONG' else '空')})
                pos = 1 if s.signal == 'LONG' else -1
            
            prev_signal = s.signal
        
        # 如果最后还有持仓，强制平仓
        if pos != 0 and len(signals_list) > 0:
            last_s = signals_list[-1]
            if last_s.signal != 'WAIT':
                if pos == 1:
                    pnl = (last_s.price - entry_price) * multiplier
                else:
                    pnl = (entry_price - last_s.price) * multiplier
                com = last_s.price * multiplier * commission_rate
                equity += pnl - com
                close_action = '卖平' if pos == 1 else '买平'
                trades_list.append({'time': last_s.time, 'action': close_action, 'price': last_s.price, 'quantity': 1, 'equity': round(equity, 2), 'pnl': round(pnl - com, 2), 'reason': 'ML信号强制平仓'})

        # 基于交易记录计算策略收益指标
        trade_equities = [t['equity'] for t in trades_list]
        if len(trade_equities) > 1:
            initial_equity = 100000
            final_equity = trade_equities[-1]
            strategy_return = (final_equity - initial_equity) / initial_equity
            # 权益曲线：用每次交易后的equity构建
            equity_curve_list = [{'time': t['time'], 'value': t['equity']} for t in trades_list]
            # 夏普：用每笔平仓的收益率算
            trade_rets = []
            for t in trades_list:
                if t['pnl'] != 0:  # 只有平仓有pnl
                    # 找开仓时的equity
                    idx = trades_list.index(t)
                    prev_equity = trades_list[idx - 1]['equity'] if idx > 0 else 100000
                    trade_rets.append(t['pnl'] / prev_equity)
            if len(trade_rets) > 1:
                trade_rets_arr = np.array(trade_rets)
                strategy_sharpe = float(trade_rets_arr.mean() / trade_rets_arr.std() * np.sqrt(244 * 6)) if trade_rets_arr.std() > 1e-10 else 0
            else:
                strategy_sharpe = 0
            # 最大回撤
            equity_values = np.array(trade_equities)
            peak = np.maximum.accumulate(equity_values)
            dd = equity_values / peak - 1
            strategy_max_dd = float(dd.min()) if len(dd) > 0 else 0
        else:
            strategy_return = 0
            strategy_sharpe = 0
            strategy_max_dd = 0
            equity_curve_list = []

        bm_long = float((1 + np.nan_to_num(test_rets)).prod() - 1)
        bm_short = float((1 - np.nan_to_num(test_rets)).prod() - 1)

        latest = signals_list[-1] if signals_list else MLSignalItem(time='', price=0, signal='WAIT', confidence=0, prob=0.5)
        signal_count = sum(1 for s in signals_list if s.signal != 'WAIT')

        return MLBacktestResponse(
            status='ok',
            total_samples=raw_count,
            signal_samples=len(df),
            signal_count=signal_count,
            accuracy=acc,
            auc=auc,
            strategy_return=strategy_return,
            strategy_sharpe=strategy_sharpe,
            strategy_max_dd=strategy_max_dd,
            benchmark_long=bm_long,
            benchmark_short=bm_short,
            latest_signal=latest.signal,
            latest_price=latest.price,
            signals=signals_list[-100:],
            trades=trades_list,
            equity_curve=equity_curve_list,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ML回测失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
