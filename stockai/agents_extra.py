"""Additional analysis agents: Technician, Fundamentalist, Newsdesk.

Every one obeys the same rule as the rest of the system: real data or an
explicit "no data" signal. None of them fabricate. The Newsdesk in particular
returns real headlines with source URLs, or says it has no verified news -
it NEVER invents a headline or a sentiment score.

Data source for fundamentals + news: Alpha Vantage (needs STOCKAI_DATA_KEY).
Alpha Vantage NSE coverage for small-caps is thin; "no data" is expected and
is the correct, honest result - not a bug.
"""
import time
from dataclasses import dataclass, field
from typing import Optional, List

import requests

_AV = "https://www.alphavantage.co/query"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
}

# Cached Yahoo session (cookie + crumb) so we don't re-auth on every call.
_yahoo_session = {"crumb": None, "cookies": None}


def _get_yahoo_crumb():
    """Fetch and cache a Yahoo cookie + crumb, required by quoteSummary.

    Yahoo gates its fundamentals API behind a session cookie and a matching
    'crumb' token. We grab both once and reuse them. Returns (crumb, cookies)
    or (None, None) if Yahoo blocks us - caller then falls back to 'no data'.
    """
    if _yahoo_session["crumb"] and _yahoo_session["cookies"] is not None:
        return _yahoo_session["crumb"], _yahoo_session["cookies"]
    try:
        s = requests.Session()
        s.headers.update(_HEADERS)
        # 1) hit a Yahoo page to receive the session cookie
        s.get("https://fc.yahoo.com", timeout=12)
        # 2) request a crumb that matches that cookie
        r = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=12)
        crumb = r.text.strip() if r.status_code == 200 else None
        if crumb and "<" not in crumb:   # a valid crumb, not an error page
            _yahoo_session["crumb"] = crumb
            _yahoo_session["cookies"] = s.cookies
            return crumb, s.cookies
    except requests.RequestException:
        pass
    return None, None


# --- Technician: derived purely from the screener bars we already have -------
@dataclass
class TechRead:
    symbol: str
    rvol: Optional[float]        # relative volume (today / avg)
    above_sma: Optional[bool]
    trend: str                  # "up" / "down" / "unknown"
    note: str = ""

    def summary(self) -> str:
        if self.rvol is None:
            return f"{self.symbol}: no reliable technical data"
        pos = "above" if self.above_sma else "below"
        return (f"{self.symbol}: RVOL {self.rvol:.1f}x, price {pos} SMA, "
                f"trend {self.trend}")


def technician_read(brief) -> TechRead:
    """No new fetch - reasons over the StockBrief the screener already built."""
    rvol = brief.volume_multiple if brief.volume_multiple else None
    above = brief.close > brief.sma if (brief.close and brief.sma) else None
    trend = "unknown"
    if above is not None:
        trend = "up" if (above and brief.pct_change and brief.pct_change > 0) else \
                ("down" if brief.pct_change and brief.pct_change < 0 else "flat")
    return TechRead(brief.symbol, rvol, above, trend)


# --- Fundamentalist: Alpha Vantage OVERVIEW ---------------------------------
@dataclass
class FundRead:
    symbol: str
    name: Optional[str] = None
    pe: Optional[str] = None
    peg: Optional[str] = None
    eps: Optional[str] = None
    book_value: Optional[str] = None
    dividend_yield: Optional[str] = None
    profit_margin: Optional[str] = None
    roe: Optional[str] = None
    revenue_ttm: Optional[str] = None
    target: Optional[str] = None
    market_cap: Optional[str] = None
    week52_high: Optional[str] = None
    week52_low: Optional[str] = None
    ma50: Optional[str] = None
    ma200: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    ok: bool = False
    note: str = ""

    def summary(self) -> str:
        if not self.ok:
            return f"{self.symbol}: no fundamental data ({self.note})"
        bits = []
        if _has(self.pe):
            bits.append(f"P/E {self.pe}")
        if _has(self.target):
            bits.append(f"analyst target {self.target}")
        if _has(self.market_cap):
            bits.append(f"mkt cap {self.market_cap}")
        return f"{self.symbol}: " + (", ".join(bits) if bits else "no usable fields")

    def details(self) -> dict:
        """All fields as a dict, with 'no data' for anything missing.
        Never fabricates - missing fields are explicitly 'no data'.
        """
        def v(x):
            return x if _has(x) else "no data"
        return {
            "name": v(self.name),
            "sector": v(self.sector),
            "industry": v(self.industry),
            "market_cap": v(self.market_cap),
            "pe": v(self.pe),
            "peg": v(self.peg),
            "eps": v(self.eps),
            "book_value": v(self.book_value),
            "dividend_yield": v(self.dividend_yield),
            "profit_margin": v(self.profit_margin),
            "roe": v(self.roe),
            "revenue_ttm": v(self.revenue_ttm),
            "analyst_target": v(self.target),
            "week52_high": v(self.week52_high),
            "week52_low": v(self.week52_low),
            "ma50": v(self.ma50),
            "ma200": v(self.ma200),
        }


