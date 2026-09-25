#!/usr/bin/env python3
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
HK_MIN_MCAP = 10_000_000_000
CACHE_DAYS = 7
CHUNK = 40
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
HEADERS = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
US_FALLBACK_CSV = ("https://raw.githubusercontent.com/BackupBackupFede/"
                   "Russell1000_Yfinance_List/main/russell1000_full_enriched.csv")


def calc_rsi(closes, period=RSI_PERIOD):
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

    def rv(ag, al):
        return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

    rsi[period] = rv(avg_gain, avg_loss)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi[i + 1] = rv(avg_gain, avg_loss)
    return rsi


def find_swing_lows(prices, w=SWING_W):
    return [i for i in range(w, len(prices) - w)
            if prices[i] == min(prices[i - w:i + w + 1])]


def detect_divergence(dates, closes, rsi):
    signals = []
    n = len(closes)
    if n < 60:
        return signals
    lows = find_swing_lows(closes)
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


def _yf_symbol(sym):
    return sym.replace(".", "-").strip()


def _parse_wiki_table(html):
    for tbl in pd.read_html(io.StringIO(html)):
        cols = [str(c).lower() for c in tbl.columns]
        if any("ticker" in c or "symbol" in c for c in cols) and any("company" in c for c in cols):
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


_WIKI_HOST = "https://en." + "wikipedia.org/wiki/"
WIKI_URLS = [
    _WIKI_HOST + "List_of_Russell_1000_companies",
    _WIKI_HOST + "Russell_1000_Index",
]


def get_us_tickers():
    print("[US] Fetching Russell 1000 constituents...", flush=True)
    for url in WIKI_URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                out = _parse_wiki_table(r.text)
                if out:
                    print("[US] Wikipedia OK: " + str(len(out)) + " tickers", flush=True)
                    return out
            print("[US] " + url + " HTTP " + str(r.status_code), flush=True)
        except Exception as e:
            print("[US] failed: " + str(e), flush=True)
    return []


def get_hk_tickers(min_mcap=HK_MIN_MCAP):
    print("[HK] Scanning codes for market cap >= HK$" + str(int(min_mcap/1e9)) + "B...", flush=True)
    codes = (list(range(1, 2000)) + list(range(3600, 3700))
             + list(range(6000, 7000, 5)) + list(range(9600, 10000, 5)))
    out = []
    for i, c in enumerate(codes):
        tk = str(c).zfill(4) + ".HK"
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
            print("[HK] " + str(i+1) + "/" + str(len(codes)) + " scanned, " + str(len(out)) + " qualified", flush=True)
        time.sleep(0.05)
    print("[HK] " + str(len(out)) + " tickers qualified", flush=True)
    return out


def build_universe(force=False):
    if not force and UNIVERSE_CACHE.exists():
        age = datetime.datetime.now() - datetime.datetime.fromtimestamp(UNIVERSE_CACHE.stat().st_mtime)
        if age.days < CACHE_DAYS:
            universe = json.loads(UNIVERSE_CACHE.read_text())
            print("[UNIVERSE] Cached: " + str(len(universe)) + " stocks (" + str(age.days) + "d old)", flush=True)
            return universe
    us, hk = [], []
    try:
        us = get_us_tickers()
    except Exception as e:
        print("[UNIVERSE] US build error: " + str(e), flush=True)
    try:
        hk = get_hk_tickers()
    except Exception as e:
        print("[UNIVERSE] HK build error: " + str(e), flush=True)
    universe = us + hk
    if not universe:
        raise RuntimeError("Universe is empty: all sources failed and no cache exists")
    UNIVERSE_CACHE.write_text(json.dumps(universe, ensure_ascii=False))
    print("[UNIVERSE] Built & cached: " + str(len(us)) + " US + " + str(hk) + " HK = " + str(len(universe)) + " stocks", flush=True)
    return universe


def _field(sub, name):
    return sub[name].to_numpy(float) if name in sub.columns else None


def _download_chunk(tickers, tries=6):
    for i in range(tries):
        try:
            data = yf.download(tickers, period="1y", interval="1d", auto_adjust=False,
                               group_by="ticker", progress=False, threads=True)
            if data is not None and not data.empty and len(data.columns) > 0:
                return data
        except Exception:
            pass
        wait = min(10 * (2 ** i), 240)
        print("  [RATE] chunk of " + str(len(tickers)) + " limited/failed; waiting " + str(wait) + "s (try " + str(i+1) + "/" + str(tries) + ")", flush=True)
        time.sleep(wait)
    return None


