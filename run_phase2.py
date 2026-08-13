#!/usr/bin/env python3
"""Phase 2 manual run: screen -> package survivors -> show token budget.

Usage:
    python3 run_phase2.py           # LIVE data
    python3 run_phase2.py --demo    # SAMPLE data, no network

Still makes NO LLM calls and sends nothing anywhere. It shows you EXACTLY what
would be sent to the debate agents in Phase 3, and the estimated token cost,
so you approve the bill before Phase 3 ever spends anything.
"""
import sys
from stockai.config import load_config
from stockai.screener import run_screener
from stockai.package import package_shortlist

DEMO_CSV = "sample_data.csv"


def main():
    demo = "--demo" in sys.argv
    config = load_config()

    print("=" * 68)
    print("StockAI - Phase 2: Package + Token Budget Guard")
    print("Research/education only. No LLM calls. Sends nothing.")
    if demo:
        print("*** DEMO MODE - SAMPLE DATA, NOT LIVE. ***")
    print("=" * 68)

    if not demo:
        print("\nFetching real market data...")
    all_results, shortlist = run_screener(config, demo_csv=DEMO_CSV if demo else None)
    tag = " [SAMPLE]" if demo else ""

    print(f"\nScreener: {len(shortlist)} survivor(s) of "
          f"{len(all_results)} screened{tag}.")

    briefs, estimate = package_shortlist(shortlist, config)

    print("\n" + "-" * 68)
    print(f"BRIEFS{tag} - this is the ONLY data that reaches the debate:")
    print("-" * 68)
    if not briefs:
        print("  (no survivors - nothing would go to the debate, $0 cost)")
    for i, b in enumerate(briefs, 1):
        print(f"\n  [{i}] {b.symbol}{tag}")
        for line in b.to_prompt_block().split("\n"):
            print(f"      {line}")

    print("\n" + "-" * 68)
    print("TOKEN BUDGET GUARD:")
    print("-" * 68)
    tb = config["debate"]["token_budget"]
    print(f"  Universe screened:        {len(all_results)}")
    print(f"  Survivors -> debate:      {estimate.n_stocks}  "
          f"(cap: {tb['max_stocks_to_debate']})")
    print(f"  Est. input tokens:        {estimate.est_input_tokens:,}")
    print(f"  Est. output tokens:       {estimate.est_output_tokens:,}")
    print(f"  Est. TOTAL tokens/run:    {estimate.est_total_tokens:,}  "
          f"(budget: {tb['max_tokens_per_run']:,})")
    print(f"  Est. cost/run:            ~${estimate.est_usd:.3f}")
    print(f"  Verdict:                  {estimate.reason}")

    print("\n" + "=" * 68)
    if estimate.within_budget and briefs:
        print("Within budget. Phase 3 would debate ONLY the stocks above.")
    elif not briefs:
        print("Nothing to debate today. Phase 3 would make zero calls.")
    else:
        print("OVER BUDGET - Phase 3 would REFUSE to run. Tune config and retry.")
    print("Note: the full universe is NEVER sent - only the survivors above.")
    print("=" * 68)


if __name__ == "__main__":
    main()
