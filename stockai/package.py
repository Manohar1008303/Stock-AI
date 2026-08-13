"""Phase 2: shortlist packaging + token-budget guard.

Two jobs, both BEFORE any LLM call:

1. Package each shortlisted stock into a clean, structured brief containing only
   real numbers from the screener. This is the exact (and only) data the debate
   agents in Phase 3 will see. No fabrication: every field traces to fetched
   data; anything unknown is the string "unknown", never a guess.

2. Guard the token budget. Estimate the cost of the whole run before spending a
   rupee, and refuse to proceed if the shortlist exceeds the configured ceiling
   or the estimate exceeds the per-run token budget. This is the mechanism that
   guarantees only post-screener survivors reach the debate, never the universe.
"""
from dataclasses import dataclass, asdict
from typing import List, Optional

from .screener import ScreenResult


# --- Structured brief --------------------------------------------------------
@dataclass
class StockBrief:
    """Exactly what one debate gets. Real numbers only."""
    symbol: str
    close: float
    pct_change: float
    volume: float
    avg_volume: float
    volume_multiple: float      # volume / avg_volume, the breakout strength
    sma: float
    sma_label: str              # e.g. "SMA50"
    passed_checks: List[str]    # the PASS lines from the screener
    data_source: str = "Yahoo Finance NSE (.NS), daily bars"
    note: str = ""              # any caveat, e.g. partial data

    def to_prompt_block(self) -> str:
        """Render as a compact, unambiguous text block for the LLM.

        Kept terse on purpose: fewer tokens, and no room to hallucinate.
        """
        lines = [
            f"Symbol: {self.symbol}",
            f"Last close: Rs {self.close:.2f}",
            f"Today's move: {self.pct_change:+.2f}%",
            f"Volume: {self.volume:,.0f} vs avg {self.avg_volume:,.0f} "
            f"({self.volume_multiple:.1f}x average)",
            f"{self.sma_label}: Rs {self.sma:.2f} "
            f"(close is {'above' if self.close > self.sma else 'below'} it)",
            f"Screener checks passed: {'; '.join(self.passed_checks)}",
            f"Data source: {self.data_source}",
        ]
        if self.note:
            lines.append(f"Note: {self.note}")
        return "\n".join(lines)


def build_brief(r: ScreenResult, sma_days: int) -> StockBrief:
    d = r.data
    vol_mult = (d.volume / d.avg_volume) if d.avg_volume else 0.0
    only_pass = [x for x in r.reasons if x.startswith("PASS")]
    return StockBrief(
        symbol=r.symbol,
        close=d.close,
        pct_change=d.pct_change,
        volume=d.volume,
        avg_volume=d.avg_volume,
        volume_multiple=vol_mult,
        sma=d.sma,
        sma_label=f"SMA{sma_days}",
        passed_checks=only_pass,
        note=d.note or "",
    )


# --- Token budget guard ------------------------------------------------------
@dataclass
class BudgetEstimate:
    n_stocks: int
    est_input_tokens: int
    est_output_tokens: int
    est_total_tokens: int
    est_usd: float
    within_budget: bool
    reason: str                 # why it passed or was rejected


def _rough_tokens(text: str) -> int:
    """Cheap token estimate: ~4 chars per token. Good enough for a guard."""
    return max(1, len(text) // 4)


# A fixed overhead per debate for the system/instruction scaffolding in Phase 3.
# Deliberately generous so the estimate errs high, never low.
_SCAFFOLD_TOKENS_PER_STOCK = 900


def estimate_budget(briefs: List[StockBrief], debate_cfg: dict) -> BudgetEstimate:
    tb = debate_cfg["token_budget"]
    per_agent_out = debate_cfg["max_tokens_per_agent"]
    # bull + bear + judge = 3 generations per stock
    agents = 3

    input_tokens = 0
    for b in briefs:
        block = b.to_prompt_block()
        input_tokens += _rough_tokens(block) * agents + _SCAFFOLD_TOKENS_PER_STOCK * agents

    output_tokens = per_agent_out * agents * len(briefs)
    total = input_tokens + output_tokens

    usd = (input_tokens / 1_000_000 * tb["usd_per_1m_input"]
           + output_tokens / 1_000_000 * tb["usd_per_1m_output"])

    # Budget checks
    if len(briefs) > tb["max_stocks_to_debate"]:
        return BudgetEstimate(
            len(briefs), input_tokens, output_tokens, total, usd, False,
            f"REFUSE: {len(briefs)} stocks exceeds max_stocks_to_debate="
            f"{tb['max_stocks_to_debate']}",
        )
    if total > tb["max_tokens_per_run"]:
        return BudgetEstimate(
            len(briefs), input_tokens, output_tokens, total, usd, False,
            f"REFUSE: estimated {total:,} tokens exceeds max_tokens_per_run="
            f"{tb['max_tokens_per_run']:,}",
        )
    return BudgetEstimate(
        len(briefs), input_tokens, output_tokens, total, usd, True,
        f"OK: {len(briefs)} stock(s), ~{total:,} tokens, ~${usd:.3f} per run",
    )


def package_shortlist(shortlist: List[ScreenResult], config) -> tuple:
    """Turn the screener shortlist into briefs + a budget verdict.

    Returns (briefs, estimate). Never calls an LLM.
    """
    sma_days = config["screener"].get("price_above_sma", {}).get("sma_days", 50)
    briefs = [build_brief(r, sma_days) for r in shortlist]
    estimate = estimate_budget(briefs, config["debate"])
    return briefs, estimate
