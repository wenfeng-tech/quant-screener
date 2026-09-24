#!/usr/bin/env python3
import json, time, datetime, requests, os
from pathlib import Path
import yfinance as yf
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"

def calc_rsi(closes, period=14):
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    ag = pd.Series(gains).ewm(alpha=1/period, min_periods=period).mean().values
    al = pd.Series(losses).ewm(alpha=1/period, min_periods=period).mean().values
    rs = np.where(al == 0, 100, ag / np.maximum(al, 1e-10))
    rsi = 100 - 100 / (1 + rs)
    return np.concatenate([[np.nan], rsi])

def find_swing_lows(prices, w=5):
    return [i for i in range(w, len(prices)-w) if prices[i] == min(prices[i-w:i+w+1])]

def detect_divergence(dates, closes, rsi):
    signals = []
    n = len(closes)
    if n < 60: return signals
    sl = find_swing_lows(closes, 5)
    if len(sl) < 2: return signals
    for j in range(1, len(sl)):
        i1, i2 = sl[j-1], sl[j]
        if np.isnan(rsi[i1]) or np.isnan(rsi[i2]): continue
        if closes[i2] < closes[i1] and rsi[i2] > rsi[i1]:
            age = n - 1 - i2
            if age <= 5:
                wk = bool(rsi[i2] > rsi[max(0,i2-10)]) if i2 >= 10 else False
                post = ((closes[-1]-closes[i2])/closes[i2]*100) if i2 < n-1 else 0.0
                signals.append(dict(d1=dates[i1], d2=dates[i2],
                    c1=round(float(closes[i1]),2), c2=round(float(closes[i2]),2),
                    r1=round(float(rsi[i1]),1), r2=round(float(rsi[i2]),1),
                    lift=round(float(rsi[i2]-rsi[i1]),1),
                    post=round(float(post),1), age=age, weekly=wk, i1=i1, i2=i2))
    return signals

def get_us_tickers():
    print("[US] Russell 1000...")
    h = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get("https://en.wikipedia.org/wiki/Russell_1000_Index", headers=h, timeout=30)
        tables = pd.read_html(r.text)
        for t in tables:
            cols = [str(c).lower() for c in t.columns]
            if any("ticker" in c or "symbol" in c for c in cols):
                df = t; break
        else: raise Exception("no table")
        tkc = next((c for c in df.columns if "ticker" in str(c).lower() or "symbol" in str(c).lower()), df.columns[0])
        nmc = next((c for c in df.columns if "company" in str(c).lower() or "security" in str(c).lower() or "name" in str(c).lower()), df.columns[1] if len(df.columns)>1 else df.columns[0])
        out = []
        for _, row in df.iterrows():
            tk = str(row[tkc]).strip().replace(".", "-")
            if tk and tk != "nan" and len(tk) <= 6:
                nm = str(row[nmc]).strip()
                if nm == "nan": nm = tk
                out.append((tk, nm, "US"))
        print(f"[US] {len(out)} tickers")
        return out
    except Exception as e:
        print(f"[US] S&P 500 fallback")
        sp = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
        return [(r["Symbol"].replace(".","-"), r["Security"], "US") for _, r in sp.iterrows()]

def get_us_tickers():
    print("[US] Russell 1000...")
    h = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get("https://en.wikipedia.org/wiki/Russell_1000_Index", headers=h, timeout=30)
        tables = pd.read_html(r.text)
        for t in tables:
            cols = [str(c).lower() for c in t.columns]
            if any("ticker" in c or "symbol" in c for c in cols):
                df = t; break
        else: raise Exception("no table")
        tkc = next((c for c in df.columns if "ticker" in str(c).lower() or "symbol" in str(c).lower()), df.columns[0])
        nmc = next((c for c in df.columns if "company" in str(c).lower() or "security" in str(c).lower() or "name" in str(c).lower()), df.columns[1] if len(df.columns)>1 else df.columns[0])
        out = []
        for _, row in df.iterrows():
            tk = str(row[tkc]).strip().replace(".", "-")
            if tk and tk != "nan" and len(tk) <= 6:
                nm = str(row[nmc]).strip()
                if nm == "nan": nm = tk
                out.append((tk, nm, "US"))
        print(f"[US] {len(out)} tickers")
        return out
    except:
        print("[US] S&P 500 fallback")
        sp = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
        return [(r["Symbol"].replace(".","-"), r["Security"], "US") for _, r in sp.iterrows()]

