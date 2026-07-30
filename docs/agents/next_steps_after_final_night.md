# Next Steps After the Final Night (post-2026-07-26)

Implementation brief for a follow-up agent. Self-contained: every task states why it matters, which
file and function to touch, the flag name, the tests to write, the exact command to verify, and the
bar that decides whether it ships. Do the tasks in the order given; each is independent, so a task
that stalls can be abandoned without blocking the next one.

Read [`final_night_commonsense_first.md`](final_night_commonsense_first.md) first for context on what
already landed. That document is a **record of completed work** — do not re-implement it.

## Ground rules (apply to every task)

- Use Python 3.12 through `.venv/bin/python`. Never invoke bare `python`.
- **Never read, edit, stage, or overwrite `.env`.** It is local user configuration. When an LLM
  backend is needed, set `TPC_P2_LLM_BACKEND=deepinfra` and let the code's
  `build_llm_client` → `load_local_env()` load the key itself.
- **Every new behavior goes behind an env flag that is OFF by default in the library.** The
  deterministic floor must stay byte-identical when the flag is unset, and a unit test must assert
  that. Only `agent_env/scripts/solve_phase2.py::apply_deterministic_solver_defaults()` may turn a
  flag on by default, and only after a measured screen.
- **Ground every fact in `WorldEnv`.** Never fabricate a POI, price, opening window, or transport
  leg. Never let an LLM decide a fact; LLM output is a proposal that deterministic code must verify.
- **Acceptance first.** A candidate plan is only retained after its applicable logical, schema, and
  commonsense checks pass. Do not weaken `_make_checker`, `_accepted`, or the commit rules in
  `_pack_plan`.
- Work on a branch (`claude/<topic>` or similar), never commit directly to `main`, and run
  `.venv/bin/python -m pytest tests -q` before every commit. The suite is currently green at 666
  tests.
- Current harness defaults, already promoted: `TPC_PIN_TIMED_WINDOWS=1`,
  `TPC_SOLVE_CONVERGE_PATIENCE=15`, `TPC_COMMONSENSE_FIRST=1`. Any A/B arm you run inherits these
  unless you override them explicitly.

## How to measure anything (read before running an experiment)

The paired quick screen is the only measurement tool you need:

```bash
.venv/bin/python scripts/phase2_quick_eval.py \
  --flag <YOUR_FLAG> --on 1 \
  --mode end-to-end --n 40 --budget-sec 120 --parallel 7
```

It runs the same 40-query subset twice — once with your flag off, once on — and prints FPR,
`overall_true`, per-layer metrics (EPR micro/macro, C-LPR, logical micro, `all_pass`), timeouts, and
parse failures for both arms. Trust only the **delta**; the reduced budget makes absolute numbers
non-comparable to the committed `900 s` rows under `results/phase2_baselines/runs/`.

Two facts about the scoring that determine what is worth doing at all (re-verified against upstream
`LAMDA-NeSy/ChinaTravel` `main` `764614c` on 2026-07-30 — our `eval_tpc.py` reproduces upstream's
official numbers to the last digit):

1. **C-LPR is conditional on the commonsense pass.** A plan failing commonsense scores `0` on the
   `0.25`-weighted logical term and `0` on EPR-macro (`0.10`), regardless of how many clauses it
   satisfies.
2. **DAV/ATT/DDR are averaged over every query in the split, with a zero for each non-passing one**
   (upstream PR #30 changed this on 2026-07-28; `eval_tpc.cal_default_pr_score` used to skip
   non-passing uids). Preference work still only pays on plans that already pass everything, but its
   payout is now scaled by FPR: at FPR `f`, perfecting one preference term is worth `0.05 · f · 100`
   at most, not `0.05 · 100`. FPR is the lever; preference is second order.

Official score weights: `0.10 MicEPR + 0.10 MacEPR + 0.25 C-LPR + 0.40 FPR + 0.05 DAV + 0.05 ATT +
0.05 DDR`.

---

## Task 1: make the organizers' LLM endpoint reachable (default-off)

**Why.** As packaged, the Phase 2 submission makes **zero LLM calls and cannot reach the organizers'
Qwen3.6-27B/SGLang endpoint at all**: `TPC_P2_LLM_BACKEND` defaults to `none`,
`agent_env/config.toml` is gitignored and absent from git (only `config.toml.example` is tracked),
and `TPCAgent`'s `backbone_llm` is `TPCLLM`, whose `_get_response` returns the literal string
`"Empty LLM response"`. Any LLM-backed row in the ledger came from local environment variables, not
from anything in the tree. This task closes the reachability gap **without** turning any LLM stage on
— it is robustness and competition-compliance work, not a score change.

