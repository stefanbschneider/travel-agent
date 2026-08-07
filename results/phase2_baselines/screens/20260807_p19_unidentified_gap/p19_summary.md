Held-out C-LPR (published): **55.2**. Dense threshold: `>= 10` oracle clauses.

## 1. Density

| set | n | clauses mean | p50 | p75 | p90 | max | % dense | overall ceiling | dense-tail ceiling | sparse-rest ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| familiar_100_control | 100 | 11.09 | 11 | 12 | 13 | 13 | 88.0% | 100.0 | 100.0 (n=88) | 100.0 |
| local_released_150 | 150 | 3.48 | 5 | 6 | 6 | 6 | 0.0% | 98.85 | None (n=0) | 98.85 |
| hf_easy | 300 | 5.26 | 5 | 5 | 6 | 7 | 0.0% | 91.96 | None (n=0) | 91.96 |
| hf_medium | 150 | 8.43 | 8 | 9 | 10 | 12 | 18.0% | 90.03 | 74.91 (n=27) | 94.39 |
| hf_human | 154 | 4.46 | 4 | 5 | 6 | 9 | 0.0% | 85.59 | None (n=0) | 85.59 |
| hf_preference_base50 | 50 | 5.2 | 5 | 5 | 6 | 7 | 0.0% | 92.69 | None (n=0) | 92.69 |

## 2. Families never produced on any set

None -- every oracle family is produced (matched or wrong_value) on at least one set.

## 3. Families ranked by instances x miss_rate (top 20)

| family | oracle instances | missing | miss_rate | score |
| --- | --- | --- | --- | --- |
| required_attraction_types | 160 | 102 | 0.6375 | 102.0 |
| cuisine_preference | 127 | 100 | 0.7874 | 100.0 |
| required_attractions | 133 | 46 | 0.3459 | 46.0 |
| required_hotel_all_types | 82 | 38 | 0.4634 | 38.0 |
| required_restaurants | 63 | 32 | 0.5079 | 32.0 |
| budgets | 421 | 21 | 0.0499 | 21.01 |
| required_hotels | 63 | 19 | 0.3016 | 19.0 |
| room_type | 184 | 15 | 0.0815 | 15.0 |
| position_presence | 105 | 4 | 0.0381 | 4.0 |
| required_hotel_any_types | 5 | 4 | 0.8 | 4.0 |
| activity_time_windows | 102 | 3 | 0.0294 | 3.0 |
| excluded_inner_transport | 81 | 3 | 0.037 | 3.0 |
| excluded_attraction_types | 54 | 2 | 0.037 | 2.0 |
| excluded_attractions | 57 | 1 | 0.0175 | 1.0 |
| excluded_cuisine_types | 59 | 1 | 0.0169 | 1.0 |
| intercity_mode | 17 | 1 | 0.0588 | 1.0 |
| excluded_hotels | 56 | 0 | 0.0 | 0.0 |
| excluded_restaurants | 62 | 0 | 0.0 | 0.0 |
| taxi_cars_equals | 744 | 0 | 0.0 | 0.0 |
| free_attractions_only | 7 | 0 | 0.0 | 0.0 |