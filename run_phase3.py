#!/usr/bin/env python3
"""Phase 3: run the bull-vs-bear-vs-judge debate on shortlisted stocks.

Usage:
    python3 run_phase3.py --dry-run          # show prompts, NO API calls, $0
    python3 run_phase3.py --dry-run --demo   # same, using sample data
    python3 run_phase3.py                     # LIVE: real data + real API calls ($)
    python3 run_phase3.py --demo              # sample data + real API calls ($)

--dry-run makes ZERO API calls and spends nothing. It prints the exact prompts
that WOULD be sent so you can inspect them first.

A real run (no --dry-run) calls the Claude API and costs money. It still sends
nothing to Telegram - that's Phase 4. Phase 3 prints the debate + alert text to
your screen so you can read it.
"""
import sys
from stockai.config import load_config
from stockai.screener import run_screener
from stockai.package import package_shortlist
from stockai.debate import BULL_SYS, BEAR_SYS, JUDGE_SYS, build_messages
from stockai.orchestrate import run_debate, format_alert

DEMO_CSV = "sample_data.csv"


def preview(briefs, config):
    """Dry-run: show exactly what would be sent. No API calls."""
    print("\n" + "=" * 68)
    print("DRY RUN - these prompts would be sent. NOTHING is sent. $0 spent.")
    print("=" * 68)
    for b in briefs:
        print(f"\n########## {b.symbol} ##########")
        for role, sysprompt in [("BULL", BULL_SYS), ("BEAR", BEAR_SYS)]:
            msgs, sysp = build_messages(sysprompt, b)
            print(f"\n----- {role} system prompt (truncated) -----")
            print(sysp[:400] + ("..." if len(sysp) > 400 else ""))
            print(f"\n----- {role} user message (the DATA) -----")
            print(msgs[0]["content"])
        print(f"\n----- JUDGE would then see BULL + BEAR outputs + the DATA -----")
    print("\n" + "=" * 68)
    print("End dry run. Run without --dry-run to make real calls (costs money).")
    print("=" * 68)


def main():
    dry = "--dry-run" in sys.argv
    demo = "--demo" in sys.argv
    config = load_config()

    print("=" * 68)
    print("StockAI - Phase 3: Bull vs Bear vs Judge Debate")
    print("Research/education only. Never places orders.")
    if dry:
        print("*** DRY RUN - no API calls, no spend. ***")
    if demo:
        print("*** DEMO DATA - not live. ***")
    print("=" * 68)

    if not demo:
        print("\nFetching real market data...")
    _, shortlist = run_screener(config, demo_csv=DEMO_CSV if demo else None)
    briefs, estimate = package_shortlist(shortlist, config)

    print(f"\n{len(briefs)} stock(s) shortlisted. "
          f"Est. cost if run: ~${estimate.est_usd:.3f}")
    print(f"Budget verdict: {estimate.reason}")

    if not briefs:
        print("\nNothing shortlisted today - no debate, $0. Done.")
        return

    if not estimate.within_budget:
        print("\nOVER BUDGET - refusing to run. Tune config.yaml and retry.")
        return

    if dry:
        preview(briefs, config)
        return

    # Real run - confirm before spending.
    key_present = bool(config.secret("anthropic_api_key"))
    if not key_present:
        print("\nNo Anthropic API key found. Set STOCKAI_ANTHROPIC_KEY in .env "
              "or your shell, then re-run. (Dry-run works without a key.)")
        return

    print(f"\nAbout to make ~{len(briefs)*3} API calls (bull+bear+judge per "
          f"stock), est. ~${estimate.est_usd:.3f}.")
    ans = input("Type 'yes' to proceed with real calls: ").strip().lower()
    if ans != "yes":
        print("Cancelled. $0 spent.")
        return

    print("\nRunning debate...\n")
    report = run_debate(briefs, config)
    if report.refused:
        print(f"Refused: {report.refuse_reason}")
        return

    disclaimer = config["alerts"]["disclaimer"]
    brief_by_sym = {b.symbol: b for b in briefs}
    for res in report.results:
        b = brief_by_sym[res.symbol]
        print("\n" + "=" * 68)
        print(format_alert(res, b, disclaimer))
    print("\n" + "=" * 68)
    print(f"ACTUAL usage: {report.total_input_tokens:,} in + "
          f"{report.total_output_tokens:,} out = "
          f"{report.total_input_tokens + report.total_output_tokens:,} tokens")
    print(f"ACTUAL cost: ~${report.total_usd:.3f}")
    print("Nothing sent anywhere - Phase 4 adds Telegram delivery.")
    print("=" * 68)


if __name__ == "__main__":
    main()
