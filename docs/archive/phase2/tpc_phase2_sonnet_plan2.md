# Phase 2 Plan 2: fast evaluation loop + parsing architecture (autonomous implementation)

> **Status 2026-07-12:** Steps 0 (coding-VM parts), 1, 2, 3, and 5 are landed (`2fb808c4`,
> `d6d45df3`, `4d88d459`); Step 4's worker code is landed (`e31ef2c2` — VM-2 deployment and
> first ledger-branch rows pending); Step 6's extract mode is implemented and probe-tested
> (`79121a95` — e2e A/B rungs 2–4 and the promotion/kill verdict pending). Step 3's calibration
> run pair and Step 0.2's det-only anchor still need the eval VM. All remaining work — Step 4
> deployment, Step 6's measurement, Step 7 — is **carried over into `docs/tpc_phase2_plan3.md`**
> (as M1, M2, and N4/N6/L3 respectively), which is the plan to execute next — it reorders
> priorities around the 2026-07-12 deep-review findings (see the gap map there) and inherits
> this plan's ground rules verbatim.

Self-contained follow-up to `docs/tpc_phase2_sonnet_plan.md` (plan 1), written for a Sonnet 5
agent to execute without access to the conversation that produced it. Read this whole file before
starting. Plan 1's steps 1–5 are landed (commits `33795fab`…`000b88a7`); its steps 6–7 are carried
over here (Step 7 below). Background docs, read as needed: `docs/tpc_phase2_design.md`
(architecture + status), `docs/tpc_phase2_eval.md` (measurement methodology),
`docs/phase2_baselines/README.md` (ledger row comparability rules).

## Why this plan exists

Two things throttle progress right now, and they compound:

1. **End-to-end evaluation is the only signal we can trust, and it is slow.** The one honest
   headline from plan 1's measurements: better *parsing metrics* do not reliably mean better
   *end-to-end FPR* (behavioral agreement +9 pts coincided with e2e FPR −4.7 pts at 60s; see
   `docs/tpc_phase2_eval.md`, "the parser win did not transfer"). So every parsing change must be
   judged e2e — but a full-fold e2e row costs 67–90 min at the "fast" 100s config and ~7.5 h at
   the realistic 300s config, and the working tree is code-frozen for the duration.
2. **Parsing quality is still the dominant loss** (parsing loss 15.3 FPR pts vs solver headroom
   4.7 at 300s, run `20260711T192208Z`), and the current architecture — regex parser + LLM
   corrective audit — has structural ceilings (Findings F6/F7 below) that suggest an LLM-first
   extraction mode is worth a real A/B.

The ordering consequence: **make evaluation fast and trustworthy first (Steps 1–5), then use that
machinery to settle the parsing-architecture question (Step 6).** Attacking parsing first would
just re-run the plan-1 experience of waiting hours per data point.

## Current measured state (2026-07-12)

- Latest completed ledger row `20260711T192208Z` (300s, fold 0, n=85, repeats=2, LLM audit on,
  *static* budget, *pre*-step-5 parser): ceiling 100 / solver-only FPR 95.29 / e2e FPR 80.00.
  Parsing loss 15.29 pts, solver headroom 4.71 pts.
- 60s comparison pair (n=85): deterministic parse e2e FPR **85.88** (`20260711T000602Z`) vs
  genuine LLM-audit e2e FPR **81.18** (`20260711T071751Z`) — the audit *regressed* e2e despite
  raising full-val behavioral agreement 0.7788 → 0.8694. e2e FPR is nearly budget-flat for
  parsing purposes (81.18@60s vs 80.00@300s).
- Deterministic parser after plan-1 step 5 (5a–5d commits `50c2a240`…`000b88a7`): full-val
  behavioral agreement ≥ 0.7988 (measured after 5c; 5d closed `room_type` wrong_value 19 → 0).
  Big family gaps (`poi_distance_hotel`, `hotel_amenity`, `excluded_cuisine_types`, `room_type`)
  are closed or reduced to documented ceilings.
