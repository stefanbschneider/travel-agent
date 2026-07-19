# Phase 2 Baseline (Latest)

- run_id: 20260718T155006Z
- timestamp_utc: 2026-07-18T15:50:06+00:00
- git_sha: ae6337f0b3fb7809e88e93e03c99d7bb5a3d05a3
- split: tpc_phase2_familiar_100 (set=familiar_100, fold=0/1, n=100)
- data_source_id: ijcai2026_phase2_familiar_100@sha256:32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- data_source_url: https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip
- data_source_archive_sha256: 32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- budget_sec: 300.0
- label: familiar100-timewindows
- repeats: 2 (fresh=True)

## Rehearsal Attribution (FPR)

- ceiling_fpr: unavailable (no evaluated ceiling plans for this data source)
- solver_only_fpr: 26.0000
- end_to_end_fpr: 7.0000
- solver_headroom: unavailable
- parsing_loss: 19.0000

## Run-To-Run Variance (across repeats)

- repeats: 2
- e2e_fpr mean/std: 7.5000 / 0.5000
- solver_only_fpr mean/std: 26.0000 / 0.0000
- e2e_overall_true mean/std: 39.1265 / 0.7217
- solver_only_overall_true mean/std: 47.0856 / 0.4740

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_true_mean: 47.5596
- end_to_end_overall_true_mean: 38.4048
- overall_true_solver_headroom: unavailable
- overall_true_parsing_loss: 9.1548
- ceiling_overall_parsed_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_parsed_mean: 39.9376
- end_to_end_overall_parsed_mean: 49.5671
- overall_parsed_solver_headroom: unavailable
- overall_parsed_parsing_loss: -9.6295

## Parser Vs Oracle

- precision: 0.8180
- recall: 0.3518
- f1: 0.4920
- value_accuracy: 0.9380
- disjunction_flattened: 0
- behavioral_agreement_rate: 0.0000

## Parser Vs Oracle (full split: tpc_phase2_familiar_100, n=100) -- headline signal, solver-free

- precision: 0.8180
- recall: 0.3518
- f1: 0.4920
- value_accuracy: 0.9380
- disjunction_flattened: 0
- behavioral_agreement_rate (accept-side): 0.0000
- reject_agreement (reject-side probes): None
- behavioral_balanced: 0.0000

## LLM Parse Config

- backend: deepinfra
- model: Qwen/Qwen3.6-27B

## Timing And Reliability

- total_p50_sec: 270.3838
- total_p95_sec: 271.0285
- valid_output_rate: 1.0000
- timed_out: 34
- used_fallback: 0
- budget_overruns: 0
- llm_parse_attempted: 100
- llm_parse_failed: 0

## Completion Status

- parse_completed: 100/100
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 66/100
- end_to_end_timed_out: 34
- solver_only_completed_without_timeout: 77/100
- solver_only_timed_out: 23
- solver_only_recovered_from_timeout: 23
- solver_only_used_fallback: 0
