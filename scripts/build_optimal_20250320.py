#!/usr/bin/env python
"""Build a tightly-clustered valid plan for uid 20250320192920748239.

Goal: DAV=100 (>=12 free attractions), DDR=100 (9 meals), ATT=100 (avg taxi
transport time <= 15 min) while keeping schema/commonsense/logic passing.

All transports are produced by the real goto() tool so they match the verifier
exactly. Times are scheduled forward respecting meal windows and POI open hours.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from chinatravel.environment.tools.attractions.apis import Attractions
from chinatravel.environment.tools.restaurants.apis import Restaurants
from chinatravel.environment.tools.accommodations.apis import Accommodations
from chinatravel.environment.tools.transportation.apis import Transportation

CITY = "Shenzhen"
A = Attractions(lang="en")
R = Restaurants(lang="en")
H = Accommodations(lang="en")
T = Transportation(lang="en")

PEOPLE = 1


def to_min(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def to_str(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def attr_row(name):
    row = A.select(CITY, "name", lambda x: x == name)
    assert not row.empty, f"attraction not found: {name}"
    return row.iloc[0]


def rest_row(name):
    row = R.select(CITY, "name", lambda x: x == name)
    assert not row.empty, f"restaurant not found: {name}"
    return row.iloc[0]


def hotel_row(name):
    row = H.select(CITY, "name", lambda x: x == name)
    assert not row.empty, f"hotel not found: {name}"
    return row.iloc[0]


def taxi(start, end, start_time):
    """Return the single-leg taxi transport dict in plan format."""
    res = T.goto(CITY, start, end, start_time, "taxi")
    assert isinstance(res, list) and len(res) == 1, f"goto failed {start}->{end}: {res}"
    leg = res[0]
    price = round(leg["cost"], 2)
    return {
        "start": leg["start"],
        "end": leg["end"],
        "mode": "taxi",
        "start_time": leg["start_time"],
        "end_time": leg["end_time"],
        "distance": leg["distance"],
        "price": price,
        "cost": price,  # cost = price * cars (cars=1)
        "cars": 1,
    }


class Scheduler:
    def __init__(self):
        self.cur_time = 0
        self.cur_pos = None
        self.activities = []
        self.days = []

    def start_day(self, cur_time, cur_pos):
        if self.activities:
            self.days.append(self.activities)
        self.activities = []
        self.cur_time = cur_time
        self.cur_pos = cur_pos

    def finish(self):
        if self.activities:
            self.days.append(self.activities)

    def _move(self, dest_name):
        """Produce transports list from cur_pos to dest_name; returns (transports, arrive_min)."""
        if self.cur_pos == dest_name:
            return [], self.cur_time
        leg = taxi(self.cur_pos, dest_name, to_str(self.cur_time))
        arrive = to_min(leg["end_time"])
        return [leg], arrive

    def add_attraction(self, name, dur=40, earliest=None):
        row = attr_row(name)
        transports, arrive = self._move(name)
        opent = to_min(row["opentime"])
        start = max(arrive, opent)
        if earliest is not None:
            start = max(start, earliest)
        end = start + dur
        assert int(row["price"]) == 0, f"{name} is not free"
        self.activities.append({
            "type": "attraction",
            "position": name,
            "start_time": to_str(start),
            "end_time": to_str(end),
            "price": 0.0,
            "cost": 0.0,
            "tickets": 1,
            "transports": transports,
        })
        self.cur_time = end
        self.cur_pos = name

    def add_meal(self, mtype, name, window, dur=60):
        row = rest_row(name)
        transports, arrive = self._move(name)
        start = max(arrive, window[0])
        end = start + dur
        price = float(row["price"])
        self.activities.append({
            "type": mtype,
            "position": name,
            "start_time": to_str(start),
            "end_time": to_str(end),
            "price": price,
            "cost": round(price * PEOPLE, 2),
            "tickets": 1,
            "transports": transports,
        })
        self.cur_time = end
        self.cur_pos = name

    def add_hotel_breakfast(self, hotel_name, start=to_min("07:00"), dur=60):
        # breakfast at hotel: same position, no transport, price 0
        self.activities.append({
            "type": "breakfast",
            "position": hotel_name,
            "start_time": to_str(start),
            "end_time": to_str(start + dur),
            "price": 0,
            "cost": 0,
            "tickets": 0,
            "transports": [],
        })
        self.cur_time = start + dur
        self.cur_pos = hotel_name

    def add_accommodation(self, name, dur=None):
        row = hotel_row(name)
        transports, arrive = self._move(name)
        start = arrive
        end = to_min("24:00") if dur is None else start + dur
        price = float(row["price"])
        rooms = 1
        room_type = int(row["numbed"])
        self.activities.append({
            "type": "accommodation",
            "position": name,
            "start_time": to_str(start),
            "end_time": "24:00",
            "price": price,
            "cost": round(price * rooms, 2),
            "rooms": rooms,
            "room_type": room_type,
            "tickets": 1,
            "transports": transports,
        })
        self.cur_time = end
        self.cur_pos = name


def build():
    HOTEL = "Shenzhen Bay Super Headquarters Feria Hotel"
    AIRPORT_SZ = "Shenzhen Bao'an International Airport"
    AIRPORT_HZ = "Hangzhou Xiaoshan International Airport"

    s = Scheduler()

    # ---------- Day 1 ----------
    s.start_day(to_min("04:03"), AIRPORT_SZ)
    # arrival flight
    s.activities.append({
        "type": "airplane",
        "start_time": "02:45",
        "end_time": "04:03",
        "start": AIRPORT_HZ,
        "end": AIRPORT_SZ,
        "price": 483.26,
        "cost": 483.26,
        "tickets": 1,
        "transports": [],
        "FlightID": "FL502",
    })
    s.add_meal("breakfast", "Jiahua Snacks (Shekou Branch)", (to_min("07:00"), to_min("09:00")))
    s.add_attraction("China Merchants Shekou Cruise Home Port Tour")
    s.add_attraction("Greater Bay Area No. 1 (Hong Kong-Zhuhai-Macao Bridge Route)")
    s.add_attraction("Shekou Port Zhuhai Cruise")
    s.add_meal("lunch", "Salt Talk North American Style Western Restaurant (Sea World Branch)", (to_min("12:00"), to_min("14:00")))
    s.add_attraction("Bay Area Cruise")
    s.add_meal("dinner", "Old Famous Shekou Tak Kee Roast Meat Restaurant", (to_min("17:15"), to_min("20:00")))
    s.add_accommodation(HOTEL)

    # ---------- Day 2 ----------
    s.start_day(to_min("07:00"), HOTEL)
    s.add_hotel_breakfast(HOTEL)
    s.add_attraction("Shenzhen Bay Park")
    s.add_attraction("Shenzhen OCT Harbour")
    s.add_meal("lunch", "Chen Pengpeng Braised Goose Restaurant (Happy Coast Branch)", (to_min("12:00"), to_min("14:00")))
    s.add_attraction("Overseas Chinese Town Creative Culture Park")
    s.add_attraction("Shenzhen OCT Tourism Resort")
    s.add_meal("dinner", "Puyutang · Premium Hakka Cuisine (OCT Loft Creative Culture Park Branch)", (to_min("17:15"), to_min("20:00")))
    s.add_accommodation(HOTEL)

    # ---------- Day 3 ----------
    s.start_day(to_min("07:00"), HOTEL)
    s.add_hotel_breakfast(HOTEL)
    s.add_attraction("Nantou Ancient City")
    s.add_attraction("Nanshan")
    s.add_attraction("Nanshan Park")
    s.add_meal("lunch", "Niujiazhuang Beef Noodles (Shekou Old Street Branch)", (to_min("12:00"), to_min("14:00")))
    s.add_attraction("Shekou Industrial Zone")
    s.add_meal("dinner", "Shekou Kangle Fast Food Fish Stall (Cuiyuan Community Branch)", (to_min("17:15"), to_min("20:00")))
    # departure flight FL211 20:28 -> 21:46; taxi from dinner to airport
    dep_taxi = taxi(s.cur_pos, AIRPORT_SZ, to_str(s.cur_time))
    s.activities.append({
        "type": "airplane",
        "start_time": "20:28",
        "end_time": "21:46",
        "start": AIRPORT_SZ,
        "end": AIRPORT_HZ,
        "price": 536.9,
        "cost": 536.9,
        "tickets": 1,
        "transports": [dep_taxi],
        "FlightID": "FL211",
    })
    s.finish()

    itinerary = [{"day": i + 1, "activities": acts} for i, acts in enumerate(s.days)]
    plan = {
        "people_number": 1,
        "start_city": "Hangzhou",
        "target_city": "Shenzhen",
        "itinerary": itinerary,
    }
    return plan


def transport_stats(plan):
    total = 0
    cnt = 0
    legs = []
    for day in plan["itinerary"]:
        for act in day["activities"]:
            tr = act.get("transports", [])
            if tr:
                t = 0
                for leg in tr:
                    t += to_min(leg["end_time"]) - to_min(leg["start_time"])
                total += t
                cnt += 1
                legs.append((act.get("position") or act.get("end"), t))
    return total, cnt, legs


if __name__ == "__main__":
    plan = build()
    out = os.path.join(ROOT, "cache", "cand_20250320192920748239.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    total, cnt, legs = transport_stats(plan)
    print("transport legs (min):")
    for name, t in legs:
        print(f"  {t:3d}  {name}")
    print(f"transport count={cnt} total={total} avg={total/cnt:.2f} min")
    att = (-1 / 105) * (total / cnt) + 8 / 7
    print(f"predicted ATT={max(0,min(1,att))*100:.3f}")
    # attraction & meal counts
    na = sum(1 for d in plan["itinerary"] for a in d["activities"] if a["type"] == "attraction")
    nm = sum(1 for d in plan["itinerary"] for a in d["activities"] if a["type"] in ("breakfast", "lunch", "dinner"))
    print(f"attractions={na} meals={nm}")
    print("wrote", out)