def _has(x) -> bool:
    """True only if the field is a real, usable value (not None/empty/'None'/'-')."""
    return x is not None and str(x).strip() not in ("", "None", "-", "0", "0.0")


def yahoo_fundamentals_backup(symbol: str) -> dict:
    """Rich fundamentals from Yahoo's quoteSummary. Best-effort, never fakes.

    Pulls P/E, market cap, EPS, book value, dividend yield, margins, ROE, and
    52-week range where Yahoo has them. Returns only fields actually present;
    everything else is left for the caller to mark 'no data'. Yahoo's India
    coverage is decent for large/mid caps, thinner for micro-caps.
    """
    out = {}
    modules = "summaryDetail,defaultKeyStatistics,financialData,price,assetProfile"
    crumb, cookies = _get_yahoo_crumb()
    for suffix in (".NS", ".BO"):   # try NSE first, then BSE
        try:
            params = {"modules": modules}
            if crumb:
                params["crumb"] = crumb
            url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}{suffix}"
            r = requests.get(url, params=params, headers=_HEADERS,
                             cookies=cookies, timeout=14)
            if r.status_code != 200:
                continue
            res = r.json().get("quoteSummary", {}).get("result")
            if not res:
                continue
            d = res[0]
            sd = d.get("summaryDetail", {})
            ks = d.get("defaultKeyStatistics", {})
            fd = d.get("financialData", {})
            pr = d.get("price", {})
            ap = d.get("assetProfile", {})

            def raw(node, key):
                v = node.get(key)
                if isinstance(v, dict):
                    return v.get("raw")
                return v

            def fmt(node, key, pct=False, money=False):
                v = raw(node, key)
                if v is None or v == 0:
                    return None
                if pct:
                    return f"{v*100:.2f}%"
                if money:
                    return _human_money(v)
                return f"{v:.2f}" if isinstance(v, (int, float)) else str(v)

            _set(out, "pe", fmt(sd, "trailingPE") or fmt(ks, "trailingPE"))
            _set(out, "market_cap", fmt(pr, "marketCap", money=True) or fmt(sd, "marketCap", money=True))
            _set(out, "eps", fmt(ks, "trailingEps"))
            _set(out, "book_value", fmt(ks, "bookValue"))
            _set(out, "dividend_yield", fmt(sd, "dividendYield", pct=True))
            _set(out, "profit_margin", fmt(fd, "profitMargins", pct=True))
            _set(out, "roe", fmt(fd, "returnOnEquity", pct=True))
            _set(out, "peg", fmt(ks, "pegRatio"))
            _set(out, "revenue_ttm", fmt(fd, "totalRevenue", money=True))
            _set(out, "analyst_target", fmt(fd, "targetMeanPrice"))
            _set(out, "week52_high", fmt(sd, "fiftyTwoWeekHigh"))
            _set(out, "week52_low", fmt(sd, "fiftyTwoWeekLow"))
            _set(out, "ma50", fmt(sd, "fiftyDayAverage"))
            _set(out, "ma200", fmt(sd, "twoHundredDayAverage"))
            if ap.get("sector"):
                out["sector"] = ap["sector"]
            if ap.get("industry"):
                out["industry"] = ap["industry"]
            if pr.get("longName"):
                out["name"] = pr["longName"]

            if out:   # got something from this exchange; stop
                return out
        except (requests.RequestException, ValueError, KeyError, IndexError):
            continue

    # Fallback: the simpler v7 quote endpoint often returns core fields
    # (P/E, market cap, EPS, 52w range) even when quoteSummary is empty.
    if not out:
        out = _yahoo_quote_fallback(symbol, crumb, cookies)
    return out


def _yahoo_quote_fallback(symbol, crumb, cookies):
    """Simpler Yahoo quote endpoint - fewer fields but more reliable."""
    out = {}
    for suffix in (".NS", ".BO"):
        try:
            params = {"symbols": symbol + suffix}
            if crumb:
                params["crumb"] = crumb
            url = "https://query2.finance.yahoo.com/v7/finance/quote"
            r = requests.get(url, params=params, headers=_HEADERS,
                             cookies=cookies, timeout=14)
            if r.status_code != 200:
                continue
            arr = r.json().get("quoteResponse", {}).get("result") or []
            if not arr:
                continue
            q = arr[0]

            def g(key, pct=False, money=False, div=False):
                v = q.get(key)
                if v is None or v == 0:
                    return None
                if pct:
                    return f"{v:.2f}%"
                if money:
                    return _human_money(v)
                return f"{v:.2f}" if isinstance(v, (int, float)) else str(v)

            _set(out, "pe", g("trailingPE"))
            _set(out, "market_cap", g("marketCap", money=True))
            _set(out, "eps", g("epsTrailingTwelveMonths"))
            _set(out, "book_value", g("bookValue"))
            _set(out, "week52_high", g("fiftyTwoWeekHigh"))
            _set(out, "week52_low", g("fiftyTwoWeekLow"))
            _set(out, "ma50", g("fiftyDayAverage"))
            _set(out, "ma200", g("twoHundredDayAverage"))
            if q.get("longName") or q.get("shortName"):
                out["name"] = q.get("longName") or q.get("shortName")
            if out:
                return out
        except (requests.RequestException, ValueError, KeyError, IndexError):
            continue
    return out


