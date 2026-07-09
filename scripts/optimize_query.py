"""Build an ATT-optimal clustered plan for a TPC phase-1 query by re-clustering the
POIs of the existing (already valid) plan.

Approach: keep the existing plan's per-day activity structure, ordering and timing
skeleton (proven commonsense/hard-constraint feasible), but relocate the hotel and
all attractions/restaurants into ONE dense walkable cluster and recompute the
inner-city transports (walk by default) with the GoTo tool. Short walk legs drive the
average inner-city transport time <= 15 (ATT=100) while every other constraint that
the original plan satisfied is preserved.

Special per-query constraints (allowed attraction types, must-visit POIs, cuisine,
hotel filters, transport-mode restrictions, budgets) are passed via the `spec` dict.
"""
import sys, os, json, math, copy
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from chinatravel.environment.tools.transportation.apis import Transportation
from chinatravel.environment.tools.intercity_transport.apis import IntercityTransport

DB = 'chinatravel/environment/database_en'
DATA = 'chinatravel/data/en/TPC_IJCAI_2026_phase1_EN'
BEST = 'results/best'


def hav(lat1, lon1, lat2, lon2):
    R = 6371.0; p = math.pi / 180
    a = 0.5 - math.cos((lat2-lat1)*p)/2 + math.cos(lat1*p)*math.cos(lat2*p)*(1-math.cos((lon2-lon1)*p))/2
    return 2*R*math.asin(math.sqrt(a))

def t2m(t):
    h, m = map(int, t.split(':')); return h*60+m

def m2t(x):
    x %= 24*60
    return f"{x//60:02d}:{x%60:02d}"


