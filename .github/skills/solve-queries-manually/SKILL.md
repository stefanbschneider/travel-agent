---
name: solve-queries-manually
description: "Use when selecting the next N suboptimal queries and solving each query to exact optimal score 100.0 with manual/API-driven itinerary edits, strict constraint validation, default sequential solving, optional user-requested subagent parallelization, optional repeat across N-query windows, and checkpoint updates to results/best, results/optimal, and the suboptimal split. Triggers: suboptimal N-query runs, manual optimization loop, eval_tpc per-UID repair, tail query fixing, optimize next N queries."
---

# Solve Queries Manually

## Outcome

Run a repeatable workflow that:
- Selects the next N unresolved queries from the suboptimal split and runs them sequentially (default N: 10)
- Solves each selected query individually toward overall score 100
- Uses API-driven edits and manual itinerary changes as needed
- Validates each UID after changes with official evaluation
- Writes solved outputs to `results/best` and `results/optimal`
- Prunes solved UIDs from `chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt`
- Tracks repeatedly stuck hard-tail queries and temporarily de-prioritizes them to preserve throughput
- Guarantees fairness by periodically forcing hard-tail revisits until all queries are solved
- Reports solved count and aggregate score snapshot
- Always runs a final tpc eval on `best` results and reports overall score + number of optimally solved queries
- Computes the final optimally solved count from `results/optimal` entries that are verified to have score 100

## Scope and Defaults

- Default split source: `chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt` (first N policy)
- Default scoring split: `tpc_phase1`
- Default run length (`N`): `10`
- Default language: `en`
- Default behavior: run exactly N queries in order, once
- Optional repeat mode: continue with the next N after completion when explicitly requested
- Default execution mode: sequential query-by-query solving
- Parallelization: disabled by default; only enable when the user explicitly requests `parallelize=true`
- Default stuck handling: enabled with temporary skip + mandatory revisit
- Default tracker file: `cache/solve_logs/stuck_tracker_tpc_phase1.json`

## Inputs

- `n` (int, optional, default `10`) - number of consecutive queries to process in this run
- `batch_size` (int, optional, alias of `n`)
- `repeat` (bool/int, optional, default `false`; when true, continue with subsequent N-sized windows)
- `split_name` (optional, default `tpc_phase1`)
- `index_source` (optional, default suboptimal split file)
- `parallelize` (bool, optional, default `false`; only used when user explicitly requests subagent parallelization across independent UIDs)
- `stuck_threshold` (int, optional, default `2`; consecutive no-meaningful-progress batch attempts before cooldown)
- `cooldown_batches` (int, optional, default `2`; number of subsequent batches a stuck UID is temporarily skipped)
- `forced_revisit_per_batch` (int, optional, default `2`; number of cooled/stuck UIDs forcibly re-inserted each batch)
- `min_progress_delta` (float, optional, default `0.1`; minimum overall gain to count as meaningful progress)

## Workflow

1. Select Batch
- Read the suboptimal split file.
- Load stuck tracker state (or initialize if missing).
- Select the next N UIDs in order (first-N policy) unless user requested another policy.
- If stuck handling is active, selection priority is:
  1) force-insert up to `forced_revisit_per_batch` eligible cooled/stuck UIDs,
  2) fill remaining slots from first-N unresolved UIDs that are not in cooldown.
- If all top candidates are in cooldown, select cooled/stuck UIDs anyway (never stall the loop).
- If fewer than N remain, process all remaining UIDs and stop.
- If file is empty, report and stop.

2. Baseline Snapshot
- For each UID in batch, run per-UID evaluation using existing tpc eval: `eval_tpc.py --splits tpc_phase1 --index <uid> --method best --lang en`.
- Extract overall + DAV/ATT/DDR/FPR and identify deficit source(s).
- Keep a baseline table for before/after comparison.

3. Solve Each UID Individually (Manual + API-Driven)
- Treat each UID as an isolated optimization loop.
- Inspect hard constraints and commonsense constraints from query data.
- Apply targeted edits to `results/best/<uid>.json`:
  - Increase DAV: add suitable free attractions, improve diversity while preserving constraints.
  - Increase ATT: reduce average transport time via rewires and better sequencing.
  - Increase DDR: ensure meal density near 3/day using valid meal insertions.
  - Preserve FPR=100: never keep edits that break schema/commonsense/hard constraints.
- Use available environment APIs and transportation/nearby APIs for candidate generation.
- Prefer manual result construction and direct itinerary edits.
- Do not rely on the TPC agent or CP solver for normal solving; use them only briefly when truly necessary.
- After each candidate change, re-evaluate and keep only score-improving valid plans.

