import sys
import os
import time
import math

from chinatravel.environment.world_env import WorldEnv

sys.path.append("./../../../")
project_root_path = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

if project_root_path not in sys.path:
    sys.path.insert(0, project_root_path)


from agent.base import AbstractAgent, BaseAgent


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

    def run(self, query, prob_idx=None, oralce_translation=False):
        self.reset_clock()

        try:
            plan = self._build_plan(query)
        except Exception as e:
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

        env: WorldEnv = self.env

        # --- Get intercity transport (outbound + return) ---
        outbound = self._get_intercity(env, start_city, target_city, "07:00")
        return_transport = self._get_intercity(env, target_city, start_city, "17:00")
        # If no return at 17:00, try earlier
        if return_transport is None:
            return_transport = self._get_intercity(env, target_city, start_city, "14:00")
        if return_transport is None:
            return_transport = self._get_intercity(env, target_city, start_city, "00:00")

        # --- Get one accommodation near the arrival/departure point ---
        arrival_pos = outbound["To"] if outbound else None
        hotel = None
        if arrival_pos:
            try:
                nearby_hotels = env.accommodations.nearby(target_city, arrival_pos, topk=5, dist=20)
                if not isinstance(nearby_hotels, str) and len(nearby_hotels) > 0:
                    hotel = nearby_hotels.iloc[0]
            except Exception:
                pass
        if hotel is None:
            accom_df = env.accommodations.select(target_city, "name", lambda x: True)
            hotel = accom_df.iloc[0]
        hotel_name = str(hotel["name"])
        rooms_needed = math.ceil(people / int(hotel["numbed"]))

        # --- Get attractions that are open during reasonable visit hours ---
        attr_df = env.attractions.select(target_city, "name", lambda x: True)
        # Filter to attractions open during daytime visit windows (09:00-17:00)
        good_attrs = []
        for i in range(len(attr_df)):
            a = attr_df.iloc[i]
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
            good_attrs = [attr_df.iloc[i] for i in range(min(len(attr_df), days * 4))]

        # --- Get restaurants open during meal times ---
        rest_df = env.restaurants.select(target_city, "name", lambda x: True)
        lunch_restaurants = []
        dinner_restaurants = []
        used_rest_names = set()
        for i in range(len(rest_df)):
            r = rest_df.iloc[i]
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
                        lunch_start = max(travel_end, "11:00")
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
                        dinner_start = max(travel_end, "17:00")
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
                        later = self._get_intercity(env, target_city, start_city, hotel_to_station_end)
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
                                lunch_start = max(travel_end, "11:00")
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
                        later = self._get_intercity(env, target_city, start_city, travel_end)
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
                        lunch_start = max(travel_end, "11:00")
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
                        dinner_start = max(travel_end, "17:00")
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

    def _get_intercity(self, env, from_city, to_city, earliest):
        """Get first available flight, falling back to train."""
        for transport_type in ["airplane", "train"]:
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
        try:
            result = env.transportation.goto(city, from_pos, to_pos, start_time, "taxi")
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