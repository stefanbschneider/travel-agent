"""Parsed-constraint verifier for the no-oracle (Phase-2) code path.

`evaluate_parsed_constraints` mirrors the DSL semantics of the oracle's hard_logic_py
but operates on the constraints emitted by the live NL parser (`parse_query_no_oracle`)
instead of the in-data hard_logic_py. One boolean is appended per constraint that the
parser actually emitted, computed with the same `func_dict` concept helpers the oracle
uses, so an all-True result means the plan satisfies every parsed constraint.
"""

from chinatravel.symbol_verification.concept_func import func_dict


def _norm(value):
    return str(value).strip().lower() if value is not None else ""


def _match_text(candidate, constraint):
    c = _norm(candidate)
    q = _norm(constraint)
    if not c or not q:
        return False
    return c == q or q in c or c in q


def _room_type_to_numbed(room_type):
    if room_type is None:
        return None
    if isinstance(room_type, (int, float)):
        try:
            iv = int(room_type)
            return iv if iv in (1, 2) else None
        except Exception:
            return None
    t = _norm(room_type)
    if any(k in t for k in ["single", "1", "one"]):
        return 1
    if any(k in t for k in ["double", "twin", "2", "two"]):
        return 2
    return None


def _time_to_min(value):
    try:
        h, m = map(int, str(value).split(":"))
        return h * 60 + m
    except Exception:
        return None


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def evaluate_parsed_constraints(constraints, plan, target_city):
    """Return a list[bool], one entry per parsed constraint the plan is checked against."""
    if not isinstance(constraints, dict):
        return []

    allactivities = func_dict["allactivities"]
    activity_type = func_dict["activity_type"]
    activity_cost = func_dict["activity_cost"]
    activity_price = func_dict["activity_price"]
    activity_position = func_dict["activity_position"]
    activity_transports = func_dict["activity_transports"]
    activity_time = func_dict["activity_time"]
    activity_start_time = func_dict["activity_start_time"]
    activity_end_time = func_dict["activity_end_time"]
    innercity_transport_cost = func_dict["innercity_transport_cost"]
    innercity_transport_type = func_dict["innercity_transport_type"]
    innercity_transport_distance = func_dict["innercity_transport_distance"]
    restaurant_type_fn = func_dict["restaurant_type"]
    attraction_type_fn = func_dict["attraction_type"]
    accommodation_type_fn = func_dict["accommodation_type"]
    room_type_fn = func_dict["room_type"]
    taxi_cars_fn = func_dict["taxi_cars"]
    poi_distance_fn = func_dict["poi_distance"]

    acts = allactivities(plan)
    attractions = [a for a in acts if activity_type(a) == "attraction"]
    meals = [a for a in acts if activity_type(a) in ("breakfast", "lunch", "dinner")]
    hotels = [a for a in acts if activity_type(a) == "accommodation"]

    results = []

    def add(ok):
        try:
            results.append(bool(ok))
        except Exception:
            results.append(False)

    def acts_at(location, types=None):
        candidates = [a for a in acts if _match_text(activity_position(a), location)]
        if types:
            candidates = [a for a in candidates if activity_type(a) in types]
        return candidates

    # --- Budgets -----------------------------------------------------------
    budgets = constraints.get("budgets")
    if isinstance(budgets, dict):
        def _cap(key):
            try:
                v = float(budgets.get(key))
            except (TypeError, ValueError):
                return None
            return v if v >= 0 else None

        bucket_sources = {
            "sightseeing": attractions,
            "dining": meals,
            "accommodation": hotels,
            "intercity_transport": [a for a in acts if activity_type(a) in ("airplane", "train")],
        }
        for bucket, source in bucket_sources.items():
            cap = _cap(bucket)
            if cap is not None:
                add(sum(activity_cost(a) for a in source) <= cap + 1e-6)
        cap = _cap("inner_transport")
        if cap is not None:
            add(sum(innercity_transport_cost(activity_transports(a)) for a in acts) <= cap + 1e-6)
        cap = _cap("total")
        if cap is not None:
            total = sum(activity_cost(a) for a in acts) + sum(
                innercity_transport_cost(activity_transports(a)) for a in acts
            )
            add(total <= cap + 1e-6)

    # --- Attractions: free / required / excluded / types -------------------
    if constraints.get("free_attractions_only"):
        add(all(activity_price(a) == 0 for a in attractions))

    for name in _as_list(constraints.get("required_attractions")):
        add(any(_match_text(activity_position(a), name) for a in attractions))
    for name in _as_list(constraints.get("excluded_attractions")):
        add(not any(_match_text(activity_position(a), name) for a in attractions))

    visited_attr_types = [attraction_type_fn(a, target_city) for a in attractions]
    for t in _as_list(constraints.get("required_attraction_types")):
        add(any(_match_text(vt, t) for vt in visited_attr_types))
    for t in _as_list(constraints.get("excluded_attraction_types")):
        add(not any(_match_text(vt, t) for vt in visited_attr_types))

    # --- Restaurants: required / excluded / cuisine ------------------------
    for name in _as_list(constraints.get("required_restaurants")):
        add(any(_match_text(activity_position(a), name) for a in meals))
    for name in _as_list(constraints.get("excluded_restaurants")):
        add(not any(_match_text(activity_position(a), name) for a in meals))

    visited_cuisines = [restaurant_type_fn(a, target_city) for a in meals]
    for t in _as_list(constraints.get("cuisine_preference")):
        add(any(_match_text(vc, t) for vc in visited_cuisines))
    for t in _as_list(constraints.get("excluded_cuisine_types")):
        add(not any(_match_text(vc, t) for vc in visited_cuisines))

    # --- Hotels: required / excluded / types / amenity / room --------------
    for name in _as_list(constraints.get("required_hotels")):
        add(any(_match_text(activity_position(a), name) for a in hotels))
    for name in _as_list(constraints.get("excluded_hotels")):
        add(not any(_match_text(activity_position(a), name) for a in hotels))

    visited_hotel_types = [accommodation_type_fn(a, target_city) for a in hotels]
    for t in _as_list(constraints.get("required_hotel_all_types")):
        add(any(_match_text(ht, t) for ht in visited_hotel_types))
    if constraints.get("required_hotel_any_types"):
        add(any(
            _match_text(ht, t)
            for ht in visited_hotel_types
            for t in _as_list(constraints.get("required_hotel_any_types"))
        ))
    for t in _as_list(constraints.get("hotel_type")):
        add(any(_match_text(ht, t) for ht in visited_hotel_types))

    room_numbed = _room_type_to_numbed(constraints.get("room_type"))
    if room_numbed is not None and hotels:
        add(all(room_type_fn(a) == room_numbed for a in hotels))

    # --- Room count (P28) --------------------------------------------------
    # The oracle checks this exactly (``room_count(activity) != N -> False``), so the acceptance
    # gate and the oracle-free self-score have to see it too, or the scheduler will call a query
    # satisfied while it fails a clause on the real oracle.
    rooms_required = constraints.get("rooms")
    try:
        rooms_required = int(rooms_required)
    except (TypeError, ValueError):
        rooms_required = None
    if rooms_required and hotels:
        add(all(int(a.get("rooms", 0) or 0) == rooms_required for a in hotels))

    # --- Hotel proximity ---------------------------------------------------
    # Display-rounded hotel-distance values can be up to 0.01 km looser than the oracle
    # threshold. Tighten by that bound so this acceptance check is never looser; retain the
    # parsed display value in the constraint dict for reporting and diffing.
    nearby = constraints.get("hotel_nearby")
    if isinstance(nearby, dict) and nearby.get("reference") and hotels:
        ref = nearby["reference"]
        limit_m = max(0.0, float(nearby.get("distance_km", 5)) - 0.01) * 1000.0
        ok = True
        for a in hotels:
            try:
                if poi_distance_fn(target_city, activity_position(a), ref) > limit_m:
                    ok = False
                    break
            except Exception:
                ok = False
                break
        add(ok)

    # --- Per-POI dwell time ------------------------------------------------
    for sd in _as_list(constraints.get("stay_duration")):
        if not isinstance(sd, dict):
            continue
        loc = sd.get("location")
        try:
            need = int(sd.get("min_minutes", 0))
        except (TypeError, ValueError):
            need = 0
        if loc and need > 0:
            add(any(activity_time(a) >= need for a in acts_at(loc)))

    # --- Per-POI time windows ---------------------------------------------
    for w in _as_list(constraints.get("activity_time_windows")):
        if not isinstance(w, dict) or not w.get("location"):
            continue
        earliest = _time_to_min(w.get("earliest"))
        latest = _time_to_min(w.get("latest"))
        end_after = _time_to_min(w.get("end_after"))
        end_before = _time_to_min(w.get("end_before"))
        # A "Dine at X between A and B" / "Stay at X between A and B" window is gated by activity
        # type in the oracle (activity_type(activity) in [...] and activity_position(...)==X), not
        # by location alone -- the same POI name routinely carries both a meal window and an
        # accommodation window (a hotel with an on-site restaurant). Filtering acts_at() by the
        # parsed activity_types here (roadmap P12) keeps an accommodation-stay activity from
        # satisfying a meal-only window purely because it happens to overlap in time, and vice
        # versa; a window without a type-bearing verb keeps ``types=None`` (any activity, the prior
        # behaviour).
        window_types = w.get("activity_types")

        def _fits(a):
            st = _time_to_min(activity_start_time(a))
            et = _time_to_min(activity_end_time(a))
            if earliest is not None and (st is None or st < earliest):
                return False
            if latest is not None and (st is None or st > latest):
                return False
            if end_after is not None and (et is None or et < end_after):
                return False
            if end_before is not None and (et is None or et > end_before):
                return False
            return True

        add(any(_fits(a) for a in acts_at(w["location"], types=window_types)))

    # --- Required visit ordering --------------------------------------------
    # "Visit X first, then Y": X's earliest chronological occurrence (day order, then in-day
    # activity order -- allactivities()'s own iteration order) must precede Y's. Both POIs must
    # actually appear; a missing one fails the check rather than defaulting to pass, which is
    # stricter than -- and therefore never more lenient than -- the oracle's own index-comparison
    # DSL (roadmap P12; the oracle initializes both indices to 0, so a plan that omits the first
    # POI but visits the second at any later index can flip the oracle's own check True by
    # accident. Mirroring that quirk would let a false positive back in, exactly what this item
    # exists to remove).
    order = _as_list(constraints.get("required_order"))
    if len(order) >= 2:
        def _first_index(name):
            for i, a in enumerate(acts):
                if _match_text(activity_position(a), name):
                    return i
            return None

        indices = [_first_index(name) for name in order]
        ok = all(i is not None for i in indices) and all(
            indices[i] < indices[i + 1] for i in range(len(indices) - 1)
        )
        add(ok)

    # --- Intercity mode ----------------------------------------------------
    mode = constraints.get("intercity_mode")
    if mode and acts:
        if isinstance(mode, dict):
            if mode.get("outbound"):
                add(activity_type(acts[0]) == _norm_mode(mode["outbound"]))
            if mode.get("return"):
                add(activity_type(acts[-1]) == _norm_mode(mode["return"]))
        else:
            want = _norm_mode(mode)
            add(activity_type(acts[0]) == want)
            add(activity_type(acts[-1]) == want)

    # --- Inner transport exclusions ---------------------------------------
    excluded_modes = [_norm(m) for m in _as_list(constraints.get("excluded_inner_transport"))]
    if excluded_modes:
        # Mirror the oracle's hard_logic encoding exactly. The oracle builds the set of
        # activity_position values for *top-level* activities whose activity_type is
        # 'transportation' and checks the excluded mode string is not in that set. The plan
        # schema never emits standalone 'transportation' activities (inner-city transport is
        # carried as embedded `transports` segments), so that set is empty and the oracle
        # clause is vacuously true. Inspecting embedded segments here instead over-constrains
        # relative to the oracle and falsely rejects oracle-accepted plans (all 76 val queries
        # with this family encode it via the vacuous pattern). See docs roadmap 1c.
        transport_positions = {
            _norm(activity_position(a)) for a in acts if activity_type(a) == "transportation"
        }
        add(not any(m in transport_positions for m in excluded_modes))

    # --- Conditional transport (distance threshold -> required mode) -------
    cond = constraints.get("conditional_transport")
    if isinstance(cond, dict) and cond.get("threshold_km") is not None:
        threshold_m = float(cond["threshold_km"]) * 1000.0
        want = _norm(cond.get("mode", "taxi"))
        ok = True
        for a in acts:
            tr = activity_transports(a)
            if tr and innercity_transport_distance(tr) > threshold_m:
                if _norm(innercity_transport_type(tr)) != want:
                    ok = False
                    break
        add(ok)

    # --- Taxi car count ----------------------------------------------------
    if constraints.get("taxi_cars_equals") is not None:
        try:
            want_cars = int(constraints["taxi_cars_equals"])
        except (TypeError, ValueError):
            want_cars = None
        if want_cars is not None:
            # Mirror the oracle clause: a transport is "taxi" iff
            # innercity_transport_type(tr) == 'taxi' (the same helper the oracle uses),
            # and only taxi transports are constrained -- so a taxi-free plan is
            # vacuously accepted, exactly like the oracle. See docs roadmap 1c.
            ok = True
            for a in acts:
                tr = activity_transports(a)
                if _norm(innercity_transport_type(tr)) == "taxi":
                    cars = taxi_cars_fn(tr)
                    if not isinstance(cars, int) or cars != want_cars:
                        ok = False
                        break
            add(ok)

    return results


def _norm_mode(mode):
    m = _norm(mode)
    if m in ("airplane", "flight", "plane"):
        return "airplane"
    if m in ("train", "rail"):
        return "train"
    return m