- A baseline job labeled `dynbudget-step5-fullfold0-300s` (300s, n=85, repeats=2, parallel=3,
  runner defaults = dynamic budget + disjunction + LLM audit) was launched 2026-07-12 ~08:00
  UTC+2 from the main working tree. **Check it completed and read its row before Step 6** — it is
  the first row with both the dynamic budget and the step-5 parser, i.e. the freshest anchor.
- Runner defaults (`agent_env/scripts/solve_phase2.py::run_split`, lines ~146–160):
  `TPC_P2_DISJUNCTION`, `TPC_P2_DYNAMIC_BUDGET` on; `TPC_P2_LLM_PARSE` on whenever a backend is
  configured. Library `Flags()` defaults all off (byte-identical deterministic path invariant).
- **Missing anchor:** there is no deterministic-only (LLM off) 300s row with the step-5 parser and
  dynamic budget. Step 6's promotion decision needs it; Step 4's eval worker should produce it
  (or run it locally overnight) — see Step 0.

## Review findings (evidence for the step designs)

**F1 — Eval cost is a design artifact of the solve loop, and FPR barely depends on budget.**
`TPCAgent._solve` (`chinatravel/agent/tpc_agent/tpc_agent.py:650`) keeps running random restarts
(max 400) until the wall-clock slice is exhausted *even after an accepted plan is found* — by
design, to lift the continuous preference score. So every rehearsal query costs ~0.95 × budget
regardless of difficulty, and a row costs `repeats × n × 1.9 × budget ÷ parallel`. But the metric
we iterate on (FPR, a binary oracle-pass per query) moved only 1.18 pts between 60s and 300s.
We are paying linearly in budget for a signal that is nearly budget-flat → Step 3 (early-exit
eval mode).

**F2 — Most e2e re-solves are redundant across parser iterations.** A parser change alters the
solver's *input* (the constraint variants) for only the uids whose parse actually changed —
typically a handful per fix (step-5 commits touched 10–60 of 850 val uids each). The solver is
deterministic given its variants (measured `*_std = 0.0` across repeats; LLM at temp 0 with disk
cache), so re-solving the other ~95% of uids reproduces the baseline row byte-for-byte. Nothing
exploits this today: `--fresh` wipes the whole fold and re-solves everything → Step 2
(differential e2e). Ledger rows already record per-uid outcomes (`all_pass_ids` in
`rehearsal`), so only the fingerprint side is missing.

**F3 — Working-tree evals impose a repo-wide code freeze.** The rehearsal's chunked subprocesses
re-import on-disk code mid-run, and `phase2_record_baseline.py::_git_sha` stamps `git rev-parse
HEAD` at *write* time (line 71), so a mid-run commit silently produces a mixed-code, mislabeled
row (this happened; see the measurement-hygiene rule in plan 1). Running evals from a pinned
`git worktree` checkout kills both problems at once and is the prerequisite for the second-VM
eval worker → Step 1.

**F4 — The 20-second proxy is one-sided, which is exactly why it mispredicted e2e.**
`parser_vs_oracle.py`'s behavioral check (lines ~383–388) evaluates parsed vs oracle constraints
on **one plan per uid: the oracle-optimal `results/best/<uid>.json`**. That catches *spurious*
parsed constraints (they reject the good plan) but is structurally blind to *missing* constraints
(both sides accept the good plan) — and missing constraints are precisely what makes a freshly
solved plan fail the oracle check e2e. The LLM audit's +9 behavioral pts came partly from
*removing* constraints (recall 0.6977 → 0.6779), which this metric cannot penalize → Step 5
(two-sided proxy).

**F5 — The two-VM setup removes the last excuse for measuring rarely.** The user has a second VM
available to run long evals continuously against whatever is pushed. With Step 1's pinned
checkouts, an unattended worker can produce one canonical 300s ledger row per pushed commit with
a truthful `git_sha`, while the coding VM iterates freely → Step 4.

