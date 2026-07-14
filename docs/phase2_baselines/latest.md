# Phase 2 Baseline (Latest)

- run_id: 20260713T130105Z
- timestamp_utc: 2026-07-13T13:01:05+00:00
- git_sha: ace69b66869fb6ff881c0a3e925fd04292d279e4
- split: tpc_phase2_val (set=val, fold=0/10, n=85)
- budget_sec: 300.0
- label: plan3-n1n7-gate
- repeats: 2 (fresh=True)

## Rehearsal Attribution (FPR)

- ceiling_fpr: 100.0000
- solver_only_fpr: 95.2941
- end_to_end_fpr: 85.8824
- solver_headroom: 4.7059
- parsing_loss: 9.4118

## Run-To-Run Variance (across repeats)

- repeats: 2
- e2e_fpr mean/std: 71.1765 / 14.7059
- solver_only_fpr mean/std: 95.2941 / 0.0000
- e2e_overall_true mean/std: 88.2001 / 0.1820
- solver_only_overall_true mean/std: 94.2338 / 0.1690

## Rehearsal Attribution (Continuous Score)

- ceiling_overall_true_mean: 100.0000
- solver_only_overall_true_mean: 94.0647
- end_to_end_overall_true_mean: 88.3821
- overall_true_solver_headroom: 5.9353
- overall_true_parsing_loss: 5.6826
- ceiling_overall_parsed_mean: 76.4657
- solver_only_overall_parsed_mean: 69.2682
- end_to_end_overall_parsed_mean: 69.8440
- overall_parsed_solver_headroom: 7.1975
- overall_parsed_parsing_loss: -0.5758

## Parser Vs Oracle

- precision: 0.7584
- recall: 0.7839
- f1: 0.7710
- value_accuracy: 0.8526
- disjunction_flattened: 12
- behavioral_agreement_rate: 0.7882

## Parser Vs Oracle (full val, n=850) -- headline signal, solver-free

- precision: 0.7587
- recall: 0.7635
- f1: 0.7611
- value_accuracy: 0.8363
- disjunction_flattened: 113
- behavioral_agreement_rate (accept-side): 0.8141
- reject_agreement (reject-side probes): 0.8348
- behavioral_balanced: 0.8245

## LLM Parse Config

- backend: deepinfra
- model: Qwen/Qwen3.6-27B

## Timing And Reliability

- total_p50_sec: 271.0164
- total_p95_sec: 271.1362
- valid_output_rate: 1.0000
- timed_out: 66
- used_fallback: 0
- budget_overruns: 0
- llm_parse_attempted: 85
- llm_parse_failed: 0

## Completion Status

- parse_completed: 85/85
- parse_failed: 0
- parse_timed_out: 0
- end_to_end_completed_without_timeout: 19/85
- end_to_end_timed_out: 66
- solver_only_completed_without_timeout: 15/85
- solver_only_timed_out: 70
- solver_only_recovered_from_timeout: 70
- solver_only_used_fallback: 0
