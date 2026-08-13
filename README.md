# StockAI

A live-running agent system that screens Indian (NSE) stocks, then runs a
structured bull-vs-bear debate on the survivors and sends a Telegram alert
explaining **why a stock is worth a look**.

**This is a research/alert tool. It never places orders, never touches a broker,
never deploys capital.** Screening and explanation only.

---

## Status: live dashboard + 8 agents — done

| Phase | What it does | State |
|-------|--------------|-------|
| 1 | **Scout / Screener** — filter the universe by your thresholds | ✅ done |
| 2 | **Packaging + token-budget guard** — build briefs, bound the cost | ✅ done |
| 3 | **Bull → Bear → Judge debate** via Claude | ✅ done |
| + | **Technician, Fundamentalist, Newsdesk** agents | ✅ done |
| + | **layrs desk** — live browser dashboard (local server) | ✅ done |
| 4 | Messenger — Telegram (alert with bear case + disclaimer) | pending |
| 5 | Scheduler (daily auto-run) | pending |

## The layrs desk dashboard (live)

A browser cockpit showing all 8 agents working through the shortlist, with the
"layers" spine that fills as each analysis layer completes. It runs on a **local
Python server on your machine** — your API keys stay server-side and are never
sent to the browser.

```bash
pip install -r requirements.txt
export STOCKAI_ANTHROPIC_KEY="sk-ant-..."      # for the debate (optional)
export STOCKAI_DATA_KEY="your-alphavantage"    # for fundamentals + news (optional)
python3 serve_dashboard.py
```

Then open **http://localhost:8000**. Two ways to use it:

- **Analyze one stock** — type a symbol (`DEVYANI`) or company name
  (`Reliance Industries`) in the box and hit analyze. Runs all 8 agents on just
  that stock, skipping the screener. If it can't resolve what you typed, it says
  so — it never analyses the wrong company by guessing.
- **Scan movers** — the button screens your whole universe and debates only the
  survivors (the original screener flow).

Without keys, the fundamentals/news agents honestly show "no data" and the
debate is skipped — never fabricated. Get a free Alpha Vantage key at
alphavantage.co/support/#api-key.

**Two guardrails, built in and visible:**
- **Newsdesk** shows only real headlines with source links, or "no news data".
  It never invents a headline or a sentiment score. (Alpha Vantage coverage for
  NSE small-caps is thin, so "no news data" is common and correct.)
- **The Judge** gives a lean + the bear case, always attached — never a naked BUY.

The demo dashboard (`dashboard/layrs_desk.html`) is a standalone file you can
open by double-clicking — it runs a simulated pass for a quick look. The **live**
dashboard (`dashboard/layrs_desk_live.html`) only works through the server.

---

## Quick start

```bash
pip install -r requirements.txt

# Phase 1 - screener only (free):
python3 run_phase1.py                  # live
python3 run_phase1.py --demo           # sample data, no network

# Phase 2 - package survivors + token budget (free):
python3 run_phase2.py                  # live
python3 run_phase2.py --demo           # sample data, no network

# Phase 3 - the debate:
python3 run_phase3.py --dry-run        # show prompts, NO API calls, $0
python3 run_phase3.py                   # LIVE: real data + real API calls ($)
```

Phases 1 and 2 never call an LLM. Phase 3's `--dry-run` also spends nothing —
it prints the exact prompts that would be sent. A real Phase 3 run calls the
Claude API (costs money) and needs `STOCKAI_ANTHROPIC_KEY` set. It still sends
nothing to Telegram; that's Phase 4.

### The debate, and how it can't fabricate

Three agents run per shortlisted stock: **bull → bear → judge**.

- Each agent sees **only** the screener brief (real numbers). Every factual
  claim must trace to a number in that brief.
- Agents **never invent** news, results, or events. If something matters but
  isn't in the data, the agent raises it as a **"verify this" question for you**
  — phrased as a question, never as an answer it made up.
- The **judge** enforces this: if the bull or bear stated something ungrounded,
  the judge flags it instead of passing it into your alert, and **always**
  includes the bear counter-point.
- Every alert carries the bear case, "verify before acting" items, and the
  research-only disclaimer — even if an agent's output fails to parse (the
  pipeline degrades gracefully and never drops the bear case).

