# Phase 2 Baseline (Latest)

- run_id: 20260711T000602Z
- timestamp_utc: 2026-07-11T00:06:02+00:00
- git_sha: 86f7304e8e14257613e191b6f7e39ae570d90941
- split: tpc_phase2_val (set=val, fold=0/10, n=85)
- budget_sec: 60.0
- label: llmparse-disj-fullfold0-60s
- repeats: 2 (fresh=True)

## Rehearsal Attribution (FPR)

- ceiling_fpr: 100.0000
- solver_only_fpr: 94.1176
- end_to_end_fpr: 85.8824
- solver_headroom: 5.8824
- parsing_loss: 8.2353

## Run-To-Run Variance (across repeats)

- repeats: 2
- e2e_fpr mean/std: 84.1176 / 1.7647
- solver_only_fpr mean/std: 94.7059 / 0.5882
- e2e_overall_true mean/std: 86.3822 / 1.0221
- solver_only_overall_true mean/std: 92.4458 / 0.6836

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: 100.0000
- solver_only_overall_true_mean: 91.7622
- end_to_end_overall_true_mean: 87.4043
- overall_true_solver_headroom: 8.2378
- overall_true_parsing_loss: 4.3579
- ceiling_overall_parsed_mean: 75.5245
- solver_only_overall_parsed_mean: 68.0450
- end_to_end_overall_parsed_mean: 73.2958
- overall_parsed_solver_headroom: 7.4795
- overall_parsed_parsing_loss: -5.2508

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
- model: (n/a)

## Timing And Reliability

- total_p50_sec: 34.7319
- total_p95_sec: 35.1239
- valid_output_rate: 1.0000
- timed_out: 73
- used_fallback: 0
- budget_overruns: 0

## Completion Status

- parse_completed: 85/85
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 12/85
- end_to_end_timed_out: 73
- solver_only_completed_without_timeout: 5/85
- solver_only_timed_out: 80
- solver_only_recovered_from_timeout: 80
- solver_only_used_fallback: 0
