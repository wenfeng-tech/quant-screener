"""RSI(14) 底背离信号检测（与原项目口径一致，见 README「方法学」）。

统一以**收盘价**判定低点（与原项目一致：分形、新低、回采均按收盘）：
- RSI(14) Wilder 平滑，基于复权收盘价。
- 摆动低点（前低 d1）：±5 根 K 线分形确认的低点（收盘价最低）。
- 信号日 d2：收盘创新低（close[d2] < close[d1]）且 RSI 未创新低
  （rsi[d2] >= rsi[d1]，允许持平），d2 与 d1 间隔 >= 5 个交易日，
  d1 在 60 个交易日内。
- d2 为当前未确认低点：收盘价为其前 5 日内最低，且 d2 之后
  收盘价均未跌破 d2 收盘（回采有效）。
- 日龄 = d2 距最后一个交易日的交易日数（0-5 天）。
- 每只股票只保留最近一个有效信号。

周线确认：
- 周线 RSI(14)，±3 周分形前低 w1（收盘价判定）；
- 近 8 周内存在周低点 w2：周收盘新低（close[w2] < close[w1]）
  且周 RSI 未创新低，w2 之后周收盘未跌破。
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger("signals")

RSI_N = 14
FRACTAL_K = 5          # 日线分形 ±5
WK_FRACTAL_K = 3       # 周线分形 ±3
MIN_GAP = 5            # d2 与 d1 最小间隔（交易日）
MAX_LOOKBACK = 60      # d1 距 d2 最大间隔
MAX_AGE = 5            # 信号最大日龄
RSI_MAX_DAILY = 45.0   # 日线 RSI 上限（背离发生在偏弱区）
RSI_MAX_WEEKLY = 55.0  # 周线 RSI 上限
WK_LOOKBACK = 8        # 周线新低窗口（周）
LIFT_EPS = 0.051       # 「RSI 未创新低」容忍度（吸收四舍五入持平）


def wilder_rsi(close: pd.Series, n: int = RSI_N) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    dn = (-delta).clip(lower=0.0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.mask(ad.eq(0) & au.gt(0), 100.0)   # 只涨不跌
    rsi = rsi.mask(ad.eq(0) & au.eq(0), 50.0)    # 横盘
    return rsi


def _confirmed_swing_lows(px: np.ndarray, k: int) -> np.ndarray:
    """±k 分形确认的摆动低点（收盘价最低，允许并列）。"""
    n = len(px)
    out = np.zeros(n, dtype=bool)
    for i in range(k, n - k):
        w = px[i - k:i + k + 1]
        if px[i] == w.min() and (w < px[i]).sum() == 0:
            out[i] = True
    return out


def _provisional_low(i: int, close: np.ndarray, k: int) -> bool:
    """「当前低点」：收盘价为左侧 k 根内最低，且之后收盘未跌破。"""
    left = close[max(0, i - k):i]
    if len(left) and close[i] >= left.min():
        return False
    right = close[i + 1:]
    if len(right) and close[i] > right.min():
        return False
    return True


def _find_pair(close, rsi, swings, i2, max_rsi, min_gap, max_lookback):
    """给定信号低点 i2，找最近的有效前低 i1；返回 i1 或 None。"""
    if not (0 < rsi[i2] <= max_rsi):
        return None
    lo = max(0, i2 - max_lookback)
    for i1 in range(i2 - min_gap, lo - 1, -1):
        if not swings[i1]:
            continue
        if not (0 < rsi[i1] <= max_rsi):
            continue
        if close[i2] < close[i1] and rsi[i2] >= rsi[i1] - LIFT_EPS:
            return i1
    return None


def detect_daily(df: pd.DataFrame) -> dict | None:
    """日线底背离。返回信号 dict 或 None。"""
    close = df["close"].to_numpy(float)
    rsi = wilder_rsi(df["close"]).to_numpy(float)
    n = len(df)
    if n < MAX_LOOKBACK + 10:
        return None
    swings = _confirmed_swing_lows(close, FRACTAL_K)
    for age in range(0, MAX_AGE + 1):
        i2 = n - 1 - age
        if i2 < MAX_LOOKBACK // 2:
            break
        if not _provisional_low(i2, close, FRACTAL_K):
            continue
        i1 = _find_pair(close, rsi, swings, i2,
                        RSI_MAX_DAILY, MIN_GAP, MAX_LOOKBACK)
        if i1 is None:
            continue
        dates = df.index
        last_close = close[-1]
        return {
            "d1": dates[i1].strftime("%Y-%m-%d"),
            "c1": round(float(close[i1]), 4),
            "r1": round(float(rsi[i1]), 1),
            "d2": dates[i2].strftime("%Y-%m-%d"),
            "c2": round(float(close[i2]), 4),
            "r2": round(float(rsi[i2]), 1),
            "lift": round(float(rsi[i2] - rsi[i1]), 1),
            "age": int(age),
            "post": round((last_close / close[i2] - 1) * 100, 1),
            "last": round(float(last_close), 4),
        }
    return None


def weekly_confirm(df: pd.DataFrame) -> tuple[bool, str | None]:
    """周线底背离确认。返回 (是否确认, 周线低点周日)。"""
    wk = df.resample("W-FRI").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    if len(wk) < 30:
        return False, None
    close = wk["close"].to_numpy(float)
    rsi = wilder_rsi(wk["close"]).to_numpy(float)
    n = len(wk)
    swings = _confirmed_swing_lows(close, WK_FRACTAL_K)
    for back in range(0, WK_LOOKBACK + 1):
        w2 = n - 1 - back
        if w2 < 15:
            break
        if not _provisional_low(w2, close, WK_FRACTAL_K):
            continue
        w1 = _find_pair(close, rsi, swings, w2,
                        RSI_MAX_WEEKLY, WK_FRACTAL_K, 30)
        if w1 is not None:
            return True, wk.index[w2].strftime("%Y-%m-%d")
    return False, None


def detect_stock(df: pd.DataFrame) -> dict | None:
    sig = detect_daily(df)
    if sig is None:
        return None
    wk_ok, wk_date = weekly_confirm(df)
    sig["weekly"] = bool(wk_ok)
    sig["weekly_low"] = wk_date or ""
    return sig
