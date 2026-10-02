# QuantScreener · RSI 底背离量化选股

自动扫描 **美股（罗素1000 成分股）** 与 **港股（市值 ≥ 100 亿港元）**，检测
RSI(14) 经典底背离形态，按信号日龄分桶（0–5 天），并叠加周线级别双重确认。
每个交易日由 GitHub Actions 自动更新并发布到 GitHub Pages。

## 在线访问

👉 **https://wenfeng-tech.github.io/quant-screener/**

## 股票池

| 市场 | 范围 | 来源 |
| --- | --- | --- |
| 美股 | 罗素1000 当前成分股（约 1020 只） | iShares IWB ETF 官方持仓 CSV |
| 港股 | 主板/GEM Equity 且总市值 ≥ 100 亿港元（约 400+ 只） | 港交所官方证券名单 × 东方财富行情市值 |

股票池每次运行实时刷新；抓取失败时回退到 `data/universe_*.csv` 快照。

## 方法学

**指标**：RSI(14)，Wilder 平滑，基于前复权日线收盘价。
统一以**收盘价**判定低点（分形、新低、回采均按收盘）。

**日线底背离（经典标准）**：

1. 前低 d1：±5 根 K 线分形确认的摆动低点；
2. 信号日 d2：收盘价创出新低（`close[d2] < close[d1]`）而 RSI 未创新低
   （`rsi[d2] ≥ rsi[d1]`，允许持平），d1 与 d2 间隔 ≥ 5 且 ≤ 60 个交易日；
3. d2 是「当前低点」：收盘价为前 5 日最低，且 d2 之后收盘未再跌破
   （日龄 0–5 天回采窗口；日龄越大越可靠，5 天为完整回采确认）；
4. 两侧 RSI 均 ≤ 45（背离发生在偏弱区）。

**周线双重确认**：周线 RSI(14) 同样出现「收盘新低 + RSI 未创新低」
（±3 周分形前低，新低在近 8 周内）。

**数据源**：港股主用东方财富前复权 K 线、yfinance 兜底；美股主用
yfinance（复权）、东方财富兜底。不同数据源的分红复权口径略有差异，
个别股票 RSI 小数位可能与其他终端略有出入，属正常现象。

## 自动更新

`.github/workflows/daily-update.yml` 每个交易日运行两次：

| 触发 | 时间 | 更新内容 |
| --- | --- | --- |
| cron `48 8 * * 1-5` | 港股收盘后（16:48 HKT） | 港股 |
| cron `52 21 * * 1-5` | 美股收盘后（美东收盘 + 约 1 小时） | 美股 + 港股 |
| 手动 workflow_dispatch | 任意 | 可选 all / us / hk |

管道每次运行重新拉取股票池与行情，检测信号，重写 `app/data.js` 并自动提交，
随后将 `app/` 部署到 GitHub Pages。行情下载成功率低于 80% 时放弃本次更新，
保留上一份可用数据。

## 本地运行

```bash
pip install -r requirements.txt
python -m pipeline.update --market all    # 或 us / hk
cd app && python -m http.server 8000      # http://localhost:8000
```

## 目录结构

```
app/                  站点（index.html + data.js + echarts），由 CI 部署到 Pages
pipeline/
  universe.py         股票池构建（IWB 持仓 / 港交所名单 × 东财市值）
  quotes.py           行情下载（东方财富 + yfinance 双源互备）
  signals.py          RSI(14) Wilder + 底背离检测 + 周线确认
  update.py           主入口：生成 app/data.js
data/                 股票池快照（抓取失败时的兜底）
.github/workflows/    每日自动更新 + Pages 部署
```

## 免责声明

本项目仅为技术面量化形态筛选，不构成任何投资建议。底背离在强下跌趋势中
可能多次失败，请结合基本面与仓位管理独立决策。
