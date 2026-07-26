# Phase 2 Baseline (Latest)

- run_id: 20260726T004535Z
- timestamp_utc: 2026-07-26T00:45:35+00:00
- git_sha: 6d354b99b442d1952639405c2a2610299c2691b3
- split: tpc_phase2_familiar_100_val (set=familiar_100_val, fold=0/1, n=80)
- data_source_id: ijcai2026_phase2_familiar_100@sha256:32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- data_source_url: https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip
- data_source_archive_sha256: 32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- budget_sec: 900.0
- label: val-pincascade-900s
- repeats: 2 (fresh=True)

## Rehearsal Attribution (FPR)

- ceiling_fpr: unavailable (no evaluated ceiling plans for this data source)
- solver_only_fpr: 28.7500
- end_to_end_fpr: 26.2500
- solver_headroom: unavailable
- parsing_loss: 2.5000

## Run-To-Run Variance (across repeats)

- repeats: 2
- e2e_fpr mean/std: 26.2500 / 0.0000
- solver_only_fpr mean/std: 28.7500 / 0.0000
- e2e_overall_true mean/std: 48.1370 / 0.4429
- solver_only_overall_true mean/std: 50.1306 / 0.4188

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_true_mean: 50.5494
- end_to_end_overall_true_mean: 47.6941
- overall_true_solver_headroom: unavailable
- overall_true_parsing_loss: 2.8553
- ceiling_overall_parsed_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_parsed_mean: 49.5360
- end_to_end_overall_parsed_mean: 49.6849
- overall_parsed_solver_headroom: unavailable
- overall_parsed_parsing_loss: -0.1489

## Parser Vs Oracle

- precision: 0.9588
- recall: 0.9588
- f1: 0.9588
- value_accuracy: 0.9588
- disjunction_flattened: 0
- behavioral_agreement_rate: unavailable (no best plans for this data source)

## Parser Vs Oracle (full split: tpc_phase2_familiar_100_val, n=80) -- headline signal, solver-free

- precision: 0.9588
- recall: 0.9588
- f1: 0.9588
- value_accuracy: 0.9588
- disjunction_flattened: 0
- behavioral_agreement_rate (accept-side): unavailable (no best plans for this data source)
- reject_agreement (reject-side probes): None
- behavioral_balanced: unavailable (no best plans for this data source)

## LLM Parse Config

- backend: deepinfra
- model: Qwen/Qwen3.6-27B

## Phase 2 Flags (resolved for the e2e run)

- disjunction: True
- llm_parse: True
- llm_parse_mode: audit
- llm_refine: False
- dynamic_budget: True
- entity_resolution: True

## Timing And Reliability

- total_p50_sec: 371.4482
- total_p95_sec: 602.7883
- valid_output_rate: 1.0000
- timed_out: 0
- used_fallback: 0
- budget_overruns: 0
- llm_parse_attempted: 80
- llm_parse_failed: 0

## Completion Status

- parse_completed: 80/80
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 80/80
- end_to_end_timed_out: 0
- solver_only_completed_without_timeout: 80/80
- solver_only_timed_out: 0
- solver_only_recovered_from_timeout: 0
- solver_only_used_fallback: 0
