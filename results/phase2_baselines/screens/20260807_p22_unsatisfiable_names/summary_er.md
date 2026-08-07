# Provably unsatisfiable required-POI-name constraints

`entity_resolution=True` · `drop_unsatisfiable_names=False` · static parse-only measurement, no solve.

| set | n | queries with >=1 unsatisfiable constraint | share | by field |
| --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | 0 | 0 % | {} |
| local_released_150 | 150 | 21 | 14 % | {'required_restaurants': 10, 'required_hotels': 6, 'required_attractions': 5, 'position_presence': 1} |
