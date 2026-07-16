# Phase 2 Baseline (Latest)

- run_id: 20260716T090638Z
- timestamp_utc: 2026-07-16T09:06:38+00:00
- git_sha: a3fcdc39aa5a14aecfb1257b5d427dfa676eb20a
- split: tpc_phase2_familiar_100 (set=familiar_100, fold=0/1, n=100)
- data_source_id: ijcai2026_phase2_familiar_100@sha256:32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- data_source_url: https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip
- data_source_archive_sha256: 32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- budget_sec: 300.0
- label: familiar100-qwen-baseline
- repeats: 2 (fresh=True)

## Rehearsal Attribution (FPR)

- ceiling_fpr: unavailable (no evaluated ceiling plans for this data source)
- solver_only_fpr: 26.0000
- end_to_end_fpr: 2.0000
- solver_headroom: unavailable
- parsing_loss: 24.0000

## Run-To-Run Variance (across repeats)

- repeats: 2
- e2e_fpr mean/std: 2.0000 / 0.0000
- solver_only_fpr mean/std: 26.0000 / 0.0000
- e2e_overall_true mean/std: 36.0610 / 0.0530
- solver_only_overall_true mean/std: 48.2979 / 0.1584

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_true_mean: 48.1395
- end_to_end_overall_true_mean: 36.1140
- overall_true_solver_headroom: unavailable
- overall_true_parsing_loss: 12.0255
- ceiling_overall_parsed_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_parsed_mean: 42.1844
- end_to_end_overall_parsed_mean: 53.2298
- overall_parsed_solver_headroom: unavailable
- overall_parsed_parsing_loss: -11.0455

## Parser Vs Oracle

- precision: 0.4445
- recall: 0.1281
- f1: 0.1988
- value_accuracy: 0.6400
- disjunction_flattened: 0
- behavioral_agreement_rate: 0.0000

## Parser Vs Oracle (full split: tpc_phase2_familiar_100, n=100) -- headline signal, solver-free

- precision: 0.4445
- recall: 0.1281
- f1: 0.1988
- value_accuracy: 0.6400
- disjunction_flattened: 0
- behavioral_agreement_rate (accept-side): 0.0000
- reject_agreement (reject-side probes): None
- behavioral_balanced: 0.0000

## LLM Parse Config

- backend: deepinfra
- model: Qwen/Qwen3.6-27B

## Timing And Reliability

- total_p50_sec: 270.4289
- total_p95_sec: 271.1225
- valid_output_rate: 1.0000
- timed_out: 35
- used_fallback: 0
- budget_overruns: 0
- llm_parse_attempted: 100
- llm_parse_failed: 0

## Completion Status

- parse_completed: 100/100
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 65/100
- end_to_end_timed_out: 35
- solver_only_completed_without_timeout: 77/100
- solver_only_timed_out: 23
- solver_only_recovered_from_timeout: 23
- solver_only_used_fallback: 0
