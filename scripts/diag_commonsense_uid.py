#!/usr/bin/env python
"""READ-ONLY: run each commonsense check for a uid and print error_info."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from chinatravel.symbol_verification.commonsense_constraint import (
    Is_activity_grounded, Is_intercity_transport_correct, Is_attractions_correct,
    Is_hotels_correct, Is_restaurants_correct, Is_transport_correct, Is_time_correct,
    Is_space_correct, _infer_lang, _set_tool_lang,
)
from chinatravel.evaluation.utils import load_json_file

DATA_DIR = os.path.join(ROOT, "chinatravel", "data", "en")


def find_query(uid):
    for d in os.listdir(DATA_DIR):
        p = os.path.join(DATA_DIR, d, uid + ".json")
        if os.path.exists(p):
            return p
    return None


def main():
    uid = sys.argv[1]
    method = sys.argv[2] if len(sys.argv) > 2 else "best"
    q = load_json_file(find_query(uid))
    plan = load_json_file(os.path.join(ROOT, "results", method, uid + ".json"))
    _set_tool_lang("en")
    funcs = [Is_activity_grounded, Is_intercity_transport_correct, Is_attractions_correct,
             Is_hotels_correct, Is_restaurants_correct, Is_transport_correct, Is_time_correct,
             Is_space_correct]
    for func in funcs:
        table, info = func(q, plan, verbose=False)
        s = table.loc[0].sum()
        if s != 0:
            print("### %s FAILED" % func.__name__)
            for line in info:
                print("   ", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