**Where.**
- `chinatravel/agent/phase2/llm_client.py::build_llm_client`
- `agent_env/scripts/solve_phase2.py::_phase2_llm_config` and `resolve_llm_client_and_flags`

**What to implement.**

1. In `_phase2_llm_config` (or `build_llm_client`, whichever keeps the logic in one place — prefer
   `_phase2_llm_config` so the client factory stays dumb), when the resolved backend would be
   `none`, probe these environment variables in order for an OpenAI-compatible base URL:
   `TPC_P2_LLM_BASE_URL`, `OPENAI_BASE_URL`, `OPENAI_API_BASE`, `SGLANG_BASE_URL`. The first
   non-empty one wins, and the backend becomes `openai`.
2. Resolve the model from `TPC_P2_LLM_MODEL`, else `OPENAI_MODEL`. If neither is set, issue **one**
   `GET <base_url>/models` with a short timeout (5 s) and take the first `id` from `data`. Any
   failure — timeout, non-200, malformed JSON, empty list — must fall back to backend `none` rather
   than raise.
3. API key: use `TPC_P2_LLM_API_KEY` or `OPENAI_API_KEY` if set; if neither is set, pass a dummy
   value such as `"EMPTY"`. A local SGLang server does not check keys, and the `openai` SDK requires
   a non-empty string.
4. Record how the backend was chosen. Add a key like `llm_backend_source` with values
   `"config" | "env-explicit" | "autodetect" | "none"` into the telemetry that
   `orchestrator.solve_phase2` already writes, so a row proves what happened.
5. **Keep the parse audit off when the backend was auto-detected.** In
   `resolve_llm_client_and_flags`, the existing rule "default `llm_parse` on when a usable backend is
   configured" must NOT fire for an auto-detected backend. Only an explicit `TPC_P2_LLM_PARSE=1`
   from the operator enables it. Rationale: the last paired screen on current head was RED for
   audit-on versus parse-off, so a discovered endpoint must not silently change planning behavior.

**Tests** (new file `tests/phase2/test_llm_endpoint_autodetect.py`, monkeypatched env only, **no
network**):
- No relevant env var set → `backend == "none"`, `llm_parse is False`.
- `OPENAI_BASE_URL` set plus `TPC_P2_LLM_MODEL` set → `backend == "openai"`, model as given,
  `llm_parse is False`, `llm_backend_source == "autodetect"`.
- `TPC_P2_LLM_BACKEND=deepinfra` explicitly set → unchanged behavior, `llm_backend_source` is not
  `"autodetect"`.
- Model probe raises or returns an empty list → degrades to `backend == "none"` and does not raise.
- `TPC_P2_LLM_PARSE=1` with an auto-detected backend → `llm_parse is True` (operator override wins).

**Verify.**

```bash
.venv/bin/python -m pytest tests/phase2/test_llm_endpoint_autodetect.py -q
.venv/bin/python -m pytest tests -q

# End-to-end proof that a discovered endpoint changes nothing by default:
OPENAI_BASE_URL=http://127.0.0.1:9999/v1 TPC_P2_LLM_MODEL=fake-model \
  .venv/bin/python agent_env/scripts/solve_phase2.py \
  --split tpc_phase2_familiar_100_val --limit 1 --budget-sec 60 --method phase2_llmdetect_check
```

That URL is intentionally dead. The run must still complete with `valid=True fallback=False`, and
`agent_env/runs/phase2_llmdetect_check/<uid>/telemetry.json` must show `llm_parse` false with no
error. Delete the throwaway method directory afterwards.

**Also do:** add a tracked `agent_env/config.phase2.example.toml` documenting the `[phase2.llm]`
block for an SGLang endpoint (`backend = "openai"`, `base_url`, `model`, `temperature = 0.0`), and
one paragraph in `agent_env/README.md` pointing at it.

**Ship bar.** Tests green and the dead-endpoint run unaffected. This task does not need a screen,
because default behavior is unchanged by construction. **Stop here** — do not enable any LLM stage as
part of this task.

**Optional follow-up, only with a working endpoint and spare API credits.** Three-arm parse screen at
`n=20`, `--budget-sec 120`: parse off, `TPC_P2_LLM_PARSE=1` (audit mode), and `TPC_P2_LLM_PARSE=1
TPC_P2_LLM_PARSE_MODE=extract`. Set `TPC_P2_LLM_TIMEOUT_SEC=8` so the call fits the parse slice, and
confirm from the screen's LLM-activity line that `llm_parse fired > 0` before believing any arm. Ship
a parse mode only if it beats parse-off on **both** `fpr` and `overall_true` with no new parse
failures; otherwise set `TPC_P2_LLM_PARSE=0` explicitly in
`resolve_llm_client_and_flags` and record the decision in
[`../tpc_phase2_roadmap.md`](../tpc_phase2_roadmap.md).