---

## Where everything lives: `config.yaml`

**All** thresholds, the universe list, schedule times, and key *placeholders*
live in one file: `config.yaml`. Nothing tunable is hardcoded elsewhere.

Key sections:

- `universe.symbols` — the NSE stocks to screen. Add/remove freely.
- `screener` — every threshold:
  - `min_price` / `max_price` — price band
  - `volume_breakout.multiple` — e.g. `2.0` = today's volume ≥ 2× the 20-day avg
  - `volume_breakout.lookback_days` — the averaging window
  - `price_above_sma.sma_days` — close must be above this SMA (e.g. 50)
  - `min_pct_change.value` — minimum daily move, e.g. `2.0` (%)
  - `max_shortlist` — hard cap on how many go to the debate (token control)
  - any check can be turned off with `enabled: false`
- `debate` — model + token budget per agent (Phase 3), plus the **token-budget
  guard** (Phase 2):
  - `token_budget.max_stocks_to_debate` — hard ceiling on stocks sent to the
    debate; the run refuses if exceeded
  - `token_budget.max_tokens_per_run` — if the pre-call estimate exceeds this,
    the run refuses rather than spending
  - `token_budget.usd_per_1m_input` / `usd_per_1m_output` — pricing for the
    cost display only; never affects what's sent
- `schedule` — run time / timezone (Phase 5)
- `alerts.disclaimer` — the research-only text on every alert
- `runtime.dry_run` — `true` prints alerts instead of sending them

### Tuning example

Want a stricter screen? In `config.yaml`:

```yaml
screener:
  volume_breakout:
    multiple: 3.0        # was 2.0 — demand a bigger volume spike
  min_pct_change:
    value: 4.0           # was 2.0 — only strong movers
```

Re-run `python run_phase1.py`. No code changes needed.

---

## Secrets

Phase 1 needs no keys. Later phases do. Put them in the environment (preferred),
not in the file:

```bash
cp .env.example .env      # then fill in .env
```

Environment variables override `config.yaml`. Recognised vars:
`STOCKAI_TELEGRAM_TOKEN`, `STOCKAI_TELEGRAM_CHAT_ID`, `STOCKAI_ANTHROPIC_KEY`,
`STOCKAI_DATA_KEY`.

---

## Hard constraints this project keeps

- **No orders, ever.** No broker API, no capital deployment. Alerts only.
- **No fabricated data.** If data is missing, the system says *"no reliable
  data"* and skips the stock. It never invents a number or a headline. (Demo
  mode uses clearly-labelled SAMPLE data that can never become an alert.)
- **One config file** for all thresholds, lists, schedule, and key placeholders.
- **Token awareness.** Only post-screener survivors reach the debate — never the
  full universe. `max_shortlist` caps it.
- **Every alert** (Phase 4) carries the bear counter-point and a research-only
  disclaimer.

---

## Project layout

```
stockai/
├── config.yaml           # <-- the one place you tune anything
├── requirements.txt
├── .env.example
├── sample_data.csv       # SAMPLE bars for --demo (not live)
├── run_phase1.py         # Phase 1 runner (screener)
├── run_phase2.py         # Phase 2 runner (package + budget guard)
├── run_phase3.py         # Phase 3 runner (debate; --dry-run is free)
└── stockai/
    ├── config.py         # loads yaml, overlays env vars, validates
    ├── data.py           # real market data; explicit "no data" on failure
    ├── screener.py       # applies thresholds, returns pass/fail + reasons
    ├── package.py        # builds debate briefs + token-budget guard
    ├── debate.py         # bull/bear/judge prompts + JSON parsing
    ├── llm.py            # Anthropic API client (isolated; unused in dry-run)
    └── orchestrate.py    # runs the debate, formats alerts, enforces bear case
```

## Token cost

Phases 1 and 2 make **no** LLM calls, so they cost nothing in tokens. Phase 2
*estimates* the Phase-3 cost before any call and prints it, e.g. ~$0.12 for a
3-stock run. The estimate errs high on purpose (it over-counts scaffolding) so
the real bill comes in at or under what you're shown. The guard refuses to
proceed if a run would exceed `max_stocks_to_debate` or `max_tokens_per_run`.
