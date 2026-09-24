#!/usr/bin/env python3
"""
RSI(14) Bullish Divergence Screener
Universes: US Russell 1000, HK stocks with market cap >= HK$10B.
Output:  app/data.js  (consumed by app/index.html)
"""
import json, time, datetime, sys, io
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
UNIVERSE_CACHE = ROOT / "pipeline" / "universe.json"
RSI_PERIOD = 14
SWING_W = 5
MAX_AGE = 5
HK_MIN_MCAP = 10_000_000_000  # HK$10B
CACHE_DAYS = 7

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
HEADERS = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}

# Fallback Russell 1000 list (validated yfinance symbols), used only if Wikipedia fails.
US_FALLBACK_CSV = ("https://raw.githubusercontent.com/BackupBackupFede/"
                   "Russell1000_Yfinance_List/main/russell1000_full_enriched.csv")


# ----------------------------------------------------------------------------
# Indicators
# ----------------------------------------------------------------------------
def calc_rsi(closes, period=RSI_PERIOD):
    """Wilder's RSI. NaN for the first `period` bars."""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    rsi = np.full(n, np.nan)
    if n <= period:
        return rsi
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()

    def rsi_value(ag, al):
        if al == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    rsi[period] = rsi_value(avg_gain, avg_loss)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi[i + 1] = rsi_value(avg_gain, avg_loss)
    return rsi


def find_swing_lows(prices, w=SWING_W):
    return [i for i in range(w, len(prices) - w)
            if prices[i] == min(prices[i - w:i + w + 1])]


def detect_divergence(dates, closes, rsi):
    """Bullish divergence: price makes a lower low while RSI makes a higher low."""
    signals = []
    n = len(closes)
    if n < 60:
        return signals
    lows = find_swing_lows(closes)
    if len(lows) < 2:
        return signals
    for j in range(1, len(lows)):
        i1, i2 = lows[j - 1], lows[j]
        if np.isnan(rsi[i1]) or np.isnan(rsi[i2]):
            continue
        if closes[i2] < closes[i1] and rsi[i2] > rsi[i1]:
            age = n - 1 - i2
            if age > MAX_AGE:
                continue
            weekly = bool(rsi[i2] > rsi[max(0, i2 - 10)]) if i2 >= 10 else False
            post = ((closes[-1] - closes[i2]) / closes[i2] * 100) if i2 < n - 1 else 0.0
            signals.append(dict(
                d1=dates[i1], d2=dates[i2],
                c1=round(float(closes[i1]), 2), c2=round(float(closes[i2]), 2),
                r1=round(float(rsi[i1]), 1), r2=round(float(rsi[i2]), 1),
                lift=round(float(rsi[i2] - rsi[i1]), 1),
                post=round(float(post), 1), age=age, weekly=weekly))
    return signals


# ----------------------------------------------------------------------------
# Universe construction
# ----------------------------------------------------------------------------
def _yf_symbol(sym):
    """yfinance uses '-' instead of '.' in US class symbols (BRK.B -> BRK-B)."""
    return sym.replace(".", "-").strip()


def _parse_wiki_table(html):
    for tbl in pd.read_html(io.StringIO(html)):
        cols = [str(c).lower() for c in tbl.columns]
        if any("ticker" in c or "symbol" in c for c in cols) and \
           any("company" in c for c in cols):
            tcol = next(i for i, c in enumerate(cols) if "ticker" in c or "symbol" in c)
            ncol = next(i for i, c in enumerate(cols) if "company" in c)
            out = []
            for _, row in tbl.iterrows():
                sym = _yf_symbol(str(row.iloc[tcol]))
                name = str(row.iloc[ncol]).split("[")[0].strip()
                if sym and name and sym.lower() != "nan":
                    out.append([sym, name, "US"])
            if out:
                return out
    return None


