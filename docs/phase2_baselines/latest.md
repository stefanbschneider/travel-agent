# Phase 2 Baseline (Latest)

- run_id: 20260712T060018Z
- timestamp_utc: 2026-07-12T06:00:18+00:00
- git_sha: 170b460ca1559c564e60edf8fe01aa4b37a07d72
- split: tpc_phase2_val (set=val, fold=0/10, n=85)
- budget_sec: 300.0
- label: dynbudget-step5-fullfold0-300s
- repeats: 2 (fresh=True)

## Rehearsal Attribution (FPR)

- ceiling_fpr: 100.0000
- solver_only_fpr: 95.2941
- end_to_end_fpr: 82.3529
- solver_headroom: 4.7059
- parsing_loss: 12.9412

## Run-To-Run Variance (across repeats)

- repeats: 2
- e2e_fpr mean/std: 82.3529 / 0.0000
- solver_only_fpr mean/std: 95.2941 / 0.0000
- e2e_overall_true mean/std: 86.4287 / 0.0301
- solver_only_overall_true mean/std: 94.4141 / 0.0177

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: 100.0000
- solver_only_overall_true_mean: 94.3964
- end_to_end_overall_true_mean: 86.4588
- overall_true_solver_headroom: 5.6036
- overall_true_parsing_loss: 7.9376
- ceiling_overall_parsed_mean: 77.1127
- solver_only_overall_parsed_mean: 69.4186
- end_to_end_overall_parsed_mean: 72.4229
- overall_parsed_solver_headroom: 7.6942
- overall_parsed_parsing_loss: -3.0043

## Parser Vs Oracle

- precision: 0.5534
- recall: 0.7314
- f1: 0.6301
- value_accuracy: 0.8196
- disjunction_flattened: 16
- behavioral_agreement_rate: 0.7647

## Parser Vs Oracle (full val, n=850) -- headline signal, solver-free

- precision: 0.5713
- recall: 0.7269
- f1: 0.6398
- value_accuracy: 0.8091
- disjunction_flattened: 134
- behavioral_agreement_rate: 0.7988

## LLM Parse Config

- backend: infradeep
- model: Qwen/Qwen3.6-27B

## Timing And Reliability

- total_p50_sec: 271.0208
- total_p95_sec: 271.1341
- valid_output_rate: 1.0000
- timed_out: 71
- used_fallback: 0
- budget_overruns: 0
- llm_parse_attempted: 85
- llm_parse_failed: 0

## Completion Status

- parse_completed: 85/85
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 14/85
- end_to_end_timed_out: 71
- solver_only_completed_without_timeout: 14/85
- solver_only_timed_out: 71
- solver_only_recovered_from_timeout: 71
- solver_only_used_fallback: 0
