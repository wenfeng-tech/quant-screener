"""Fetch stock universe: Russell 1000 (US) + HK stocks with market cap > 10B HKD."""
import json, time, requests
import yfinance as yf
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pipeline" / "universe.json"

def fetch_russell1000():
    print("[US] Fetching Russell 1000 from Wikipedia...")
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    try:
        resp = requests.get("https://en.wikipedia.org/wiki/Russell_1000_Index", headers=headers, timeout=30)
        tables = pd.read_html(resp.text)
        for t in tables:
            cols = [str(c).lower() for c in t.columns]
            if any("ticker" in c for c in cols) or any("symbol" in c for c in cols):
                df = t; break
        else:
            raise Exception("no table found")
        tk_col = next((c for c in df.columns if "ticker" in str(c).lower() or "symbol" in str(c).lower()), df.columns[0])
        nm_col = next((c for c in df.columns if "company" in str(c).lower() or "security" in str(c).lower() or "name" in str(c).lower()), df.columns[1] if len(df.columns)>1 else df.columns[0])
        tickers = []
        for _, row in df.iterrows():
            tk = str(row[tk_col]).strip().replace(".", "-")
            if tk and tk != "nan" and len(tk) <= 6:
                nm = str(row[nm_col]).strip()
                if nm == "nan": nm = tk
                tickers.append({"ticker": tk, "name": nm, "market": "US"})
        print(f"[US] Found {len(tickers)} Russell 1000 tickers")
        return tickers
    except Exception as e:
        print(f"[US] Wikipedia failed ({e}), trying S&P 500...")
        sp = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
        tickers = [{"ticker": r["Symbol"].replace(".","-"), "name": r["Security"], "market": "US"} for _, r in sp.iterrows()]
        print(f"[US] Fallback S&P 500: {len(tickers)}")
        return tickers

def fetch_hk_large_caps(min_mcap=10_000_000_000):
    print(f"[HK] Checking HK stocks > {min_mcap/1e9:.0f}B HKD...")
    # Check a broad range of HK tickers
    codes = list(range(1, 2000)) + list(range(3600, 3700)) + list(range(6000, 7000, 5)) + list(range(9600, 10000, 5))
    tickers = [f"{c:04d}.HK" for c in codes]
    results = []
    for i, tk in enumerate(tickers):
        try:
            info = yf.Ticker(tk).info
            mc = info.get("marketCap", 0)
            cur = info.get("currency", "")
            nm = info.get("longName") or info.get("shortName") or ""
            if mc and mc >= min_mcap and cur == "HKD" and nm:
                results.append({"ticker": tk, "name": nm, "market": "HK", "marketCap": mc})
                print(f"  [HK] +{tk} {nm[:30]} MC={mc/1e9:.1f}B")
        except:
            pass
        if (i+1) % 100 == 0:
            print(f"[HK] {i+1}/{len(tickers)}, found {len(results)}")
        time.sleep(0.03)
    print(f"[HK] Total: {len(results)} stocks")
    return results

def main():
    us = fetch_russell1000()
    hk = fetch_hk_large_caps()
    universe = us + hk
    with open(OUT, "w") as f:
        json.dump(universe, f, ensure_ascii=False, indent=2)
    print(f"\n[DONE] {OUT}")
    print(f"  US: {len(us)}, HK: {len(hk)}, Total: {len(universe)}")

if __name__ == "__main__":
    main()
