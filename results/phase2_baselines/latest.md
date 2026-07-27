# Phase 2 Baseline (Latest)

- run_id: 20260726T235203Z
- timestamp_utc: 2026-07-26T23:52:03+00:00
- git_sha: c599570b614512681c8aec6c2e6305a5490d7e3a
- split: tpc_phase2_familiar_100_val (set=familiar_100_val, fold=0/1, n=80)
- data_source_id: ijcai2026_phase2_familiar_100@sha256:32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- data_source_url: https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip
- data_source_archive_sha256: 32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- budget_sec: 900.0
- label: final-night-csfirst-off
- repeats: 1 (fresh=True)

## Rehearsal Attribution (FPR)

- ceiling_fpr: unavailable (no evaluated ceiling plans for this data source)
- solver_only_fpr: 23.7500
- end_to_end_fpr: 25.0000
- solver_headroom: unavailable
- parsing_loss: -1.2500

## Run-To-Run Variance (across repeats)

- repeats: 1
- e2e_fpr mean/std: 25.0000 / 0.0000
- solver_only_fpr mean/std: 23.7500 / 0.0000
- e2e_overall_true mean/std: 47.8242 / 0.0000
- solver_only_overall_true mean/std: 46.5215 / 0.0000

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_true_mean: 46.5215
- end_to_end_overall_true_mean: 47.8242
- overall_true_solver_headroom: unavailable
- overall_true_parsing_loss: -1.3027
- ceiling_overall_parsed_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_parsed_mean: 45.5092
- end_to_end_overall_parsed_mean: 49.7823
- overall_parsed_solver_headroom: unavailable
- overall_parsed_parsing_loss: -4.2731

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

- total_p50_sec: 272.7315
- total_p95_sec: 515.3029
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
