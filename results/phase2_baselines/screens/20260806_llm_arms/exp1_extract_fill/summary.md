Mode `extract_fill` · model `Qwen/Qwen3.6-27B` · backend `deepinfra` · thinking `False`

| set | n | arm | parse P | parse R | parse F1 | parse-gap clauses | C-LPR ceiling | queries w/ gap | FPR ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| familiar_100 | 100 | deterministic | 0.9552 | 0.9552 | 0.9552 | 0/1109 | 100.0 | 0 | 100.0 |
| familiar_100 | 100 | LLM-assisted | 0.759 | 0.8662 | 0.8091 | 0/1109 | 100.0 | 0 | 100.0 |
| local_released_150 | 150 | deterministic | 0.8063 | 0.7852 | 0.7956 | 15/522 | 97.13 | 15 | 90.0 |
| local_released_150 | 150 | LLM-assisted | 0.7421 | 0.753 | 0.7475 | 5/522 | 99.04 | 5 | 96.67 |
| hf_easy | 300 | deterministic | 0.6961 | 0.7156 | 0.7057 | 132/1579 | 91.64 | 131 | 56.33 |
| hf_easy | 300 | LLM-assisted | 0.623 | 0.7156 | 0.6661 | 62/1579 | 96.07 | 62 | 79.33 |
| hf_medium | 150 | deterministic | 0.7743 | 0.7609 | 0.7676 | 126/1264 | 90.03 | 71 | 52.67 |
| hf_medium | 150 | LLM-assisted | 0.6926 | 0.756 | 0.7229 | 76/1264 | 93.99 | 28 | 81.33 |
| hf_human | 154 | deterministic | 0.8001 | 0.6725 | 0.7308 | 99/687 | 85.59 | 80 | 48.05 |
| hf_human | 154 | LLM-assisted | 0.6421 | 0.6696 | 0.6556 | 42/687 | 93.89 | 37 | 75.97 |
| hf_preference_base50 | 50 | deterministic | 0.6617 | 0.7333 | 0.6957 | 20/260 | 92.31 | 20 | 60.0 |
| hf_preference_base50 | 50 | LLM-assisted | 0.595 | 0.7333 | 0.657 | 7/260 | 97.31 | 7 | 86.0 |

| set | clauses recovered by LLM | clauses newly broken by LLM | queries R up | queries R down |
| --- | --- | --- | --- | --- |
| familiar_100 | 0 | 0 | 0 | 60 |
| local_released_150 | 10 | 0 | 14 | 28 |
| hf_easy | 70 | 0 | 0 | 0 |
| hf_medium | 50 | 0 | 0 | 3 |
| hf_human | 57 | 0 | 1 | 3 |
| hf_preference_base50 | 13 | 0 | 0 | 0 |