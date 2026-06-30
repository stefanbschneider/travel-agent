---
name: solve-queries-manually
description: "Use when repeatedly selecting the first N suboptimal queries and solving each query to exact optimal score 100.0 with manual/API-driven itinerary edits, strict constraint validation, default smart parallelization, automatic repeat across batches, and checkpoint updates to results/best, results/optimal, and the suboptimal split. Triggers: suboptimal batch solving, manual optimization loop, eval_tpc per-UID repair, tail query fixing, optimize next N queries."
---

# Solve Queries Manually

## Outcome

Run a repeatable workflow that:
- Selects a configurable batch from the suboptimal split (default batch size: 10)
- Solves each selected query individually toward overall score 100
- Uses API-driven edits and manual itinerary changes as needed
- Validates each UID after changes with official evaluation
- Writes solved outputs to `results/best` and `results/optimal`
- Prunes solved UIDs from `chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt`
- Reports solved count and aggregate score snapshot

## Scope and Defaults

- Default split source: `chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt` (first N policy)
- Default scoring split: `tpc_phase1`
- Default batch size: `10`
- Default language: `en`
- Default behavior: keep iterating automatically across batches
- No hard cap on repeat runs; continue until explicitly stopped or no meaningful progress remains
- Default parallelization: enabled when it makes sense; can opt out via `parallelize=false`

## Inputs

- `batch_size` (int, optional, default `10`)
- `repeat` (bool/int, optional, default automatic repeat)
- `split_name` (optional, default `tpc_phase1`)
- `index_source` (optional, default suboptimal split file)
- `parallelize` (bool, optional, default `true` when multiple UIDs can be solved independently)

## Workflow

1. Select Batch
- Read the suboptimal split file.
- Select the first `batch_size` unresolved UIDs unless user requested another policy.
- If file is empty or too short, report and stop.

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

4. Parallelization (Default Smart Mode)
- Parallelize by default when beneficial (for example with subagents), but keep per-UID state isolated.
- Apply strict acceptance criteria before writing final per-UID outputs.
- If parallel path risks conflicts or noisy regressions, switch back to sequential solving.

5. Validate and Finalize Per UID
- Re-run official per-UID eval for final candidate.
- Solved threshold is exact `overall == 100.0`.
- If exact 100.0 appears not reasonably achievable after substantial valid effort, stop that UID and move on.
- If solved, set `_eval_score` to 100.0 in `results/best/<uid>.json`.
- Copy solved UID to `results/optimal/<uid>.json`.
- If not solved, keep best known safe candidate and record reason (for example hard cap bottleneck).

6. Batch Checkpoint Update
- Remove solved UIDs from `chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt` using exact line matching.
- Do not remove unresolved UIDs.
- Avoid touching unrelated files.

7. Report
- Return a concise summary including:
  - Batch UIDs processed
  - Solved-to-100 count and list
  - Remaining unresolved list with latest scores
  - Overall score snapshot for the batch on `best`
  - Whether workflow continues automatically to next batch

8. Repeat Loop
- After reporting one batch, automatically select the next first-N batch from the updated suboptimal split and continue.
- Continue until one of the following:
  - User explicitly asks to stop
  - Suboptimal split has no remaining UIDs
  - Multiple consecutive batches show no meaningful progress

## Operational Guardrails

- Never commit or push unless user explicitly requests it.
- Do not revert unrelated workspace changes.
- Keep edits targeted to relevant `results/best`, `results/optimal`, and split files.

## Decision Rules

- If any edit causes schema/commonsense/hard failure, rollback that edit.
- If score plateaus and no valid improving candidates remain, stop on that UID and move on.
- Prefer minimal, localized changes over broad rewrites.
- Never regress a UID that was already at 100.
- If unrelated workspace changes are detected, do not revert them; continue safely with targeted files only.

## Completion Criteria

A batch run is complete when all selected UIDs have:
- A final validated `best` evaluation result
- Either solved checkpointed to `optimal` + pruned from suboptimal split, or unresolved with explicit reason
- A final batch summary with solved count and score deltas

## Example Prompts

- "Run solve-queries-manually for the next batch from suboptimal with defaults."
- "Run solve-queries-manually with batch_size=20 and parallelize=true."
- "Repeat solve-queries-manually until no more 100s are found or 3 batches are done."
- "Run solve-queries-manually only for ATT-deficit UIDs in the next batch."
- "Run solve-queries-manually continuously with default smart parallelization; stop only when I say stop."
