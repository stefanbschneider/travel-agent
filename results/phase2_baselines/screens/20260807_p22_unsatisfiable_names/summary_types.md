# Category values with no grounded candidate in the target city

`entity_resolution=False` · `drop_unsatisfiable_names=False` · static parse-only measurement, no solve.

| set | n | queries with >=1 unsatisfiable constraint | share | by field |
| --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | 0 | 0 % | {} |
| local_released_150 | 150 | 5 | 3 % | {'cuisine_preference': 3, 'required_hotel_any_types': 2, 'required_hotel_all_types': 1} |
