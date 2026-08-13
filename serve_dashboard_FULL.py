#!/usr/bin/env python3
"""Local server for Manohar's Stock Desk dashboard.

Runs everything on YOUR machine. Your API keys live here, server-side, and are
NEVER sent to the browser. The browser only receives finished analysis results.

Start it:
    export STOCKAI_ANTHROPIC_KEY="sk-ant-..."     # for the debate
    export STOCKAI_DATA_KEY="your-alphavantage"   # for fundamentals + news
    python3 serve_dashboard.py

Then open http://localhost:8000 in your browser and click "run live".

Endpoints:
    GET  /            -> the dashboard HTML
    GET  /api/run     -> runs the full pipeline, returns JSON results
    GET  /api/status  -> which keys are present (booleans only, never the keys)

No key is ever included in any response body. /api/status returns only
true/false so the dashboard can show what's wired without exposing secrets.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from stockai.config import load_config
from stockai.screener import run_screener
from stockai.package import package_shortlist, build_brief
from stockai.screener import ScreenResult, screen_one
from stockai.data import get_stock_data
from stockai.resolve import resolve_symbol
from stockai.agents_extra import (
    technician_read, fundamentalist_read, newsdesk_read,
)
from stockai.orchestrate import run_debate

HERE = Path(__file__).resolve().parent
DASHBOARD = HERE / "dashboard" / "layrs_desk_live.html"
PORT = 8000


def _recent_closes(symbol, n=30):
    """Best-effort: last n daily closes for a sparkline. Empty list on failure."""
    try:
        import requests
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.NS"
        r = requests.get(url, params={"range": "2mo", "interval": "1d"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            return []
        res = r.json().get("chart", {}).get("result", [{}])[0]
        closes = [c for c in (res.get("indicators", {})
                  .get("quote", [{}])[0].get("close") or []) if c is not None]
        return [round(c, 2) for c in closes[-n:]]
    except Exception:
        return []


def _trade_plan(symbol, close):
    """Compute a swing trade plan from real price data using ATR.

    All levels derive from 14-day ATR (true daily range) - nothing invented.
    Rules (standard swing practice):
      entry zone : close .. close + 0.3*ATR   (enter on the move, don't chase)
      stop       : entry_low - 1.5*ATR        (below structure; setup fails here)
      target 1   : entry_low + 2*ATR          (~first scale-out)
      target 2   : entry_low + 4*ATR          (let it run)
      R:R        : (target-entry)/(entry-stop) - pure math
    Returns dict of levels, or None if we can't get enough bars (then we say so).
    """
    try:
        import requests
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.NS"
        r = requests.get(url, params={"range": "3mo", "interval": "1d"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            return None
        res = r.json().get("chart", {}).get("result", [{}])[0]
        q = res.get("indicators", {}).get("quote", [{}])[0]
        highs = q.get("high") or []
        lows = q.get("low") or []
        closes = q.get("close") or []
        # keep only complete bars
        bars = [(h, l, c) for h, l, c in zip(highs, lows, closes)
                if None not in (h, l, c)]
        if len(bars) < 15:
            return None
        # True Range per bar, then 14-period average
        trs = []
        for i in range(1, len(bars)):
            h, l, _ = bars[i]
            prev_c = bars[i - 1][2]
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
        atr = sum(trs[-14:]) / 14
        if atr <= 0:
            return None
        entry_low = close
        entry_high = close + 0.3 * atr
        stop = entry_low - 1.5 * atr
        t1 = entry_low + 2 * atr
        t2 = entry_low + 4 * atr
        risk = entry_low - stop
        rr1 = (t1 - entry_low) / risk if risk > 0 else None
        rr2 = (t2 - entry_low) / risk if risk > 0 else None

        def rup(x):
            return round(x, 2)
        return {
            "atr": rup(atr),
            "entry_low": rup(entry_low), "entry_high": rup(entry_high),
            "stop": rup(stop), "t1": rup(t1), "t2": rup(t2),
            "rr1": round(rr1, 1) if rr1 else None,
            "rr2": round(rr2, 1) if rr2 else None,
            "risk_per_share": rup(risk),
        }
    except Exception:
        return None


def _analyze_briefs(briefs, config, universe_n, note=""):
    """Shared: run the extra agents + debate over a list of briefs.

    Used by both the screener path and the manual single-stock path.
    """
    av_key = config.secret("data_provider_key")
    anthropic_key = config.secret("anthropic_api_key")
    from stockai.package import estimate_budget
    estimate = estimate_budget(briefs, config["debate"])

    stocks = []
    for b in briefs:
        tech = technician_read(b)
        fund = fundamentalist_read(b.symbol, av_key)
        news = newsdesk_read(b.symbol, av_key)
        # Backfill thin fundamentals with what Yahoo can provide (rich source).
        from stockai.agents_extra import yahoo_fundamentals_backup
        details = fund.details()
        backup = yahoo_fundamentals_backup(b.symbol)
        _text_fields = {"sector", "industry", "name"}
        for k, v in backup.items():
            if details.get(k) in (None, "no data") and v:
                # asterisk marks a value sourced from Yahoo, not Alpha Vantage;
                # skip the mark on plain text fields where it reads oddly.
                details[k] = v if k in _text_fields else (str(v) + " *")
        any_detail = any(v not in ("no data",) for v in details.values())
        # recent closes for the sparkline (best-effort; empty if unavailable)
        spark = _recent_closes(b.symbol)
        # computed swing trade plan (entry/stop/targets/R:R from real ATR)
        plan = _trade_plan(b.symbol, b.close)
        stocks.append({
            "symbol": b.symbol, "close": b.close, "pct_change": b.pct_change,
            "rvol": round(b.volume_multiple, 1), "sma": b.sma,
            "technician": tech.summary(), "spark": spark, "plan": plan,
            "fundamentals": {"ok": fund.ok or any_detail, "pe": fund.pe,
                             "target": fund.target, "summary": fund.summary(),
                             "details": details},
            "news": {"ok": news.ok, "count": len(news.headlines),
                     "summary": news.summary(),
                     "headlines": [{"title": h.title, "url": h.url,
                                    "source": h.source, "sentiment": h.sentiment}
                                   for h in news.headlines]},
        })

    result = {
        "universe": universe_n, "shortlisted": len(briefs),
        "est_cost": round(estimate.est_usd, 3), "budget_ok": estimate.within_budget,
        "keys": {"anthropic": bool(anthropic_key), "data": bool(av_key)},
        "verdict_style": config["alerts"].get("verdict_style", "research"),
        "stocks": stocks, "debate": None, "note": note,
    }

    if anthropic_key and estimate.within_budget and briefs:
        report = run_debate(briefs, config)
        if not report.refused:
            debate_out = []
            for res in report.results:
                j = res.judge.parsed or {}
                bear = res.bear.parsed or {}
                bull = res.bull.parsed or {}
                debate_out.append({
                    "symbol": res.symbol, "verdict": j.get("verdict", "n/a"),
                    "signal": j.get("signal", "amber"),
                    "conviction": j.get("conviction", 5),
                    "why": j.get("why_interesting", []),
                    "key_bear_point": j.get("key_bear_point",
                                            (bear.get("points") or ["n/a"])[0]),
                    "bull_points": bull.get("points", []),
                    "bear_points": bear.get("points", []),
                    "must_verify": j.get("must_verify", bear.get("verify", [])),
                    "flagged": j.get("flagged", []),
                })
            result["debate"] = {
                "results": debate_out, "actual_cost": round(report.total_usd, 3),
                "tokens": report.total_input_tokens + report.total_output_tokens}
        else:
            result["debate"] = {"refused": report.refuse_reason}
    return result


def build_single(user_input):
    """Analyze ONE user-specified stock, bypassing the screener filter.

    Fetches the stock's real data, builds a brief (even if it wouldn't 'pass'
    the screen), and runs all agents on it. Honest about bad symbols.
    """
    config = load_config()
    symbol, note = resolve_symbol(user_input)
    if symbol is None:
        return {"error": note, "kind": "resolve"}

    sc = config["screener"]
    lookback = sc.get("volume_breakout", {}).get("lookback_days", 20)
    sma_days = sc.get("price_above_sma", {}).get("sma_days", 50)

    sd = get_stock_data(symbol, lookback, sma_days)
    if not sd.ok:
        return {"error": f"No reliable data for {symbol} ({sd.note}). "
                         f"Check the symbol is a valid NSE ticker.",
                "kind": "data", "symbol": symbol}

    # Build a brief directly - no pass/fail filter, just the real numbers.
    fake_result = ScreenResult(symbol, passed=True, reasons=[
        f"manual: RVOL {sd.volume/sd.avg_volume:.1f}x" if sd.avg_volume else "manual",
        f"manual: {'above' if sd.close > sd.sma else 'below'} SMA{sma_days}",
    ], data=sd)
    brief = build_brief(fake_result, sma_days)
    return _analyze_briefs([brief], config, universe_n=1,
                           note=f"Manual analysis of {symbol} ({note})")


def build_payload(demo=False):
    """Run the SCREENER pipeline (Scout picks the survivors)."""
    config = load_config()
    _, shortlist = run_screener(config, demo_csv=None if not demo else "sample_data.csv")
    briefs, _ = package_shortlist(shortlist, config)
    return _analyze_briefs(briefs, config,
                           universe_n=len(config["universe"]["symbols"]),
                           note="Screener run")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # quiet

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            if DASHBOARD.exists():
                self._send(200, DASHBOARD.read_text(), "text/html; charset=utf-8")
            else:
                self._send(500, "<h1>dashboard file missing</h1>", "text/html")
            return

        if self.path.startswith("/api/status"):
            config = load_config()
            self._send(200, json.dumps({
                "keys": {
                    "anthropic": bool(config.secret("anthropic_api_key")),
                    "data": bool(config.secret("data_provider_key")),
                }
            }))
            return

        if self.path.startswith("/api/analyze"):
            # Single-stock manual analysis. ?q=SYMBOL_OR_NAME
            from urllib.parse import urlparse, parse_qs, unquote
            q = parse_qs(urlparse(self.path).query).get("q", [""])[0]
            q = unquote(q)
            try:
                payload = build_single(q)
                self._send(200, json.dumps(payload))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
            return

        if self.path.startswith("/api/run"):
            demo = "demo=1" in self.path
            try:
                payload = build_payload(demo=demo)
                self._send(200, json.dumps(payload))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
            return

        self._send(404, json.dumps({"error": "not found"}))


def main():
    print("=" * 60)
    print("Manohar's Stock Desk - local server")
    print("=" * 60)
    config = load_config()
    has_anthropic = bool(config.secret("anthropic_api_key"))
    has_data = bool(config.secret("data_provider_key"))
    print(f"Anthropic key (debate):     {'set' if has_anthropic else 'NOT set'}")
    print(f"Data key (fundamentals/news): {'set' if has_data else 'NOT set'}")
    if not has_anthropic:
        print("  -> debate will be skipped until STOCKAI_ANTHROPIC_KEY is set")
    if not has_data:
        print("  -> fundamentals/news will show 'no data' until STOCKAI_DATA_KEY is set")
    print(f"\nOpen  http://localhost:{PORT}  in your browser.")
    print("Keys stay here on your machine - never sent to the browser.")
    print("Ctrl+C to stop.\n")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
