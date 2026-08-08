# P23 — make the free-prose register scoreable (oracle-literal translation pass)

**What this is.** [P23](../../../../docs/tpc_phase2_roadmap.md#p23--make-the-free-prose-register-scoreable):
the four HF free-prose splits (`easy`/`medium`/`human`/`preference_base50`) carry native-Chinese
`hard_logic_py` literals against English query text, so under `--lang en` a clause like
`'博物馆' in attraction_type(x)` is structurally unsatisfiable regardless of solver quality — every
free-prose FPR/C-LPR measurement this project has ever made was read against a `100` denominator when
the real cap was `38.67–46.0`. This item builds the tool that lifts the cap: `scripts/
materialize_hf_split.py --translate-oracle-literals`, backed by the zh→en map and per-literal rewrite
now in `scripts/phase2_oracle_literal_translation.py` (`build_map` / `translate_clause` /
`translate_hard_logic`).

**What this is not.** This screen is a *static build-and-verify* pass — it produces the translation
map, applies it, and reports what changed and what could not be mapped. It does **not** run the
solver or produce an FPR/C-LPR number. That is
[R31](../../../../docs/tpc_phase2_eval.md#r31--the-first-real-free-prose-fpr-gate) — a whole-run-shaped
measurement blocked on this merging, and out of scope for the coding VM (see the two-VM rule in
`docs/tpc_phase2_eval.md`). This screen only unblocks it.

## Scope discipline (a reviewer will ask)

Per P23's hard constraints: this pass touches only `scripts/materialize_hf_split.py`, `scripts/
phase2_oracle_literal_translation.py`, `.gitignore`, and `tests/phase2/`. It does **not** touch
`chinatravel/evaluation/`, `chinatravel/symbol_verification/`, `eval_tpc.py`'s scoring, or
`chinatravel/data/load_datasets.py` — confirmed by `git diff --stat` against `main` before this
commit. It rewrites *query files in a materialized local split*, never the upstream evaluator, so
[upstream evaluator parity](../../../../CLAUDE.md#non-negotiable-invariants) is untouched.

## The map (`build_map`, `scripts/phase2_oracle_literal_translation.py`)

Derived from the row-parallel `chinatravel/environment/database/` ↔ `database_en/` CSVs (identical
row counts, same order, verified per file — the builder raises `ValueError` if that stops holding,
covered by `test_build_map_raises_on_row_count_mismatch`), canonicalized through
`normalize_concept_value`, plus a positional/whole-value split for `/`-compound category values (e.g.
`博物馆/纪念馆` → `Museum/Memorial Hall`). Ambiguity — two different English values surfacing for one
Chinese literal — raises rather than guessing (`test_build_map_raises_on_ambiguous_translation`).

**Reproduced today: `11957` entries**, matching the count already cited in
`docs/tpc_phase2_roadmap.md`'s P23 section exactly (`14` attraction types, `43`ish cuisines, `74`
hotel features, `11810` POI names, plus the `/`-compound part entries — the roadmap's headline
component breakdown predates the compound-split logic, which is why a naive recount without it lands
a little lower; the code path that actually ships, `build_map()`, was already committed and already
reproduces `11957` byte-for-byte). Full map committed here: [`zh_en_map.json`](zh_en_map.json).

## The rewrite (`translate_clause` / `translate_hard_logic`)

Scans each `hard_logic_py` clause for quoted string literals (regex-scoped to actual Python string
literals, never bare identifiers or comments — `test_translate_clause_only_touches_string_literals_not_code`),
and rewrites a literal only when **every** CJK run inside it has a map entry. A partially-mappable
literal — a POI-name fragment (a branch suffix, e.g. `前门店`) or a generic location word (`河边`) — is
left verbatim and its unmapped run(s) are reported, never approximated
(`test_translate_clause_leaves_partially_mapped_literal_untouched_and_reports_it`). This matches
P23's own instruction: "leave them, and have the pass report them, rather than approximating."

## What ran

```
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_oracle_literal_translation.py \
  --out-dir results/phase2_baselines/screens/20260808_p23_oracle_literal_translation \
  --emit-map results/phase2_baselines/screens/20260808_p23_oracle_literal_translation/zh_en_map.json

# then, per split:
HF_HUB_OFFLINE=1 .venv/bin/python scripts/materialize_hf_split.py \
  --hf-split <split> --name hf_<split>_en_oracle --translate-oracle-literals \
  --report-out results/phase2_baselines/screens/20260808_p23_oracle_literal_translation/translation_report_<split>.json
```

[`report.json`](report.json) / [`summary.md`](summary.md) are the pre-existing cap-pricing instrument's
output, reproduced unchanged (see below). `translation_report_<split>.json` are new: what the rewrite
pass actually changed on the full, untruncated split. **The materialized query files themselves
(`chinatravel/data/en/hf_*_en_oracle/`, `chinatravel/evaluation/default_splits/hf_*_en_oracle.txt`)
are evaluation-only, gitignored by the forced `_en_oracle` suffix, and deleted from this box after
this screen was written** — regenerating them is the one-line command above, deterministic (HF row
order, no LLM, no randomness), and is exactly what R31 will do on the eval machine.

## Results

**Cap pricing, reproduced byte-identical to the roadmap's own table** (confirms the existing
instrument is unaffected by this change — it was not modified beyond the new imports it now shares
with the rewrite):

| HF split | n | oracle clauses | unsatisfiable under `en` | of those, mappable | queries blocked | FPR ceiling | C-LPR ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- |
| easy | 300 | 1579 | 180 | 135 | 180 | **40.0** | 88.6 |
| medium | 150 | 1264 | 126 | 125 | 92 | **38.67** | 90.03 |
| human | 154 | 687 | 117 | 105 | 91 | **40.91** | 82.97 |
| preference_base50 | 50 | 260 | 27 | 19 | 27 | **46.0** | 89.62 |

**What the rewrite pass actually did**, full splits (map: `11957` entries throughout):

| HF split | n | queries with ≥1 clause translated | clauses translated | queries with residual unmapped literal |
| --- | --- | --- | --- | --- |
| easy | 300 | 135 | 135 | **45** |
| medium | 150 | 91 | 125 | **1** |
| human | 154 | 86 | 109 | **12** |
| preference_base50 | 50 | 19 | 19 | **8** |

Total across all four: **331** queries got at least one clause translated, **388** clauses translated,
**66** queries still carry a residual unmapped literal. `medium`'s single residual
(`e20241028161036243215`, unmapped runs `前门店` / `北京全聚德`) is exactly the branch-name-fragment
example the roadmap's own P23 section names — reproduced independently by this pass, not copied from
the doc.

**Read the two tables together, not separately.** "Of those, mappable" (the cap-pricing table) and
"clauses translated" (the rewrite table) are close but not identical measurement methods — the pricer
checks "does this clause's CJK content have *any* full mapping" per whole clause, the rewriter counts
per string literal, and a clause can hold more than one literal. `easy` and `preference_base50`
partition cleanly (`queries translated + residual == queries blocked`); `human` does not (`86 + 12 =
98 > 91`) — `7` `human` queries have **both** a clause that translated cleanly and a separate clause
still carrying a residual literal, which is expected (nothing in the design assumes one clause per
query) and does not indicate a bug.

**The residual, categorized** (samples in `translation_report_<split>.json`,
`unmapped_residual_samples`, capped at 50 queries per split): dominated by two shapes exactly as P23
predicted going in — POI-name fragments where a restaurant/hotel branch suffix (`...店`, "...branch")
was captured as part of the name but the base name itself is a separate token the oracle quotes on its
own (`北京全聚德` / `前门店` — two literals for what is one real POI, "Beijing Quanjude, Qianmen
Branch"), and generic-location words with no catalog row (`河边`/`海边`/`江边` — "riverside"/"seaside",
`天安门` in isolation rather than as part of a specific attraction's catalog name). `easy` carries by
far the most residual (`45/300` queries) — its oracle appears to fragment restaurant/hotel names into
`(base name, branch suffix)` pairs more often than the other three splits; `medium` is nearly clean
(`1/150`). No fix is attempted here: P23's own text is explicit that this class "need[s] substring
matching rather than token lookup — leave them, and have the pass report them, rather than
approximating," which this pass does.

## Bar (from P23 / the roadmap)

- [x] Evaluation-only, never ships: forced `_en_oracle` name suffix (`materialize()` raises
  `ValueError` otherwise, `test_translate_oracle_literals_requires_en_oracle_suffix`), and the same
  suffix is gitignored (`test_translate_oracle_literals_output_is_gitignored`).
- [x] Does not touch `chinatravel/evaluation/`, `chinatravel/symbol_verification/`, `eval_tpc.py`
  scoring, or `load_datasets.py` — see "Scope discipline" above.
- [x] The builder raises rather than guesses on drift: `test_build_map_raises_on_ambiguous_translation`,
  `test_build_map_raises_on_row_count_mismatch`.
- [x] Residuals reported, not approximated: `test_translate_clause_leaves_partially_mapped_literal_untouched_and_reports_it`,
  and the real per-split reports above.
- [x] A translated-oracle row is a new, non-comparable register: labeled `hf_<split>_en_oracle`
  throughout; map entry count (`11957`) recorded in every report.
- [x] `pytest tests` green, `14` new tests added
  (`tests/phase2/test_phase2_oracle_literal_translation.py`,
  `tests/phase2/test_materialize_hf_split.py`), no pre-existing test edited.

**One incidental fix, in the same commit.** `materialize_hf_split.py`'s `split_file.write_text(...)`
had no `.parent.mkdir(parents=True, exist_ok=True)` — silently relied on
`chinatravel/evaluation/default_splits/` already existing (true on the real repo tree, false for a
fresh `project_root` in a test). Fixed; a one-line defensive guard, not a scoring change, and covered
by every test in `test_materialize_hf_split.py` that passes a `tmp_path` as `project_root`.

## What this unblocks

[R31](../../../../docs/tpc_phase2_eval.md#r31--the-first-real-free-prose-fpr-gate) on the eval
machine: materialize an `_en_oracle` split, run it through the real harness, and read free-prose FPR
against a denominator that no longer structurally excludes `59–61 %` of queries by construction. It
also unblocks a locally-measurable e2e gate for
[P20](../../../../docs/tpc_phase2_roadmap.md#p20--close-the-two-dominant-family-recall-gaps)'s
`required_attraction_types` fallback and any future e2e arm for
[P22](../../../../docs/tpc_phase2_roadmap.md#p22--drop-provably-unsatisfiable-required-name-constraints)/
[P24](../../../../docs/tpc_phase2_roadmap.md#p24--stop-inventing-satisfiable-but-unrequested-constraints)
on free prose — none of that is run here.

**Not done, and out of scope for this item**: fixing `scripts/phase2_family_recall_gap_partition.py`'s
disjunction handling (the R26-found blind spot P23's own text flags as optional, "or at minimum note
in the screen which of the two tools a 'zero measurable misses' claim came from" — noted here: that
blind spot is orthogonal to this item, which only builds and applies the literal map, so it is left
for whoever next needs to make a "zero measurable misses" claim against that script).
