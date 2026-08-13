#!/usr/bin/env python3
"""Phase 1 manual run: screen the universe and print the shortlist.

Usage:
    python run_phase1.py           # LIVE: fetches real NSE data
    python run_phase1.py --demo    # SAMPLE data, no network, logic demo only

Live mode does NOT send anything anywhere in Phase 1 - it fetches real data,
applies the config thresholds, and prints what passed and why.

Demo mode uses fabricated sample bars (sample_data.csv) purely to show the
screening logic. Every line is labelled SAMPLE. This data never leaves the
screener and never becomes an alert.
"""
import sys
from stockai.config import load_config
from stockai.screener import run_screener

DEMO_CSV = "sample_data.csv"


def main():
    demo = "--demo" in sys.argv
    config = load_config()

    print("=" * 68)
    print("StockAI - Phase 1: Screener")
    print("Research/education only. Screening tool. Never places orders.")
    if demo:
        print("*** DEMO MODE - SAMPLE DATA, NOT LIVE. Logic demonstration only. ***")
    print("=" * 68)

    universe = config["universe"]["symbols"]
    if demo:
        print("\nUsing SAMPLE bars from sample_data.csv (no network).")
    else:
        print(f"\nUniverse: {len(universe)} symbols")
        print("Fetching real market data (this is polite-paced)...")
    print(f"Shortlist cap: {config['screener']['max_shortlist']}\n")

    all_results, shortlist = run_screener(config, demo_csv=DEMO_CSV if demo else None)
    tag = " [SAMPLE]" if demo else ""

    skipped = [r for r in all_results if r.skipped]
    failed = [r for r in all_results if not r.passed and not r.skipped]

    print("-" * 68)
    print(f"SHORTLIST ({len(shortlist)}){tag} - these would go to the debate:")
    print("-" * 68)
    if not shortlist:
        print("  (nothing passed)")
    for r in shortlist:
        d = r.data
        mult = d.volume / d.avg_volume if d.avg_volume else 0
        print(f"\n  {r.symbol}{tag}  Rs{d.close:.1f}  ({d.pct_change:+.1f}%)  "
              f"vol {mult:.1f}x avg")
        for reason in r.reasons:
            print(f"      {reason}")

    print("\n" + "-" * 68)
    print(f"DID NOT PASS ({len(failed)}){tag}:")
    print("-" * 68)
    for r in failed:
        first_fail = next((x for x in r.reasons if x.startswith("FAIL")), "")
        print(f"  {r.symbol:<12}{tag} {first_fail}")

    if skipped:
        print("\n" + "-" * 68)
        print(f"SKIPPED - NO RELIABLE DATA ({len(skipped)}):  (never guessed)")
        print("-" * 68)
        for r in skipped:
            print(f"  {r.symbol:<12} {r.reasons[0]}")

    print("\n" + "=" * 68)
    print(f"Done. {len(shortlist)} shortlisted / {len(all_results)} screened{tag}.")
    if demo:
        print("Reminder: SAMPLE data. Run without --demo on your machine for live.")
    print("=" * 68)


if __name__ == "__main__":
    main()
