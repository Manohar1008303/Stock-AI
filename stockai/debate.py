"""Phase 3: the multi-agent debate (bull -> bear -> judge).

Design contract (this is the anti-fabrication core):
- Every AGENT reasons only from the StockBrief it is given (real screener
  numbers). Any statement made as a FACT must trace to a number in the brief.
- Unknowns are never asserted. If something matters but isn't in the data, the
  agent raises it as a "verify this" item addressed to the human - phrased as a
  question, never as a claimed answer.
- The judge enforces the above: it flags any ungrounded factual claim rather
  than letting it reach the alert, and always outputs a bear counter-point.

No headline fetching, no external data. The debate adds *reasoning* on top of
the real numbers, not new facts.
"""
import json
from dataclasses import dataclass
from typing import Optional

from .package import StockBrief


# --- System prompts ----------------------------------------------------------
# Shared grounding rule injected into every agent so the constraint is explicit.
_GROUNDING = (
    "STRICT RULES:\n"
    "1. Only state as FACT things present in the DATA block below. Every factual "
    "claim must be traceable to a number given to you.\n"
    "2. NEVER invent numbers, news, headlines, results, orders, or events. You "
    "do not have news access.\n"
    "3. If something matters but is not in the DATA, do NOT guess it. Instead add "
    "it to 'verify' as a question for the human to check (e.g. 'Check whether Q "
    "results were announced today'). Phrase it as a question, not an answer.\n"
    "4. Be concise and specific. No filler. Plain English, short sentences.\n"
)

_BULL_SYS = (
    "You are the BULL analyst in a stock debate. Your job: make the strongest "
    "evidence-based case for why this stock is worth a closer look RIGHT NOW, "
    "using only the screener data provided. You are not a cheerleader; a weak "
    "case honestly stated is better than an inflated one.\n\n" + _GROUNDING +
    "\nRespond ONLY with JSON: {\"thesis\": str, \"points\": [str, ...], "
    "\"verify\": [str, ...]}. 'points' = 2-4 concrete bullish observations from "
    "the data. 'verify' = things the human should check that you cannot know."
)

_BEAR_SYS = (
    "You are the BEAR analyst in a stock debate. Your job: be the skeptic. Ask "
    "whether this is a real setup or a trap - e.g. a spike being chased at the "
    "top. Use only the screener data provided. Your value is catching what an "
    "excited buyer would miss.\n\n" + _GROUNDING +
    "\nRespond ONLY with JSON: {\"thesis\": str, \"points\": [str, ...], "
    "\"verify\": [str, ...]}. 'points' = 2-4 concrete bearish/cautionary "
    "observations grounded in the data (e.g. what a large single-day move plus "
    "an outsized volume multiple can imply). 'verify' = specific things the "
    "human must check before acting that you cannot know from price/volume "
    "alone. Always include at least one verify item."
)

_JUDGE_SYS = (
    "You are the JUDGE of a stock debate. You did NOT do your own research; you "
    "weigh the bull and bear cases against the DATA. Your output goes into a "
    "research alert for a human.\n\n" + _GROUNDING +
    "5. If the bull or bear stated anything as fact that is NOT supported by the "
    "DATA, do not repeat it; note it under 'flagged'.\n"
    "6. You must ALWAYS include the bear's key counter-point in your summary. "
    "This is non-negotiable.\n\n"
    "Respond ONLY with JSON: {\"verdict\": str, \"signal\": str, "
    "\"conviction\": int, \"why_interesting\": [str,...], \"key_bear_point\": str, "
    "\"must_verify\": [str,...], \"flagged\": [str,...]}. "
    "'verdict' is a short phrase like 'Leans bullish, with caution' - NEVER a "
    "bare buy/sell instruction. 'signal' MUST be one of exactly: 'green' (bull "
    "case clearly stronger and well-supported), 'amber' (mixed / needs "
    "verification / extended), or 'red' (bear case stronger / looks like a trap). "
    "When in doubt, choose amber - a spike being chased should be amber or red, "
    "not green. 'conviction' is an integer 1-10 for how strong the case is "
    "(higher = stronger), and should be modest when data is thin or the move is "
    "extended. 'key_bear_point' is the single most important caution. 'flagged' "
    "lists any ungrounded claims you caught (empty list if none)."
)


@dataclass
class AgentOut:
    role: str
    raw: str                 # raw text returned
    parsed: Optional[dict]   # parsed JSON, or None if parse failed
    ok: bool
    error: str = ""


@dataclass
class DebateResult:
    symbol: str
    bull: AgentOut
    bear: AgentOut
    judge: AgentOut
    usage: dict              # token usage totals for this stock


def _data_block(brief: StockBrief) -> str:
    return "DATA (the only facts you have):\n" + brief.to_prompt_block()


def build_messages(role_sys: str, brief: StockBrief, prior: dict = None):
    """Construct the messages list for one agent call."""
    user = _data_block(brief)
    if prior:
        # give the judge the bull and bear outputs to weigh
        user += "\n\nBULL SAID:\n" + json.dumps(prior.get("bull", {}), indent=2)
        user += "\n\nBEAR SAID:\n" + json.dumps(prior.get("bear", {}), indent=2)
    return [{"role": "user", "content": user}], role_sys


def parse_agent(role: str, text: str) -> AgentOut:
    """Parse an agent's JSON response defensively."""
    cleaned = text.strip()
    # strip code fences if the model added them
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip("`").strip()
    try:
        parsed = json.loads(cleaned)
        return AgentOut(role, text, parsed, ok=True)
    except (json.JSONDecodeError, ValueError) as e:
        return AgentOut(role, text, None, ok=False,
                        error=f"could not parse JSON: {e}")


# Exposed so the runner can show prompts in --dry-run without an API client.
BULL_SYS = _BULL_SYS
BEAR_SYS = _BEAR_SYS
JUDGE_SYS = _JUDGE_SYS
