import sys
import os
import time
import math
import json

sys.path.append("./../../../")
project_root_path = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

if project_root_path not in sys.path:
    sys.path.insert(0, project_root_path)


from agent.base import BaseAgent


def add_minutes(time_str, minutes):
    """Add minutes to a HH:MM time string, clamping at 23:59."""
    h, m = map(int, time_str.split(":"))
    total = h * 60 + m + minutes
    total = min(total, 23 * 60 + 59)
    return f"{total // 60:02d}:{total % 60:02d}"


def time_to_minutes(t):
    """Convert HH:MM string to total minutes."""
    h, m = map(int, t.split(":"))
    return h * 60 + m


def time_before(t1, t2):
    """Return True if t1 <= t2 (both HH:MM strings)."""
    return time_to_minutes(t1) <= time_to_minutes(t2)


def is_open_during(attr, start_time, end_time):
    """Check if attraction is open for the entire visit period [start_time, end_time]."""
    opentime = str(attr["opentime"])
    endtime = str(attr["endtime"])
    ot_min = time_to_minutes(opentime)
    et_min = time_to_minutes(endtime)
    # Handle wrap-around
    if et_min <= ot_min:
        et_min += 24 * 60
    st_min = time_to_minutes(start_time)
    ed_min = time_to_minutes(end_time)
    return ot_min <= st_min and ed_min <= et_min


class TPCAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(name="TPC", **kwargs)
        self.parsed_constraints = self._load_parsed_constraints()
        self._transport_constraints = {}

    def _load_parsed_constraints(self):
        constraints_path = os.path.join(project_root_path, "data", "en", "parsed_constraints.json")
        try:
            with open(constraints_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _norm_text(self, value):
        return str(value).strip().lower() if value is not None else ""

    def _match_constraint_text(self, candidate, constraint):
        c = self._norm_text(candidate)
        q = self._norm_text(constraint)
        if not c or not q:
            return False
        return c == q or q in c or c in q

    def _collect_constraints(self, query):
        uid = str(query.get("uid", ""))
        raw = self.parsed_constraints.get(uid, {})
        if not isinstance(raw, dict):
            return {}

        constraints = {
            k: v
            for k, v in raw.items()
            if k not in ["groups", "disjunctive"]
        }
        groups = raw.get("groups", [])
        if raw.get("disjunctive") and isinstance(groups, list) and len(groups) > 0:
            # For OR constraints, choose the first branch as primary guidance.
            # We keep non-disjunctive constraints active and avoid enforcing all groups.
            first_group = groups[0]
            if isinstance(first_group, dict):
                constraints.update(first_group)
        return constraints

    def _room_type_to_numbed(self, room_type):
        if room_type is None:
            return None
        if isinstance(room_type, (int, float)):
            try:
                iv = int(room_type)
                if iv in [1, 2]:
                    return iv
            except Exception:
                return None
        t = self._norm_text(room_type)
        if any(k in t for k in ["single", "1", "one"]):
            return 1
        if any(k in t for k in ["double", "twin", "2", "two"]):
            return 2
        return None

    def run(self, query, prob_idx=None, oralce_translation=False):
        self.reset_clock()

        try:
            plan = self._build_plan(query)
        except Exception:
            import traceback
            traceback.print_exc()
            plan = {
                "people_number": query.get("people_number", 1),
                "start_city": query.get("start_city", ""),
                "target_city": query.get("target_city", ""),
                "itinerary": [],
            }

        plan["elapsed_time(sec)"] = time.time() - self.start_clock
        return True, plan

    def _build_plan(self, query):
        """Build a valid itinerary with proper transport, timing, and costs."""
        people = query["people_number"]
        start_city = query["start_city"]
        target_city = query["target_city"]
        days = query["days"]
        constraints = self._collect_constraints(query)
        self._transport_constraints = {
            "excluded_inner_transport": constraints.get("excluded_inner_transport", []),
            "conditional_transport": constraints.get("conditional_transport", None),
        }

        env = self.env
        if env is None:
            return {
                "people_number": people,
                "start_city": start_city,
                "target_city": target_city,
                "itinerary": [],
            }

        # --- Get intercity transport (outbound + return) ---
        intercity_mode = constraints.get("intercity_mode", None)
        outbound_pref = None
        return_pref = None
        if isinstance(intercity_mode, dict):
            outbound_pref = intercity_mode.get("outbound", None)
            return_pref = intercity_mode.get("return", None)
        elif isinstance(intercity_mode, str):
            outbound_pref = intercity_mode
            return_pref = intercity_mode

        outbound = self._get_intercity(env, start_city, target_city, "07:00", outbound_pref)
        return_transport = self._get_intercity(env, target_city, start_city, "17:00", return_pref)
        # If no return at 17:00, try earlier
        if return_transport is None:
            return_transport = self._get_intercity(env, target_city, start_city, "14:00", return_pref)
        if return_transport is None:
            return_transport = self._get_intercity(env, target_city, start_city, "00:00", return_pref)

        # --- Get one accommodation near the arrival/departure point ---
        arrival_pos = outbound["To"] if outbound else None
        required_hotels = constraints.get("required_hotels", []) or []
        excluded_hotels = constraints.get("excluded_hotels", []) or []
        room_numbed = self._room_type_to_numbed(constraints.get("room_type", None))
        hotel_type = constraints.get("hotel_type", None)
        hotel_amenity = constraints.get("hotel_amenity", None)
        hotel_nearby = constraints.get("hotel_nearby", None)

        accom_df = env.accommodations.select(target_city, "name", lambda x: True)

        def _hotel_ok(h):
            name = str(h["name"])
            if required_hotels and not any(self._match_constraint_text(name, n) for n in required_hotels):
                return False
            if excluded_hotels and any(self._match_constraint_text(name, n) for n in excluded_hotels):
                return False
            if room_numbed is not None:
                try:
                    if int(h["numbed"]) != room_numbed:
                        return False
                except Exception:
                    return False
            if hotel_type:
                if not self._match_constraint_text(h.get("featurehoteltype", ""), hotel_type):
                    return False
            if hotel_amenity:
                if not self._match_constraint_text(h.get("featurehoteltype", ""), hotel_amenity):
                    return False
            return True

        hotel = None
        nearby_df = None
        if isinstance(hotel_nearby, dict):
            ref = hotel_nearby.get("reference", None)
            dist_km = hotel_nearby.get("distance_km", 5)
            if ref:
                try:
                    nearby_df = env.accommodations.nearby(target_city, ref, topk=20, dist=dist_km)
                except Exception:
                    nearby_df = None

        if nearby_df is not None and not isinstance(nearby_df, str) and len(nearby_df) > 0:
            for i in range(len(nearby_df)):
                h = nearby_df.iloc[i]
                if _hotel_ok(h):
                    hotel = h
                    break

        if arrival_pos:
            try:
                nearby_hotels = env.accommodations.nearby(target_city, arrival_pos, topk=5, dist=20)
                if not isinstance(nearby_hotels, str) and len(nearby_hotels) > 0:
                    for i in range(len(nearby_hotels)):
                        h = nearby_hotels.iloc[i]
                        if _hotel_ok(h):
                            hotel = h
                            break
            except Exception:
                pass
        if hotel is None:
            for i in range(len(accom_df)):
                h = accom_df.iloc[i]
                if _hotel_ok(h):
                    hotel = h
                    break
        if hotel is None:
            hotel = accom_df.iloc[0]
        hotel_name = str(hotel["name"])
        rooms_needed = math.ceil(people / int(hotel["numbed"]))

        # --- Get attractions that are open during reasonable visit hours ---
        required_attractions = constraints.get("required_attractions", []) or []
        required_attraction_types = constraints.get("required_attraction_types", []) or []
        excluded_attractions = constraints.get("excluded_attractions", []) or []
        excluded_attraction_types = constraints.get("excluded_attraction_types", []) or []
        free_attractions_only = bool(constraints.get("free_attractions_only", False))

        attr_df = env.attractions.select(target_city, "name", lambda x: True)

        prioritized_required = []
        optional_pool = []
        seen_attr = set()
        for i in range(len(attr_df)):
            a = attr_df.iloc[i]
            name = str(a["name"])
            attr_type = str(a.get("type", ""))

            if excluded_attractions and any(self._match_constraint_text(name, ex) for ex in excluded_attractions):
                continue
            if excluded_attraction_types and any(self._match_constraint_text(attr_type, ex) for ex in excluded_attraction_types):
                continue
            if free_attractions_only:
                try:
                    if float(a["price"]) > 0:
                        continue
                except Exception:
                    continue

            required_by_name = required_attractions and any(
                self._match_constraint_text(name, req)
                for req in required_attractions
            )
            required_by_type = required_attraction_types and any(
                self._match_constraint_text(attr_type, req_t)
                for req_t in required_attraction_types
            )

            name_key = self._norm_text(name)
            if required_by_name or required_by_type:
                if name_key not in seen_attr:
                    prioritized_required.append(a)
                    seen_attr.add(name_key)
            else:
                if name_key not in seen_attr:
                    optional_pool.append(a)
                    seen_attr.add(name_key)

        candidate_attrs = prioritized_required + optional_pool

        # Filter to attractions open during daytime visit windows (09:00-17:00)
        good_attrs = []
        for a in candidate_attrs:
            opentime = str(a["opentime"])
            endtime = str(a["endtime"])
            ot_min = time_to_minutes(opentime)
            et_min = time_to_minutes(endtime)
            # Handle wrap-around (e.g., 00:00-24:00 = always open)
            if et_min <= ot_min:
                et_min += 24 * 60
            # Must be open by 09:30 and stay open until at least 12:00
            # so we can fit a 90-min visit in the morning or afternoon
            if ot_min <= 570 and et_min >= 720:  # 09:30=570, 12:00=720
                good_attrs.append(a)
            if len(good_attrs) >= days * 4:
                break
        # Fallback: just take the first ones
        if len(good_attrs) < days * 2:
            base_pool = candidate_attrs if len(candidate_attrs) > 0 else [attr_df.iloc[i] for i in range(len(attr_df))]
            good_attrs = list(base_pool[: min(len(base_pool), days * 4)])

        # --- Get restaurants open during meal times ---
        required_restaurants = constraints.get("required_restaurants", []) or []
        excluded_restaurants = constraints.get("excluded_restaurants", []) or []
        cuisine_preference = constraints.get("cuisine_preference", None)
        excluded_cuisine_types = constraints.get("excluded_cuisine_types", []) or []

        rest_df = env.restaurants.select(target_city, "name", lambda x: True)
        lunch_restaurants = []
        dinner_restaurants = []
        required_rest_pool = []
        optional_rest_pool = []
        seen_rest = set()
        for i in range(len(rest_df)):
            r = rest_df.iloc[i]
            name = str(r["name"])
            cuisine = str(r.get("cuisine", ""))

            if excluded_restaurants and any(self._match_constraint_text(name, ex) for ex in excluded_restaurants):
                continue
            if excluded_cuisine_types and any(self._match_constraint_text(cuisine, ex) for ex in excluded_cuisine_types):
                continue

            is_required = required_restaurants and any(
                self._match_constraint_text(name, req)
                for req in required_restaurants
            )
            cuisine_match = cuisine_preference and self._match_constraint_text(cuisine, cuisine_preference)

            key = self._norm_text(name)
            if key in seen_rest:
                continue
            seen_rest.add(key)
            if is_required or cuisine_match:
                required_rest_pool.append(r)
            else:
                optional_rest_pool.append(r)

        candidate_restaurants = required_rest_pool + optional_rest_pool

        used_rest_names = set()
        for r in candidate_restaurants:
            name = str(r["name"])
            opentime = str(r["opentime"])
            endtime = str(r["endtime"])
            ot_min = time_to_minutes(opentime)
            # Handle wrap-around (endtime < opentime means open past midnight)
            if endtime < opentime:
                et_min = time_to_minutes(endtime) + 24 * 60
            else:
                et_min = time_to_minutes(endtime)
            # Check if open for lunch (11:00-14:00)
            if name not in used_rest_names and ot_min <= 660 and et_min >= 840:  # 11:00=660, 14:00=840
                lunch_restaurants.append(r)
                used_rest_names.add(name)
            # Check if open for dinner (17:00-20:00)
            elif name not in used_rest_names and ot_min <= 1020 and et_min >= 1200:  # 17:00=1020, 20:00=1200
                dinner_restaurants.append(r)
                used_rest_names.add(name)
            if len(lunch_restaurants) >= days and len(dinner_restaurants) >= days:
                break

        # --- Build day-by-day itinerary ---
        itinerary = []
        attr_idx = 0
        lunch_idx = 0
        dinner_idx = 0
        current_pos = None  # Track current position for transport

        for day_num in range(1, days + 1):
            activities = []

            if day_num == 1:
                # === DAY 1: Arrive + activities + hotel ===
                if outbound is not None:
                    act = self._make_intercity_activity(outbound, people)
                    activities.append(act)
                    current_time = outbound["EndTime"]
                    current_pos = outbound["To"]
                else:
                    current_time = "09:00"
                    current_pos = hotel_name

                # Lunch (if time allows, start between 11:00-13:00)
                if time_before(current_time, "13:00") and lunch_idx < len(lunch_restaurants):
                    restaurant = lunch_restaurants[lunch_idx]
                    lunch_idx += 1
                    lunch_start = max(current_time, "11:00")
                    # Add transport to restaurant
                    rest_name = str(restaurant["name"])
                    transports, travel_end = self._get_transport(
                        env, target_city, current_pos, rest_name, current_time, people)
                    if transports is not None:
                        lunch_start = max(travel_end or current_time, "11:00")
                    else:
                        transports = []
                    lunch_end = add_minutes(lunch_start, 60)
                    if time_before(lunch_end, "14:00"):
                        activities.append(self._make_meal_activity(
                            "lunch", restaurant, people, lunch_start, lunch_end, transports))
                        current_time = lunch_end
                        current_pos = rest_name

                # Afternoon attraction
                if time_before(current_time, "16:30") and attr_idx < len(good_attrs):
                    # Estimate visit time and check open hours
                    est_start = add_minutes(current_time, 20)  # ~20 min travel
                    est_end = add_minutes(est_start, 90)
                    attr, attr_idx = self._pick_attraction(good_attrs, attr_idx, est_start, est_end)
                    if attr is not None:
                        attr_name = str(attr["name"])
                        transports, travel_end = self._get_transport(
                            env, target_city, current_pos, attr_name, current_time, people)
                        if transports is not None:
                            attr_start = travel_end
                        else:
                            transports = []
                            attr_start = current_time
                        attr_end = add_minutes(attr_start, 90)
                        if is_open_during(attr, attr_start, attr_end):
                            activities.append(self._make_attraction_activity(
                                attr, people, attr_start, attr_end, transports))
                            current_time = attr_end
                            current_pos = attr_name

                # Dinner (start between 17:00-19:00)
                if time_before(current_time, "19:00") and dinner_idx < len(dinner_restaurants):
                    restaurant = dinner_restaurants[dinner_idx]
                    dinner_idx += 1
                    rest_name = str(restaurant["name"])
                    transports, travel_end = self._get_transport(
                        env, target_city, current_pos, rest_name, current_time, people)
                    if transports is not None:
                        dinner_start = max(travel_end or current_time, "17:00")
                    else:
                        transports = []
                        dinner_start = max(current_time, "17:00")
                    dinner_end = add_minutes(dinner_start, 60)
                    if time_before(dinner_end, "20:00"):
                        activities.append(self._make_meal_activity(
                            "dinner", restaurant, people, dinner_start, dinner_end, transports))
                        current_time = dinner_end
                        current_pos = rest_name

                # Accommodation
                transports, travel_end = self._get_transport(
                    env, target_city, current_pos, hotel_name, current_time, people)
                if transports is None or current_pos == hotel_name:
                    transports = []
                    travel_end = current_time
                activities.append(self._make_accommodation_activity(
                    hotel, rooms_needed, travel_end, transports))
                current_pos = hotel_name

            elif day_num == days:
                # === LAST DAY: breakfast + maybe attraction + return transport ===
                # First, figure out the return transport based on hotel position
                # Compute transport from hotel to departure point to know earliest feasible departure
                if return_transport is not None:
                    departure_pos = return_transport["From"]
                    hotel_to_station, hotel_to_station_end = self._get_transport(
                        env, target_city, hotel_name, departure_pos, "08:30", people)
                    if hotel_to_station is None:
                        hotel_to_station_end = "08:30"
                    # If we can't make it to the original return transport, find a later one
                    if time_to_minutes(hotel_to_station_end) > time_to_minutes(return_transport["BeginTime"]):
                        later = self._get_intercity(env, target_city, start_city, hotel_to_station_end, return_pref)
                        if later is not None:
                            return_transport = later
                            departure_pos = later["From"]
                            # Re-compute transport if departure pos changed
                            if later["From"] != (hotel_to_station[-1]["end"] if hotel_to_station else hotel_name):
                                hotel_to_station, hotel_to_station_end = self._get_transport(
                                    env, target_city, hotel_name, departure_pos, "08:30", people)
                                if hotel_to_station is None:
                                    hotel_to_station_end = "08:30"

                # Breakfast at hotel (free)
                activities.append(self._make_hotel_breakfast(
                    hotel_name, "07:30", "08:30"))
                current_time = "08:30"
                current_pos = hotel_name

                # Morning attraction if time before return
                if attr_idx < len(good_attrs) and return_transport is not None:
                    departure_time = return_transport["BeginTime"]
                    departure_pos = return_transport["From"]
                    # Need time: transport to attr + 90min + transport to departure point
                    if time_to_minutes(departure_time) >= time_to_minutes(current_time) + 150:
                        est_start = add_minutes(current_time, 20)
                        est_end = add_minutes(est_start, 90)
                        attr, attr_idx = self._pick_attraction(good_attrs, attr_idx, est_start, est_end)
                        if attr is not None:
                            attr_name = str(attr["name"])
                            transports, travel_end = self._get_transport(
                                env, target_city, current_pos, attr_name, current_time, people)
                            if transports is not None:
                                attr_start = travel_end
                            else:
                                transports = []
                                attr_start = current_time
                            attr_end = add_minutes(attr_start, 90)
                            # Check we can get back to departure in time
                            _, return_arrival = self._get_transport(
                                env, target_city, attr_name, departure_pos, attr_end, people)
                            can_return = (return_arrival is not None and
                                         time_to_minutes(return_arrival) <= time_to_minutes(departure_time))
                            if can_return and is_open_during(attr, attr_start, attr_end):
                                activities.append(self._make_attraction_activity(
                                    attr, people, attr_start, attr_end, transports))
                                current_time = attr_end
                                current_pos = attr_name

                # Lunch before departure if time allows
                if return_transport is not None and lunch_idx < len(lunch_restaurants):
                    departure_time = return_transport["BeginTime"]
                    departure_pos = return_transport["From"]
                    if time_to_minutes(departure_time) >= time_to_minutes("11:00") + 90:
                        if time_before(current_time, "13:00"):
                            restaurant = lunch_restaurants[lunch_idx]
                            rest_name = str(restaurant["name"])
                            transports, travel_end = self._get_transport(
                                env, target_city, current_pos, rest_name, current_time, people)
                            if transports is not None:
                                lunch_start = max(travel_end or current_time, "11:00")
                            else:
                                transports = []
                                lunch_start = max(current_time, "11:00")
                            lunch_end = add_minutes(lunch_start, 60)
                            # Check we can still reach departure point after lunch
                            _, return_arrival = self._get_transport(
                                env, target_city, rest_name, departure_pos, lunch_end, people)
                            can_return = (return_arrival is not None and
                                         time_to_minutes(return_arrival) <= time_to_minutes(departure_time))
                            if time_before(lunch_end, "14:00") and can_return:
                                lunch_idx += 1
                                activities.append(self._make_meal_activity(
                                    "lunch", restaurant, people, lunch_start, lunch_end, transports))
                                current_time = lunch_end
                                current_pos = rest_name

                # Return intercity transport
                if return_transport is not None:
                    departure_pos = return_transport["From"]
                    transports, travel_end = self._get_transport(
                        env, target_city, current_pos, departure_pos, current_time, people)
                    if transports is None or current_pos == departure_pos:
                        transports = []
                        travel_end = current_time
                    # If transport to station arrives after departure, find later transport
                    if time_to_minutes(travel_end) > time_to_minutes(return_transport["BeginTime"]):
                        later = self._get_intercity(env, target_city, start_city, travel_end, return_pref)
                        if later is not None:
                            return_transport = later
                            if later["From"] != departure_pos:
                                departure_pos = later["From"]
                                transports, travel_end = self._get_transport(
                                    env, target_city, current_pos, departure_pos, current_time, people)
                                if transports is None or current_pos == departure_pos:
                                    transports = []
                    act = self._make_intercity_activity(return_transport, people, transports)
                    activities.append(act)

            else:
                # === MIDDLE DAYS: breakfast + attractions + meals + hotel ===
                # Breakfast at hotel (free)
                activities.append(self._make_hotel_breakfast(
                    hotel_name, "07:30", "08:30"))
                current_time = "08:30"
                current_pos = hotel_name

                # Morning attraction
                if attr_idx < len(good_attrs):
                    est_start = add_minutes(current_time, 20)
                    est_end = add_minutes(est_start, 90)
                    attr, attr_idx = self._pick_attraction(good_attrs, attr_idx, est_start, est_end)
                    if attr is not None:
                        attr_name = str(attr["name"])
                        transports, travel_end = self._get_transport(
                            env, target_city, current_pos, attr_name, current_time, people)
                        if transports is not None:
                            attr_start = travel_end
                        else:
                            transports = []
                            attr_start = current_time
                        attr_end = add_minutes(attr_start, 90)
                        if is_open_during(attr, attr_start, attr_end):
                            activities.append(self._make_attraction_activity(
                                attr, people, attr_start, attr_end, transports))
                            current_time = attr_end
                            current_pos = attr_name

                # Lunch
                if lunch_idx < len(lunch_restaurants) and time_before(current_time, "13:00"):
                    restaurant = lunch_restaurants[lunch_idx]
                    rest_name = str(restaurant["name"])
                    transports, travel_end = self._get_transport(
                        env, target_city, current_pos, rest_name, current_time, people)
                    if transports is not None:
                        lunch_start = max(travel_end or current_time, "11:00")
                    else:
                        transports = []
                        lunch_start = max(current_time, "11:00")
                    lunch_end = add_minutes(lunch_start, 60)
                    if time_before(lunch_end, "14:00"):
                        lunch_idx += 1
                        activities.append(self._make_meal_activity(
                            "lunch", restaurant, people, lunch_start, lunch_end, transports))
                        current_time = lunch_end
                        current_pos = rest_name

                # Afternoon attraction
                if attr_idx < len(good_attrs) and time_before(current_time, "16:00"):
                    est_start = add_minutes(current_time, 20)
                    est_end = add_minutes(est_start, 90)
                    attr, attr_idx = self._pick_attraction(good_attrs, attr_idx, est_start, est_end)
                    if attr is not None:
                        attr_name = str(attr["name"])
                        transports, travel_end = self._get_transport(
                            env, target_city, current_pos, attr_name, current_time, people)
                        if transports is not None:
                            attr_start = travel_end
                        else:
                            transports = []
                            attr_start = current_time
                        attr_end = add_minutes(attr_start, 90)
                        if is_open_during(attr, attr_start, attr_end):
                            activities.append(self._make_attraction_activity(
                                attr, people, attr_start, attr_end, transports))
                            current_time = attr_end
                            current_pos = attr_name

                # Dinner
                if dinner_idx < len(dinner_restaurants) and time_before(current_time, "19:00"):
                    restaurant = dinner_restaurants[dinner_idx]
                    rest_name = str(restaurant["name"])
                    transports, travel_end = self._get_transport(
                        env, target_city, current_pos, rest_name, current_time, people)
                    if transports is not None:
                        dinner_start = max(travel_end or current_time, "17:00")
                    else:
                        transports = []
                        dinner_start = max(current_time, "17:00")
                    dinner_end = add_minutes(dinner_start, 60)
                    if time_before(dinner_end, "20:00"):
                        dinner_idx += 1
                        activities.append(self._make_meal_activity(
                            "dinner", restaurant, people, dinner_start, dinner_end, transports))
                        current_time = dinner_end
                        current_pos = rest_name

                # Accommodation
                transports, travel_end = self._get_transport(
                    env, target_city, current_pos, hotel_name, current_time, people)
                if transports is None or current_pos == hotel_name:
                    transports = []
                    travel_end = current_time
                activities.append(self._make_accommodation_activity(
                    hotel, rooms_needed, travel_end, transports))
                current_pos = hotel_name

            itinerary.append({"day": day_num, "activities": activities})

        return {
            "people_number": people,
            "start_city": start_city,
            "target_city": target_city,
            "itinerary": itinerary,
        }

    def _get_intercity(self, env, from_city, to_city, earliest, preferred_mode=None):
        """Get first available flight, falling back to train."""
        preferred = self._norm_text(preferred_mode)
        transport_order = ["airplane", "train"]
        if preferred in ["airplane", "flight", "plane"]:
            transport_order = ["airplane", "train"]
        elif preferred in ["train", "rail"]:
            transport_order = ["train", "airplane"]

        for transport_type in transport_order:
            try:
                df = env.intercitytransport.select(from_city, to_city, transport_type, earliest)
                if df is not None and len(df) > 0:
                    return df.iloc[0].to_dict()
            except Exception:
                pass
        return None

    def _pick_attraction(self, good_attrs, attr_idx, start_time, end_time):
        """Pick the next attraction that is open during [start_time, end_time].
        Returns (attr, new_attr_idx) or (None, attr_idx) if none found."""
        idx = attr_idx
        while idx < len(good_attrs):
            attr = good_attrs[idx]
            if is_open_during(attr, start_time, end_time):
                return attr, idx + 1
            idx += 1
        return None, attr_idx

    def _get_transport(self, env, city, from_pos, to_pos, start_time, people):
        """Get taxi transport between two positions. Returns (transports_list, arrival_time) or (None, None)."""
        if from_pos == to_pos:
            return [], start_time
        excluded = set(
            self._norm_text(m)
            for m in (self._transport_constraints.get("excluded_inner_transport", []) or [])
        )
        conditional = self._transport_constraints.get("conditional_transport", None)
        mode_order = ["taxi", "metro", "walk"]

        if isinstance(conditional, dict):
            preferred = self._norm_text(conditional.get("mode", ""))
            if preferred in ["taxi", "metro", "walk"]:
                mode_order = [preferred] + [m for m in mode_order if m != preferred]

        mode_order = [m for m in mode_order if self._norm_text(m) not in excluded]
        if len(mode_order) == 0:
            mode_order = ["taxi"]

        try:
            for mode in mode_order:
                result = env.transportation.goto(city, from_pos, to_pos, start_time, mode)
                if isinstance(result, list) and len(result) > 0:
                    transports = []
                    for seg in result:
                        t = {
                            "start": seg["start"],
                            "end": seg["end"],
                            "mode": seg["mode"],
                            "start_time": seg["start_time"],
                            "end_time": seg["end_time"],
                            "distance": seg["distance"],
                        }
                        if seg["mode"] == "taxi":
                            t["price"] = seg["cost"]
                            t["cost"] = seg["cost"] * 1  # 1 car
                            t["cars"] = 1
                        elif seg["mode"] == "metro":
                            t["price"] = seg["cost"]
                            t["cost"] = seg["cost"] * people
                            t["tickets"] = people
                        else:  # walk
                            t["price"] = 0
                            t["cost"] = 0
                        transports.append(t)
                    arrival_time = transports[-1]["end_time"]
                    return transports, arrival_time
        except Exception:
            pass
        return None, None

    def _make_intercity_activity(self, transport, people, transports=None):
        """Create an intercity transport activity dict."""
        if transports is None:
            transports = []
        activity = {
            "type": "airplane" if "FlightID" in transport else "train",
            "start_time": transport["BeginTime"],
            "end_time": transport["EndTime"],
            "start": transport["From"],
            "end": transport["To"],
            "price": transport["Cost"],
            "cost": transport["Cost"] * people,
            "tickets": people,
            "transports": transports,
        }
        if "FlightID" in transport:
            activity["FlightID"] = transport["FlightID"]
        else:
            activity["TrainID"] = transport["TrainID"]
        return activity

    def _make_attraction_activity(self, attr, people, start_time, end_time, transports=None):
        """Create an attraction activity dict."""
        if transports is None:
            transports = []
        return {
            "type": "attraction",
            "position": str(attr["name"]),
            "start_time": start_time,
            "end_time": end_time,
            "price": float(attr["price"]),
            "cost": float(attr["price"]) * people,
            "tickets": people,
            "transports": transports,
        }

    def _make_meal_activity(self, meal_type, restaurant, people, start_time, end_time, transports=None):
        """Create a meal (breakfast/lunch/dinner) activity dict."""
        if transports is None:
            transports = []
        return {
            "type": meal_type,
            "position": str(restaurant["name"]),
            "start_time": start_time,
            "end_time": end_time,
            "price": float(restaurant["price"]),
            "cost": float(restaurant["price"]) * people,
            "tickets": people,
            "transports": transports,
        }

    def _make_hotel_breakfast(self, hotel_name, start_time, end_time):
        """Create a breakfast-at-hotel activity (free)."""
        return {
            "type": "breakfast",
            "position": hotel_name,
            "start_time": start_time,
            "end_time": end_time,
            "price": 0,
            "cost": 0,
            "tickets": 0,
            "transports": [],
        }

    def _make_accommodation_activity(self, hotel, rooms, check_in_time, transports=None):
        """Create an accommodation activity dict."""
        if transports is None:
            transports = []
        return {
            "type": "accommodation",
            "position": str(hotel["name"]),
            "start_time": check_in_time,
            "end_time": "24:00",
            "price": float(hotel["price"]),
            "cost": float(hotel["price"]) * rooms,
            "rooms": rooms,
            "room_type": int(hotel["numbed"]),
            "tickets": rooms,
            "transports": transports,
        }