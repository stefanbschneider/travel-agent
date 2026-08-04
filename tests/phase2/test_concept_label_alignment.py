"""The solver's concept literals must use the same canonical labels the sandbox exposes.

Upstream ``LAMDA-NeSy/ChinaTravel`` ``c89cfca`` moved concept normalization into the sandbox:
the English tools now expose one canonical label per concept, so a raw hard_logic_py literal
such as ``'Art Museum'`` no longer appears in any tool column.  The solver compares constraint
values against those columns with case-sensitive equality, so ``solver_constraint_variants``
has to canonicalize its literals the same way the verifier does.
"""

import unittest

from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants
from chinatravel.environment.concept_labels import ENGLISH_CONCEPT_VALUE_ALIASES
from chinatravel.environment.tools.accommodations.apis import Accommodations
from chinatravel.environment.tools.attractions.apis import Attractions
from chinatravel.environment.tools.restaurants.apis import Restaurants


def _hard_logic_type_set(set_name, accessor, activity_filter, literal):
    return (
        f"{set_name}=set()\n"
        "for activity in allactivities(plan):\n"
        f"  if {activity_filter}: {set_name}.add({accessor}(activity, target_city(plan)))\n"
        f"result=({{'{literal}'}} <= {set_name})"
    )


class OracleLiteralCanonicalizationTests(unittest.TestCase):
    def test_hard_logic_literals_are_canonicalized(self):
        query = {
            "hard_logic_py": [
                _hard_logic_type_set(
                    "attraction_type_set",
                    "attraction_type",
                    "activity_type(activity)=='attraction'",
                    "Art Museum",
                ),
                _hard_logic_type_set(
                    "restaurant_type_set",
                    "restaurant_type",
                    "activity_type(activity) in ['breakfast','lunch','dinner']",
                    "cafe",
                ),
                _hard_logic_type_set(
                    "accommodation_type_set",
                    "accommodation_type",
                    "activity_type(activity)=='accommodation'",
                    "Swimming pool",
                ),
            ]
        }

        (variant,) = solver_constraint_variants(query, {}, use_oracle=True)

        self.assertEqual(variant["required_attraction_types"], ["Art museum"])
        self.assertEqual(variant["cuisine_preference"], "coffee shop")
        self.assertEqual(variant["required_hotel_all_types"], ["Swimming Pool"])

    def test_parsed_literals_are_canonicalized_and_deduped(self):
        raw = {
            "required_attraction_types": ["Park", "park", "Historical Site"],
            "excluded_cuisine_types": ["hot pot"],
            "required_hotel_all_types": ["Serviced Apartment"],
            "hotel_type": "viral swimming pool",
            "hotel_amenity": "Chess and Card Room",
        }

        (variant,) = solver_constraint_variants({}, raw, use_oracle=False)

        self.assertEqual(
            variant["required_attraction_types"], ["park", "historical site"]
        )
        self.assertEqual(variant["excluded_cuisine_types"], ["Hot pot"])
        self.assertEqual(variant["required_hotel_all_types"], ["Hotel Apartment"])
        self.assertEqual(variant["required_hotel_any_types"], ["Instagrammable pool"])
        self.assertEqual(variant["hotel_amenity"], "Mahjong and Card Game Room")

    def test_non_concept_literals_are_left_alone(self):
        raw = {
            "required_attraction_types": ["Museum/Memorial Hall"],
            "required_attractions": ["Park Hyatt Shanghai"],
        }

        (variant,) = solver_constraint_variants({}, raw, use_oracle=False)

        self.assertEqual(variant["required_attraction_types"], ["Museum/Memorial Hall"])
        self.assertEqual(variant["required_attractions"], ["Park Hyatt Shanghai"])


class CanonicalLabelsMatchSandboxColumnsTests(unittest.TestCase):
    """A canonicalized literal must still be findable in the column the solver filters on."""

    def test_canonical_labels_are_the_only_labels_the_english_tools_expose(self):
        cases = (
            ("attraction", Attractions(lang="en"), "type"),
            ("restaurant", Restaurants(lang="en"), "cuisine"),
            ("accommodation", Accommodations(lang="en"), "featurehoteltype"),
        )

        for kind, tool, column in cases:
            aliases = ENGLISH_CONCEPT_VALUE_ALIASES[kind]
            exposed = set()
            for table in tool.data.values():
                exposed.update(table[column].dropna())
            with self.subTest(kind=kind):
                self.assertTrue(exposed.isdisjoint(aliases))
                # Every alias target the solver can now emit is a real column value.
                self.assertTrue(set(aliases.values()) <= exposed)


if __name__ == "__main__":
    unittest.main()
