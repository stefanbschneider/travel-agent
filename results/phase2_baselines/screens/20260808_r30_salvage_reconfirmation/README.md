# R30 salvage-before-drop e2e re-confirmation

**Date** 2026-08-08 · **Branch** `eval/r31-oracle-literal-translation` (same evaluation-workstream
branch as R31; both land in one PR) · **`git_sha`** `7405e723` (`main` tip plus R31's commit — includes
[the P22 salvage-before-drop static fix](../20260808_p22_salvage_before_drop/README.md)) · **host**
4-core Linux (3-way sharded per split) · **Contract**: exact re-run of
[R30](../20260807_r30_unsatisfiable_names_e2e/README.md)'s paired e2e A/B — same 103 target uids
(`target_uids.json`/`uids/*.txt` copied verbatim from that screen), same six sets, same
`TPC_P2_DROP_UNSATISFIABLE_NAMES=0|1` flag pair, same `budget-sec=90`, `--lang en`, no `--resume`,
distinct method directories per arm/set. Not a `full_runs/`/`runs/` row.
Evaluation workstream instrument, the unnumbered follow-up
[R30's own writeup names](../../../../docs/tpc_phase2_eval.md#r30--does-dropping-unsatisfiable-names-flip-queries-closed-2026-08-07-negative-result)
and [P22's salvage fix](../../../../docs/tpc_phase2_roadmap.md#p22--drop-provably-unsatisfiable-required-name-constraints)
asked for.

## Headline: the genuine loss is closed, the unrelated loss is unchanged, no new loss anywhere

**`20250324075652034944` (the salvage-fixable Hangzhou loss) now passes in both arms.** This is
exactly the fix's target: R30 found the flag dropped a real POI name
(`"Xixi Paradise Commercial Street"`) that had been tail-swallowed together with an unrelated clause,
and the static P22 follow-up added a salvage step at the drop rule's terminal branch to recover it.
Confirmed directly, per-uid, not just by aggregate movement:

```
off pass: {..., '20250324075652034944', ...}   # 22 of 24 target uids
on  pass: {..., '20250324075652034944', ...}   # 21 of 24 target uids
lost (off pass -> on fail):   ['20250322180344489669']   # the *other* R30 loss, unrelated mechanism
gained (off fail -> on pass): []
```

**`20250322180344489669` (the Beijing search-perturbation loss) is unchanged — still lost, exactly as
R30's own causal analysis predicted.** That loss was never caused by the dropped value itself (the
dropped "Sauna" hotel-type garbage had no real catalog match to salvage — confirmed again by the P22
salvage-rate screen); it is a side effect of the deterministic solver's `90 s` search landing on a
different itinerary once the freed repair-queue budget changes what gets explored. The salvage fix
does not touch this mechanism, and R30 said explicitly it would need envelope-level (`full_runs/`)
re-measurement, not a parser fix — nothing here changes that.

**Net: `local_released_150`'s regression is halved (2 lost → 1 lost, 0 gained → 0 gained), one loss
is now fully explained and closed, the other is unchanged, and no new loss appears anywhere.**

| set | metric | off | on (R30, 2026-08-07) | on (this row, 2026-08-08) |
| --- | --- | --- | --- | --- |
| local_released_150 | FPR | 91.67 (22/24) | 83.33 (20/24) | **87.50 (21/24)** |
| local_released_150 | C-LPR | 97.75 | 95.51 | 96.63 |
| familiar_100 (control) | FPR / C-LPR | 42.86 / 91.57 | 42.86 / 91.57 (byte-identical) | 42.86 / 91.57 (byte-identical) |
| hf_easy | C-LPR | 80.37 | 81.31 | 81.31 (unchanged) |
| hf_medium | C-LPR | 72.57 | 74.34 | 74.34 (unchanged) |
| hf_human | C-LPR | 67.07 | 67.07 (flat) | 67.07 (flat) |
| hf_preference_base50 | C-LPR | 80.0 | 80.0 (flat) | 80.0 (flat) |

Full `eval_tpc.py` logs for all 12 arms: [`eval/`](eval/). HF FPR stays flat/predetermined on all four
sets (`0/40`, `0/12`, `7.14%/7.14%` same single uid, `0/0`) — unchanged from R30, matching the CJK-oracle
ceiling this document already established
([the corrected dataset boundary](../../../../docs/tpc_phase2_eval.md#3-hugging-face-chinatravel);
[R31](../20260808_r31_oracle_literal_translation/README.md) is what lifts it, out of scope here since
this row's job is reproducing R30's exact contract, not R31's).

## Solve-time mechanism: unchanged

The speedup P22 actually targets reproduces closely to R30's own numbers (mean `solve_sec`, off →
on): `local_released_150` `60.05 → 26.89` (R30: `61.00 → 26.92`), `hf_easy` `57.74 → 11.74` (R30:
`57.83 → 9.43`), `hf_medium` `58.03 → 10.32` (R30: `59.06 → 9.95`), `hf_human` `63.88 → 17.47` (R30:
`63.65 → 17.74`), `hf_preference_base50` `52.42 → 9.96` (R30: `53.20 → 9.11`), `familiar_100`
`57.14 → 57.09` (R30: `57.28 → 57.28`, flat — no unsatisfiable-name pressure there). The salvage fix
does not erode the mechanism P22 exists for.

## What this does and does not authorize

**Still does not meet R30's own promotion bar** ("at least one target uid flips to fully passing") —
`0/103` fail→pass on this exact target set, same as R30. `TPC_P2_DROP_UNSATISFIABLE_NAMES` stays
library-default-off; nothing here changes that default, consistent with the
[non-negotiable invariant](../../../../CLAUDE.md#non-negotiable-invariants) that a measurement gates a
change rather than promoting by itself.

**What did change: the risk this flag carried is now measured smaller, not just claimed smaller.**
R30 named this exact follow-up as the condition under which the flag's regression risk would close
("the mechanism P22 targets — solve time — is real and large... this per-query screen contract cannot
measure whether the real envelope scheduler converts that into more passes elsewhere; that needs a
`full_runs/`-shaped measurement"). This row confirms the *parser-side* half of that condition: the one
loss that was a genuine requirement-dropping bug is fixed, and the remaining loss is an already-diagnosed,
unrelated, envelope-level mechanism. The natural next step — whether the freed solve time actually
converts into more full-run passes elsewhere, which only a `full_runs/`-shaped envelope measurement can
answer — remains unscheduled, not yet assigned an R-number, exactly as R30 left it.

## Reproduce

```bash
# Re-materialize the four HF sets under R30's exact names (full split, no translation):
HF_HUB_OFFLINE=1 .venv/bin/python scripts/materialize_hf_split.py --hf-split easy   --name hf_easy_r30
HF_HUB_OFFLINE=1 .venv/bin/python scripts/materialize_hf_split.py --hf-split medium --name hf_medium_r30
HF_HUB_OFFLINE=1 .venv/bin/python scripts/materialize_hf_split.py --hf-split human  --name hf_human_r30
HF_HUB_OFFLINE=1 .venv/bin/python scripts/materialize_hf_split.py --hf-split preference_base50 --name hf_preference_base50_r30

# Overwrite each set's default_splits/*.txt with R30's committed target-uid-only lists
# (results/phase2_baselines/screens/20260807_r30_unsatisfiable_names_e2e/uids/*.txt), and for the two
# local sets create *_r30targets split names (directory-search fallback onto the existing canonical
# data, canonical split files never touched) pointed at the same uid lists. Then, per set, per arm:

TPC_P2_DROP_UNSATISFIABLE_NAMES=0|1 .venv/bin/python agent_env/scripts/solve_phase2.py \
  --split <split> --uids-file <shard-of-target-uids> --method phase2_e2e_r30recheck_<set>_<off|on> \
  --budget-sec 90 --lang en   # 3-way sharded per set/arm

.venv/bin/python eval_tpc.py --splits <split> --method phase2_e2e_r30recheck_<set>_<off|on> --lang en
```

All four re-materialized HF split data dirs and every temporary `default_splits/*.txt` file
(`*_r30targets`, `hf_*_r30`) were **deleted after scoring** — confirmed absent from `git status`,
matching R30's own cleanup discipline and the project-wide "materialized split must never ship" rule.
