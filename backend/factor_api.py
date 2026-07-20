"""
多因子动态评分模型 API v2 — 自适应模式
- 7个独立因子，分组：趋势组 vs 反转组
- ADX 判断市场状态 → 自动切换因子组合
- 近30/60/90/120根K线收益滚动评分，越近权重越大
- 因子评分动态分配权重
- 加权ensemble回测（修复WAIT扛单bug）
"""
import os
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import logging
logger = logging.getLogger('factor_api')

router = APIRouter()
import warnings
warnings.filterwarnings('ignore')


# ============================================================
# 因子定义
# ============================================================

FACTOR_DEFS = [
    {"id": "ma_cross",    "name": "均线交叉",   "desc": "MA5上穿MA20做多，下穿做空", "group": "trend"},
    {"id": "rsi",         "name": "RSI反转",    "desc": "RSI<30超卖做多，>70超买做空", "group": "reversal"},
    {"id": "macd",        "name": "MACD",       "desc": "MACD线上穿信号线做多，下穿做空", "group": "trend"},
    {"id": "bb",          "name": "布林带",     "desc": "触及下轨做多，上轨做空", "group": "reversal"},
    {"id": "volume",      "name": "成交量突破", "desc": "放量+价格突破均线", "group": "reversal"},
    {"id": "momentum",    "name": "动量ROC",    "desc": "10期ROC趋势方向", "group": "trend"},
    {"id": "ma_trend",    "name": "均线排列",   "desc": "价格相对多周期均线位置综合评分", "group": "trend"},
]

TREND_FACTORS = [f["id"] for f in FACTOR_DEFS if f["group"] == "trend"]
REVERSAL_FACTORS = [f["id"] for f in FACTOR_DEFS if f["group"] == "reversal"]
ALL_FACTORS = [f["id"] for f in FACTOR_DEFS]


