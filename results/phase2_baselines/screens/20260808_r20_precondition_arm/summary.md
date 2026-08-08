Mode `extract_fill` · model `Qwen/Qwen3.6-27B` · backend `deepinfra` · thinking `False`

| set | n | arm | parse P | parse R | parse F1 | parse-gap clauses | C-LPR ceiling | queries w/ gap | FPR ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| local_released_150 | 150 | deterministic | 0.8222 | 0.8243 | 0.8233 | 5/522 | 99.04 | 5 | 96.67 |
| local_released_150 | 150 | LLM-assisted | 0.7913 | 0.8108 | 0.8009 | 2/522 | 99.62 | 2 | 98.67 |

| set | clauses recovered by LLM | clauses newly broken by LLM | queries R up | queries R down |
| --- | --- | --- | --- | --- |
| local_released_150 | 3 | 0 | 19 | 28 |