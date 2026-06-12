import sys
import os
import time
import argparse
import pandas as pd
import json
import numpy as np
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
    """Add minutes to a HH:MM time string, clamping at 23:59."""    # TODO: Clamping is hacky and may lead to issues later
    h, m = map(int, time_str.split(":"))
    total = h * 60 + m + minutes
    total = min(total, 23 * 60 + 59)
    return f"{total // 60:02d}:{total % 60:02d}"


def time_before(t1, t2):
    """Return True if t1 <= t2 (both HH:MM strings)."""
    return t1 <= t2


class TPCAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(name="TPC", **kwargs)

    def run(self, query, prob_idx=None, oralce_translation=False):
        self.reset_clock()

        try:
            plan = self._build_plan(query)
        except Exception as e:
            plan = {
                "people_number": query.get("people_number", 1),
                "start_city": query.get("start_city", ""),
                "target_city": query.get("target_city", ""),
                "itinerary": [],
            }

        plan["elapsed_time(sec)"] = time.time() - self.start_clock
        return True, plan

    def _build_plan(self, query):
        """Build a minimal schema-valid itinerary."""
        people = query["people_number"]
        start_city = query["start_city"]
        target_city = query["target_city"]
        days = query["days"]

        env: WorldEnv = self.env

        # --- Get intercity transport (outbound + return) ---
        outbound = self._get_flight(env, start_city, target_city, "07:00")
        return_flight = self._get_flight(env, target_city, start_city, "18:00")

        # If no flights, try trains
        if outbound is None:
            outbound = self._get_train(env, start_city, target_city, "07:00")
        if return_flight is None:
            return_flight = self._get_train(env, target_city, start_city, "18:00")

        # --- Get one accommodation in target city ---
        accom_df = env.accommodations.select(target_city, "name", lambda x: True)
        hotel = accom_df.iloc[0]
        rooms_needed = math.ceil(people / int(hotel["numbed"]))

        # --- Get some attractions ---
        attr_df = env.attractions.select(target_city, "name", lambda x: True)

        # --- Get some restaurants ---
        rest_df = env.restaurants.select(target_city, "name", lambda x: True)

        # --- Build day-by-day itinerary ---
        itinerary = []
        attr_idx = 0
        rest_idx = 0

        for day_num in range(1, days + 1):
            activities = []

            if day_num == 1:
                # Outbound intercity transport
                if outbound is not None:
                    activities.append(self._make_intercity_activity(outbound, people))
                    current_time = outbound["EndTime"]
                else:
                    current_time = "09:00"

                # Lunch
                if time_before(current_time, "14:00") and rest_idx < len(rest_df):
                    lunch_start = current_time if current_time >= "11:00" else "11:00"
                    lunch_end = add_minutes(lunch_start, 60)
                    restaurant = rest_df.iloc[rest_idx]
                    rest_idx += 1
                    activities.append(self._make_meal_activity(
                        "lunch", restaurant, people, lunch_start, lunch_end))
                    current_time = lunch_end

                # One attraction
                if time_before(current_time, "17:00") and attr_idx < len(attr_df):
                    attr = attr_df.iloc[attr_idx]
                    attr_idx += 1
                    attr_start = current_time
                    attr_end = add_minutes(attr_start, 90)
                    activities.append(self._make_attraction_activity(
                        attr, people, attr_start, attr_end))
                    current_time = attr_end

                # Dinner
                if time_before(current_time, "21:00") and rest_idx < len(rest_df):
                    dinner_start = current_time if current_time >= "17:00" else "17:00"
                    dinner_end = add_minutes(dinner_start, 60)
                    restaurant = rest_df.iloc[rest_idx]
                    rest_idx += 1
                    activities.append(self._make_meal_activity(
                        "dinner", restaurant, people, dinner_start, dinner_end))
                    current_time = dinner_end

                # Accommodation
                activities.append(self._make_accommodation_activity(
                    hotel, rooms_needed, current_time))

            elif day_num == days:
                # Last day: breakfast, maybe attraction, then return transport
                if rest_idx < len(rest_df):
                    restaurant = rest_df.iloc[rest_idx]
                    rest_idx += 1
                    activities.append(self._make_meal_activity(
                        "breakfast", restaurant, people, "08:00", "09:00"))
                    current_time = "09:00"
                else:
                    current_time = "09:00"

                # One attraction if time allows
                if attr_idx < len(attr_df) and return_flight is not None:
                    departure_time = return_flight["BeginTime"]
                    if time_before(add_minutes(current_time, 90), departure_time):
                        attr = attr_df.iloc[attr_idx]
                        attr_idx += 1
                        attr_end = add_minutes(current_time, 90)
                        activities.append(self._make_attraction_activity(
                            attr, people, current_time, attr_end))
                        current_time = attr_end

                # Return intercity transport
                if return_flight is not None:
                    activities.append(self._make_intercity_activity(return_flight, people))

            else:
                # Middle days: breakfast, attractions, lunch, attractions, dinner, hotel
                # Breakfast
                if rest_idx < len(rest_df):
                    restaurant = rest_df.iloc[rest_idx]
                    rest_idx += 1
                    activities.append(self._make_meal_activity(
                        "breakfast", restaurant, people, "08:00", "09:00"))
                current_time = "09:00"

                # Morning attraction
                if attr_idx < len(attr_df):
                    attr = attr_df.iloc[attr_idx]
                    attr_idx += 1
                    attr_end = add_minutes(current_time, 90)
                    activities.append(self._make_attraction_activity(
                        attr, people, current_time, attr_end))
                    current_time = attr_end

                # Lunch
                if rest_idx < len(rest_df):
                    lunch_start = current_time if current_time >= "11:00" else "11:00"
                    lunch_end = add_minutes(lunch_start, 60)
                    restaurant = rest_df.iloc[rest_idx]
                    rest_idx += 1
                    activities.append(self._make_meal_activity(
                        "lunch", restaurant, people, lunch_start, lunch_end))
                    current_time = lunch_end

                # Afternoon attraction
                if attr_idx < len(attr_df):
                    attr = attr_df.iloc[attr_idx]
                    attr_idx += 1
                    attr_end = add_minutes(current_time, 90)
                    activities.append(self._make_attraction_activity(
                        attr, people, current_time, attr_end))
                    current_time = attr_end

                # Dinner
                if rest_idx < len(rest_df):
                    dinner_start = current_time if current_time >= "17:00" else "17:00"
                    dinner_end = add_minutes(dinner_start, 60)
                    restaurant = rest_df.iloc[rest_idx]
                    rest_idx += 1
                    activities.append(self._make_meal_activity(
                        "dinner", restaurant, people, dinner_start, dinner_end))
                    current_time = dinner_end

                # Accommodation
                activities.append(self._make_accommodation_activity(
                    hotel, rooms_needed, current_time))

            itinerary.append({"day": day_num, "activities": activities})

        return {
            "people_number": people,
            "start_city": start_city,
            "target_city": target_city,
            "itinerary": itinerary,
        }

    def _get_flight(self, env, from_city, to_city, earliest):
        """Get first available flight."""
        try:
            df = env.intercitytransport.select(from_city, to_city, "airplane", earliest)
            if df is not None and len(df) > 0:
                return df.iloc[0].to_dict()
        except Exception:
            pass
        return None

    def _get_train(self, env, from_city, to_city, earliest):
        """Get first available train."""
        try:
            df = env.intercitytransport.select(from_city, to_city, "train", earliest)
            if df is not None and len(df) > 0:
                return df.iloc[0].to_dict()
        except Exception:
            pass
        return None

    def _make_intercity_activity(self, transport, people):
        """Create an intercity transport activity dict."""
        activity = {
            "type": "airplane" if "FlightID" in transport else "train",
            "start_time": transport["BeginTime"],
            "end_time": transport["EndTime"],
            "start": transport["From"],
            "end": transport["To"],
            "price": float(transport["Cost"]),
            "cost": float(transport["Cost"]) * people,
            "tickets": people,
            "transports": [],
        }
        if "FlightID" in transport:
            activity["FlightID"] = transport["FlightID"]
        else:
            activity["TrainID"] = transport["TrainID"]
        return activity

    def _make_attraction_activity(self, attr, people, start_time, end_time):
        """Create an attraction activity dict."""
        return {
            "type": "attraction",
            "position": str(attr["name"]),
            "start_time": start_time,
            "end_time": end_time,
            "price": float(attr["price"]),
            "cost": float(attr["price"]) * people,
            "tickets": people,
            "transports": [],
        }

    def _make_meal_activity(self, meal_type, restaurant, people, start_time, end_time):
        """Create a meal (breakfast/lunch/dinner) activity dict."""
        return {
            "type": meal_type,
            "position": str(restaurant["name"]),
            "start_time": start_time,
            "end_time": end_time,
            "price": float(restaurant["price"]),
            "cost": float(restaurant["price"]) * people,
            "tickets": people,
            "transports": [],
        }

    def _make_accommodation_activity(self, hotel, rooms, current_time):
        """Create an accommodation activity dict."""
        return {
            "type": "accommodation",
            "position": str(hotel["name"]),
            "start_time": current_time,
            "end_time": "23:59",
            "price": float(hotel["price"]),
            "cost": float(hotel["price"]) * rooms,
            "rooms": rooms,
            "room_type": int(hotel["numbed"]),
            "tickets": rooms,
            "transports": [],
        }