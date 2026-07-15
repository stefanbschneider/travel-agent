# Phase 2 Dataset Boundaries

Phase 2 measurements must name their data source.
These four sources have different trust and generalization properties; none substitutes for the organizer's final held-out set.

## 1. Hugging Face ChinaTravel

[`LAMDA-NeSy/ChinaTravel`](https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel) is public benchmark data with multiple configurations and splits.
It is useful for an auxiliary parser or solver generalization probe when the selected rows include the required text and oracle fields.
It is not the IJCAI 2026 final evaluation set.
Keep the HF configuration and split names with every result; do not merge different configurations into one comparison.

The repository comparison utility is:

```bash
.venv/bin/python scripts/compare_hf_dataset.py --hf-config default
```

Its output answers overlap and field-presence questions for the selected HF rows and local `tpc_phase1`; it does not establish final-evaluation performance.

## 2. Repository-local released data

The repository contains the released Phase 1 English queries and their oracle fields under `chinatravel/data/en/TPC_IJCAI_2026_phase1_EN/`.
`make phase2-splits` deterministically partitions that released source into `tpc_phase2_val` and `tpc_phase2_test` for local development.
Despite the local `test` name, these are not organizer-held-out Phase 2 data.
They remain useful only when the agent path hides `hard_logic_py` and other oracle-only fields.

## 3. Official familiar-100 development set

The organizers released the [familiar-100 archive](https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip) on 2026-07-15 with the Agent Environment Guide.
The 100 source records are imported unchanged under `chinatravel/data/en/TPC_IJCAI_2026_phase2_familiar_100_data/` and selected by `tpc_phase2_familiar_100`.
`_provenance.json` pins the source URL, release/retrieval dates, archive SHA-256, and every extracted member's size, CRC32, and SHA-256.
The records contain `hard_logic_py`; loaders retain it only for scoring and attribution, while the adapter and both harnesses expose only `uid`, trip metadata, and `nature_language` to the agent path.
A familiar-100 result must identify this imported artifact and run configuration; it must not be presented as a final-evaluation estimate.

## 4. Organizer final held-out set

The final Phase 2 set is separate, unavailable locally, and evaluated only through the organizer-run no-oracle harness.
No local split, HF subset, or familiar-100 result proves performance on it.
Use those sources to diagnose and rank work, then preserve no-oracle boundaries and regression gates so the submitted harness remains robust to unseen requests.

## Measurement rule

Do not compare rows across sources as if they had the same distribution or oracle exposure.
Record the source name, selected split, deterministic selection, budget, flags, and model/backend with each measurement.
For methodology and ledger semantics, see [Phase 2 evaluation](tpc_phase2_eval.md) and the [baseline ledger guide](phase2_baselines/README.md).
