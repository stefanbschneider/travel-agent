Mode `audit` · model `Qwen/Qwen3.6-27B` · backend `deepinfra` · thinking `False`

| set | n | arm | parse P | parse R | parse F1 | parse-gap clauses | C-LPR ceiling | queries w/ gap | FPR ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| familiar_100 | 100 | deterministic | 0.9552 | 0.9552 | 0.9552 | 0/1109 | 100.0 | 0 | 100.0 |
| familiar_100 | 100 | LLM-assisted | 0.9285 | 0.9303 | 0.9294 | 0/1109 | 100.0 | 0 | 100.0 |
| local_released_150 | 150 | deterministic | 0.8063 | 0.7852 | 0.7956 | 15/522 | 97.13 | 15 | 90.0 |
| local_released_150 | 150 | LLM-assisted | 0.8063 | 0.7852 | 0.7956 | 15/522 | 97.13 | 15 | 90.0 |
| hf_medium | 150 | deterministic | 0.7743 | 0.7609 | 0.7676 | 126/1264 | 90.03 | 71 | 52.67 |
| hf_medium | 150 | LLM-assisted | 0.7743 | 0.7609 | 0.7676 | 126/1264 | 90.03 | 71 | 52.67 |

| set | clauses recovered by LLM | clauses newly broken by LLM | queries R up | queries R down |
| --- | --- | --- | --- | --- |
| familiar_100 | 0 | 0 | 0 | 8 |
| local_released_150 | 0 | 0 | 0 | 0 |
| hf_medium | 0 | 0 | 0 | 0 |