def _set(d, k, v):
    if v is not None:
        d[k] = v


def _human_money(v):
    """Format a large rupee figure like Yahoo's raw market cap into cr/L."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v >= 1e7:
        return f"{v/1e7:,.0f} Cr"
    return f"{v:,.0f}"


def _av_symbol(nse_symbol: str) -> str:
    # Alpha Vantage uses "SYMBOL.BSE" for Indian equities in many cases.
    # NSE coverage is patchy; we try .BSE which AV documents for India.
    return f"{nse_symbol}.BSE"


def fundamentalist_read(symbol: str, api_key: str) -> FundRead:
    if not api_key:
        return FundRead(symbol, note="no data-provider key set")
    try:
        r = requests.get(_AV, params={
            "function": "OVERVIEW", "symbol": _av_symbol(symbol), "apikey": api_key,
        }, headers=_HEADERS, timeout=20)
        if r.status_code != 200:
            return FundRead(symbol, note=f"HTTP {r.status_code}")
        data = r.json()
        # AV returns {} or a note when nothing is found - do NOT invent.
        if not data or "Symbol" not in data:
            return FundRead(symbol, note="no coverage for this symbol")
        return FundRead(
            symbol,
            name=data.get("Name"),
            pe=data.get("PERatio"),
            peg=data.get("PEGRatio"),
            eps=data.get("EPS"),
            book_value=data.get("BookValue"),
            dividend_yield=data.get("DividendYield"),
            profit_margin=data.get("ProfitMargin"),
            roe=data.get("ReturnOnEquityTTM"),
            revenue_ttm=data.get("RevenueTTM"),
            target=data.get("AnalystTargetPrice"),
            market_cap=data.get("MarketCapitalization"),
            week52_high=data.get("52WeekHigh"),
            week52_low=data.get("52WeekLow"),
            ma50=data.get("50DayMovingAverage"),
            ma200=data.get("200DayMovingAverage"),
            sector=data.get("Sector"),
            industry=data.get("Industry"),
            ok=True,
        )
    except (requests.RequestException, ValueError) as e:
        return FundRead(symbol, note=f"fetch error: {e}")


# --- Newsdesk: Alpha Vantage NEWS_SENTIMENT (real headlines + links only) ----
@dataclass
class Headline:
    title: str
    url: str
    source: str
    time: str
    sentiment: Optional[str] = None   # only what AV explicitly labelled


@dataclass
class NewsRead:
    symbol: str
    headlines: List[Headline] = field(default_factory=list)
    ok: bool = False
    note: str = ""

    def summary(self) -> str:
        if not self.headlines:
            return f"{self.symbol}: no news data"
        return f"{self.symbol}: {len(self.headlines)} verified headline(s)"


def newsdesk_read(symbol: str, api_key: str, max_items: int = 5) -> NewsRead:
    """Return REAL headlines with URLs, or an explicit no-data result.

    Never fabricates a headline. Never invents sentiment - only passes through
    a label AV itself attached.
    """
    if not api_key:
        return NewsRead(symbol, note="no data-provider key set")
    try:
        r = requests.get(_AV, params={
            "function": "NEWS_SENTIMENT", "tickers": _av_symbol(symbol),
            "apikey": api_key, "limit": max_items,
        }, headers=_HEADERS, timeout=20)
        if r.status_code != 200:
            return NewsRead(symbol, note=f"HTTP {r.status_code}")
        data = r.json()
        feed = data.get("feed", [])
        if not feed:
            # This is the HONEST, expected result for many NSE small-caps.
            return NewsRead(symbol, note="no verified news returned")
        heads = []
        for item in feed[:max_items]:
            # pull the ticker-specific sentiment label if AV provided one
            label = None
            for ts in item.get("ticker_sentiment", []):
                if ts.get("ticker", "").upper().startswith(symbol.upper()):
                    label = ts.get("ticker_sentiment_label")
                    break
            heads.append(Headline(
                title=item.get("title", "(no title)"),
                url=item.get("url", ""),
                source=item.get("source", ""),
                time=item.get("time_published", ""),
                sentiment=label,
            ))
        return NewsRead(symbol, headlines=heads, ok=True)
    except (requests.RequestException, ValueError) as e:
        return NewsRead(symbol, note=f"fetch error: {e}")
