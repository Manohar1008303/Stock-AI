"""Phase 1 screener.

Applies the thresholds from config.yaml to real market data and returns a
shortlist. Each result carries the exact reasons it passed or failed, so nothing
is a black box. Stocks with missing data are never guessed into a pass — they
are reported as skipped with the reason.
"""
from dataclasses import dataclass, field
from typing import List

from .data import StockData, get_many, load_demo


@dataclass
class ScreenResult:
    symbol: str
    passed: bool
    reasons: List[str] = field(default_factory=list)   # human-readable checks
    data: StockData = None
    skipped: bool = False                               # True if data missing


def _check(cond: bool, label_pass: str, label_fail: str, reasons: list) -> bool:
    reasons.append(("PASS " + label_pass) if cond else ("FAIL " + label_fail))
    return cond


def screen_one(sd: StockData, sc: dict) -> ScreenResult:
    if not sd.ok:
        return ScreenResult(sd.symbol, passed=False, skipped=True,
                            reasons=[f"SKIP no reliable data ({sd.note})"], data=sd)

    reasons = []
    ok = True

    # price band
    ok &= _check(sd.close >= sc["min_price"],
                 f"price ₹{sd.close:.1f} >= min ₹{sc['min_price']}",
                 f"price ₹{sd.close:.1f} < min ₹{sc['min_price']}", reasons)
    ok &= _check(sd.close <= sc["max_price"],
                 f"price ₹{sd.close:.1f} <= max",
                 f"price ₹{sd.close:.1f} > max ₹{sc['max_price']}", reasons)

    # volume breakout
    vb = sc.get("volume_breakout", {})
    if vb.get("enabled"):
        mult = sd.volume / sd.avg_volume if sd.avg_volume else 0
        need = vb["multiple"]
        ok &= _check(mult >= need,
                     f"volume {mult:.1f}x avg >= {need}x",
                     f"volume {mult:.1f}x avg < {need}x", reasons)

    # price above SMA
    pas = sc.get("price_above_sma", {})
    if pas.get("enabled"):
        ok &= _check(sd.close > sd.sma,
                     f"close ₹{sd.close:.1f} > SMA{pas['sma_days']} ₹{sd.sma:.1f}",
                     f"close ₹{sd.close:.1f} <= SMA{pas['sma_days']} ₹{sd.sma:.1f}",
                     reasons)

    # min % change
    mpc = sc.get("min_pct_change", {})
    if mpc.get("enabled"):
        ok &= _check(sd.pct_change >= mpc["value"],
                     f"move {sd.pct_change:+.1f}% >= {mpc['value']}%",
                     f"move {sd.pct_change:+.1f}% < {mpc['value']}%", reasons)

    return ScreenResult(sd.symbol, passed=ok, reasons=reasons, data=sd)


def run_screener(config, demo_csv: str = None) -> List[ScreenResult]:
    sc = config["screener"]
    vb = sc.get("volume_breakout", {})
    pas = sc.get("price_above_sma", {})
    lookback = vb.get("lookback_days", 20)
    sma_days = pas.get("sma_days", 50)

    if demo_csv:
        # Sample data path: no network, logic-only demonstration.
        data = load_demo(demo_csv)
    else:
        symbols = config["universe"]["symbols"]
        data = get_many(symbols, lookback, sma_days)
    results = [screen_one(sd, sc) for sd in data]

    # rank passers by volume multiple (strongest breakout first), cap the list
    passers = [r for r in results if r.passed]
    passers.sort(
        key=lambda r: (r.data.volume / r.data.avg_volume) if r.data.avg_volume else 0,
        reverse=True,
    )
    capped = passers[: sc["max_shortlist"]]
    return results, capped
