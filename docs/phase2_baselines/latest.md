# Phase 2 Baseline (Latest)

- run_id: 20260710T124113Z
- timestamp_utc: 2026-07-10T12:41:13+00:00
- git_sha: 2eda9f666972bf6889cec2fb20ba568ea56996e6
- split: tpc_phase2_val (set=val, fold=0/10, n=20)
- budget_sec: 60.0
- label: baseline-60s-n20
- repeats: 1 (fresh=False)

## Rehearsal Attribution (FPR)

- ceiling_fpr: 100.0000
- solver_only_fpr: 95.0000
- end_to_end_fpr: 85.0000
- solver_headroom: 5.0000
- parsing_loss: 10.0000

## Run-To-Run Variance (across repeats)

- repeats: 1
- e2e_fpr mean/std: 85.0000 / 0.0000
- solver_only_fpr mean/std: 95.0000 / 0.0000
- e2e_overall_true mean/std: 85.3893 / 0.0000
- solver_only_overall_true mean/std: 93.2763 / 0.0000

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: 100.0000
- solver_only_overall_true_mean: 93.2763
- end_to_end_overall_true_mean: 85.3893
- overall_true_solver_headroom: 6.7237
- overall_true_parsing_loss: 7.8870
- ceiling_overall_parsed_mean: 75.3125
- solver_only_overall_parsed_mean: 66.9218
- end_to_end_overall_parsed_mean: 65.5691
- overall_parsed_solver_headroom: 8.3907
- overall_parsed_parsing_loss: 1.3527

## Parser Vs Oracle

- precision: 0.5250
- recall: 0.7667
- f1: 0.6232
- value_accuracy: 0.8667
- disjunction_flattened: 3
- behavioral_agreement_rate: 0.7500

## Timing And Reliability

- total_p50_sec: 34.0281
- total_p95_sec: 34.1442
- valid_output_rate: 1.0000
- timed_out: 16
- used_fallback: 0
- budget_overruns: 0

## Completion Status

- parse_completed: 20/20
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 4/20
- end_to_end_timed_out: 16
- solver_only_completed_without_timeout: 1/20
- solver_only_timed_out: 19
- solver_only_recovered_from_timeout: 19
- solver_only_used_fallback: 0
