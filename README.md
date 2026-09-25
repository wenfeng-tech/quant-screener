# QuantScreener · RSI 底背离量化选股

A professional, auto-updating **RSI(14) Bullish Divergence** screener covering the
**US Russell 1000** and **Hong Kong large-cap stocks (market cap ≥ HK$10B)**.
Data is refreshed every trading day by GitHub Actions and published as a live website.

## 在线访问 / Live Site

👉 **https://wenfeng-tech.github.io/quant-screener/**

## 策略逻辑 / Strategy

A *bullish RSI divergence* occurs when, near a swing low:

- the price makes a **lower low**, while
- the RSI(14) makes a **higher low** (selling momentum is weakening).

The screener:

1. Computes **Wilder RSI(14)** on ~1 year of daily (adjusted) bars.
2. Identifies swing lows with a ±5 bar local-minimum filter.
3. Matches consecutive swing-low pairs where price is lower but RSI is higher.
4. Buckets hits by **signal age (0–5 trading days)** and flags a simple
   weekly-timeframe confirmation.
5. Renders interactive candlestick + volume + RSI charts for every signal.

> Signals older than 5 days are not shown; the universe is re-scanned daily.

## 覆盖范围 / Coverage

| Market | Universe |
|---|---|
| 🇺🇸 United States | Russell 1000 constituents (Wikipedia via browser UA), validated GitHub CSV fallback |
| 🇭🇰 Hong Kong | Main-board stocks, HKD denominated, market cap ≥ HK$10 billion |

## 技术栈 / Tech Stack

- **Data:** Python 3.11, [yfinance](https://github.com/ranaroussi/yfinance), pandas, NumPy
- **Frontend:** Vanilla JS, [Apache ECharts](https://echarts.apache.org/), no build step
- **Automation:** GitHub Actions (cron + manual dispatch)
- **Hosting:** GitHub Pages (deployed from CI)

## 自动更新 / Automation

Two GitHub Actions workflows keep the site current while staying within Yahoo
Finance rate limits:

**1. Daily screen — `.github/workflows/daily-update.yml`**
Runs **Mon–Fri at 05:00 UTC** (01:00 ET / 13:00 HKT, after both markets close):

1. Loads the cached universe (`pipeline/universe.json`).
2. Batch-downloads 1 year of daily bars via `yf.download` (tickers grouped into
   chunks, with exponential-backoff retries on HTTP 429) → regenerates `app/data.js`.
3. Commits & pushes the new data, then deploys `app/` to GitHub Pages.

**2. Weekly universe refresh — `.github/workflows/universe-refresh.yml`**
Runs **Saturday at 06:00 UTC**: rebuilds the US + HK constituent list (the HK
scan is request-heavy) and commits the updated `pipeline/universe.json`.

Separating the heavy universe scan from the daily screen prevents the scan from
consuming the rate-limit budget before prices are fetched.

## 本地运行 / Run Locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python pipeline/run_screener.py                     # screen using cached universe
python pipeline/run_screener.py --build-universe    # only rebuild universe.json
python pipeline/run_screener.py --refresh           # rebuild universe, then screen
```

Then open `app/index.html` in a browser (or serve `app/` with any static server).

## 项目结构 / Layout

```
.
├── app/
│   ├── index.html          # single-page dashboard
│   ├── data.js             # generated: cutoff, signals, chart series
│   └── vendor/echarts.min.js
├── pipeline/
│   ├── run_screener.py     # indicators + universe + screening
│   └── universe.json       # cached stock universe (generated)
├── .github/workflows/
│   ├── daily-update.yml       # weekday screen + Pages deploy
│   └── universe-refresh.yml   # weekly constituent rebuild
└── requirements.txt
```

## 免责声明 / Disclaimer

本项目仅用于量化技术形态的研究与展示，**不构成任何投资建议**。
数据来源于公开渠道（Yahoo Finance），可能存在延迟、缺失或错误，使用风险自负。

This project is for research and educational purposes only. It is **not investment
advice**. Data comes from public sources (Yahoo Finance) and may be delayed,
incomplete, or inaccurate. Use it at your own risk.