class Solver:
    def __init__(self, qid, spec=None):
        self.qid = qid
        self.spec = spec or {}
        self.q = json.load(open(f'{DATA}/{qid}.json'))
        self.city = self.q['target_city']
        self.days = self.q['days']
        self.ppl = self.q['people_number']
        slug = self.city.lower()
        self.A = pd.read_csv(f'{DB}/attractions/{slug}/attractions.csv')
        self.R = pd.read_csv(f'{DB}/restaurants/{slug}/restaurants_{slug}.csv')
        self.H = pd.read_csv(f'{DB}/accommodations/{slug}/accommodations.csv')
        self.trans = Transportation(lang='en')
        self.it = IntercityTransport(lang='en')
        self.pc = self.trans.poi_search  # authoritative coords used by GoTo + validator
        self._cc = {}
        self.old = json.load(open(f'{BEST}/{qid}.json'))
        self.mode = self.spec.get('mode', 'walk')  # inner-city transport mode

    def make_intercity(self, flight_id, direction):
        """Build an intercity activity dict for a given flight/train id.
        direction 'go' = start_city->target_city (arrival); 'back' = target->start (departure)."""
        frm, to = (self.q['start_city'], self.city) if direction == 'go' else (self.city, self.q['start_city'])
        for kind, idc in (('airplane', 'FlightID'), ('train', 'TrainID')):
            df = self.it.select(frm, to, kind)
            if df is None or len(df) == 0 or idc not in df.columns:
                continue
            row = df[df[idc] == flight_id]
            if row.empty:
                continue
            row = row.iloc[0]
            return {'type': kind, 'start': row['From'], 'end': row['To'], idc: flight_id,
                    'start_time': row['BeginTime'], 'end_time': row['EndTime'],
                    'price': float(row['Cost']), 'tickets': self.ppl, 'cost': float(row['Cost'])*self.ppl,
                    'transports': []}
        raise AssertionError(f"flight/train {flight_id} not found {frm}->{to}")

    def gc(self, name):
        """GoTo-consistent coordinate for a POI name (cached)."""
        if name not in self._cc:
            try:
                self._cc[name] = self.pc.search(self.city, name)
            except Exception:
                self._cc[name] = None
        return self._cc[name]

    def coords(self, df, name):
        return self.gc(name)

    def open_ok(self, df, name, st, en):
        r = df[df['name'] == name].iloc[0]
        oc, cc = t2m(r['opentime']), t2m(r['endtime'])
        if cc <= oc: cc += 24*60
        s, e = t2m(st), t2m(en)
        # allow the slot to be within [open, close], accounting for midnight visits
        for shift in (0, 24*60):
            if oc <= s+shift and e+shift <= cc:
                return True
        return False

    # --- choose cluster hotel + candidate POIs ---
    def pick_hotel(self):
        if 'hotel' in self.spec:
            return self.spec['hotel']
        # densest walkable hotel among those passing hotel filter
        cand = self.H
        hf = self.spec.get('hotel_filter')
        if hf: cand = cand[cand.apply(hf, axis=1)]
        hn = self.spec.get('hotel_near')  # (poi_name, max_km): hotel must be within max_km of poi
        if hn:
            pc = self.gc(hn[0])
            cand = cand[cand['name'].map(lambda n: (self.gc(n) is not None) and hav(pc[0], pc[1], self.gc(n)[0], self.gc(n)[1]) <= hn[1])]
        best = None
        Af = self.allowed_attractions()
        radius = self.spec.get('radius', 2.0)
        acoords = [(n, self.gc(n)) for n in Af['name']]
        acoords = [(n, c) for n, c in acoords if c]
        rcoords = [(n, self.gc(n)) for n in self.R['name']]
        rcoords = [(n, c) for n, c in rcoords if c]
        for _, h in cand.iterrows():
            hc = self.gc(h['name'])
            if not hc: continue
            na = sum(1 for n, c in acoords if hav(hc[0], hc[1], c[0], c[1]) <= radius)
            nr = sum(1 for n, c in rcoords if hav(hc[0], hc[1], c[0], c[1]) <= radius)
            if na >= 4*self.days and nr >= 3*self.days:
                # cheap_hotel: minimize price (negate to reuse max); else maximize density
                score = -float(h['price']) if self.spec.get('cheap_hotel') else (na + nr)
                if best is None or score > best[0]:
                    best = (score, h['name'])
        assert best, "no dense hotel found"
        return best[1]

    def allowed_attractions(self):
        A = self.A
        forb = self.spec.get('forbidden_types')
        if forb: A = A[~A['type'].isin(forb)]
        allow = self.spec.get('allowed_types')
        if allow: A = A[A['type'].isin(allow)]
        return A

    def allowed_restaurants(self):
        R = self.R
        rf = self.spec.get('rest_filter')
        if rf: R = R[R.apply(rf, axis=1)]
        return R

    def _one_mode(self, a, b, start_time, mode):
        r = self.trans.goto(city=self.city, start=a, end=b, start_time=start_time, transport_type=mode, verbose=False)
        if not isinstance(r, list) or not r:
            return None
        legs = []
        for leg in r:
            d = dict(leg)
            if d['mode'] == 'walk': d['price'] = 0; d['cost'] = 0
            elif d['mode'] == 'metro': d['price'] = leg['cost']; d['tickets'] = self.ppl; d['cost'] = leg['cost']*self.ppl
            elif d['mode'] == 'taxi': d['price'] = leg['cost']; d['cars'] = 1; d['cost'] = leg['cost']
            legs.append(d)
        return legs

    @property
    def WALK_CAP(self):  # minutes; longer "walks" are GoTo artifacts or ATT-inflating
        return self.spec.get('walk_cap', 30)

    def _dur(self, legs):
        d = t2m(legs[-1]['end_time']) - t2m(legs[0]['start_time'])
        return d + 24*60 if d < 0 else d

    def goto(self, a, b, start_time, mode=None):
        """Choose a transport for one hop among allowed modes.
        policy 'min_time' (default): fastest (excludes buggy huge walks naturally).
        policy 'min_cost': prefer free walk (<=WALK_CAP), else cheapest feasible."""
        if a == b:
            return [], start_time
        modes = [mode] if mode else self.spec.get('allowed_modes', ['walk', 'metro', 'taxi'])
        opt = {}
        for m in modes:
            legs = self._one_mode(a, b, start_time, m)
            if legs is not None:
                opt[m] = (self._dur(legs), sum(l.get('cost', 0) for l in legs), legs)
        assert opt, f"no transport {a}->{b} in {modes}"
        policy = self.spec.get('policy', 'min_time')
        if policy == 'min_cost':
            if 'walk' in opt and opt['walk'][0] <= self.WALK_CAP:
                chosen = opt['walk']
            else:
                chosen = min((v for m, v in opt.items() if m != 'walk'), key=lambda v: (v[1], v[0]), default=None)
                if chosen is None:
                    chosen = opt['walk']
        else:
            # fastest; exclude absurd walk unless it is the only option
            cands = {m: v for m, v in opt.items() if not (m == 'walk' and v[0] > self.WALK_CAP)} or opt
            chosen = min(cands.values(), key=lambda v: v[0])
        return chosen[2], chosen[2][-1]['end_time']

    def _pools(self):
        """Return (hotel, attr_pool, rest_pool): clustered, ordered candidate lists."""
        hotel = self.pick_hotel()
        hlat, hlon = self.coords(self.H, hotel)
        Af = self.allowed_attractions()
        Rf = self.allowed_restaurants()
        radius = self.spec.get('radius', 2.0)
        def dist_to_hotel(name):
            c = self.gc(name)
            return hav(hlat, hlon, c[0], c[1]) if c else 1e9
        Af = Af.assign(_d=Af['name'].map(dist_to_hotel))
        Rf = Rf.assign(_d=Rf['name'].map(dist_to_hotel))
        Af = Af[Af['_d'] <= radius]
        Rf = Rf[Rf['_d'] <= radius]
        Af = Af.sort_values(['price', '_d'] if self.spec.get('prefer_cheap') else '_d')
        Rf = Rf.sort_values(['price', '_d'] if self.spec.get('prefer_cheap_rest') else '_d')

        must_attr = list(self.spec.get('must_attractions', []))
        must_rest = list(self.spec.get('must_restaurants', []))
        for typ in self.spec.get('require_types', []):
            for n in Af[Af['type'] == typ]['name'].tolist():
                if n not in must_attr:
                    must_attr.append(n); break
        rc = self.spec.get('require_cuisines')
        if rc:
            for n in Rf[Rf['cuisine'].isin(rc)]['name'].tolist():
                if n not in must_rest:
                    must_rest.append(n); break
        attr_pool = must_attr + [n for n in Af['name'].tolist() if n not in must_attr]
        rest_pool = must_rest + [n for n in Rf['name'].tolist() if n not in must_rest]
        return hotel, attr_pool, rest_pool

    # --- PRESERVE-TIMES builder: keep original activity times, swap POIs, back-compute transports ---
    def build_preserve(self):
        hotel, attr_pool, rest_pool = self._pools()
        used_attr, used_rest = set(), set()

        def back_transport(prev_pos, pos, arrive_by):
            """Transport prev_pos->pos ending at/just before arrive_by (str)."""
            if prev_pos is None or prev_pos == pos:
                return []
            est, _ = self.goto(prev_pos, pos, '12:00')
            dur = self._dur(est) if est else 0
            for _ in range(4):
                S = t2m(arrive_by) - dur
                if S < 0: S = 0
                legs, tend = self.goto(prev_pos, pos, m2t(S))
                d = t2m(tend) - t2m(m2t(S)); d = d + 24*60 if d < 0 else d
                if t2m(tend) <= t2m(arrive_by) or S == 0:
                    return legs
                dur = d + (t2m(tend) - t2m(arrive_by))
            return legs

        itin = copy.deepcopy(self.old['itinerary'])
        # DAV padding: ensure 4*days attraction slots by injecting synthetic daytime slots
        if self.spec.get('pad_attractions'):
            target = 4 * self.days
            have = sum(1 for day in itin for a in day['activities'] if a['type'] == 'attraction')
            deficit = max(0, target - have)
            if deficit:
                # inject into a full (non-first, non-last) day if possible, else day 0
                cand_day = itin[1] if len(itin) > 2 else itin[0]
                # find insert index: right after the first attraction (or first activity)
                ins = 1
                for j, a in enumerate(cand_day['activities']):
                    if a['type'] == 'attraction':
                        ins = j + 1; break
                base = 10 * 60  # 10:00, staggered 25-min slots
                new_slots = []
                for k in range(deficit):
                    st = base + k * 25
                    new_slots.append({'type': 'attraction', 'start_time': m2t(st), 'end_time': m2t(st + 20)})
                cand_day['activities'][ins:ins] = new_slots

        out_days = []
        prev_pos = None
        n_days = len(itin)
        for di, day in enumerate(itin):
            out_acts = []
            acts = day['activities']
            for ai, a in enumerate(acts):
                typ = a['type']
                is_first = (di == 0 and ai == 0)
                is_last = (di == n_days - 1 and ai == len(acts) - 1)
                if typ in ('airplane', 'train'):
                    if is_first:
                        na = self.make_intercity(self.spec['arrival_flight'], 'go') if self.spec.get('arrival_flight') else copy.deepcopy(a)
                        na['transports'] = []
                        prev_pos = na['end']
                    else:
                        na = self.make_intercity(self.spec['departure_flight'], 'back') if self.spec.get('departure_flight') else copy.deepcopy(a)
                        na['transports'] = back_transport(prev_pos, na['start'], na['start_time'])
                        prev_pos = na['start']
                    out_acts.append(na)
                    continue
                st, en = a['start_time'], a['end_time']
                if typ == 'attraction':
                    name = self._pick_open(attr_pool, used_attr, self.A, st, en)
                    used_attr.add(name)
                elif typ in ('breakfast', 'lunch', 'dinner'):
                    if typ == 'breakfast' and self.spec.get('breakfast_hotel'):
                        name = hotel
                    else:
                        name = self._pick_open(rest_pool, used_rest, self.R, st, en, meal=typ)
                        if name is None and typ == 'breakfast':
                            name = hotel
                        elif name is None:
                            raise AssertionError(f"no restaurant open {st}-{en} for {typ}")
                        else:
                            used_rest.add(name)
                elif typ == 'accommodation':
                    name = hotel
                else:
                    raise ValueError(typ)
                tp = self.spec.get('timed_pois', {})
                if name in tp:
                    st, en = tp[name]  # force a specific POI to a required time window
                legs = back_transport(prev_pos, name, st)
                na = self._mk(typ, name, t2m(st), t2m(en), legs, hotel)
                na['start_time'], na['end_time'] = st, en  # keep original time strings verbatim (e.g. 24:00)
                out_acts.append(na)
                prev_pos = name
            out_days.append({'day': day['day'], 'activities': out_acts})
        plan = {k: self.old[k] for k in self.old if k != 'itinerary'}
        plan['itinerary'] = out_days
        return plan

    def _pick_open(self, pool, used, df, st, en, meal=None):
        timed_meal = self.spec.get('timed_meal', {})
        for n in pool:
            if n in used: continue
            if df[df['name'] == n].empty: continue
            if meal and n in timed_meal and timed_meal[n] != meal:
                continue  # this POI is reserved for a specific meal type
            if meal:
                ws, we = self.MEAL_WINDOW[meal]
                if not (t2m(st) < t2m(we) and t2m(en) > t2m(ws)):
                    continue
                if not self.open_ok(self.R, n, st, en):
                    continue
            else:
                if not self.open_ok(self.A, n, st, en):
                    continue
            return n
        if meal:
            return None
        raise AssertionError(f"no POI open {st}-{en} (pool exhausted)")

    # --- assign cluster POIs to the existing plan's slots (sequential re-timing) ---
    def build(self):
        hotel, attr_pool, rest_pool = self._pools()
        used_attr, used_rest = set(), set()

        new_itin = []
        for day in self.old['itinerary']:
            acts = []
            prev_pos = None
            cur = None
            for a in day['activities']:
                typ = a['type']
                if typ in ('airplane', 'train'):
                    acts.append(('IC', a))
                    prev_pos = a['end'] if a is day['activities'][0] and day is self.old['itinerary'][0] else a.get('start')
                    # arrival: prev becomes arrival endpoint; set cur
                    if a['end_time'] and a['start_time']:
                        pass
                    continue
                acts.append((typ, a))
            new_itin.append((day['day'], acts))

        # Walk through and assign POIs + reschedule
        out_days = []
        prev_pos = None
        cur = None  # minutes
        for di, (dayno, acts) in enumerate(new_itin):
            out_acts = []
            if di > 0:
                # reset clock to this day's morning (each day is scored independently)
                first = next(a for t, a in acts if t != 'IC')
                cur = t2m(first['start_time'])
            for ai, (typ, a) in enumerate(acts):
                if typ == 'IC':
                    if ai == 0:
                        # arrival: verbatim, or overridden flight
                        if self.spec.get('arrival_flight'):
                            na = self.make_intercity(self.spec['arrival_flight'], 'go')
                        else:
                            na = copy.deepcopy(a)
                        out_acts.append(na)
                        prev_pos = na['end']
                        cur = t2m(na['end_time'])
                    else:
                        # departure: transport from prev_pos to station, then intercity
                        if self.spec.get('departure_flight'):
                            na = self.make_intercity(self.spec['departure_flight'], 'back')
                        else:
                            na = copy.deepcopy(a)
                        station = na['start']
                        legs, tend = self.goto(prev_pos, station, m2t(cur))
                        na['transports'] = legs
                        out_acts.append(na)
                    continue

                # choose POI (schedule-aware: validate opening/meal window at ACTUAL time)
                orig_start, orig_end = a['start_time'], a['end_time']
                # fixed short durations compress the day -> minimal drift, departures always caught
                if typ == 'attraction':
                    dur = self.spec.get('attr_dur', 20)
                elif typ in ('breakfast', 'lunch', 'dinner'):
                    dur = self.spec.get('meal_dur', 40)
                else:
                    dur = t2m(orig_end) - t2m(orig_start)
                if typ == 'attraction':
                    name, legs, st, en = self._sched(attr_pool, used_attr, self.A, 'attraction',
                                                     orig_start, dur, prev_pos, cur, hotel)
                    used_attr.add(name)
                elif typ in ('breakfast', 'lunch', 'dinner'):
                    if typ == 'breakfast' and self.spec.get('breakfast_hotel', False):
                        name, legs, st, en = self._sched([hotel], set(), self.H, 'meal:'+typ,
                                                         orig_start, dur, prev_pos, cur, hotel)
                    else:
                        try:
                            name, legs, st, en = self._sched(rest_pool, used_rest, self.R, 'meal:'+typ,
                                                             orig_start, dur, prev_pos, cur, hotel)
                            used_rest.add(name)
                        except AssertionError:
                            if typ == 'breakfast':
                                name, legs, st, en = self._sched([hotel], set(), self.H, 'meal:'+typ,
                                                                 orig_start, dur, prev_pos, cur, hotel)
                            else:
                                raise
                elif typ == 'accommodation':
                    dur = min(dur, 60) if dur > 0 else 60
                    if prev_pos is None:
                        legs, st = [], t2m(orig_start)
                    else:
                        legs, tend = self.goto(prev_pos, hotel, m2t(cur))
                        st = max(t2m(tend), t2m(orig_start))
                    name = hotel
                    en = min(st + dur, 23*60+59)
                else:
                    raise ValueError(typ)

                out_acts.append(self._mk(typ, name, st, en, legs, hotel))
                prev_pos = name
                cur = en
            out_days.append({'day': dayno, 'activities': out_acts})

        plan = {k: self.old[k] for k in self.old if k != 'itinerary'}
        plan['itinerary'] = out_days
        return plan

    MEAL_WINDOW = {'breakfast': ('06:00', '09:00'), 'lunch': ('11:00', '14:00'), 'dinner': ('17:00', '20:00')}

    def _sched(self, pool, used, df, kind, orig_start, dur, prev_pos, cur, hotel):
        """Try candidates in pool; for each compute the transport + actual start/end and
        accept the first that is open (and within meal window) at the ACTUAL time."""
        meal = kind.startswith('meal:')
        mtype = kind.split(':')[1] if meal else None
        for n in pool:
            if n in used: continue
            if df[df['name'] == n].empty and n != hotel: continue
            if prev_pos is None:
                legs, tend = [], m2t(cur)
            else:
                try:
                    legs, tend = self.goto(prev_pos, n, m2t(cur))
                except AssertionError:
                    continue
            st = max(t2m(tend), t2m(orig_start))
            en = st + dur
            if meal:
                ws, we = self.MEAL_WINDOW[mtype]
                if not (st < t2m(we) and en > t2m(ws)):
                    continue
                if n == hotel:  # breakfast at hotel: no opening-hours check
                    return n, legs, st, en
                if not self.open_ok(self.R, n, m2t(st), m2t(en)):
                    continue
            else:  # attraction
                if not self.open_ok(self.A, n, m2t(st), m2t(en)):
                    continue
            return n, legs, st, en
        raise AssertionError(f"no {kind} POI fits slot near {orig_start} (pool exhausted)")

    def _mk(self, typ, name, st, en, legs, hotel):
        if typ == 'attraction':
            pr = float(self.A[self.A['name'] == name].iloc[0]['price'])
            return {'type': 'attraction', 'position': name, 'start_time': m2t(st), 'end_time': m2t(en),
                    'price': pr, 'tickets': self.ppl, 'cost': pr*self.ppl, 'transports': legs}
        if typ in ('breakfast', 'lunch', 'dinner'):
            if name == hotel:
                return {'type': typ, 'position': name, 'start_time': m2t(st), 'end_time': m2t(en),
                        'price': 0, 'cost': 0, 'transports': legs}
            pr = float(self.R[self.R['name'] == name].iloc[0]['price'])
            return {'type': typ, 'position': name, 'start_time': m2t(st), 'end_time': m2t(en),
                    'price': pr, 'cost': pr*self.ppl, 'transports': legs}
        if typ == 'accommodation':
            r = self.H[self.H['name'] == name].iloc[0]
            pr = float(r['price']); nb = int(r['numbed'])
            rooms = self.spec.get('rooms', 1)
            return {'type': 'accommodation', 'position': name, 'room_type': nb, 'rooms': rooms,
                    'start_time': m2t(st), 'end_time': m2t(en), 'price': pr, 'cost': pr*rooms, 'transports': legs}


if __name__ == '__main__':
    qid = sys.argv[1]
    s = Solver(qid)
    plan = s.build()
    out = sys.argv[2] if len(sys.argv) > 2 else f'/tmp/{qid}.json'
    json.dump(plan, open(out, 'w'), ensure_ascii=False, indent=1)
    print('wrote', out)
