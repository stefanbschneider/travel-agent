# R22 refresh — standing phrasing tripwire + unsatisfiable-names probe, post-P24

**Date** 2026-08-08 · **Branch** `main` · **git_sha** `fecdf7ca` (tip after R29/R30 merged)
**Contract** Static, read-only, no solve, no LLM call, no held-out artifact. Two probes:
`scripts/phase2_generalization_probe.py` (the P18/R22 gate itself) and
`scripts/phase2_unsatisfiable_names_probe.py` (the two conditions R22 flags as "still missing" from
the floor file: `spurious` per set and unsatisfiable-required-name count per set).

## Why this run

P24 ("stop inventing satisfiable but unrequested constraints") landed at `5ffae2f4`
(2026-08-07), after R22's last recorded run at `f413eb2a`. The doc's own rule is "run with every
parser change," and this is the first R22 run since. It also directly targets R22's own named gap:
the standing gate does not yet check `spurious` or unsatisfiable-name counts, and P24 is exactly the
kind of change that moves both.

## Commands run

```bash
make phase2-generalization-gate

HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py \
  --out-dir results/phase2_baselines/screens/20260808_r22_refresh_post_p24

HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py \
  --out-dir results/phase2_baselines/screens/20260808_r22_refresh_post_p24
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --entity-resolution \
  --out-dir results/phase2_baselines/screens/20260808_r22_refresh_post_p24
```

## Result 1 — the gate itself: PASS, no floor rise

`make phase2-generalization-gate` → `PHRASING GENERALIZATION GATE: PASS (no set rose above its
recorded floor)`. The floor file (`results/phase2_baselines/phrasing_generalization_floor.json`)
was already ratcheted to the post-P24 values by P24's own second commit (`0f7bfcbb`), with the
`_meta` field documenting why the floor rose there (garbage captures that used to count as
"covered" correctly lose credit once P24 removes the garbage). This run reproduces every number in
that floor file exactly — `familiar_100` `0/1109`, `local_released_150` `5/522`, `hf_easy` `99/1579`,
`hf_medium` `131/1264`, `hf_human` `109/687`, `hf_preference_base50` `14/260` — confirming `main` is
currently at the floor, not drifted past it. No action needed; `pytest tests/phase2` is green on
this gate as-is.

## Result 2 — unsatisfiable-required-name count, the largest finding here

This is R22's still-missing "no set's unsatisfiable-required-name count may rise" condition, run for
the first time against a tree that includes P24. It is not a regression check yet (P24 is the first
measurement since the original diagnosis), but the comparison against the roadmap's own recorded
baseline is stark enough to report as a finding in its own right.

| set | n | original baseline (roadmap §6, pre-P24, `entity_resolution` off) | this run, `entity_resolution=False` | this run, `entity_resolution=True` (real harness default, R29) |
| --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | `7 (7 %)` | `7 (7 %)` | `0 (0 %)` |
| local_released_150 | 150 | `24 (16 %)` | `20 (13 %)` | `17 (11 %)` |
| hf_easy | 300 | `127 (42 %)` | `33 (11 %)` | `33 (11 %)` |
| hf_medium | 150 | `53 (35 %)` | `4 (3 %)` | `4 (3 %)` |
| hf_human | 154 | `36 (23 %)` | `13 (8 %)` | `13 (8 %)` |
| hf_preference_base50 | 50 | `25 (50 %)` | `6 (12 %)` | `6 (12 %)` |

**The HF columns are identical with `entity_resolution` on or off** (`33/4/13/6` either way) — this
rules out entity resolution as the cause of the drop, matching R29's own finding that entity
resolution is flat on the CJK-oracle-literal HF register. `local_released_150` is the one set where
entity resolution adds a further reduction on top of the baseline drop (`20 → 17`), consistent with
R29's isolated e2e result on that same set.

**It does not by itself isolate P24 from P20 and P22, which also landed in this window.** The
original `23–50 %` baseline in the roadmap's §6 predates P20/P22/P24 together; this run measures the
tree with all three landed, not P24 alone. One data point argues against a clean "P24 alone" story:
P24's own screens ([`20260807_p24_attractions_hotels_precision`](../20260807_p24_attractions_hotels_precision/README.md))
claim `local_released_150` is **byte-identical** under P24 in isolation, yet this run measures
`local_released_150` at `20/150` (no-ER) against the pre-window baseline's `24/150` — so *something*
in this window moved that register, and by P24's own account it was not P24. Precise attribution
between P20/P22/P24 needs a pinned-SHA re-run of this probe at each landing point, not done here —
read the headline number as "attributable to the post-P20/P22/P24 parse path, not to entity
resolution," not as "P24 alone."

**This means the CJK-oracle-literal-register free-prose sets' unsatisfiable-required-name share fell
from `23–50 %` (the number `CLAUDE.md` and the roadmap's §6 currently cite as "the largest single
mechanically-certain finding") to `3–12 %` on the current tree, as an already-landed, already-default
side effect of the post-P20/P22/P24 parse path — not because anyone targeted this metric.** P24's
guards (the `stay at/in X` room-type filter, the `" and "`-split trailing-clause guard) strip almost exactly
the same over-captured "whole sentence as a name" text that made those names unresolvable against any
catalog. The two defects diagnosed as separate (§6's infeasibility-by-invention vs P24's
satisfiable-but-unrequested invention) turn out to share most of their root cause on free prose.

**This does not mean P22 (`TPC_P2_DROP_UNSATISFIABLE_NAMES`) is now unnecessary** — `3–13 %` of
queries are still pinned at `FPR = 0` by this mechanism on every set including the control, and R30's
e2e screen (run on this same post-P24 tree) already measured that flag's effect on exactly this
residual: 0/103 flips, 2 regressions on `local_released_150`, stays library-default-off. What changes
here is the *size of the problem P22 is solving* — R30's target-query denominator (`103`) already
reflects the post-P24 numbers (its own text notes the target set "moved from the stale `24/150` on
`local_released_150` to `20/150`"), so R30's negative result is not stale; this run is additional
confirmation of *why* the denominator moved, not a reason to re-open R30.

**Follow-up for the docs workstream:** `CLAUDE.md`'s "Precision, found 2026-08-07 and possibly
larger" paragraph and `docs/tpc_phase2_roadmap.md#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves`
both still cite the pre-P24 `23–50 %` figure as current. Both should be corrected to cite this
screen's post-P24 numbers (`3–12 %` on HF sets, `11 %` on `local_released_150`) so the next reader
does not re-derive P22's now-smaller expected impact from a stale premise. Not done in this commit —
this is an eval-workstream row; the doc-prose correction belongs with the analysis/docs workstream
per `CLAUDE.md`'s parallel-workstream table, except where precedent already allows an eval PR to
correct doc-framing directly (R29 did this for the `entity_resolution` default claim). Given the size
of the correction, a short pointer is added to the `docs/tpc_phase2_eval.md` R22 entry in this same
commit; the `CLAUDE.md` prose itself is left for a follow-up so as not to blur workstream ownership on
a change this large.

## Files

- `probe.json`, `summary.md`, `fix_headroom.json`, `residual_gaps_after_fix.json` — generalization
  probe output (byte-identical to the floor file's recorded values).
- `unsatisfiable_names_report{,_er}.json`, `unsatisfiable_names_summary{,_er}.md` — unsatisfiable-names
  probe output for the `entity_resolution=False` and `entity_resolution=True` arms (renamed from the
  script's default `report.json`/`summary.md` to avoid colliding with the generalization probe's
  same-named output in this shared directory — both scripts default to unsuffixed filenames when no
  probe-specific flag is set).
