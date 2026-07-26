from chinatravel.symbol_verification.commonsense_constraint import (
    Is_time_correct,
    Is_time_correct_strict,
)


def test_time_checkers_tolerate_malformed_itinerary_entries():
    symbolic_input = {"target_city": "B"}
    plan = {
        "itinerary": [
            123,
            {"activities": "not-a-list"},
        ]
    }

    table_statistics, error_info = Is_time_correct(symbolic_input, plan)
    assert table_statistics.loc[0, 'Invalid duration information of each activity'] == 1
    assert error_info

    strict_statistics, strict_error_info = Is_time_correct_strict(symbolic_input, plan)
    assert strict_statistics.loc[0, 'Invalid duration information of each activity'] == 1
    assert strict_error_info