---

## Task 2: fix the single-day-trip overnight-accommodation defect

**Why.** This is the cheapest remaining FPR gain and it is fully deterministic. Three uids in
familiar-100-val fail all four intercity commonsense columns at once
(`phase2_familiar_e20241028160403455246_00065`, `phase2_familiar_e20241028160409480928_00071`,
`phase2_familiar_e20241028160444030851_00066`). Diagnosis, already done: each is a **1-day trip whose
last activity is an overnight accommodation running to `24:00`**. `_repair_intercity_endpoints` then
computes its departure floor from that activity's end time (`24:00` = 1440 minutes) and no return
train or flight can depart after it, so the repair silently declines and the plan ships without a
return leg. Reproduce:

```bash
.venv/bin/python -c "
import json
uid='phase2_familiar_e20241028160444030851_00066'
p=json.load(open(f'results/phase2_e2e_tpc_phase2_familiar_100_val/{uid}.json'))
print('days:', len(p['itinerary']))
print('last activity:', p['itinerary'][-1]['activities'][-1])
"
```

An overnight stay in a single-day itinerary is wrong on its own terms, independent of the return leg.

**Where.** `chinatravel/agent/tpc_agent/tpc_agent.py`, inside `_repair_intercity_endpoints` (the
return-endpoint half, which starts at the `# Return endpoint: last-day final activity.` comment).

**What to implement.** Behind a new flag `TPC_REPAIR_DROP_TRAILING_STAY` (default off; also enabled
implicitly by `TPC_COMMONSENSE_FIRST` via the existing `_flag_enabled_with_umbrella` helper, matching
how `TPC_REPAIR_INTERCITY` is wired):

1. Before computing the return-leg departure floor, if the plan has **exactly one day** and the last
   day's final activity has `type == "accommodation"`, drop that activity from the trial copy, then
   recompute the floor from the new final non-intercity activity.
2. Re-run the existing return-row search unchanged. Commit through the existing
   `_repair_commit_allowed` — no new commit rule. It already handles the unaccepted case (schema
   valid, commonsense invalid → valid, parsed passes not lower).
3. Do **not** touch multi-day plans: an overnight stay is required there
   (`Accomondation is necessary for trips longer than one day` is an official commonsense column).

**Tests** (extend `tests/phase2/test_repair_intercity_endpoints.py`, reusing its `_FakeEnv` /
`ROWS` / `_base_plan` fixtures — do not build a real `WorldEnv`):
- Flag off → a 1-day plan ending in an accommodation is returned byte-identical.
- Flag on → the accommodation is dropped, a grounded return row is placed, and the stubbed
  commonsense verdict flips to valid.
- Flag on, **2-day** plan ending in an accommodation → untouched (the stay is mandatory there).
- Flag on but no return row can be placed even after the drop → plan returned byte-identical (no
  partial commit that leaves the plan without its overnight stay *and* without a return leg).

**Verify.**

```bash
.venv/bin/python -m pytest tests/phase2/test_repair_intercity_endpoints.py -q

for UID in phase2_familiar_e20241028160403455246_00065 \
           phase2_familiar_e20241028160409480928_00071 \
           phase2_familiar_e20241028160444030851_00066; do
  TPC_REPAIR_DROP_TRAILING_STAY=1 .venv/bin/python agent_env/scripts/solve_phase2.py \
    --split tpc_phase2_familiar_100_val --uid $UID --budget-sec 150 --method phase2_stay_check
done

.venv/bin/python -c "
import json,glob
for f in sorted(glob.glob('agent_env/runs/phase2_stay_check/*/evaluation.json')):
    e=json.load(open(f)); r=e['commonsense_details'][0]
    print(e['uid'], [k for k,v in r.items() if k!='data_id' and v==1], 'overall_true', round(e['overall_true'],2))
"
```

**Ship bar.** All three uids lose their intercity commonsense failures, plus a paired screen
(`--flag TPC_REPAIR_DROP_TRAILING_STAY`, `--mode end-to-end --n 40 --budget-sec 120 --parallel 7`)
showing `overall_true` not worse and `commonsense pass` not worse. Because only single-day trips are
affected, expect a small but clean delta. If the screen is clean, promote in
`apply_deterministic_solver_defaults()` with the evidence in the docstring, following the
`TPC_COMMONSENSE_FIRST` entry as the template. Clean up the throwaway method directories.

---

## Task 3: preference packing (DAV/ATT/DDR) on already-passing plans

