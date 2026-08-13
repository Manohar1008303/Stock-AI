"""Runs the full debate over a shortlist and formats alert-ready output.

Order per stock: bull -> bear -> judge. The budget guard from Phase 2 is
re-checked here and the run REFUSES if over budget, so we never spend beyond
what was estimated. Real token usage is summed and reported.
"""
from dataclasses import dataclass
from typing import List

from .package import StockBrief, estimate_budget
from .debate import (
    BULL_SYS, BEAR_SYS, JUDGE_SYS,
    build_messages, parse_agent, AgentOut, DebateResult,
)
from .llm import AnthropicClient


@dataclass
class RunReport:
    results: List[DebateResult]
    total_input_tokens: int
    total_output_tokens: int
    total_usd: float
    refused: bool = False
    refuse_reason: str = ""


def _run_one(client: AnthropicClient, brief: StockBrief) -> DebateResult:
    usage = {"input": 0, "output": 0}

    # Bull
    msgs, sys = build_messages(BULL_SYS, brief)
    bull_r = client.call(msgs, sys)
    usage["input"] += bull_r.input_tokens
    usage["output"] += bull_r.output_tokens
    bull = (parse_agent("bull", bull_r.text) if bull_r.ok
            else AgentOut("bull", "", None, ok=False, error=bull_r.error))

    # Bear
    msgs, sys = build_messages(BEAR_SYS, brief)
    bear_r = client.call(msgs, sys)
    usage["input"] += bear_r.input_tokens
    usage["output"] += bear_r.output_tokens
    bear = (parse_agent("bear", bear_r.text) if bear_r.ok
            else AgentOut("bear", "", None, ok=False, error=bear_r.error))

    # Judge (sees bull + bear)
    prior = {
        "bull": bull.parsed if bull.parsed else {"error": bull.error},
        "bear": bear.parsed if bear.parsed else {"error": bear.error},
    }
    msgs, sys = build_messages(JUDGE_SYS, brief, prior=prior)
    judge_r = client.call(msgs, sys)
    usage["input"] += judge_r.input_tokens
    usage["output"] += judge_r.output_tokens
    judge = (parse_agent("judge", judge_r.text) if judge_r.ok
             else AgentOut("judge", "", None, ok=False, error=judge_r.error))

    return DebateResult(brief.symbol, bull, bear, judge, usage)


def run_debate(briefs: List[StockBrief], config) -> RunReport:
    debate_cfg = config["debate"]
    tb = debate_cfg["token_budget"]

    # Re-check the budget guard before spending anything.
    est = estimate_budget(briefs, debate_cfg)
    if not est.within_budget:
        return RunReport([], 0, 0, 0.0, refused=True, refuse_reason=est.reason)

    api_key = config.secret("anthropic_api_key")
    client = AnthropicClient(
        api_key=api_key,
        model=debate_cfg["model"],
        max_tokens=debate_cfg["max_tokens_per_agent"],
    )

    results = []
    tot_in = tot_out = 0
    for b in briefs:
        res = _run_one(client, b)
        results.append(res)
        tot_in += res.usage["input"]
        tot_out += res.usage["output"]

    usd = (tot_in / 1_000_000 * tb["usd_per_1m_input"]
           + tot_out / 1_000_000 * tb["usd_per_1m_output"])
    return RunReport(results, tot_in, tot_out, usd)


# --- Alert formatting --------------------------------------------------------
def format_alert(res: DebateResult, brief: StockBrief, disclaimer: str) -> str:
    """Build the human-facing alert text. ALWAYS includes bear case + disclaimer.

    If the judge output failed to parse, we degrade gracefully and still show
    the raw bear points, never dropping the counter-point.
    """
    j = res.judge.parsed
    lines = [f"📊 {brief.symbol}  (research only)"]
    lines.append(f"Rs {brief.close:.2f}  |  {brief.pct_change:+.2f}%  |  "
                 f"{brief.volume_multiple:.1f}x avg volume")
    lines.append("")

    if j:
        lines.append(f"Verdict: {j.get('verdict', 'n/a')}")
        why = j.get("why_interesting", [])
        if why:
            lines.append("Why it's on the radar:")
            for w in why:
                lines.append(f"  • {w}")
        # BEAR case - mandatory
        lines.append("")
        lines.append(f"⚠️ Bear counter-point: {j.get('key_bear_point', 'n/a')}")
        mv = j.get("must_verify", [])
        if mv:
            lines.append("Verify before acting:")
            for m in mv:
                lines.append(f"  • {m}")
        flagged = j.get("flagged", [])
        if flagged:
            lines.append("Claims the judge could not ground (ignored):")
            for f in flagged:
                lines.append(f"  • {f}")
    else:
        # Judge failed to parse - degrade but keep the bear case.
        lines.append("Verdict: (judge output unavailable - showing raw cases)")
        if res.bear.parsed:
            lines.append("")
            bear_pts = res.bear.parsed.get("points", [])
            lines.append("⚠️ Bear points:")
            for p in bear_pts:
                lines.append(f"  • {p}")
            for v in res.bear.parsed.get("verify", []):
                lines.append(f"  • verify: {v}")
        else:
            lines.append("⚠️ Bear case could not be generated - do not act on "
                         "this alert; treat as incomplete.")

    lines.append("")
    lines.append("—")
    lines.append(disclaimer.strip())
    return "\n".join(lines)
