Mode `extract_fill` · model `Qwen/Qwen3.6-27B` · backend `deepinfra` · thinking `False`

| set | n | arm | parse P | parse R | parse F1 | parse-gap clauses | C-LPR ceiling | queries w/ gap | FPR ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| local_released_150 | 150 | deterministic | 0.811 | 0.811 | 0.811 | 6/522 | 98.85 | 6 | 96.0 |
| local_released_150 | 150 | LLM-assisted | 0.7508 | 0.7658 | 0.7582 | 3/522 | 99.43 | 3 | 98.0 |

| set | clauses recovered by LLM | clauses newly broken by LLM | queries R up | queries R down |
| --- | --- | --- | --- | --- |
| local_released_150 | 3 | 0 | 9 | 30 |