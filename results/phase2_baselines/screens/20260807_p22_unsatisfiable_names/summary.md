# Provably unsatisfiable required-POI-name constraints

`entity_resolution=False` · `drop_unsatisfiable_names=False` · static parse-only measurement, no solve.

| set | n | queries with >=1 unsatisfiable constraint | share | by field |
| --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | 7 | 7 % | {'required_attractions': 8, 'required_restaurants': 3} |
| local_released_150 | 150 | 24 | 16 % | {'required_restaurants': 12, 'required_hotels': 8, 'required_attractions': 7, 'position_presence': 1} |