def get_us_tickers():
    print("[US] Fetching Russell 1000 constituents...", flush=True)
    wiki_urls = [
        "https://en.wikipedia.org/wiki/List_of_Russell_1000_companies",
        "https://en.wikipedia.org/wiki/Russell_1000_Index",
    ]
    # 1) Wikipedia via requests with a browser User-Agent (default urllib UA gets 403)
    for url in wiki_urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                out = _parse_wiki_table(r.text)
                if out:
                    print(f"[US] Wikipedia OK: {len(out)} tickers", flush=True)
                    return out
            print(f"[US] {url} -> HTTP {r.status_code}", flush=True)
        except Exception as e:
            print(f"[US] {url} failed: {e}", flush=True)

    # 2) Fallback: validated yfinance Russell 1000 CSV on GitHub
    try:
        r = requests.get(US_FALLBACK_CSV, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            df = pd.read_csv(io.StringIO(r.text.lstrip("\ufeff")))
            out = [[_yf_symbol(str(s)), str(n).strip(), "US"]
                   for n, s in zip(df["Company"], df["Symbol"])]
            out = [o for o in out if o[0] and o[0].lower() != "nan"]
            if out:
                print(f"[US] GitHub fallback OK: {len(out)} tickers", flush=True)
                return out
    except Exception as e:
        print(f"[US] fallback CSV failed: {e}", flush=True)

    print("[US] WARNING: all Russell 1000 sources failed", flush=True)
    return []


def get_hk_tickers(min_mcap=HK_MIN_MCAP):
    """Scan HK main-board code ranges, keep HKD stocks >= HK$10B."""
    print(f"[HK] Scanning codes for market cap >= HK${min_mcap/1e9:.0f}B...", flush=True)
    codes = (list(range(1, 2000))
             + list(range(3600, 3700))
             + list(range(6000, 7000, 5))
             + list(range(9600, 10000, 5)))
    out = []
    for i, c in enumerate(codes):
        tk = f"{c:04d}.HK"
        try:
            info = yf.Ticker(tk).info
            mc = info.get("marketCap", 0) or 0
            cur = info.get("currency", "")
            nm = info.get("longName") or info.get("shortName") or ""
            if mc >= min_mcap and cur == "HKD" and nm:
                out.append([tk, nm, "HK"])
        except Exception:
            pass
        if (i + 1) % 200 == 0:
            print(f"[HK] {i+1}/{len(codes)} scanned, {len(out)} qualified", flush=True)
        time.sleep(0.08)
    print(f"[HK] {len(out)} tickers qualified", flush=True)
    return out


def build_universe(force=False):
    """Build/cache the universe. A failure in one market never aborts the other."""
    if not force and UNIVERSE_CACHE.exists():
        age = datetime.datetime.now() - datetime.datetime.fromtimestamp(UNIVERSE_CACHE.stat().st_mtime)
        if age.days < CACHE_DAYS:
            universe = json.loads(UNIVERSE_CACHE.read_text())
            print(f"[UNIVERSE] Cached: {len(universe)} stocks ({age.days}d old)", flush=True)
            return universe

    us, hk = [], []
    try:
        us = get_us_tickers()
    except Exception as e:
        print(f"[UNIVERSE] US build error: {e}", flush=True)
    try:
        hk = get_hk_tickers()
    except Exception as e:
        print(f"[UNIVERSE] HK build error: {e}", flush=True)

    universe = us + hk
    if not universe:
        raise RuntimeError("Universe is empty: all sources failed and no cache exists")
    UNIVERSE_CACHE.write_text(json.dumps(universe, ensure_ascii=False))
    print(f"[UNIVERSE] Built & cached: {len(us)} US + {len(hk)} HK "
          f"= {len(universe)} stocks", flush=True)
    return universe


# ----------------------------------------------------------------------------
# Screening
# ----------------------------------------------------------------------------
def screen_all(universe):
    all_signals, all_series = [], {}
    total = len(universe)
    for idx, (tk, name, market) in enumerate(universe):
        if idx == 0 or (idx + 1) % 25 == 0:
            print(f"[SCREEN] {idx+1}/{total} - {tk} ({market})", flush=True)
        try:
            hist = yf.Ticker(tk).history(period="1y", interval="1d", auto_adjust=False)
            if hist is None or len(hist) < 60:
                continue
            dates = [d.strftime("%Y-%m-%d") for d in hist.index]
            opens = hist["Open"].to_numpy(float)
            closes = hist["Close"].to_numpy(float)
            highs = hist["High"].to_numpy(float)
            lows = hist["Low"].to_numpy(float)
            vols = hist["Volume"].to_numpy(float)
            rsi = calc_rsi(closes)

            sigs = detect_divergence(dates, closes, rsi)
            if not sigs:
                continue

            mc_str = ""
            try:
                mc = yf.Ticker(tk).info.get("marketCap", 0) or 0
                mc_str = f"{mc/1e9:.1f}B" if mc else ""
            except Exception:
                pass

            for s in sigs:
                all_signals.append(dict(
                    ticker=tk, name=name, mc=mc_str, market=market,
                    age=s["age"], d1=s["d1"], d2=s["d2"],
                    c1=s["c1"], c2=s["c2"], r1=s["r1"], r2=s["r2"],
                    lift=s["lift"], post=s["post"], weekly=s["weekly"],
                    last=round(float(closes[-1]), 2)))

            n = len(dates)
            start = max(0, n - 250)
            all_series[tk] = dict(
                dates=dates[start:],
                ohlc=[[round(float(opens[i]), 2), round(float(closes[i]), 2),
                       round(float(lows[i]), 2), round(float(highs[i]), 2)]
                      for i in range(start, n)],
                close=[round(float(c), 2) for c in closes[start:]],
                vol=[int(v) for v in vols[start:]],
                rsi=[None if np.isnan(r) else round(float(r), 1)
                     for r in rsi[start:]])
        except Exception as e:
            print(f"[WARN] {tk}: {e}", flush=True)
        time.sleep(0.15)
    return all_signals, all_series


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    force = "--refresh" in sys.argv
    universe = build_universe(force=force)
    signals, series = screen_all(universe)

    cutoff = datetime.date.today().strftime("%Y-%m-%d")
    out = dict(cutoff=cutoff, totalScanned=len(universe),
               signals=signals, series=series)
    js = "window.RPT_DATA = " + json.dumps(out, ensure_ascii=False,
                                           separators=(",", ":")) + ";"
    APP_DIR.mkdir(exist_ok=True)
    out_path = APP_DIR / "data.js"
    out_path.write_text(js)
    print(f"\n[DONE] {len(signals)} signals across {len(series)} stocks", flush=True)
    print(f"[DONE] -> {out_path} ({out_path.stat().st_size/1024:.0f} KB)", flush=True)


if __name__ == "__main__":
    main()
