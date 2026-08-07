| set | n | clauses | arm | parse-gap | C-LPR ceiling | FPR ceiling | family F1 | value acc |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| familiar_100 | 30 | 325 | regex (shipped) | 0 (0 queries) | 100.0 | 100.0 | 0.9582 | 0.9582 |
| familiar_100 | 30 | 325 | LLM extract (shipped merge) | 0 (0 queries) | 100.0 | 100.0 | 0.7747 | 0.8311 |
| familiar_100 | 30 | 325 | regex + LLM fill-only | 0 (0 queries) | 100.0 | 100.0 | 0.8939 | 0.9582 |
| hf_medium | 30 | 240 | regex (shipped) | 17 (17 queries) | 92.92 | 43.33 | 0.8829 | 0.9917 |
| hf_medium | 30 | 240 | LLM extract (shipped merge) | 1 (1 queries) | 99.58 | 96.67 | 0.7985 | 0.8389 |
| hf_medium | 30 | 240 | regex + LLM fill-only | 1 (1 queries) | 99.58 | 96.67 | 0.8082 | 0.85 |
| hf_human | 30 | 124 | regex (shipped) | 20 (17 queries) | 83.87 | 43.33 | 0.7688 | 0.9611 |
| hf_human | 30 | 124 | LLM extract (shipped merge) | 10 (9 queries) | 91.94 | 70.0 | 0.7 | 0.8167 |
| hf_human | 30 | 124 | regex + LLM fill-only | 10 (9 queries) | 91.94 | 70.0 | 0.7 | 0.8167 |
| hf_easy | 30 | 150 | regex (shipped) | 0 (0 queries) | 100.0 | 100.0 | 0.9474 | 1.0 |
| hf_easy | 30 | 150 | LLM extract (shipped merge) | 0 (0 queries) | 100.0 | 100.0 | 0.9474 | 1.0 |
| hf_easy | 30 | 150 | regex + LLM fill-only | 0 (0 queries) | 100.0 | 100.0 | 0.9474 | 1.0 |

| set | arm | queries improved | queries regressed | families recovered | families broken | LLM errors |
| --- | --- | --- | --- | --- | --- | --- |
| familiar_100 | LLM extract | 0 | 0 | {'excluded_hotels': 2, 'required_restaurants': 2, 'required_attractions': 2, 'excluded_attractions': 1} | {'budgets': 15, 'excluded_inner_transport': 14, 'cuisine_preference': 2, 'excluded_cuisine_types': 1, 'excluded_hotels': 1} | 0 |
| familiar_100 | fill-only | 0 | 0 | {} | {} | 0 |
| hf_medium | LLM extract | 16 | 0 | {} | {'budgets': 1} | 0 |
| hf_medium | fill-only | 16 | 0 | {} | {} | 0 |
| hf_human | LLM extract | 10 | 0 | {} | {} | 0 |
| hf_human | fill-only | 10 | 0 | {} | {} | 0 |
| hf_easy | LLM extract | 0 | 0 | {} | {} | 0 |
| hf_easy | fill-only | 0 | 0 | {} | {} | 0 |
