"""Resolve a user's typed input to an NSE symbol.

Accepts either a symbol (returned as-is, uppercased) or a company name matched
against a small built-in alias table. If a name can't be confidently matched,
returns None with a reason - it NEVER guesses a wrong symbol, because analyzing
the wrong company silently would be worse than saying "not found".

The alias table is deliberately small and covers common/liquid names. Add your
own watchlist names here freely - this is just a convenience map.
"""
import re

# name (lowercased, normalised) -> NSE symbol
# Extend this with any names you type often.
_ALIASES = {
    "reliance": "RELIANCE", "reliance industries": "RELIANCE",
    "tcs": "TCS", "tata consultancy": "TCS", "tata consultancy services": "TCS",
    "infosys": "INFY", "infy": "INFY",
    "hdfc bank": "HDFCBANK", "hdfcbank": "HDFCBANK",
    "icici bank": "ICICIBANK", "icici": "ICICIBANK",
    "sbi": "SBIN", "state bank": "SBIN", "state bank of india": "SBIN",
    "axis bank": "AXISBANK", "axis": "AXISBANK",
    "larsen": "LT", "larsen and toubro": "LT", "l&t": "LT", "lt": "LT",
    "itc": "ITC",
    "airtel": "BHARTIARTL", "bharti airtel": "BHARTIARTL", "bharti": "BHARTIARTL",
    "maruti": "MARUTI", "maruti suzuki": "MARUTI",
    "tata motors": "TATAMOTORS", "tatamotors": "TATAMOTORS",
    "devyani": "DEVYANI", "devyani international": "DEVYANI",
    "finolex": "FINCABLES", "finolex cables": "FINCABLES", "fincables": "FINCABLES",
    "lumax": "LUMAXTECH", "lumax auto": "LUMAXTECH",
    "lumax auto technologies": "LUMAXTECH", "lumaxtech": "LUMAXTECH",
    "hindustan unilever": "HINDUNILVR", "hul": "HINDUNILVR",
    "kotak": "KOTAKBANK", "kotak bank": "KOTAKBANK", "kotak mahindra": "KOTAKBANK",
    "bajaj finance": "BAJFINANCE", "wipro": "WIPRO", "hcl": "HCLTECH",
    "hcl tech": "HCLTECH", "adani enterprises": "ADANIENT",
    "adani ports": "ADANIPORTS", "asian paints": "ASIANPAINT",
    "titan": "TITAN", "nestle": "NESTLEIND", "sun pharma": "SUNPHARMA",
    "power grid": "POWERGRID", "ntpc": "NTPC", "ongc": "ONGC", "coal india": "COALINDIA",
    "tata steel": "TATASTEEL", "jsw steel": "JSWSTEEL", "ultratech": "ULTRACEMCO",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def looks_like_symbol(s: str) -> bool:
    """NSE symbols are uppercase letters/digits, no spaces, usually 2-12 chars."""
    s = s.strip()
    return bool(re.fullmatch(r"[A-Za-z0-9&\-]{1,15}", s)) and " " not in s


def resolve_symbol(user_input: str):
    """Return (symbol, note). symbol is None if it can't be resolved.

    Strategy:
    1. If it's in the alias table (by name), use that. (instant, offline)
    2. Else if it looks like a symbol, validate it exists via a quick fetch;
       if it does, use it.
    3. Else (a company name we don't have aliased), search Yahoo for a real
       NSE/BSE match.
    4. If nothing confident is found, give up honestly - NEVER guess.
    """
    if not user_input or not user_input.strip():
        return None, "empty input"

    key = _norm(user_input)
    if key in _ALIASES:
        return _ALIASES[key], f"matched name -> {_ALIASES[key]}"

    if looks_like_symbol(user_input):
        sym = user_input.strip().upper()
        # validate it actually exists before analysing it
        if _symbol_exists(sym):
            return sym, "used as symbol"
        # maybe they typed a name-like single token; fall through to search

    # A name (or an unknown symbol) - search Yahoo for a real match.
    found = _yahoo_search(user_input)
    if found:
        sym, name = found
        return sym, f"resolved '{user_input}' -> {sym} ({name})"

    return None, (f"couldn't find an NSE/BSE stock for \"{user_input}\". "
                  f"Try the exact NSE symbol (e.g. RELIANCE, DEVYANI).")


# --- network helpers (used only as fallback) --------------------------------
def _symbol_exists(nse_symbol: str) -> bool:
    try:
        import requests
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{nse_symbol}.NS"
        r = requests.get(url, params={"range": "5d", "interval": "1d"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return r.status_code == 200 and bool(
            r.json().get("chart", {}).get("result"))
    except Exception:
        return False


def _yahoo_search(text: str):
    """Return (symbol, name) for the best NSE/BSE equity match, or None."""
    try:
        import requests
        r = requests.get("https://query2.finance.yahoo.com/v1/finance/search",
                         params={"q": text, "quotesCount": 8},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        if r.status_code != 200:
            return None
        quotes = r.json().get("quotes", [])
        for suffix in (".NS", ".BO"):   # prefer NSE, then BSE
            for q in quotes:
                sym = q.get("symbol", "")
                if sym.endswith(suffix) and q.get("quoteType") == "EQUITY":
                    name = q.get("shortname") or q.get("longname") or sym
                    return sym[:-len(suffix)], name
        return None
    except Exception:
        return None
