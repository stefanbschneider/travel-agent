from chinatravel.symbol_verification.commonsense_constraint import Is_time_correct


def test_time_checker_tolerates_malformed_itinerary_entries():
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


def test_time_checker_rejects_overlapping_activities():
    """Upstream PR #29 folded the strict intra-day ordering into the official checker."""
    symbolic_input = {"target_city": "B"}
    plan = {
        "itinerary": [
            {
                "activities": [
                    {"type": "attraction", "start_time": "09:00", "end_time": "11:00"},
                    {"type": "attraction", "start_time": "10:30", "end_time": "12:00"},
                ]
            }
        ]
    }

    table_statistics, error_info = Is_time_correct(symbolic_input, plan)
    assert table_statistics.loc[0, 'Does not follow Chronological Order'] == 1
    assert any("must not overlap" in message for message in error_info)
