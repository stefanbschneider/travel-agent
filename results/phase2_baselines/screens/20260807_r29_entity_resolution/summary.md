# `TPC_P2_ENTITY_RESOLUTION` paired parse arms (deterministic, zero LLM calls)

| set | n | F1 off | F1 on | matched | wrong_value | spurious |
| --- | --- | --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | 0.9552 | **0.9949** | 661 -> 688 | 30 -> 3 | 0 -> 0 |
| local_released_150 | 150 | 0.8222 | **0.8451** | 325 -> 335 | 36 -> 26 | 40 -> 39 |
| hf_easy | 300 | 0.6891 | **0.6886** | 391 -> 391 | 84 -> 84 | 177 -> 179 |
| hf_medium | 150 | 0.7404 | **0.7384** | 391 -> 391 | 86 -> 86 | 114 -> 119 |
| hf_human | 154 | 0.7205 | **0.7205** | 195 -> 195 | 45 -> 45 | 44 -> 44 |
| hf_preference_base50 | 50 | 0.6768 | **0.6768** | 62 -> 62 | 13 -> 13 | 32 -> 32 |

Acceptance for a static GREEN: no set's `spurious` rises materially and F1 does not fall on any set; familiar-100 must not regress.