**F6 — The LLM audit architecture has a structural ceiling: everything round-trips through the
regex.** In `normalize.py`, every LLM `add`/`replace` patch and every alternative is realized by
feeding the LLM's `constraint_text` back through
`parse_constraints.parse_single_constraint_text` (`_parse_constraint_text`, normalize.py:275–279).
The LLM can only ever add what the regex parser can already express — a family the regex can't
parse from friendly text is unreachable no matter what the LLM says. `remove` patches are the only
unmediated operation, which is why the audit's failure mode is deleting real constraints (plan-1
gap B6, still open). The audit also spends its one call *checking* the regex instead of *reading
the query*.

**F7 — LLM-first extraction is worth a real A/B, under the existing reliability contract.** The
ingredients are all in place: a schema whitelist (`_LLM_PARSE_ALLOWED_KEYS` + list/dict/scalar
type sets in `normalize.py`), a proven fallback contract (`parse_to_ir` catches every LLM
exception and keeps the deterministic IR; request timeout + deadline-skip landed in plan-1 step
2), disk caching at temp 0, and a deterministic entity-resolution precedent
(`TPCAgent._resolve_required_names`, tpc_agent.py:327, fuzzy-matches names against WorldEnv
candidates). A direct-extraction mode also *decouples the LLM cache from regex changes* (the
audit prompt embeds the deterministic parse, so every regex fix cold-starts the 850-uid cache;
an extraction prompt depends only on the query text). What is *not* yet justified is replacing
anything: the decision must be made on e2e FPR via Steps 1–5's fast loop, with the deterministic
parser remaining the always-computed fallback either way → Step 6.

## Two-VM operating model (target state after Step 4)

- **VM 1 (coding):** development, tests, solver-free parser reports (~20s), differential e2e
  (Step 2, minutes), occasional fast-FPR fold runs (Step 3, ~15–30 min). Never blocked by a
  freeze: long evals don't run from its working tree.
- **VM 2 (eval worker):** a dumb loop (Step 4) that watches `origin/stefan/phase2`, and for each
  new commit runs the canonical 300s row from a pinned worktree checkout, then pushes the ledger
  row to a dedicated `phase2-eval-ledger` branch. Ground truth accumulates unattended; the coding
  VM merges the ledger branch when it wants the numbers.

## Ground rules (updated from plan 1; violating these invalidates results)

1. **Branch/commits:** work on `stefan/phase2`. Commit per completed step,
   `phase2(plan2 step N): ...`. Push after each step (the eval worker consumes pushes).
2. **Tests:** `.venv/bin/python -m pytest` green before every commit. TDD for new behavior.
3. **Flags-off invariant:** library-default `Flags()` keeps the deterministic path
   byte-identical. Every new eval-speed switch in this plan (early-exit, diff-eval) is
   eval-tooling-only: default off in the library *and* in `run_split` (these must never run in
   the organizers' harness), unlike the `TPC_P2_DISJUNCTION` pattern where the runner defaults on.
4. **Measurement hygiene:** promoted measurements go in the committed ledger
   (`make phase2-baseline ... P2_LABEL=<tag>`); gate with `scripts/phase2_gate.py` on
   `fpr`/`parse_failures`/`budget_overruns` (never raw `timed_out`). Rows produced with the
   early-exit mode (Step 3) are labeled `fastfpr-*` and are **never** gate-compared against
   normal rows. **Until Step 1 lands, plan 1's code-freeze rule applies verbatim** (no code
   commits while a baseline job runs from the main tree — check `ps aux | grep record_baseline`
   first); after Step 1, run all long evals via pinned worktrees and the freeze rule is retired
   (update the docs and the memory note when you retire it).
5. **LLM economics:** DeepInfra is paid (`DEEPINFRA_API_KEY` in `.env`, backend `deepinfra`,
   model `Qwen/Qwen3.6-27B`, connectivity `python scripts/try_deepinfra.py`). Responses are
   disk-cached under `cache/phase2_llm_parse/` keyed by prompt hash; **any prompt change cold-
   starts the cache and a full 850-uid run costs ~100 min of real calls.** Probe first
   (`scripts/phase2_llm_parse_probe.py`), full-val second. The 4-core rule: never two solver
   evals at once on one machine.