4. Optional Parallelization (User-Requested Only)
- Default behavior is sequential per-UID solving in batch order.
- Only parallelize across subagents when the user explicitly requests it (for example `parallelize=true`), and keep per-UID state isolated.
- Apply strict acceptance criteria before writing final per-UID outputs.
- If parallel path risks conflicts or noisy regressions, switch back to sequential solving.

5. Validate and Finalize Per UID
- Re-run official per-UID eval for final candidate.
- Solved threshold is exact `overall == 100.0`.
- If exact 100.0 appears not reasonably achievable after substantial valid effort, stop that UID and move on.
- If solved, set `_eval_score` to 100.0 in `results/best/<uid>.json`.
- Copy solved UID to `results/optimal/<uid>.json`.
- If not solved, keep best known safe candidate and record reason (for example hard cap bottleneck).

6. Update Stuck Tracker (Required)
- For each processed UID, compare baseline vs final overall.
- If solved (exact 100): clear UID from tracker.
- If unsolved and improvement < `min_progress_delta`:
  - increment consecutive_stuck_count,
  - when count >= `stuck_threshold`, set cooldown for next `cooldown_batches` batches,
  - tag as `hard_tail` with latest deficit reason (for example ATT under tight transport cap).
- If unsolved and meaningful improvement achieved:
  - reset or decrement consecutive_stuck_count,
  - remove cooldown.
- Persist tracker to `cache/solve_logs/stuck_tracker_tpc_phase1.json`.

7. Batch Checkpoint Update
- Remove solved UIDs from `chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt` using exact line matching.
- Do not remove unresolved UIDs.
- Avoid touching unrelated files.

8. Report
- Return a concise summary including:
  - UIDs processed in this N-query run
  - Solved-to-100 count and list
  - Remaining unresolved list with latest scores
  - Hard-tail tracker delta (newly cooled UIDs, forced revisits, recovered-from-stuck UIDs)
  - Overall score snapshot for the batch on `best`
  - Running count of optimally solved queries based on verified score-100 files in `results/optimal`
  - Whether workflow continues automatically to the next N-query window

9. End-of-Run Global Evaluation (Required)
- At the end of the workflow (including auto-repeat), always run tpc eval on `best` results using the configured split (default `tpc_phase1`).
- Record and report:
  - Final overall score on `best`
  - Number of optimally solved queries from `results/optimal` where each file is verified as exact `overall == 100.0`
- Validation rule for optimal count:
  - Do not use hard-constraint-pass counts.
  - Count only files in `results/optimal` whose evaluated/recorded score is exactly 100.0.
  - If any file in `results/optimal` is not 100.0, mark it invalid for the count and report it explicitly.
- Include these values in the final run summary, even if no new queries were solved in the last batch.

10. Repeat Loop
- If `repeat=true`, after reporting one run, automatically select the next first-N window from the updated suboptimal split and continue.
- If `repeat=false` (default), stop after one N-query run.
- In repeat mode, continue until one of the following:
  - User explicitly asks to stop
  - Suboptimal split has no remaining UIDs
  - Multiple consecutive windows show no meaningful progress
- Never permanently skip a UID: any temporarily cooled UID must be revisited by forced insertion until solved.

## Operational Guardrails

- Never commit or push unless user explicitly requests it.
- Do not revert unrelated workspace changes.
- Keep edits targeted to relevant `results/best`, `results/optimal`, and split files.

## Decision Rules

- If any edit causes schema/commonsense/hard failure, rollback that edit.
- If score plateaus and no valid improving candidates remain, stop on that UID and move on.
- Prefer minimal, localized changes over broad rewrites.
- Never regress a UID that was already at 100.
- Run UID solving sequentially by default; enable parallel subagent solving only on explicit user request.
- Temporary skip is allowed only via tracker cooldown; permanent skip is forbidden.
- If unrelated workspace changes are detected, do not revert them; continue safely with targeted files only.

## Completion Criteria

An N-query run is complete when all selected UIDs have:
- A final validated `best` evaluation result
- Either solved checkpointed to `optimal` + pruned from suboptimal split, or unresolved with explicit reason
- Stuck tracker updated and persisted for all unresolved UIDs
- A final run summary with solved count and score deltas

## Example Prompts

- "Run solve-queries-manually for the next 10 queries from suboptimal."
- "Run solve-queries-manually sequentially for the next N queries (default N=10)."
- "Run solve-queries-manually with batch_size=20 and parallelize=true."
- "Repeat solve-queries-manually with n=10 until no more 100s are found or 3 windows are done."
- "Run solve-queries-manually only for ATT-deficit UIDs in the next batch."
- "Run solve-queries-manually continuously in sequential mode; stop only when I say stop."
- "Run solve-queries-manually with stuck_threshold=2, cooldown_batches=3, and forced_revisit_per_batch=2."