**Why, and what it is worth.** Measured on the promoted row's all-pass plans: DAV `85.94`,
ATT `88.10`, **DDR `65.42`**. Perfecting all three is worth `3.03` points of `eval_tpc`'s official
aggregate (`0.05 × (300 − 239.46)`), and `0.76` on the per-query `overall_true` mean the rehearsal
reports — the two differ because preference is averaged over all-pass queries only. Re-measure before
starting, since the numbers move with FPR:

```bash
.venv/bin/python scripts/phase2_commonsense_headroom.py --quiet
```

**DDR is the weak axis. The honesty question that used to live here is closed** (2026-07-30):

- DDR is still `(meal_count / day_count) / 3`, but upstream PR #29 made a repeated meal type on one
  day a commonsense failure (`Repeated Meal Types in One Day`). Meal stacking therefore no longer
  raises DDR — it drops the plan out of `all_pass_id`, forfeiting FPR, C-LPR, EPR-macro and all
  three preference terms at once.
- The `patched_*` reporting that existed to expose this leniency is removed; the official checker now
  is the strict checker.
- `TPC_PACK_HOTEL_BREAKFAST` (and the duplicate-meal part of `TPC_PACK_DDR`) are consequently dead
  weight rather than a temptation: `_topup_hotel_breakfasts` commits only when `check(plan)` still
  accepts, and `check` gates on commonsense once the hard constraints pass, so a stacked day is
  reverted automatically. The remaining legitimate DDR move is adding a *missing* meal type at a real
  restaurant.

**Where.** `chinatravel/agent/tpc_agent/tpc_agent.py`. `_pack_plan` already densifies (`attr_per_day`
3 then 4) and calls `_densify_plan`; both are gated by `check`. `scripts/maxpack.py` contains the
Phase 1 implementation of every move below — **read it and port the logic**, do not invent new
moves. It reuses `_get_transport`, `_make_*_activity`, `_poi_open_bounds`, and `_find_hotel_for_day`.

**What to implement**, in this order, each committed only when the full checker still accepts and the
preference key does not regress (the existing `_accepted_eval_key` comparison):

1. **DAV top-up** (safest, legitimate): insert nearest unused attractions until the day holds 4.
   Flag `TPC_PACK_DAV`.
2. **ATT protection**: after any insertion, re-route each affected hop to its shortest-time valid
   mode via `_get_transport`, trying a free walk first so inner-city cost budgets are respected.
   Fold into the same flag as (1) — an insertion that wrecks ATT is not an improvement.
3. **DDR meal top-up**: add missing lunch/dinner at real restaurants where a free gap in the meal
   band exists. Flag `TPC_PACK_DDR`.
4. ~~**Free hotel-breakfast top-up**~~ — obsolete since the 2026-07-30 upstream evaluator sync. The
   implementation stays behind `TPC_PACK_HOTEL_BREAKFAST` (default off) but can no longer commit a
   second breakfast: the day fails `Repeated Meal Types in One Day` and `check` reverts it.

Only run these on plans that are **already accepted** — preference is worthless on a failing plan,
and this work must never risk acceptance. Bound the work by the remaining solve budget, as
`_pack_plan` already does with `time.time() - self.start_clock > self.solve_budget_sec`.

**Tests** (new `tests/phase2/test_preference_packing.py`, bare-agent pattern from
`tests/phase2/test_pin_timed_windows.py`): flag-off byte-identical floor for each flag; one committed
DAV insertion; an insertion rejected because the checker stops accepting; an insertion rejected
because it lowers the preference key; a hotel-breakfast top-up committed only with its own flag on.

**Verify and report both scores.**

```bash
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_PACK_DAV --on 1 \
  --mode end-to-end --n 40 --budget-sec 120 --parallel 7

# Official aggregate on a results directory (this is the authority for preference):
.venv/bin/python eval_tpc.py --splits tpc_phase2_familiar_100_val \
  --method phase2_e2e_tpc_phase2_familiar_100_val --lang en
```

**Ship bar.** `DAV`/`ATT`/`DDR` up in the `eval_tpc.py` output with `FPR` and `C-LPR` unchanged or
better, and no new timeouts in the screen. Promote `TPC_PACK_DAV`/`TPC_PACK_DDR` if clean. There is
no longer an official-versus-patched split to report: since the upstream sync there is one score.

---

## When you are done

Update [`../tpc_phase2_roadmap.md`](../tpc_phase2_roadmap.md): move each finished item out of "Next
steps", record the measured numbers and the screen path, and keep the "Commonsense-first finding"
section intact as history. If you promoted a flag, update the README "Current state" paragraph and
phrase it as screen evidence, not as a gate, unless a committed `900 s` row backs it.

Do not start work outside these three tasks. No new solver move, no new parser family, no agentic
loop, and no promotion of `TPC_CASCADE_TIMED_WINDOWS` (its own `900 s` gate found no effect).
