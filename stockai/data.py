"""Market data layer.

HARD RULE: never fabricate. Every function returns real data or an explicit
signal that data is missing (None / MISSING). Callers must handle missing data
by saying so, never by inventing a number.

Phase 1 uses Yahoo Finance chart endpoint for NSE symbols (SYMBOL.NS), which is
free and needs no key. Swap this out in one place if you prefer a paid provider.
"""
import time
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

MISSING = "NO_DATA"

_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}.NS"
_HEADERS = {"User-Agent": "Mozilla/5.0 (StockAI research screener)"}


@dataclass
class StockData:
    symbol: str
    close: Optional[float]           # latest close
    prev_close: Optional[float]      # previous close
    pct_change: Optional[float]      # today's % move
    volume: Optional[float]          # latest volume
    avg_volume: Optional[float]      # trailing avg volume (lookback window)
    sma: Optional[float]             # simple moving average (sma_days)
    ok: bool                         # True only if all fields present
    note: str = ""                   # why data is missing, if it is


def _fetch_raw(symbol: str, timeout: int = 12) -> Optional[dict]:
    url = _YAHOO.format(sym=symbol)
    params = {"range": "3mo", "interval": "1d"}
    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, json.JSONDecodeError):
        return None


def get_stock_data(symbol: str, lookback_days: int, sma_days: int) -> StockData:
    """Fetch real OHLCV and compute derived fields. No fabrication.

    If anything required is missing, returns ok=False with a note explaining
    which piece was unavailable.
    """
    raw = _fetch_raw(symbol)
    if raw is None:
        return StockData(symbol, None, None, None, None, None, None,
                         ok=False, note="fetch failed / no response")

    try:
        result = raw["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        closes = [c for c in quote["close"] if c is not None]
        vols = [v for v in quote["volume"] if v is not None]
    except (KeyError, IndexError, TypeError):
        return StockData(symbol, None, None, None, None, None, None,
                         ok=False, note="unexpected data shape")

    if len(closes) < 2 or len(vols) < 1:
        return StockData(symbol, None, None, None, None, None, None,
                         ok=False, note="insufficient history returned")

    close = float(closes[-1])
    prev_close = float(closes[-2])
    volume = float(vols[-1])
    pct_change = ((close - prev_close) / prev_close * 100.0) if prev_close else None

    # avg volume over the lookback window (excluding today), real bars only
    vol_window = vols[-(lookback_days + 1):-1] if len(vols) > lookback_days else vols[:-1]
    avg_volume = (sum(vol_window) / len(vol_window)) if vol_window else None

    # SMA over sma_days real closes
    sma_window = closes[-sma_days:] if len(closes) >= sma_days else None
    sma = (sum(sma_window) / len(sma_window)) if sma_window else None

    missing = []
    if pct_change is None:
        missing.append("pct_change")
    if avg_volume is None:
        missing.append(f"avg_volume(need {lookback_days}d)")
    if sma is None:
        missing.append(f"sma(need {sma_days}d)")

    ok = not missing
    note = "" if ok else "missing: " + ", ".join(missing)
    return StockData(symbol, close, prev_close, pct_change, volume,
                     avg_volume, sma, ok=ok, note=note)


def get_many(symbols, lookback_days, sma_days, pause=0.4):
    """Fetch a list of symbols with a small pause to be polite to the source."""
    out = []
    for s in symbols:
        out.append(get_stock_data(s, lookback_days, sma_days))
        time.sleep(pause)
    return out


# --- Demo mode ---------------------------------------------------------------
# Loads pre-computed SAMPLE bars from a CSV so the screener logic can be
# exercised with no network. This data is fabricated for demonstration; it is
# fenced off from alerts and every consumer must label it as sample.
IS_SAMPLE = True  # module-level flag callers check to gate alerts


def load_demo(csv_path: str) -> list:
    """Return StockData objects from the sample CSV. Marks note='SAMPLE'."""
    import csv
    out = []
    with open(csv_path) as f:
        reader = csv.DictReader(
            (line for line in f if not line.lstrip().startswith("#"))
        )
        for row in reader:
            close = float(row["close"])
            prev = float(row["prev_close"])
            vol = float(row["volume"])
            avgvol = float(row["avg_volume"])
            sma = float(row["sma"])
            pct = (close - prev) / prev * 100.0 if prev else None
            out.append(StockData(
                symbol=row["symbol"], close=close, prev_close=prev,
                pct_change=pct, volume=vol, avg_volume=avgvol, sma=sma,
                ok=True, note="SAMPLE",
            ))
    return out
