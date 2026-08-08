# zh->en oracle-literal map, and the structural scoring cap it lifts

Map entries: **11957** (derived from 11934 row-parallel database rows, 1:1 after `normalize_concept_value` — the builder raises otherwise).

| HF split | n | oracle clauses | unsatisfiable under `en` | of those, mappable | queries blocked | FPR ceiling | C-LPR ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- |
| easy | 300 | 1579 | 180 | 135 | 180 | **40.0** | 88.6 |
| medium | 150 | 1264 | 126 | 125 | 92 | **38.67** | 90.03 |
| human | 154 | 687 | 117 | 105 | 91 | **40.91** | 82.97 |
| preference_base50 | 50 | 260 | 27 | 19 | 27 | **46.0** | 89.62 |

`FPR ceiling` is the highest FPR any solver can score on that split under `--lang en`, however perfect. Read every free-prose FPR measurement against it, not against 100.
