"""行情下载模块：东方财富 K 线 API 与 yfinance 双数据源互为备份。

- 港股：主用东方财富（前复权，与股票池同源），失败列表交 yfinance 兜底。
- 美股：主用 yfinance（复权质量高），失败列表交东方财富兜底
  （美股 secid 前缀：105=NASDAQ, 106=NYSE, 107=NYSE American）。

返回 {ticker: DataFrame[open, high, low, close, volume]}（索引为日期）。
允许部分失败，由调用方判定成功率是否达标。
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd
import requests

log = logging.getLogger("quotes")

MIN_ROWS = 120          # 最少有效交易日数
EM_THREADS = 6          # 东方财富并发
YF_BATCH = 60           # yfinance 单批数量
YF_SLEEP = 1.5          # yfinance 批次间隔秒

EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EM_HEADERS = {"User-Agent": "Mozilla/5.0"}

# IWB Exchange 列 -> 东财美股市场前缀
US_EXCHANGE_MAP = {
    "NASDAQ": "105",
    "NYSE": "106",
    "Nyse Mkt Llc": "107",     # NYSE American
    "Cboe BZX": "105",         # 个别Cboe上市股票，先试105
}


# ---------------------------------------------------------------- 东方财富

def _em_secids(market: str, ticker: str, exchange: str = "") -> list[str]:
    if market == "HK":
        return [f"116.{ticker.split('.')[0].zfill(5)}"]
    # 美股：ticker 已是 yfinance 风格（BRK-B），东财用 BRK.B
    em = ticker.replace("-", ".")
    prefix = US_EXCHANGE_MAP.get(str(exchange).strip(), "105")
    cands = [f"{prefix}.{em}"]
    # 交易所未知时的备选前缀
    for p in ("105", "106", "107"):
        c = f"{p}.{em}"
        if c not in cands:
            cands.append(c)
    return cands


def _em_one(secids: list[str], beg: str, end: str) -> pd.DataFrame | None:
    s = requests.Session()
    s.trust_env = False  # 东财直连即可，绕过本机代理抖动
    for secid in secids:
        for attempt in range(2):
            try:
                r = s.get(EM_KLINE_URL, params={
                    "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56",
                    "klt": "101", "fqt": "1",
                    "beg": beg, "end": end, "lmt": "10000",
                }, headers=_EM_HEADERS, timeout=20)
                kl = (r.json().get("data") or {}).get("klines") or []
                if kl:
                    rows = [k.split(",") for k in kl]
                    df = pd.DataFrame(rows, columns=[
                        "date", "open", "close", "high", "low", "volume"])
                    df["date"] = pd.to_datetime(df["date"])
                    for c in ["open", "close", "high", "low", "volume"]:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
                    df = df.set_index("date")[
                        ["open", "high", "low", "close", "volume"]].dropna()
                    return df if len(df) >= MIN_ROWS else None
                break  # 有响应但无数据，换下一个 secid
            except Exception:  # noqa: BLE001
                time.sleep(0.8 * (attempt + 1))
    return None


def em_download(market: str, tickers: list[str],
                exchanges: dict[str, str] | None = None) -> tuple[dict, list[str]]:
    beg = (datetime.utcnow() - timedelta(days=760)).strftime("%Y%m%d")
    end = datetime.utcnow().strftime("%Y%m%d")
    ok: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    jobs = {t: _em_secids(market, t, (exchanges or {}).get(t, ""))
            for t in tickers}
    with ThreadPoolExecutor(max_workers=EM_THREADS) as ex:
        futs = {ex.submit(_em_one, ids, beg, end): t
                for t, ids in jobs.items()}
        done = 0
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                df = fut.result()
            except Exception:  # noqa: BLE001
                df = None
            (ok.__setitem__(t, df) if df is not None else failed.append(t))
            done += 1
            if done % 100 == 0:
                log.info("  东财进度 %d/%d（成功 %d）", done, len(tickers), len(ok))
    return ok, failed


# ---------------------------------------------------------------- yfinance

def yf_download(tickers: list[str]) -> tuple[dict, list[str]]:
    import yfinance as yf

    ok: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    batches = [tickers[i:i + YF_BATCH] for i in range(0, len(tickers), YF_BATCH)]
    for bi, batch in enumerate(batches, 1):
        df = None
        for attempt in range(3):
            try:
                df = yf.download(" ".join(batch), period="2y", interval="1d",
                                 auto_adjust=True, group_by="ticker",
                                 threads=True, progress=False)
                if df is not None and len(df):
                    break
            except Exception as e:  # noqa: BLE001
                log.warning("  yf 批次 %d 第 %d 次失败: %s", bi, attempt + 1, e)
            time.sleep(2 * attempt + 1)
        if df is None or not len(df):
            failed += batch
        else:
            for t in batch:
                try:
                    sub = df[t].copy() if isinstance(df.columns, pd.MultiIndex) \
                        and t in df.columns.get_level_values(0) else None
                except Exception:  # noqa: BLE001
                    sub = None
                if sub is None or not len(sub.dropna()):
                    failed.append(t)
                    continue
                sub.columns = [str(c).lower() for c in sub.columns]
                sub = sub.rename(columns={"adj close": "close"})
                need = ["open", "high", "low", "close", "volume"]
                if not all(c in sub.columns for c in need):
                    failed.append(t)
                    continue
                sub = sub[need].dropna()
                if len(sub) < MIN_ROWS:
                    failed.append(t)
                    continue
                sub.index = pd.to_datetime(sub.index).tz_localize(None)
                ok[t] = sub
        if bi < len(batches):
            time.sleep(YF_SLEEP)
    return ok, failed


# ---------------------------------------------------------------- 入口

def download_quotes(market: str, tickers: list[str],
                    exchanges: dict[str, str] | None = None
                    ) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """双源互备下载。返回 (成功字典, 失败代码)。"""
    primary = "em" if market == "HK" else "yf"
    ok: dict[str, pd.DataFrame] = {}
    failed = tickers[:]

    for source in (primary, "yf" if primary == "em" else "em"):
        if not failed:
            break
        todo, failed = failed, []
        log.info("[%s] %s 源下载 %d 只…", market, source.upper(), len(todo))
        if source == "em":
            got, failed = em_download(market, todo, exchanges)
        else:
            got, failed = yf_download(todo)
        ok.update(got)
        log.info("[%s] %s 源成功 %d，剩 %d 待兜底",
                 market, source.upper(), len(got), len(failed))
        if failed:
            time.sleep(3)
    log.info("[%s] 行情完成: 成功 %d，失败 %d", market, len(ok), len(failed))
    return ok, failed
