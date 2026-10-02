"""股票池构建模块。

- 美股：罗素1000 成分股，以 iShares IWB ETF 官方持仓 CSV 为准。
- 港股：港交所官方证券名单（Category=Equity，剔除 ETF/牛熊证/权证等）
  与东方财富港股行情（含总市值）按代码关联，保留总市值 >= 100 亿港元的股票。

两个来源都带有快照兜底：成功抓取后写入 data/universe_*.csv；
抓取失败时回退到最近一次快照，保证管道不中断。
"""
from __future__ import annotations

import io
import logging
import time
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("universe")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

IWB_CSV_URL = (
    "https://www.ishares.com/us/products/239707/"
    "ishares-russell-1000-etf/latest-holdings.csv"
)
HKEX_LIST_URL = (
    "https://www.hkex.com.hk/eng/services/trading/securities/"
    "securitieslists/ListOfSecurities.xlsx"
)
EASTMONEY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"

HK_MIN_MCAP = 10_000_000_000  # 100 亿港元

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def _robust_get(url: str, *, params: dict | None = None,
                timeout: int = 40, tries: int = 4) -> requests.Response:
    """直连/系统代理交替重试，容忍本机或 CI 网络抖动。"""
    last: Exception | None = None
    for i in range(tries):
        for trust in (True, False):
            try:
                s = requests.Session()
                s.trust_env = trust
                r = s.get(url, params=params, headers=_HEADERS, timeout=timeout)
                r.raise_for_status()
                return r
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(0.8 * (i + 1))
    raise last  # type: ignore[misc]


def _snapshot_path(market: str) -> Path:
    return DATA_DIR / f"universe_{market.lower()}.csv"


def _load_snapshot(market: str) -> pd.DataFrame | None:
    p = _snapshot_path(market)
    if p.exists():
        df = pd.read_csv(p, dtype={"ticker": str})
        log.info("%s 使用快照股票池 %d 只 (%s)", market, len(df), p.name)
        return df
    return None


