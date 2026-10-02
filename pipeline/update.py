"""主入口：构建股票池 -> 下载行情 -> 检测信号 -> 生成 docs/data.js。

用法：
    python -m pipeline.update --market all   # 美股+港股
    python -m pipeline.update --market hk    # 仅港股（港股收盘后运行）
    python -m pipeline.update --market us    # 仅美股（美股收盘后运行）

幂等合并：只更新指定市场的数据块，保留 data.js 中另一市场的既有结果。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import quotes, signals
from .universe import get_universe

log = logging.getLogger("update")

ROOT = Path(__file__).resolve().parent.parent
DATA_JS = ROOT / "app" / "data.js"

MIN_SUCCESS_RATE = 0.80   # 行情下载成功率低于此值则不更新（保留旧数据）
SERIES_DAYS = 130         # 输出序列长度（交易日）

MARKET_LABEL = {
    "US": "美股 · 罗素1000",
    "HK": "港股 · 市值≥100亿港元",
}


def _round_px(v: float) -> float:
    if v >= 100:
        return round(v, 2)
    if v >= 1:
        return round(v, 3)
    return round(v, 4)


def build_series(df: pd.DataFrame) -> dict:
    """输出前端图表所需的最近 SERIES_DAYS 个交易日序列。"""
    sub = df.tail(SERIES_DAYS)
    rsi = signals.wilder_rsi(df["close"]).tail(SERIES_DAYS)
    dates = sub.index.strftime("%Y-%m-%d").tolist()
    ohlc = [
        [_round_px(o), _round_px(c), _round_px(l), _round_px(h)]
        for o, c, l, h in zip(sub["open"], sub["close"], sub["low"], sub["high"])
    ]
    return {
        "dates": dates,
        "ohlc": ohlc,
        "close": [_round_px(v) for v in sub["close"]],
        "vol": [int(v) for v in sub["volume"]],
        "rsi": [None if pd.isna(v) else round(float(v), 1) for v in rsi],
    }


def run_market(market: str) -> dict | None:
    """跑一个市场的完整筛选，返回 data.js 中该市场的数据块。"""
    uni = get_universe(market)
    tickers = uni["ticker"].tolist()
    exchanges = (uni.set_index("ticker")["exchange"].to_dict()
                 if "exchange" in uni.columns else None)
    log.info("[%s] 股票池 %d 只，开始下载行情…", market, len(tickers))
    data, failed = quotes.download_quotes(market, tickers, exchanges)
    rate = len(data) / max(1, len(tickers))
    log.info("[%s] 行情成功率 %.1f%% (%d/%d)",
             market, rate * 100, len(data), len(tickers))
    if rate < MIN_SUCCESS_RATE:
        log.error("[%s] 成功率低于 %.0f%%，放弃本次更新", market,
                  MIN_SUCCESS_RATE * 100)
        return None

    info = uni.set_index("ticker")
    out_signals: list[dict] = []
    series: dict[str, dict] = {}
    cutoff = ""
    for t, df in data.items():
        if df.index[-1].strftime("%Y-%m-%d") > cutoff:
            cutoff = df.index[-1].strftime("%Y-%m-%d")
        try:
            sig = signals.detect_stock(df)
        except Exception as e:  # noqa: BLE001
            log.debug("[%s] %s 检测异常: %s", market, t, e)
            continue
        if sig is None:
            continue
        row = info.loc[t]
        sig["ticker"] = t
        sig["name"] = str(row["name"])
        if market == "HK" and "mcap" in row and pd.notna(row["mcap"]):
            sig["mc"] = f"{row['mcap'] / 1e8:.0f}亿"
        out_signals.append(sig)
        series[t] = build_series(df)

    out_signals.sort(key=lambda s: (s["age"], -s["lift"]))
    block = {
        "label": MARKET_LABEL[market],
        "cutoff": cutoff,
        "universe": len(tickers),
        "scanned": len(data),
        "failed": len(failed),
        "signals": out_signals,
        "series": series,
    }
    log.info("[%s] 信号 %d 只（周线确认 %d）", market, len(out_signals),
             sum(1 for s in out_signals if s["weekly"]))
    return block


def load_existing() -> dict:
    if not DATA_JS.exists():
        return {}
    try:
        text = DATA_JS.read_text(encoding="utf-8")
        payload = text.split("=", 1)[1].strip().rstrip(";")
        return json.loads(payload)
    except Exception:  # noqa: BLE001
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["us", "hk", "all"], default="all")
    args = ap.parse_args()
    markets = ["US", "HK"] if args.market == "all" else [args.market.upper()]

    rpt = load_existing()
    rpt.setdefault("markets", {})
    updated = False
    for m in markets:
        block = run_market(m)
        if block is not None:
            rpt["markets"][m] = block
            updated = True
    if not updated:
        log.error("所有市场均未更新，保留旧 data.js")
        return 1

    rpt["generated_at"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC")
    DATA_JS.parent.mkdir(exist_ok=True)
    payload = json.dumps(rpt, ensure_ascii=False, separators=(",", ":"))
    DATA_JS.write_text(f"window.RPT_DATA={payload};\n", encoding="utf-8")
    log.info("data.js 已写入 %.1f KB", DATA_JS.stat().st_size / 1024)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sys.exit(main())
