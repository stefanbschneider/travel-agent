# Phase 2 Baseline (Latest)

- run_id: 20260722T195341Z
- timestamp_utc: 2026-07-22T19:53:41+00:00
- git_sha: 110eefae80a57fe7ce1f3240d1411c08b97d6e78
- split: tpc_phase2_familiar_100 (set=familiar_100, fold=0/1, n=100)
- data_source_id: ijcai2026_phase2_familiar_100@sha256:32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- data_source_url: https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip
- data_source_archive_sha256: 32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- budget_sec: 300.0
- label: familiar100-pinwindows-on
- repeats: 2 (fresh=True)

## Rehearsal Attribution (FPR)

- ceiling_fpr: unavailable (no evaluated ceiling plans for this data source)
- solver_only_fpr: 30.0000
- end_to_end_fpr: 29.0000
- solver_headroom: unavailable
- parsing_loss: 1.0000

## Run-To-Run Variance (across repeats)

- repeats: 2
- e2e_fpr mean/std: 29.5000 / 0.5000
- solver_only_fpr mean/std: 30.5000 / 0.5000
- e2e_overall_true mean/std: 50.1754 / 1.4097
- solver_only_overall_true mean/std: 50.4195 / 0.9371

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_true_mean: 51.3566
- end_to_end_overall_true_mean: 48.7657
- overall_true_solver_headroom: unavailable
- overall_true_parsing_loss: 2.5908
- ceiling_overall_parsed_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_parsed_mean: 50.5373
- end_to_end_overall_parsed_mean: 50.2530
- overall_parsed_solver_headroom: unavailable
- overall_parsed_parsing_loss: 0.2843

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

- total_p50_sec: 271.0146
- total_p95_sec: 271.1274
- valid_output_rate: 1.0000
- timed_out: 57
- used_fallback: 0
- budget_overruns: 0
- llm_parse_attempted: 100
- llm_parse_failed: 0

## Completion Status

- parse_completed: 100/100
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 43/100
- end_to_end_timed_out: 57
- solver_only_completed_without_timeout: 73/100
- solver_only_timed_out: 27
- solver_only_recovered_from_timeout: 27
- solver_only_used_fallback: 0