def compute_adx(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    """计算 ADX 趋势强度指标"""
    high, low, close = df['high'].values, df['low'].values, df['close'].values
    n = len(df)

    # True Range
    tr = np.full(n, np.nan)
    tr[1:] = np.maximum(high[1:] - low[1:],
             np.maximum(np.abs(high[1:] - close[:-1]),
                        np.abs(low[1:] - close[:-1])))

    # Directional Movement
    up_move = np.full(n, 0.0)
    down_move = np.full(n, 0.0)
    up_move[1:] = high[1:] - high[:-1]
    down_move[1:] = low[:-1] - low[1:]

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Smoothed
    tr_smooth = pd.Series(np.nan_to_num(tr)).rolling(period).mean().values
    plus_smooth = pd.Series(plus_dm).rolling(period).mean().values
    minus_smooth = pd.Series(minus_dm).rolling(period).mean().values

    # DI
    plus_di = np.where(tr_smooth > 1e-10, 100 * plus_smooth / tr_smooth, 0.0)
    minus_di = np.where(tr_smooth > 1e-10, 100 * minus_smooth / tr_smooth, 0.0)

    # DX → ADX
    dx = np.full(n, np.nan)
    di_sum = plus_di + minus_di
    mask = di_sum > 1e-10
    dx[mask] = 100 * np.abs(plus_di[mask] - minus_di[mask]) / di_sum[mask]
    adx = pd.Series(np.nan_to_num(dx)).rolling(period).mean().values

    return adx


def detect_market_regime(df: pd.DataFrame) -> dict:
    """
    检测当前市场状态
    返回 {'regime': 'trending'|'ranging', 'adx': float, 'adx_latest': float}
    """
    adx = compute_adx(df, period=14)
    n = len(adx)

    # 取最近120根K线的平均ADX（或全部）
    lookback = min(120, n)
    recent_adx = np.nanmean(adx[-lookback:]) if lookback > 0 else 25

    # 也看最新值作为实时参考
    latest_adx = float(adx[-1]) if n > 0 and not np.isnan(adx[-1]) else 25

    regime = 'trending' if recent_adx >= 22 else 'ranging'

    return {
        'regime': regime,
        'adx_avg': round(float(recent_adx), 2),
        'adx_latest': round(float(latest_adx), 2),
        'adx_values': [float(round(a, 2)) for a in adx[-60:] if not np.isnan(a)],
    }


def compute_factor_signals(df: pd.DataFrame) -> dict:
    """对所有因子计算信号，返回 { factor_id: np.array([1,0,-1,...]) }"""
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values
    n = len(df)

    ma5 = pd.Series(close).rolling(5).mean().values
    ma10 = pd.Series(close).rolling(10).mean().values
    ma20 = pd.Series(close).rolling(20).mean().values
    ma40 = pd.Series(close).rolling(40).mean().values

    # RSI
    delta = pd.Series(close).diff()
    gain = delta.clip(lower=0).rolling(14).mean().values
    loss = (-delta.clip(upper=0)).rolling(14).mean().values
    rsi = np.full(n, 50.0)
    mask = loss > 1e-10
    rsi[mask] = 100 - 100 / (1 + gain[mask] / loss[mask])

    # MACD
    ema12 = pd.Series(close).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(close).ewm(span=26, adjust=False).mean().values
    macd_line = ema12 - ema26
    macd_signal = pd.Series(macd_line).ewm(span=9, adjust=False).mean().values

    # Bollinger Bands
    bb_mid = pd.Series(close).rolling(20).mean().values
    bb_std = pd.Series(close).rolling(20).std().values
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    vol_ma10 = pd.Series(volume).rolling(10).mean().values
    roc10 = np.full(n, 0.0)
    roc10[10:] = close[10:] / close[:-10] - 1

    signals = {}

    # 1. 均线交叉 (trend)
    sig = np.zeros(n, dtype=float)
    sig[5:] = np.where(ma5[5:] > ma20[5:], 1, np.where(ma5[5:] < ma20[5:], -1, 0))
    signals['ma_cross'] = sig

    # 2. RSI反转 (reversal)
    sig = np.zeros(n, dtype=float)
    sig[:] = np.where(rsi < 30, 1, np.where(rsi > 70, -1, 0))
    signals['rsi'] = sig

    # 3. MACD (trend)
    sig = np.zeros(n, dtype=float)
    sig[26:] = np.where(macd_line[26:] > macd_signal[26:], 1, np.where(macd_line[26:] < macd_signal[26:], -1, 0))
    signals['macd'] = sig

    # 4. 布林带 (reversal)
    sig = np.zeros(n, dtype=float)
    sig[:] = np.where(close < bb_lower, 1, np.where(close > bb_upper, -1, 0))
    signals['bb'] = sig

    # 5. 成交量突破 (reversal)
    sig = np.zeros(n, dtype=float)
    vol_surge = volume > vol_ma10 * 1.5
    sig[:] = np.where(vol_surge & (close > ma5), 1, np.where(vol_surge & (close < ma5), -1, 0))
    signals['volume'] = sig

    # 6. 动量ROC (trend)
    sig = np.zeros(n, dtype=float)
    sig[:] = np.where(roc10 > 0.02, 1, np.where(roc10 < -0.02, -1, 0))
    signals['momentum'] = sig

    # 7. 均线排列 (trend)
    sig = np.zeros(n, dtype=float)
    for i in range(n):
        above = sum(1 for ma in [ma5[i], ma10[i], ma20[i], ma40[i]]
                    if not np.isnan(ma) and close[i] > ma)
        sig[i] = 1 if above >= 3 else (-1 if above <= 1 else 0)
    signals['ma_trend'] = sig

    return signals


def compute_rolling_returns(signals: np.ndarray, bar_rets: np.ndarray,
                            periods: List[int]) -> dict:
    n = len(signals)
    strat_rets = signals * bar_rets
    result = {}
    for p in periods:
        if n < p:
            result[p] = 0.0
        else:
            result[p] = float(np.nan_to_num(strat_rets[-p:]).sum())
    return result


# ============================================================
# Pydantic 模型
# ============================================================

class FactorBacktestRequest(BaseModel):
    kline_data: List[dict] = Field(..., description="K线数据 [{time, open, high, low, close, volume, hold}]")
    periods: List[int] = Field([10, 20, 30, 50], description="评分周期列表")
    period_weights: List[float] = Field([0.4, 0.3, 0.2, 0.1], description="周期权重（从近到远）")
    factor_filter: List[str] = Field([], description="只计算指定因子，为空则全部")
    threshold: float = Field(0.15, description="ensemble信号阈值(0~1)")
    mode: str = Field("auto", description="模式: trending(趋势)/ranging(震荡)/auto(自适应)")


class FactorBacktestResponse(BaseModel):
    status: str
    factors: list = []
    ensemble: dict = {}
    kline_signals: list = []
    regime: dict = {}


# ============================================================
# API 端点
# ============================================================

@router.get("/api/factors/list")
async def list_factors():
    """列出所有可用因子"""
    return FACTOR_DEFS


@router.post("/api/factors/backtest", response_model=FactorBacktestResponse)
async def factor_backtest(req: FactorBacktestRequest):
    """多因子动态评分 + 自适应模式 + ensemble回测"""
    try:
        if not req.kline_data or len(req.kline_data) < 200:
            raise HTTPException(status_code=400,
                                detail=f"K线数据不足，至少200条，当前{len(req.kline_data)}条")

        kline_data = req.kline_data
        df = pd.DataFrame(kline_data)
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values('time').reset_index(drop=True)
        n = len(df)
        close = df['close'].values

        # 每日收益率
        bar_rets = np.full(n, 0.0)
        bar_rets[:-1] = close[1:] / close[:-1] - 1

        # ---- 市场状态检测（自适应） ----
        regime_info = detect_market_regime(df)
        regime = regime_info['regime']

        # ---- 根据模式筛选因子 ----
        if req.mode == "auto":
            # 自适应：ADX决定趋势/震荡
            factor_ids = TREND_FACTORS if regime == "trending" else REVERSAL_FACTORS
        elif req.mode == "trending":
            factor_ids = TREND_FACTORS
        elif req.mode == "ranging":
            factor_ids = REVERSAL_FACTORS
        else:
            factor_ids = ALL_FACTORS

        # 如果指定了factor_filter，取交集
        if req.factor_filter:
            factor_ids = [f for f in factor_ids if f in req.factor_filter]

        if not factor_ids:
            raise HTTPException(status_code=400, detail=f"当前模式({req.mode})下无可用因子")

        # ---- 计算因子信号 ----
        all_signals = compute_factor_signals(df)
        periods = req.periods
        p_weights = req.period_weights
        if len(p_weights) != len(periods):
            p_weights = [0.4, 0.3, 0.2, 0.1][:len(periods)]

        factor_results = []
        for fid in factor_ids:
            if fid not in all_signals:
                continue
            sig = all_signals[fid]
            valid_mask = sig != 0
            signal_count = int(valid_mask.sum())
            strat_rets = sig * bar_rets
            wins = (strat_rets[valid_mask] > 0).sum() if signal_count > 0 else 0
            win_rate = wins / signal_count if signal_count > 0 else 0.0
            rolling_rets = compute_rolling_returns(sig, bar_rets, periods)
            score = sum(rolling_rets.get(p, 0.0) * p_weights[i] for i, p in enumerate(periods))

            factor_results.append({
                "factor_id": fid,
                "factor_name": next((f['name'] for f in FACTOR_DEFS if f['id'] == fid), fid),
                "signal_count": signal_count,
                "win_rate": round(win_rate, 4),
                "returns": {str(p): round(rolling_rets.get(p, 0.0), 6) for p in periods},
                "dynamic_score": round(score, 6),
                "weight": 0.0,
            })

        if not factor_results:
            raise HTTPException(status_code=400, detail="没有可用的因子")

        # ---- 因子权重分配（仅正评分） ----
        scores = np.array([f['dynamic_score'] for f in factor_results])
        pos_scores = np.maximum(scores, 0)
        total_pos = pos_scores.sum()
        weights = pos_scores / total_pos if total_pos > 1e-10 else np.zeros(len(factor_results))

        for i, w in enumerate(weights):
            factor_results[i]['weight'] = round(float(w), 6)

        # ---- Ensemble 回测 ----
        ensemble_raw = np.zeros(n, dtype=float)
        for i, fid in enumerate(factor_ids):
            if fid in all_signals:
                ensemble_raw += weights[i] * all_signals[fid]

        thresh = req.threshold
        ensemble_sig = np.zeros(n, dtype=float)
        ensemble_sig[ensemble_raw > thresh] = 1
        ensemble_sig[ensemble_raw < -thresh] = -1
        ens_rets = ensemble_sig * bar_rets

        # ---- 交易记录生成 ----
        trades_list = []
        pos = 0
        entry_price = 0
        equity = 100000
        prev_signal = None
        base_equity = 100000
        mult = 100

        def close_position(exit_price, reason=''):
            nonlocal pos, entry_price, equity
            if pos == 0: return
            pnl = (exit_price - entry_price) * mult if pos == 1 else (entry_price - exit_price) * mult
            com = exit_price * mult * 0.0001
            equity += pnl - com
            close_action = '卖平' if pos == 1 else '买平'
            trades_list.append({
                'time': now_str, 'action': close_action, 'price': exit_price,
                'quantity': 1, 'equity': round(equity, 2),
                'pnl': round(pnl - com, 2), 'reason': reason or ('平' + ('多' if pos == 1 else '空'))
            })
            pos, entry_price = 0, 0

        def open_position(entry_price_, direction, reason=''):
            nonlocal pos, entry_price, equity
            pos, entry_price = direction, entry_price_
            com = entry_price * mult * 0.0001
            equity -= com
            open_action = '买开' if direction == 1 else '卖开'
            trades_list.append({
                'time': now_str, 'action': open_action, 'price': entry_price,
                'quantity': 1, 'equity': round(equity, 2),
                'pnl': 0, 'reason': reason or ('开' + ('多' if direction == 1 else '空'))
            })

        for i in range(n):
            sig_val = ensemble_sig[i]
            price = float(close[i])
            now_str = df['time'].iloc[i].strftime('%Y-%m-%d %H:%M') if 'time' in df.columns else f'bar_{i}'

            if sig_val == 0:
                if pos != 0:
                    close_position(price, '信号消失平仓')
                prev_signal = None
                continue

            if sig_val != prev_signal:
                if pos != 0:
                    close_position(price, '信号反转平仓')
                open_position(price, 1 if sig_val == 1 else -1, '信号开仓')
                prev_signal = sig_val

        if pos != 0:
            last_price = float(close[-1])
            now_str = df['time'].iloc[-1].strftime('%Y-%m-%d %H:%M') if 'time' in df.columns else 'last'
            close_position(last_price, '强制平仓')

        # ---- 计算指标 ----
        strategy_return = (equity - base_equity) / base_equity
        trade_equities = [t['equity'] for t in trades_list if t['equity']]
        if len(trade_equities) > 1:
            eq_arr = np.array(trade_equities)
            peak = np.maximum.accumulate(eq_arr)
            dd = eq_arr / peak - 1
            max_dd = float(dd.min())
            daily_rets = ens_rets[ens_rets != 0]
            sharpe = float(daily_rets.mean() / daily_rets.std() * np.sqrt(244)) if len(daily_rets) > 1 and daily_rets.std() > 1e-10 else 0
        else:
            max_dd, sharpe = 0, 0

        signal_list = []
        for i in range(max(0, n - 100), n):
            ev = float(ensemble_raw[i])
            sig_val = ensemble_sig[i]
            signal_str = 'LONG' if sig_val == 1 else ('SHORT' if sig_val == -1 else 'WAIT')
            now = df['time'].iloc[i].strftime('%Y-%m-%d %H:%M') if 'time' in df.columns else ''
            signal_list.append({
                'time': now, 'price': float(close[i]),
                'signal': signal_str, 'ensemble_value': round(ev, 3),
            })

        ensemble_result = {
            'total_return': round(strategy_return, 6),
            'sharpe': round(sharpe, 4),
            'max_dd': round(max_dd, 6),
            'trade_count': len([t for t in trades_list if '平' in t['action']]),
            'signal_count': int((ensemble_sig != 0).sum()),
        }

        return FactorBacktestResponse(
            status='ok',
            factors=factor_results,
            ensemble=ensemble_result,
            kline_signals=[s for s in signal_list][-50:],
            regime=regime_info,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"因子回测失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
