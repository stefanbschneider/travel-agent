# Phase 2 Baseline (Latest)

- run_id: 20260710T110908Z
- timestamp_utc: 2026-07-10T11:09:08+00:00
- git_sha: 916bb70327c65545abe6d88dfecd133a29ffabd6
- split: tpc_phase2_val (set=val, fold=0/10, n=1)
- budget_sec: 30.0

## Rehearsal Attribution (FPR)

- ceiling_fpr: 100.0000
- solver_only_fpr: 100.0000
- end_to_end_fpr: 100.0000
- solver_headroom: 0.0000
- parsing_loss: 0.0000

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: 100.0000
- solver_only_overall_true_mean: 99.2222
- end_to_end_overall_true_mean: 97.7275
- overall_true_solver_headroom: 0.7778
- overall_true_parsing_loss: 1.4947
- ceiling_overall_parsed_mean: 100.0000
- solver_only_overall_parsed_mean: 99.2222
- end_to_end_overall_parsed_mean: 97.7275
- overall_parsed_solver_headroom: 0.7778
- overall_parsed_parsing_loss: 1.4947

## Parser Vs Oracle

- precision: 1.0000
- recall: 1.0000
- f1: 1.0000
- value_accuracy: 1.0000
- disjunction_flattened: 0
- behavioral_agreement_rate: 1.0000

## Timing And Reliability

- total_p50_sec: 17.5349
- total_p95_sec: 17.5349
- valid_output_rate: 1.0000
- timed_out: 1
- used_fallback: 0
- budget_overruns: 0

## Completion Status

- parse_completed: 1/1
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 0/1
- end_to_end_timed_out: 1
- solver_only_completed_without_timeout: 1/1
- solver_only_timed_out: 0
- solver_only_recovered_from_timeout: 0
- solver_only_used_fallback: 0
