# Phase 2 Baseline (Latest)

- run_id: 20260721T174336Z
- timestamp_utc: 2026-07-21T17:43:36+00:00
- git_sha: 1de62e99b2935f9b7987a397f5dd7cbaf7d75906
- split: tpc_phase2_familiar_100 (set=familiar_100, fold=0/1, n=100)
- data_source_id: ijcai2026_phase2_familiar_100@sha256:32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- data_source_url: https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip
- data_source_archive_sha256: 32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- budget_sec: 300.0
- label: familiar100-negconstraint-llmon
- repeats: 2 (fresh=True)

## Rehearsal Attribution (FPR)

- ceiling_fpr: unavailable (no evaluated ceiling plans for this data source)
- solver_only_fpr: 26.0000
- end_to_end_fpr: 22.0000
- solver_headroom: unavailable
- parsing_loss: 4.0000

## Run-To-Run Variance (across repeats)

- repeats: 2
- e2e_fpr mean/std: 21.5000 / 0.5000
- solver_only_fpr mean/std: 25.5000 / 0.5000
- e2e_overall_true mean/std: 45.0595 / 0.4596
- solver_only_overall_true mean/std: 47.1120 / 0.8541

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_true_mean: 46.2578
- end_to_end_overall_true_mean: 45.5191
- overall_true_solver_headroom: unavailable
- overall_true_parsing_loss: 0.7387
- ceiling_overall_parsed_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_parsed_mean: 45.4573
- end_to_end_overall_parsed_mean: 47.5445
- overall_parsed_solver_headroom: unavailable
- overall_parsed_parsing_loss: -2.0872

## Parser Vs Oracle

- precision: 0.9510
- recall: 0.9510
- f1: 0.9510
- value_accuracy: 0.9510
- disjunction_flattened: 0
- behavioral_agreement_rate: unavailable (no best plans for this data source)

## Parser Vs Oracle (full split: tpc_phase2_familiar_100, n=100) -- headline signal, solver-free

- precision: 0.9510
- recall: 0.9510
- f1: 0.9510
- value_accuracy: 0.9510
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

- total_p50_sec: 270.5138
- total_p95_sec: 271.1273
- valid_output_rate: 1.0000
- timed_out: 38
- used_fallback: 0
- budget_overruns: 0
- llm_parse_attempted: 100
- llm_parse_failed: 0

## Completion Status

- parse_completed: 100/100
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 62/100
- end_to_end_timed_out: 38
- solver_only_completed_without_timeout: 78/100
- solver_only_timed_out: 22
- solver_only_recovered_from_timeout: 22
- solver_only_used_fallback: 0
