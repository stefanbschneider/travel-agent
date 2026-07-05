# Hugging Face `LAMDA-NeSy/ChinaTravel` vs Local Data

Status: **built and run** (Task 12, `scripts/compare_hf_dataset.py`; findings below verified against
the live dataset on 2026-07-05).

Dataset card: https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel

## What the HF dataset contains (from the card)

Subsets / splits:

- `default` (654 rows): `easy` (300), `medium` (150), `human` (154), `preference_base50` (50)
- `preference` (300 rows): `preference0_base50` … `preference5_base50`
- `test` (1000 rows): `human1000`

Record layout (per query):

- `uid`, `tag`, `start_city`, `target_city`, `days`, `people_number`, `limit_rooms`,
  `limits_room_type`, **`hard_logic_py`** (oracle constraints, present), `nature_language` (zh),
  `nature_language_en` (en). Preference config additionally has `preference`, `preference_en`,
  `preference_py`.

Example uids: `e20241028160248698752` (easy), `m20241028164917698287` (medium). These are the
**original ChinaTravel paper** benchmark ids.

## How this relates to our local data

- Our Phase 1 competition data lives in `chinatravel/data/en/TPC_IJCAI_2026_phase1_EN/` with uids like
  `20250322...`, listed in `chinatravel/evaluation/default_splits/tpc_phase1.txt`. That is the **TPC
  IJCAI 2026** released split (newer, 1000 queries).
- The HF dataset is the **paper benchmark** (easy/medium/human/human1000). Different uid scheme and,
  almost certainly, a **different query set** from `tpc_phase1`.
- `chinatravel/data/load_datasets.py::load_query` already pulls from HF for certain non-local `zh`
  splits and `ast.literal_eval`s `hard_logic_py`, so the HF schema is compatible with our evaluators.

## Why this matters for Phase 2

The HF `human` / `human1000` splits are described as **more diverse, with unseen constraints**, and they
ship **with oracle `hard_logic_py` and both zh/en phrasing**. That makes them a strong candidate
**generalization / held-out rehearsal set**: we can measure whether the no-oracle parser degrades on
phrasing it was never tuned on — the exact Phase-2 risk — while still having oracle ground truth for the
three-axis attribution in `docs/tpc_phase2_eval.md`.

## Findings (from `scripts/compare_hf_dataset.py`, run 2026-07-05)

Comparing HF `default` (654 rows) against local `tpc_phase1` (1000):

- **uid overlap: 0** — the HF paper benchmark and the TPC-2026 `tpc_phase1` split are disjoint uid
  spaces. No contamination risk in treating HF as an independent generalization set.
- **HF field presence:** all 654 rows have `hard_logic_py`, `nature_language`, **and
  `nature_language_en`**, plus `start_city`/`target_city`/`days`/`people_number`. (Local `tpc_phase1`
  has `hard_logic_py` but **no** `nature_language_en` — it stores English text differently.)
- **Coverage:** HF adds shorter and longer trips — `days` ∈ {1..6} (incl. 84 one-day and a 6-day),
  vs local {2..5}. People counts broadly overlap.
- **Cities:** HF `start_city`/`target_city` are stored in **Chinese** (上海, 北京, 成都, …) while the
  local `en` data uses English names (Shanghai, …). The 10 cities are the same set; the "hf-only
  cities" in the report are a language-encoding artifact, not genuinely new destinations. To use HF as
  an English generalization set, read `nature_language_en` and map city names to the English forms.

Comparing HF `test` (human1000, 1000 rows):

- The `test`/`human1000` config carries **no `hard_logic_py`** (oracle withheld). It is therefore
  **not** usable for the oracle-ground-truth attribution in `docs/tpc_phase2_eval.md`; it can only be
  used for schema/commonsense checks or blind qualitative review.

## Conclusion

- Use HF **`default`** (easy/medium/human, 654 queries) as an **independent generalization / held-out
  rehearsal set**: it has oracle `hard_logic_py` + English text and is uid-disjoint from `tpc_phase1`,
  so it directly tests whether the no-oracle parser degrades on phrasing/trip-shapes it was never tuned
  on (the core Phase-2 risk). Its extra 1-day and 6-day trips are useful stress cases.
- Do **not** rely on HF `test`/`human1000` for parser-vs-oracle attribution (no oracle fields).
- Normalization needed to run our EN pipeline/evaluators on HF `default`: prefer `nature_language_en`
  for the agent prompt, and map Chinese city names to the English environment names.

## Compare script

`scripts/compare_hf_dataset.py` (pure `compare(local_rows, hf_rows)` core + CLI):

```bash
python scripts/compare_hf_dataset.py --hf-config default   # generalization candidate
python scripts/compare_hf_dataset.py --hf-config test      # human1000 (no oracle)
```

It reports uid overlap, per-field presence, city coverage vs local, and day/people distributions, and
sets `usable_as_generalization_set` (True for `default`, False for `test`).
