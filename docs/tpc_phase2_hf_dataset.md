# Hugging Face `LAMDA-NeSy/ChinaTravel` vs Local Data

Status: **investigation note + planned compare script** (Task 12). No comparison code has been run yet;
the facts below are read from the dataset card. Confirm programmatically before relying on them.

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

## Planned compare script (Task 12, not yet built)

`scripts/compare_hf_dataset.py` should:

1. Load the HF dataset (all subsets/splits) via `datasets.load_dataset("LAMDA-NeSy/ChinaTravel", name=...)`.
2. Load local `tpc_phase1` queries.
3. Report: uid overlap, per-field presence (esp. `hard_logic_py`, `nature_language_en`), city coverage
   vs local, day/people distributions, and constraint-family coverage vs `tpc_phase1`.
4. Conclude whether HF `human`/`human1000` can serve as an independent generalization rehearsal set, and
   note any schema normalization needed to run our evaluators on it.

Open questions to resolve when building the script:

- Does HF `test/human1000` include `hard_logic_py`, or is it withheld for the leaderboard?
- Are any `tpc_phase1` uids also present in HF (contamination risk for a "generalization" claim)?
- Do all HF cities exist in our local `chinatravel/environment` database?
