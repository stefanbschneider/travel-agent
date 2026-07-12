# Phase 2 Baseline (Latest)

- run_id: 20260711T192208Z
- timestamp_utc: 2026-07-11T19:22:08+00:00
- git_sha: f36a326b9b829948e81aa4972bfb4d23d79fbdec
- split: tpc_phase2_val (set=val, fold=0/10, n=85)
- budget_sec: 300.0
- label: llmparse-disj-fullfold0-300s
- repeats: 2 (fresh=True)

## Rehearsal Attribution (FPR)

- ceiling_fpr: 100.0000
- solver_only_fpr: 95.2941
- end_to_end_fpr: 80.0000
- solver_headroom: 4.7059
- parsing_loss: 15.2941

## Run-To-Run Variance (across repeats)

- repeats: 2
- e2e_fpr mean/std: 80.0000 / 0.0000
- solver_only_fpr mean/std: 95.2941 / 0.0000
- e2e_overall_true mean/std: 84.3079 / 0.2841
- solver_only_overall_true mean/std: 94.4265 / 0.0216

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: 100.0000
- solver_only_overall_true_mean: 94.4049
- end_to_end_overall_true_mean: 84.5920
- overall_true_solver_headroom: 5.5951
- overall_true_parsing_loss: 9.8130
- ceiling_overall_parsed_mean: 75.5245
- solver_only_overall_parsed_mean: 70.0549
- end_to_end_overall_parsed_mean: 72.2257
- overall_parsed_solver_headroom: 5.4696
- overall_parsed_parsing_loss: -2.1708

## Parser Vs Oracle

- precision: 0.5369
- recall: 0.7078
- f1: 0.6106
- value_accuracy: 0.8035
- disjunction_flattened: 16
- behavioral_agreement_rate: 0.7529

## Parser Vs Oracle (full val, n=850) -- headline signal, solver-free

- precision: 0.5565
- recall: 0.6977
- f1: 0.6191
- value_accuracy: 0.8072
- disjunction_flattened: 134
- behavioral_agreement_rate: 0.7788

## LLM Parse Config

- backend: infradeep
- model: Qwen/Qwen3.6-27B

## Timing And Reliability

- total_p50_sec: 166.0330
- total_p95_sec: 166.1481
- valid_output_rate: 1.0000
- timed_out: 78
- used_fallback: 0
- budget_overruns: 0
- llm_parse_attempted: 85
- llm_parse_failed: 0

## Completion Status

- parse_completed: 85/85
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 7/85
- end_to_end_timed_out: 78
- solver_only_completed_without_timeout: 14/85
- solver_only_timed_out: 71
- solver_only_recovered_from_timeout: 71
- solver_only_used_fallback: 0
