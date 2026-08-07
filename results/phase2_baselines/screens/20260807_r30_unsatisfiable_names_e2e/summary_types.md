# Category values with no grounded candidate in the target city

`entity_resolution=False` · `drop_unsatisfiable_names=False` · static parse-only measurement, no solve.

| set | n | queries with >=1 unsatisfiable constraint | share | by field |
| --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | 0 | 0 % | {} |
| local_released_150 | 150 | 5 | 3 % | {'cuisine_preference': 3, 'required_hotel_any_types': 2, 'required_hotel_all_types': 1} |
| hf_easy | 300 | 7 | 2 % | {'required_hotel_all_types': 8} |
| hf_medium | 150 | 8 | 5 % | {'required_hotel_all_types': 7, 'required_attraction_types': 2} |
| hf_human | 154 | 2 | 1 % | {'required_hotel_all_types': 4} |
| hf_preference_base50 | 50 | 0 | 0 % | {} |
