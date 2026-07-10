# Phase 2 Baseline (Latest)

- run_id: 20260710T144747Z
- timestamp_utc: 2026-07-10T14:47:47+00:00
- git_sha: 165cd1faa24279be3887b962e2054e9e6f7113c1
- split: tpc_phase2_val (set=val, fold=0/10, n=20)
- budget_sec: 60.0
- label: rebaseline-60s-n20-post-1c
- repeats: 1 (fresh=True)

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
- e2e_overall_true mean/std: 85.7159 / 0.0000
- solver_only_overall_true mean/std: 94.0428 / 0.0000

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: 100.0000
- solver_only_overall_true_mean: 94.0428
- end_to_end_overall_true_mean: 85.7159
- overall_true_solver_headroom: 5.9572
- overall_true_parsing_loss: 8.3269
- ceiling_overall_parsed_mean: 75.3125
- solver_only_overall_parsed_mean: 67.3838
- end_to_end_overall_parsed_mean: 66.0592
- overall_parsed_solver_headroom: 7.9287
- overall_parsed_parsing_loss: 1.3247

## Parser Vs Oracle

- precision: 0.5250
- recall: 0.7667
- f1: 0.6232
- value_accuracy: 0.8667
- disjunction_flattened: 3
- behavioral_agreement_rate: 0.7500

## Timing And Reliability

- total_p50_sec: 34.0357
- total_p95_sec: 34.1581
- valid_output_rate: 1.0000
- timed_out: 15
- used_fallback: 0
- budget_overruns: 0

## Completion Status

- parse_completed: 20/20
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 5/20
- end_to_end_timed_out: 15
- solver_only_completed_without_timeout: 2/20
- solver_only_timed_out: 18
- solver_only_recovered_from_timeout: 18
- solver_only_used_fallback: 0
