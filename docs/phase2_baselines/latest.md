# Phase 2 Baseline (Latest)

- run_id: 20260711T071751Z
- timestamp_utc: 2026-07-11T07:17:51+00:00
- git_sha: 630a89fc30e82846790ead9d6f326b61f8beb31f
- split: tpc_phase2_val (set=val, fold=0/10, n=85)
- budget_sec: 60.0
- label: llmparse-disj-fullfold0-60s-fixed
- repeats: 2 (fresh=True)

## Rehearsal Attribution (FPR)

- ceiling_fpr: 100.0000
- solver_only_fpr: 94.1176
- end_to_end_fpr: 81.1765
- solver_headroom: 5.8824
- parsing_loss: 12.9412

## Run-To-Run Variance (across repeats)

- repeats: 2
- e2e_fpr mean/std: 81.1765 / 0.0000
- solver_only_fpr mean/std: 94.1176 / 0.0000
- e2e_overall_true mean/std: 84.5867 / 0.1945
- solver_only_overall_true mean/std: 91.9500 / 0.1937

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: 100.0000
- solver_only_overall_true_mean: 91.7563
- end_to_end_overall_true_mean: 84.3922
- overall_true_solver_headroom: 8.2437
- overall_true_parsing_loss: 7.3640
- ceiling_overall_parsed_mean: 75.5245
- solver_only_overall_parsed_mean: 65.7684
- end_to_end_overall_parsed_mean: 70.9637
- overall_parsed_solver_headroom: 9.7561
- overall_parsed_parsing_loss: -5.1953

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

- total_p50_sec: 34.0397
- total_p95_sec: 34.1475
- valid_output_rate: 1.0000
- timed_out: 80
- used_fallback: 0
- budget_overruns: 0
- llm_parse_attempted: 85
- llm_parse_failed: 0

## Completion Status

- parse_completed: 85/85
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 5/85
- end_to_end_timed_out: 80
- solver_only_completed_without_timeout: 6/85
- solver_only_timed_out: 79
- solver_only_recovered_from_timeout: 79
- solver_only_used_fallback: 0
