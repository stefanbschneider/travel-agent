# P24 screen: `intercity_mode` was a measurement artifact, not invention

Static, definitional screen for the first of two P24 commits
([docs/tpc_phase2_roadmap.md#p24--stop-inventing-satisfiable-but-unrequested-constraints](../../../../docs/tpc_phase2_roadmap.md#p24--stop-inventing-satisfiable-but-unrequested-constraints)).
Coding-VM, no eval-machine slot used (this is diagnosis + a static probe, not an e2e row).

## What P24 originally claimed

`docs/tpc_phase2_roadmap.md` measured `117` `intercity_mode` clauses emitted on free prose
against `0` oracle instances, and called it "pure invention": a direction-free NL fallback
(`(?:take|by|use)\s+(?:a\s+|the\s+)?(train|airplane|plane|flight)`) pins both legs on any passing
mention.

## What actually happened

`solver_constraint_variants(..., use_oracle=True)` treats `intercity_mode` as a *branch-local*
key (`_BRANCH_LOCAL_KEYS`), so the oracle-side comparison dict is rehydrated from `hard_logic_py`
via `_parse_intercity`, **discarding** whatever `parse_constraints.parse_query()`'s NL-merge
produced. `_parse_intercity` recognized two shapes:

- `allactivities(plan)[0]['type']` / `[-1]['type']` equality
- `intercity_transport_go` / `intercity_transport_back` field equality (the templated register's
  shape — familiar-100, local_released_150)

It did not recognize the shape the HF free-prose generator actually uses for this requirement:

```python
intercity_transport_set = set()
for activity in allactivities(plan):
    if activity_type(activity) in ['train', 'airplane']:
        intercity_transport_set.add(intercity_transport_type(activity))
result = ({'train'} == intercity_transport_set)
```

Measured directly (script below): **100% of a sampled `intercity_mode`-spurious set on
`hf_easy`/`hf_medium`/`hf_human`/`hf_preference_base50` had exactly this oracle clause.**
`genuinely_no_oracle_clause = 0` on every set. The "0 oracle instances" figure in the roadmap was
itself produced by this same gap (`parser_vs_oracle.py`'s oracle side calls the identical
`solver_constraint_variants(..., use_oracle=True)`), so it measured its own blind spot.

## The fix

`_parse_intercity` (`chinatravel/agent/tpc_agent/solver_constraints.py`) now also matches
`{'train'|'airplane'} == intercity_transport_set` (either operand order), mapping the single mode
to both `outbound` and `return` via `setdefault` (so a more specific go/back value already found
in the same call is never clobbered). Every sampled instance was a single-element set; a
two-element set is not expressible as one mode and is left unhandled rather than guessed.

**This is not diagnostic-only.** `tpc_agent.py:360` calls
`solver_constraint_variants(query, raw, use_oracle=self.use_oracle)`, so the same function backs
Phase 1's oracle-guided CP solve. Before this fix, Phase 1 silently dropped `intercity_mode`
constraints on any query using the set-equality shape — a real correctness gap, not only a
measurement one. `chinatravel/agent/tpc_agent/solver_constraints.py` is outside the
[upstream-evaluator-parity list](../../../../CLAUDE.md#non-negotiable-invariants)
(`evaluation/`, `symbol_verification/`, `concept_labels.py`, `environment/tools/`, `eval_tpc.py`
scoring, `load_datasets.py`), so this edit does not touch parity.

## Measurement

`scripts/parser_vs_oracle.py` family stats for `intercity_mode`, before vs. after
(`git_sha 2c730daf` base):

| set | matched (before→after) | missing (before→after) | spurious (before→after) |
| --- | --- | --- | --- |
| hf_easy | 0 → 49 | 0 → 2 | 49 → 0 |
| hf_medium | 0 → 52 | 0 → 33 | 52 → 0 |
| hf_human | 0 → 5 | 0 → 27 | 5 → 0 |
| hf_preference_base50 | 0 → 66 | 0 → 0 | 66 → 0 |
| local_released_150 (unaffected control — go/back shape, not set-equality) | 10 → 10 | 0 → 0 | 7 → 7 |

Total: `spurious 172 → 0`, `matched 0 → 172`. Bar from the roadmap item ("spurious falling on at
least two free-prose sets with matched not falling on any set") is exceeded — spurious falls to
zero on every set and matched rises on every set.

## The honest cost: P18's floor moved, and had to move manually

Fixing the oracle side does not just relabel `spurious → matched`; where our NL parse genuinely
lacks the value (`intercity_mode` never mentioned, or phrased as "we have chosen to fly" / "by
high-speed train (G)" — patterns `parse_intercity_mode` does not yet catch), the same clauses
reclassify from `schema_gap` (uninformative — no family could ever cover them, says nothing about
phrasing) to `parse_gap` (a real, phrasing-attributable coverage miss). `clause_is_covered()`
checks family **presence**, not value correctness, so this reclassification is a pure consequence
of the oracle side no longer under-reporting.

`results/phase2_baselines/phrasing_generalization_floor.json` moved: `easy 97→99`, `medium
78→111`, `human 81→108`; `preference_base50` and both local sets unchanged.
`write_floor`/`--update-floor` cannot express this — its ratchet only ever lowers a set's
recorded count, by design, so it cannot "raise the floor to a more honest number" without also
being able to launder a real regression. The floor file was edited by hand with this note
attached in its `_meta`, per the reasoning above; `pytest tests/` is green against it.

**Follow-up, not this commit:** the newly-visible recall gap (`easy +2`, `medium +33`, `human
+27`) is real and worth its own item — extend `parse_intercity_mode` to recognize "we have
chosen to fly" / "traveling by ... train (G)" phrasing. Filed as residual, not folded in here.

## Reproduce

```
.venv/bin/python -m pytest tests/phase2/test_parser_accuracy.py -k intercity
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py \
    --out-dir results/phase2_baselines/screens/20260807_p24_intercity_oracle_fix
```

`probe.json`/`summary.md` in this directory are that run's output, captured after the
`_parse_intercity` fix (before the second P24 commit's `parse_constraints.py` changes).