def download_all(tickers):
    frames = {}
    missing = list(tickers)
    for start in range(0, len(missing), CHUNK):
        chunk = missing[start:start + CHUNK]
        data = _download_chunk(chunk)
        got = set()
        multi = data is not None and isinstance(data.columns, pd.MultiIndex)
        if data is not None and not multi and len(chunk) == 1:
            got = set(chunk)
        elif multi:
            got = set(data.columns.get_level_values(0).unique())
        for tk in got:
            try:
                sub = data[tk]
                if isinstance(sub, pd.DataFrame) and not sub.empty:
                    frames[tk] = sub
            except Exception:
                pass
        print("[DL] " + str(min(start+CHUNK, len(missing))) + "/" + str(len(missing)) + " (" + str(len(frames)) + " ok)", flush=True)
        time.sleep(2)
    still_missing = [t for t in missing if t not in frames]
    if still_missing:
        print("[DL] retrying " + str(len(still_missing)) + " missing tickers individually", flush=True)
        for tk in still_missing:
            data = _download_chunk([tk], tries=4)
            if data is not None and not data.empty:
                frames[tk] = data
            time.sleep(1)
    print("[DL] total usable frames: " + str(len(frames)) + "/" + str(len(tickers)), flush=True)
    return frames


def screen(universe, frames):
    signals, series = [], {}
    name_map = {tk: (nm, mkt) for tk, nm, mkt in universe}
    signal_tickers = set()
    for tk, sub in frames.items():
        nm, mkt = name_map.get(tk, (tk, "US"))
        try:
            dates = [d.strftime("%Y-%m-%d") for d in sub.index]
            closes = _field(sub, "Close")
            if closes is None or len(closes) < 60:
                continue
            opens = _field(sub, "Open")
            highs = _field(sub, "High")
            lows = _field(sub, "Low")
            vols = _field(sub, "Volume")
            rsi = calc_rsi(closes)
            sigs = detect_divergence(dates, closes, rsi)
            if not sigs:
                continue
            signal_tickers.add(tk)
            n = len(dates)
            st = max(0, n - 250)
            ohlc = []
            for i in range(st, n):
                ohlc.append([round(float(opens[i]), 2), round(float(closes[i]), 2),
                             round(float(lows[i]), 2), round(float(highs[i]), 2)])
            if vols is not None:
                vol = [int(v) if v is not None and not np.isnan(v) else 0 for v in vols[st:]]
            else:
                vol = [0] * (n - st)
            series[tk] = dict(
                dates=dates[st:],
                ohlc=ohlc,
                close=[round(float(c), 2) for c in closes[st:]],
                vol=vol,
                rsi=[None if np.isnan(r) else round(float(r), 1) for r in rsi[st:]])
            for s in sigs:
                signals.append(dict(
                    ticker=tk, name=nm, mc="", market=mkt,
                    age=s["age"], d1=s["d1"], d2=s["d2"],
                    c1=s["c1"], c2=s["c2"], r1=s["r1"], r2=s["r2"],
                    lift=s["lift"], post=s["post"], weekly=s["weekly"],
                    last=round(float(closes[-1]), 2)))
        except Exception as e:
            print("[WARN] " + tk + ": " + str(e), flush=True)
    for tk in signal_tickers:
        for i in range(4):
            try:
                mc = yf.Ticker(tk).info.get("marketCap", 0) or 0
                mc_str = str(round(mc/1e9, 1)) + "B" if mc else ""
                for s in signals:
                    if s["ticker"] == tk:
                        s["mc"] = mc_str
                break
            except Exception:
                time.sleep(min(10 * (2 ** i), 60))
    return signals, series


def main():
    build_only = "--build-universe" in sys.argv
    force = "--refresh" in sys.argv
    if build_only:
        build_universe(force=True)
        print("[DONE] universe refreshed", flush=True)
        return
    universe = build_universe(force=force)
    tickers = [u[0] for u in universe]
    frames = download_all(tickers)
    signals, series = screen(universe, frames)
    cutoff = datetime.date.today().strftime("%Y-%m-%d")
    out = dict(cutoff=cutoff, totalScanned=len(universe), signals=signals, series=series)
    js = "window.RPT_DATA = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";"
    APP_DIR.mkdir(exist_ok=True)
    out_path = APP_DIR / "data.js"
    out_path.write_text(js)
    print("[DONE] " + str(len(signals)) + " signals across " + str(len(series)) + " stocks", flush=True)
    print("[DONE] -> " + str(out_path) + " (" + str(round(out_path.stat().st_size/1024)) + " KB)", flush=True)


if __name__ == "__main__":
    main()