def get_us_tickers():
    print("[US] Russell 1000...")
    h = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get("https://en.wikipedia.org/wiki/Russell_1000_Index", headers=h, timeout=30)
        tables = pd.read_html(r.text)
        for t in tables:
            cols = [str(c).lower() for c in t.columns]
            if any("ticker" in c or "symbol" in c for c in cols):
                df = t; break
        else: raise Exception()
        tkc = next((c for c in df.columns if "ticker" in str(c).lower() or "symbol" in str(c).lower()), df.columns[0])
        nmc = next((c for c in df.columns if "company" in str(c).lower() or "security" in str(c).lower() or "name" in str(c).lower()), df.columns[1] if len(df.columns)>1 else df.columns[0])
        out = []
        for _, row in df.iterrows():
            tk = str(row[tkc]).strip().replace(".", "-")
            if tk and tk != "nan" and len(tk) <= 6:
                nm = str(row[nmc]).strip()
                if nm == "nan": nm = tk
                out.append((tk, nm, "US"))
        print(f"[US] {len(out)} tickers")
        return out
    except:
        print("[US] S&P 500 fallback")
        sp = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
        return [(r["Symbol"].replace(".","-"), r["Security"], "US") for _, r in sp.iterrows()]

def get_hk_tickers(min_mcap=10000000000):
    print(f"[HK] Scanning > {min_mcap/1e9:.0f}B HKD...")
    codes = list(range(1,2000)) + list(range(3600,3700)) + list(range(6000,7000,5)) + list(range(9600,10000,5))
    out = []
    for i,c in enumerate(codes):
        tk = f"{c:04d}.HK"
        try:
            info = yf.Ticker(tk).info
            mc = info.get("marketCap",0)
            cur = info.get("currency","")
            nm = info.get("longName") or info.get("shortName") or ""
            if mc and mc >= min_mcap and cur == "HKD" and nm:
                out.append((tk, nm, "HK"))
        except: pass
        if (i+1) % 100 == 0: print(f"[HK] {i+1}/{len(codes)}, found {len(out)}")
        time.sleep(0.03)
    print(f"[HK] {len(out)} tickers")
    return out

def screen_all(universe):
    all_signals = []
    all_series = {}
    total = len(universe)
    for idx,(tk,name,market) in enumerate(universe):
        if (idx+1) % 20 == 0 or idx == 0:
            print(f"[SCREEN] {idx+1}/{total} - {tk} ({market})")
        try:
            t = yf.Ticker(tk)
            hist = t.history(period="1y", interval="1d")
            if len(hist) < 60: continue
            dates = [d.strftime("%Y-%m-%d") for d in hist.index]
            closes = hist["Close"].values
            opens = hist["Open"].values
            highs = hist["High"].values
            lows = hist["Low"].values
            vols = hist["Volume"].values.astype(int)
            rsi = calc_rsi(closes, 14)
            sigs = detect_divergence(dates, closes, rsi)
            if sigs:
                try:
                    info = t.info
                    mc = info.get("marketCap",0)
                    mc_str = f"{mc/1e9:.1f}B" if mc else ""
                except: mc_str = ""
                for s in sigs:
                    all_signals.append(dict(ticker=tk, name=name, mc=mc_str, market=market,
                        age=s["age"], d1=s["d1"], d2=s["d2"], c1=s["c1"], c2=s["c2"],
                        r1=s["r1"], r2=s["r2"], lift=s["lift"], post=s["post"],
                        weekly=s["weekly"], last=round(float(closes[-1]),2)))
                n = len(dates)
                start = max(0, n-250)
                all_series[tk] = dict(
                    dates=dates[start:],
                    ohlc=[[round(float(opens[i]),2),round(float(closes[i]),2),round(float(lows[i]),2),round(float(highs[i]),2)] for i in range(start,n)],
                    close=[round(float(c),2) for c in closes[start:]],
                    vol=vols[start:].tolist(),
                    rsi=[round(float(r),1) if not np.isnan(r) else None for r in rsi[start:]])
        except: pass
        time.sleep(0.1)
    return all_signals, all_series

def main():
    us = get_us_tickers()
    hk = get_hk_tickers()
    universe = us + hk
    print(f"\n[UNIVERSE] {len(universe)} stocks")
    signals, series = screen_all(universe)
    cutoff = datetime.date.today().strftime("%Y-%m-%d")
    out = dict(cutoff=cutoff, totalScanned=len(universe), signals=signals, series=series)
    js = "window.RPT_DATA = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";"
    out_path = APP_DIR / "data.js"
    with open(out_path, "w") as f: f.write(js)
    print(f"\n[DONE] {len(signals)} signals, {len(series)} series")
    print(f"[DONE] -> {out_path} ({out_path.stat().st_size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