def _save_snapshot(market: str, df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(_snapshot_path(market), index=False)


# ---------------------------------------------------------------- 美股

def fetch_us_universe() -> pd.DataFrame:
    """罗素1000 成分股：IWB 持仓。返回 [ticker, name, exchange]。"""
    r = _robust_get(IWB_CSV_URL, timeout=60)
    r.raise_for_status()
    raw = r.content.decode("utf-8", errors="replace")
    # 前 9 行为基金信息，第 10 行起为表头
    df = pd.read_csv(io.StringIO(raw), skiprows=9, dtype=str)
    df = df[df["Asset Class"].str.strip() == "Equity"]
    df = df[["Ticker", "Name", "Exchange"]].dropna(subset=["Ticker", "Name"])
    df.columns = ["ticker", "name", "exchange"]
    # iShares 代码 -> yfinance 代码（BRK B / BRK.B -> BRK-B）
    df["ticker"] = (
        df["ticker"].str.strip().str.upper()
        .str.replace(".", "-", regex=False).str.replace(" ", "-", regex=False)
    )
    df["name"] = df["name"].str.strip().str.title()
    df["exchange"] = df["exchange"].fillna("").str.strip()
    df = df.drop_duplicates("ticker").reset_index(drop=True)
    # 罗素1000 大致 1000 只；数量异常时视为抓取失败
    if not (900 <= len(df) <= 1100):
        raise ValueError(f"IWB 持仓数量异常: {len(df)}")
    return df


# ---------------------------------------------------------------- 港股

def _fetch_hkex_equities() -> pd.DataFrame:
    """港交所官方名单中的 Equity（含主板/GEM，剔除 ETF/权证/牛熊证）。
    返回 [code4]（4 位数字字符串）。"""
    r = _robust_get(HKEX_LIST_URL, timeout=60)
    df = pd.read_excel(io.BytesIO(r.content), skiprows=2)
    df = df[df["Category"].str.strip() == "Equity"]
    codes = (
        pd.to_numeric(df["Stock Code"], errors="coerce")
        .dropna().astype(int)
    )
    codes = codes[(codes >= 1) & (codes <= 9999)]  # 剔除 8xxxx 人民币柜台等
    return pd.DataFrame({"code4": codes.astype(str).str.zfill(4)})


def _fetch_eastmoney_mcaps() -> pd.DataFrame:
    """东方财富港股全列表（含总市值，单位港元）。返回 [code4, name, mcap, pe]。"""
    rows: list[dict] = []
    page, page_size = 1, 500
    while True:
        params = {
            "pn": page, "pz": page_size, "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f20",
            "fs": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2",
            "fields": "f12,f14,f20,f9",
        }
        r = _robust_get(EASTMONEY_CLIST_URL, params=params)
        data = r.json().get("data") or {}
        diff = data.get("diff") or []
        if not diff:
            break
        rows += diff
        total = int(data.get("total") or 0)
        if page * page_size >= total:
            break
        page += 1
        time.sleep(0.3)
    if not rows:
        raise ValueError("东方财富港股列表为空")
    df = pd.DataFrame(rows)
    df = df.rename(columns={"f12": "code", "f14": "name",
                            "f20": "mcap", "f9": "pe"})
    df["code"] = df["code"].astype(str)
    # 剔除人民币柜台（8 开头）及无效市值
    df = df[~df["code"].str.startswith("8")]
    df["mcap"] = pd.to_numeric(df["mcap"], errors="coerce")
    df["pe"] = pd.to_numeric(df["pe"], errors="coerce")
    df = df.dropna(subset=["mcap"])
    df["code4"] = df["code"].astype(int).astype(str).str.zfill(4)
    return df[["code4", "name", "mcap", "pe"]]


def _fetch_yahoo_hk_mcaps() -> pd.DataFrame:
    """兜底：yfinance 港股筛选器，按市值降序取 region=hk 的 Equity，
    过滤总市值 >= 100 亿港元。返回 [code4, name, mcap, pe]。"""
    import yfinance as yf
    from yfinance import EquityQuery

    q = EquityQuery("and", [
        EquityQuery("eq", ["region", "hk"]),
        EquityQuery("eq", ["quoteType", "EQUITY"]),
        EquityQuery("gte", ["intradaymarketcap", HK_MIN_MCAP]),
    ])
    rows: list[dict] = []
    offset = 0
    while True:
        r = yf.screen(q, offset=offset, size=250,
                      sortField="intradaymarketcap", sortAsc=False)
        quotes = (r or {}).get("quotes") or []
        if not quotes:
            break
        rows += quotes
        if len(quotes) < 250 or offset >= 1500:
            break
        offset += 250
        time.sleep(0.5)
    if not rows:
        raise ValueError("yfinance 港股筛选为空")
    df = pd.DataFrame(rows)
    df["code4"] = df["symbol"].astype(str).str.replace(".HK", "", regex=False)
    df = df[df["code4"].str.fullmatch(r"\d{4}")]
    df["name"] = df.get("shortName", df.get("longName", ""))
    df["mcap"] = pd.to_numeric(df.get("marketCap"), errors="coerce")
    df["pe"] = pd.to_numeric(df.get("trailingPE"), errors="coerce")
    df = df.dropna(subset=["mcap"])
    df = df[df["mcap"] >= HK_MIN_MCAP]
    return df[["code4", "name", "mcap", "pe"]]


def fetch_hk_universe() -> pd.DataFrame:
    """港股市值 >= 100 亿港元的 Equity。返回 [ticker, name, mcap]。
    主路径：港交所名单 × 东财市值；兜底：yfinance 港股筛选器。"""
    try:
        hkex = _fetch_hkex_equities()
        em = _fetch_eastmoney_mcaps()
        df = hkex.merge(em, on="code4", how="inner")
    except Exception as e:  # noqa: BLE001
        log.warning("HK 主路径(港交所×东财)失败: %s，改用 yfinance 筛选器", e)
        df = _fetch_yahoo_hk_mcaps()
    df = df[df["mcap"] >= HK_MIN_MCAP]
    # yfinance/前端代码为 4 位零填充（0700.HK）
    df["ticker"] = df["code4"] + ".HK"
    df["name"] = df["name"].astype(str).str.strip()
    df = df[["ticker", "name", "mcap"]].drop_duplicates("ticker")
    df = df.sort_values("mcap", ascending=False).reset_index(drop=True)
    if len(df) < 200:
        raise ValueError(f"港股股票池数量异常: {len(df)}")
    return df


# ---------------------------------------------------------------- 入口

def get_universe(market: str) -> pd.DataFrame:
    """market: 'US' | 'HK'。优先实时抓取，失败回退快照。"""
    market = market.upper()
    fetcher = {"US": fetch_us_universe, "HK": fetch_hk_universe}[market]
    try:
        df = fetcher()
        _save_snapshot(market, df)
        log.info("%s 股票池实时更新成功: %d 只", market, len(df))
        return df
    except Exception as e:  # noqa: BLE001
        log.warning("%s 股票池抓取失败(%s)，尝试快照", market, e)
        snap = _load_snapshot(market)
        if snap is None:
            raise RuntimeError(f"{market} 股票池无实时数据也无快照") from e
        return snap


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    us = get_universe("US")
    hk = get_universe("HK")
    print("US:", len(us), us.head(3).to_dict("records"))
    print("HK:", len(hk), hk.head(3).to_dict("records"))