6. **Never touch the held-out test split** (`tpc_phase2_test.txt`).

## Step 0 — Preconditions (do first, ~15 min of work)

1. Confirm the in-flight `dynbudget-step5-fullfold0-300s` job finished; read its row and update
   the status sections of `docs/tpc_phase2_design.md` (it answers "did dynamic budget + step-5
   parser move the 300s numbers" — the freshest anchor for everything below).
2. Queue the missing **deterministic-only anchor**: same config but `TPC_P2_LLM_PARSE=0`,
   `P2_LABEL=det-step5-dynbudget-300s`. If Step 1 is not yet done, run it overnight under the
   freeze rule; if the eval worker (Step 4) lands first, let VM 2 run it. Step 6 cannot conclude
   without this row.
3. Re-run `scripts/parser_vs_oracle.py --split-set val --behavioral --disjunction --branch-aware`
   (~20s) to pin down the post-5d deterministic behavioral number (last measured 0.7988 after 5c).

## Step 1 — Pinned-worktree eval runs (retire the code freeze)

**Goal:** every long eval runs against an explicit git sha in a disposable `git worktree`, so the
main tree stays free for development and the row's `git_sha` is truthful by construction.

**Files:** new `scripts/phase2_eval_at.py`; small additions to
`scripts/phase2_record_baseline.py`; `tests/phase2/test_eval_at.py`; docs updates
(`docs/tpc_phase2_eval.md` metric→command map, plan-1 freeze-rule retirement notes).

**Design:**

- `phase2_eval_at.py --sha <ref> [--keep] -- <recorder args…>`:
  1. `git worktree add <tmpdir> <sha> --detach` (tmpdir under `/tmp/phase2_eval/<shortsha>/`).
  2. Symlink into the worktree the gitignored state the eval needs from the main repo:
     `cache/`, `results/` (for `results/best` scoring + shared LLM cache), `agent_env/runs/`,
     `.env`. (Inspect `.gitignore` for anything else the rehearsal reads/writes; `chinatravel/
     data/` is committed so the worktree already has it.)
  3. Run `<mainrepo>/.venv/bin/python <worktree>/scripts/phase2_record_baseline.py <args>` with
     `cwd=<worktree>` — subprocesses then import the pinned code, and `_git_sha()` (which runs in
     the script's own project root) stamps the pinned sha.
  4. Pass a new recorder flag `--ledger-dir <mainrepo>/docs/phase2_baselines` so the row, the
     history append, and `latest.*` land in the main repo (the recorder currently hardcodes its
     own `PROJECT_ROOT`; make the ledger dir a parameter with the current behavior as default).
  5. `git worktree remove --force` on success unless `--keep`.
- Also add `make phase2-baseline-at SHA=<ref> ...` mirroring `phase2-baseline`.

**Tests:** unit-test the symlink/arg plumbing with a fake recorder script; one cheap integration
check (marked `integration`): run a `--limit 2 --budget-sec 10` row via `phase2_eval_at.py`,
commit a whitespace change to `parse_constraints.py` in the main tree mid-run (or simply after
worktree creation), assert the row's `git_sha` is the pinned sha, then revert.

**Accept:** the integration check passes; docs updated: the freeze rule text in
`docs/tpc_phase2_eval.md`/plan 1 replaced with "long evals run via `phase2_eval_at.py`".

## Step 2 — Differential e2e evaluation (the core speedup)

**Goal:** after a parser change, re-solve **only the uids whose solver input changed** and splice
the rest from the baseline row. Typical parser fix → e2e verdict in minutes, exact on unchanged
uids by determinism.

**Files:** `scripts/phase2_record_baseline.py` (persist per-uid fingerprints), new
`scripts/phase2_diff_eval.py`, `tests/phase2/test_diff_eval.py`, docs.

**Design:**

- **Fingerprint:** `sha256` of the canonical JSON (`sort_keys=True`) of
  `parser_vs_oracle.query_variants(query, disjunction=…, llm_parse=…)` computed with the same
  flag config as the run. Deterministic today: temp-0 LLM + warm disk cache (measured
  byte-identical reruns), regex parser pure. Recorder: store `{uid: fingerprint}` plus per-uid
  pass/fail (already have `all_pass_ids`) in each run's JSON.
- **`phase2_diff_eval.py --baseline docs/phase2_baselines/runs/<id>.json`:**
  1. Recompute fingerprints for the baseline row's uids under current working-tree code
     (~20s deterministic; LLM cache warm unless the prompt changed).
  2. Changed set = fingerprint mismatches (plus uids missing from baseline). Print it.
  3. Re-solve only those uids e2e (reuse the chunked path — `solve_phase2.py --uids-file`
     exists), score them (`rehearse_phase2._quality_metrics` on the subset), splice:
     `projected_fpr = (baseline_passes_on_unchanged + measured_passes_on_changed) / n`.
  4. Report per-uid flips (pass→fail / fail→pass) with family-level diff context.
- **Validity guard:** the splice is only sound if solver/orchestrator code is unchanged vs the
  baseline sha. Implement: `git diff --name-only <baseline_sha>` filtered against an allowlist of
  parse-only modules (`parse_constraints.py`, `chinatravel/agent/phase2/normalize.py`,
  `chinatravel/agent/phase2/schema.py`); anything else changed → refuse with "full run required"
  (override flag `--unsafe-allow-solver-drift` for exploratory use only).
- Budget: default to the baseline row's budget so spliced numbers are homogeneous.

**Tests:** fingerprint stability (same input → same hash; family value change → different hash);
splice math on synthetic baselines; the allowlist guard.

**Accept (measured, not just tested):** pick one already-landed parser commit pair (e.g.
`9f73b735`^ → `9f73b735`), build a baseline row at the parent (via Step 1, small
`--limit 20 --budget-sec 60` is fine), then run diff-eval at the child: projected FPR must equal
a full fresh run at the child **exactly** (determinism makes byte-equality the right bar, not
"within noise"). Record wall-clock of both in the step's commit message.

## Step 3 — Early-exit solve mode for evaluation (`fastfpr`)

**Goal:** an eval-only mode where the solve loop returns as soon as it has an accepted plan,
instead of spending the rest of the slice polishing preference score. Cuts per-query cost from
~budget to time-to-first-accept for the ~80% of queries that pass; failing queries still burn the
full slice.

**Files:** `chinatravel/agent/tpc_agent/tpc_agent.py` (`_solve`), `scripts/rehearse_phase2.py` +
`scripts/phase2_record_baseline.py` (plumb a `--fast-fpr` switch through to the chunk
subprocesses via env), tests.

**Design:**

- Env switch `TPC_SOLVE_STOP_AT_ACCEPT` (default unset/off), read in `_solve`: after any
  `consider()` returns accepted, break out of the variant/repair/restart loops and skip
  `_pack_plan` (packing only lifts DAV/DDR preference components, which fastfpr deliberately
  sacrifices). Off = byte-identical behavior (add a test with a spy checker).
- This flag is **eval-tooling only** (ground rule 3): never set by `run_split`, never default-on
  anywhere; `rehearse_phase2.py --fast-fpr` sets it for its subprocesses and stamps
  `fast_fpr: true` into telemetry + ledger row; recorder forces a `fastfpr-` label prefix.
- FPR under fastfpr is a *different metric* (`fpr_fast`): the returned plan is the first
  accepted one, not the best-scored one, and oracle pass/fail can differ marginally.

**Calibrate once (this is the acceptance):** fold 0, n=85, budget 100s, LLM audit on, one run
each with and without `--fast-fpr` (via Step 1 worktrees; ~75 min for the normal one, the
fastfpr one should be several× faster). Accept the mode as an iteration signal if |ΔFPR| ≤ 2 pts
(≈ grid resolution 1.2 pts + margin) and wall-clock improves ≥ 3×. Record both rows and the
calibration verdict in `docs/tpc_phase2_eval.md`. If calibration fails, keep the flag for
exploratory use, document that it is uncalibrated, and rely on Steps 1–2 alone.

**Combined effect with Step 2:** a parser fix touching ~6 uids of fold 0 at 100s fastfpr →
e2e-grounded verdict in ~2–10 minutes on the coding VM.

## Step 4 — Continuous eval worker for VM 2

**Goal:** VM 2 turns every pushed commit into one canonical ground-truth ledger row, unattended.

**Files:** new `scripts/phase2_eval_worker.py`, a short ops section in
`docs/tpc_phase2_eval.md`, optional `make phase2-ledger-sync`.

**Design (keep it a dumb loop — no daemon framework):**

- Loop forever: `git fetch origin`; `sha = rev-parse origin/stefan/phase2` (branch via
  `--branch`); if `history.jsonl` (on the ledger branch, see below) already has a row with
  `git_sha == sha` and the canonical label prefix → sleep 600 and continue. Evaluate **only the
  newest sha** (intermediate commits pushed during a run are skipped — latest-wins).
- Per new sha, via Step 1's `phase2_eval_at.py`:
  1. Canonical row: 300s, fold 0, `P2_FOLDS=10` (n=85), repeats=1, `P2_PARALLEL=3`,
     label `ci-300s`. (~2.5 h. repeats=1 is right for CI: every repeat pair so far had std 0.0.)
  2. If the sha touched parsing modules (same allowlist as Step 2) and there is spare time
     before the next push: a second row with `TPC_P2_LLM_PARSE=0`, label `ci-300s-det` — keeps
     the deterministic-vs-LLM A/B continuously fresh for Step 6.
- **Ledger publication without racing the coding VM:** the worker maintains a second worktree
  checked out to a dedicated branch `phase2-eval-ledger` (create from current `stefan/phase2`);
  it passes that worktree's `docs/phase2_baselines` as `--ledger-dir`, commits
  `phase2-eval: <label> @ <shortsha>` there, and pushes with a `pull --rebase` retry loop. Row
  files are uniquely named (`runs/<run_id>.json`), `history.jsonl` is append-only — rebases are
  clean as long as only the worker writes this branch. The coding VM consumes via
  `make phase2-ledger-sync` = `git fetch origin phase2-eval-ledger && git merge --no-edit
  origin/phase2-eval-ledger` (document that local rows recorded on the coding VM merge fine
  because run ids are timestamps).
- Ops: run under `tmux`/`nohup` (`nohup .venv/bin/python scripts/phase2_eval_worker.py
  >> ~/phase2_eval_worker.log 2>&1 &`); document a systemd unit as an optional hardening, don't
  require it. Worker refuses to start if another instance's pidfile is alive. DeepInfra key must
  be in VM 2's `.env` (it is committed to this private repo — verify with `try_deepinfra.py`).

**Tests:** pure-function tests for "is this sha already evaluated" and label construction; a
`--once --dry-run` mode that prints the plan without running (used in tests).

**Accept:** on VM 2, worker started with `--once` produces a ledger-branch row for the current
head whose `git_sha` matches; a second `--once` invocation is a no-op. Then leave it running.

## Step 5 — Two-sided behavioral proxy (make the 20-second signal trustworthy)

**Goal:** extend `parser_vs_oracle.py`'s behavioral check so missing constraints hurt the score,
fixing the one-sidedness that let the audit look +9 pts better while e2e got worse (F4).

**Files:** `scripts/parser_vs_oracle.py`, `tests/phase2/test_parser_vs_oracle.py` (or wherever
its tests live — check first), docs.

**Design:**

- Keep the existing accept-side check (oracle-best plan). Add a **reject-side probe set** per
  uid, built from plans that exist already — no perturbation engine in v1: the `results/best`
  plans of up to K=4 *other* val uids with the same `target_city` and day count. For each probe,
  evaluate the *oracle* constraints first; keep only probes the oracle **rejects** (they
  naturally violate this uid's required-attraction/hotel/cuisine families). Metric:
  `reject_agreement` = fraction of kept probes the parsed constraints also reject.
- Report `accept_agreement` (old number, renamed), `reject_agreement`, and
  `behavioral_balanced` = mean of the two. Wire `behavioral_balanced` into the recorder as a new
  `parser_full_*` column (keep the old column for row continuity). Per-family attribution of
  reject-misses (which family's absence let the bad plan through) goes into `family_stats`.
- Probe selection must be deterministic (sort uids, take first K) so the metric is comparable
  across runs. Runtime budget: ≤ 3 min full val (it is ~5 constraint evaluations per uid instead
  of 1; the evaluators are pure Python on dicts, measured ~20s for 1×).

**Validate against ground truth we already have (this is the acceptance):** compute the new
metric for (a) the post-step-5 deterministic parser and (b) the LLM-audit parser. We know from
e2e rows that (b) is *worse* end-to-end at 60s. Accept the metric if `behavioral_balanced` ranks
them consistently with e2e (b ≤ a, or within 1 pt) — i.e., the recall regression now costs the
audit visibly. If the new metric *still* strongly favors the audit, that is a genuine finding
(the audit's e2e loss is solver-interaction, not constraint quality) — document it in
`docs/tpc_phase2_eval.md` and demote behavioral metrics to secondary status explicitly.

## Step 6 — Parsing architecture A/B: LLM-first extraction mode

**Goal:** answer the standing architecture question with e2e evidence: deterministic-first +
LLM audit (today) vs **LLM-first structured extraction + deterministic validation/fallback**.

**Prereqs:** Steps 1–3 landed (fast e2e verdicts); Step 5's verdict on the proxy; the
deterministic-only 300s anchor row (Step 0.2) and at least one `ci-300s` row from Step 4.

**Files:** `chinatravel/agent/phase2/normalize.py` (new prompt builder + merge),
`chinatravel/agent/phase2/orchestrator.py`/`schema.py` (flag), `agent_env/scripts/solve_phase2.py`
(env plumbing), `tests/phase2/test_normalize_extract.py` (fixture-backend driven), docs.

**Design:**

- New flag `TPC_P2_LLM_PARSE_MODE ∈ {audit, extract}` (default `audit` = current behavior;
  master switch stays `TPC_P2_LLM_PARSE`). Library default remains LLM-off entirely.
- **Extract mode, one LLM call per query:**
  - Prompt: the NL query + structured context (`people_number`, cities, days) + a compact spec
    of every family in `_LLM_PARSE_ALLOWED_KEYS` (one line each: name, JSON type, value
    vocabulary where closed, one example) + 2–3 few-shot examples, at least one disjunctive
    (`or_arms` as arrays of family-dicts, NOT free text). Output: strict JSON
    `{"families": {...}, "or_arms": [...]}`. **Deliberately do NOT include the deterministic
    parse in the prompt** — independence avoids anchoring on regex mistakes and, operationally,
    decouples the LLM cache from regex changes (audit-mode cold-starts the 850-uid cache on
    every regex fix; extract-mode never does).
  - **Deterministic validation layer** (all in normalize.py, no LLM): key/type whitelist via the
    existing `_LLM_PARSE_*` sets; enum values checked against the data-derived vocabularies
    (cuisine types, hotel feature strings, room types — build them once from the committed data
    the same way the diagnosis scripts do); entity names (attractions/hotels/restaurants)
    resolved against WorldEnv candidates with the same fuzzy approach as
    `TPCAgent._resolve_required_names` (tpc_agent.py:327) — an unresolvable name invalidates
    that field, not the whole response.
  - **Merge policy (start conservative, recall-preserving):** per family — validated LLM value
    wins; invalid/absent LLM value → deterministic value if present; families only the
    deterministic parse found are **kept** (the LLM must not silently delete regex recall; this
    is the lesson of plan-1 gap B6). `or_arms`: use LLM arms only when the deterministic
    splitter found <2 branches (same precedence as today). A `--merge drop-unconfirmed` variant
    can be *measured* later via the proxy; do not ship it by default.
  - **Fallback:** unchanged contract — any exception/timeout/malformed JSON keeps the
    deterministic IR (`parse_to_ir` already catches; extend telemetry with `llm_parse_mode` and
    per-field source counts so rows show how much the LLM actually contributed).
- **Measurement ladder (cheapest first; stop early on a clear kill):**
  1. Fixture-backend unit tests + `scripts/phase2_llm_parse_probe.py` on ~40 current behavioral-
     disagreement uids (~40 paid calls): does extraction fix them without new regressions?
  2. Full-val `parser_vs_oracle --llm-parse` with mode=extract (~100 min paid, cold cache):
     compare precision/recall/`behavioral_balanced` (Step 5) against deterministic and audit.
  3. e2e: Step-2 differential is degenerate here (every fingerprint changes), so one fastfpr
     100s fold-0 row (Step 3, ~20–40 min) for each of {det-only, audit, extract}, then
  4. the winner gets a canonical 300s row via VM 2 (Step 4) against the det anchor.
- **Promotion criterion (write the verdict in the docs either way):** extract becomes the runner
  default only if canonical-300s e2e FPR ≥ both the det anchor and the audit row, with
  `llm_parse_failed ≈ 0`, 0 parse failures, 0 budget overruns. Kill criterion: if extract loses
  to det at both 100s-fastfpr and 300s, keep the flag (off), record the negative result, and the
  remaining parsing roadmap goes back to targeted deterministic fixes + Step 7.

## Step 7 — Carry-over from plan 1 (do only what Step 6's outcome justifies)

- **If audit mode remains the shipped default:** implement plan-1 Step 6 (recall guard on
  `remove` patches — require a quoted contradicting NL span, or whitelist high-precision
  extractor families against removal). Measure with the probe script, then one full-val run.
- **If extract mode wins:** plan-1 Step 6 is obsolete (no remove patches in extract mode);
  instead spend the time on the extract-mode merge-policy measurement (`drop-unconfirmed`
  variant) using Step 5's balanced proxy.
- **Either way:** plan-1 Step 7 (SGLang endpoint parity preset + smoke script) is still open,
  config-only, and should be done last before any submission-facing work.

## Rough cost map

| Activity | Before this plan | After Steps 1–4 |
| --- | --- | --- |
| Parser fix → e2e verdict | 67–90 min (100s fast loop) + code freeze | ~2–10 min (diff-eval on changed uids, fastfpr), no freeze |
| Parsing-architecture A/B arm | ~7.5 h @300s, frozen tree | ~20–40 min fastfpr fold row on VM 1; 300s ground truth async on VM 2 |
| Canonical 300s ground truth | manual, blocks the tree ~8 h | automatic per push on VM 2, ~2.5 h, truthful sha |
| Solver-free parser signal | 20 s but one-sided (mispredicts e2e) | ≤3 min, two-sided, validated against known e2e pairs |

## Definition of done

- Steps 1–3 landed with their measured acceptance checks recorded (worktree row with truthful
  sha; diff-eval byte-equal to a full run on a real commit pair; fastfpr calibration row pair).
- Step 4's worker running on VM 2 and at least two `ci-300s` rows on `phase2-eval-ledger`.
- Step 5's metric wired into the recorder and validated (or explicitly demoted with the finding
  written up).
- Step 6's A/B concluded with a written promotion/kill verdict and ledger rows for all three
  arms; runner default updated only if the promotion criterion was met.
- Step 7 resolved per Step 6's branch; docs (`tpc_phase2_design.md`, `tpc_phase2_eval.md`, this
  file, plan 1's status notes) reflect measured state; all work committed and pushed on
  `stefan/phase2` with green tests.
