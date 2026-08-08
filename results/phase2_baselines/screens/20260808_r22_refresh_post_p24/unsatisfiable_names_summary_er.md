# Provably unsatisfiable required-POI-name constraints

`entity_resolution=True` · `drop_unsatisfiable_names=False` · static parse-only measurement, no solve.

| set | n | queries with >=1 unsatisfiable constraint | share | by field |
| --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | 0 | 0 % | {} |
| local_released_150 | 150 | 17 | 11 % | {'required_restaurants': 10, 'required_hotels': 5, 'required_attractions': 2, 'position_presence': 1} |
| hf_easy | 300 | 33 | 11 % | {'required_attractions': 31, 'required_hotels': 12, 'required_restaurants': 4} |
| hf_medium | 150 | 4 | 3 % | {'required_attractions': 2, 'required_restaurants': 1, 'required_hotels': 1} |
| hf_human | 154 | 13 | 8 % | {'required_attractions': 10, 'required_hotels': 7} |
| hf_preference_base50 | 50 | 6 | 12 % | {'required_attractions': 6, 'required_hotels': 2, 'required_restaurants': 1} |
