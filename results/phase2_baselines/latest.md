# Phase 2 Baseline (Latest)

- run_id: 20260721T054820Z
- timestamp_utc: 2026-07-21T05:48:20+00:00
- git_sha: 7d5e1910769de8e84a861a366456251600b17afc
- split: tpc_phase2_familiar_100 (set=familiar_100, fold=0/1, n=100)
- data_source_id: ijcai2026_phase2_familiar_100@sha256:32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- data_source_url: https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip
- data_source_archive_sha256: 32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c
- budget_sec: 300.0
- label: familiar100-negconstraint-nollm
- repeats: 2 (fresh=True)

## Rehearsal Attribution (FPR)

- ceiling_fpr: unavailable (no evaluated ceiling plans for this data source)
- solver_only_fpr: 25.0000
- end_to_end_fpr: 13.0000
- solver_headroom: unavailable
- parsing_loss: 12.0000

## Run-To-Run Variance (across repeats)

- repeats: 2
- e2e_fpr mean/std: 12.5000 / 0.5000
- solver_only_fpr mean/std: 25.5000 / 0.5000
- e2e_overall_true mean/std: 41.8254 / 0.1367
- solver_only_overall_true mean/std: 47.1442 / 0.4097

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_true_mean: 46.7345
- end_to_end_overall_true_mean: 41.9622
- overall_true_solver_headroom: unavailable
- overall_true_parsing_loss: 4.7724
- ceiling_overall_parsed_mean: unavailable (no evaluated ceiling plans for this data source)
- solver_only_overall_parsed_mean: 42.5167
- end_to_end_overall_parsed_mean: 49.2443
- overall_parsed_solver_headroom: unavailable
- overall_parsed_parsing_loss: -6.7276

## Parser Vs Oracle

- precision: 0.8620
- recall: 0.8036
- f1: 0.8317
- value_accuracy: 0.9224
- disjunction_flattened: 0
- behavioral_agreement_rate: unavailable (no best plans for this data source)

## Parser Vs Oracle (full split: tpc_phase2_familiar_100, n=100) -- headline signal, solver-free

- precision: 0.8620
- recall: 0.8036
- f1: 0.8317
- value_accuracy: 0.9224
- disjunction_flattened: 0
- behavioral_agreement_rate (accept-side): unavailable (no best plans for this data source)
- reject_agreement (reject-side probes): None
- behavioral_balanced: unavailable (no best plans for this data source)

## LLM Parse Config

- backend: none
- model: (n/a)

## Phase 2 Flags (resolved for the e2e run)

- disjunction: True
- llm_parse: False
- llm_parse_mode: audit
- llm_refine: False
- dynamic_budget: True
- entity_resolution: True

## Timing And Reliability

- total_p50_sec: 270.5703
- total_p95_sec: 271.1227
- valid_output_rate: 1.0000
- timed_out: 43
- used_fallback: 0
- budget_overruns: 0
- llm_parse_attempted: 0
- llm_parse_failed: 0

## Completion Status

- parse_completed: 100/100
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 57/100
- end_to_end_timed_out: 43
- solver_only_completed_without_timeout: 78/100
- solver_only_timed_out: 22
- solver_only_recovered_from_timeout: 22
- solver_only_used_fallback: 0
