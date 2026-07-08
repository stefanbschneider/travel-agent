"""Reusable plan builder for TPC ChinaTravel. City-parametrized.
Transports filled EXACTLY from the GoTo tool; prices/costs from DB.
See conversation for the dilution+tight-cluster strategy to reach ATT=100.
"""
import sys, os
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from chinatravel.environment.tools.poi.apis import Poi
from chinatravel.environment.tools.transportation.apis import Transportation
from chinatravel.environment.tools.intercity_transport.apis import IntercityTransport

DBROOT='chinatravel/environment/database_en'

class Builder:
    def __init__(self, target_city, start_city, people):
        self.CITY=target_city; self.START=start_city; self.PPL=people
        self.poi=Poi(lang='en'); self.trans=Transportation(lang='en'); self.it=IntercityTransport(lang='en')
        slug=target_city.lower()
        self.ATTR=pd.read_csv(f'{DBROOT}/attractions/{slug}/attractions.csv')
        self.REST=pd.read_csv(f'{DBROOT}/restaurants/{slug}/restaurants_{slug}.csv')
        self.HOTEL=pd.read_csv(f'{DBROOT}/accommodations/{slug}/accommodations.csv')
    # helpers
    @staticmethod
    def t2m(t): h,m=map(int,t.split(':')); return h*60+m
    @staticmethod
    def m2t(x): return f"{x//60:02d}:{x%60:02d}"
    def attr_row(self,n): return self.ATTR[self.ATTR['name']==n].iloc[0]
    def rest_row(self,n): return self.REST[self.REST['name']==n].iloc[0]
    def hotel_row(self,n): return self.HOTEL[self.HOTEL['name']==n].iloc[0]
    def options(self,a,b,t0='08:00'):
        res={}
        for mode in ['walk','metro','taxi']:
            r=self.trans.goto(city=self.CITY,start=a,end=b,start_time=t0,transport_type=mode,verbose=False)
            if isinstance(r,list):
                tot=sum((self.t2m(x['end_time'])-self.t2m(x['start_time'])) for x in r)
                cost=sum(x.get('cost',0) for x in r)*(self.PPL if mode=='metro' else (1 if mode=='taxi' else 1))
                res[mode]=(tot,round(cost,2))
        return res
    def build_transport(self, prev_pos, pos, start_time, mode):
        r=self.trans.goto(city=self.CITY,start=prev_pos,end=pos,start_time=start_time,transport_type=mode,verbose=False)
        assert isinstance(r,list), f"goto failed {prev_pos}->{pos} {mode}: {r}"
        legs=[]
        for leg in r:
            d=dict(leg)
            if d['mode']=='walk': d['price']=0; d['cost']=0
            elif d['mode']=='metro': d['price']=leg['cost']; d['tickets']=self.PPL; d['cost']=leg['cost']*self.PPL
            elif d['mode']=='taxi': d['price']=leg['cost']; d['cars']=1; d['cost']=leg['cost']*1
            legs.append(d)
        return legs, r[-1]['end_time']
    # fillers
    def fill_attr(self,name):
        pr=float(self.attr_row(name)['price']); ppl=self.PPL
        def f(a): a['price']=pr; a['tickets']=ppl; a['cost']=pr*ppl
        return f
    def fill_rest(self,name):
        pr=float(self.rest_row(name)['price']); ppl=self.PPL
        def f(a): a['price']=pr; a['cost']=pr*ppl
        return f
    def fill_hotel(self,name,rooms=1):
        r=self.hotel_row(name); pr=float(r['price']); nb=int(r['numbed'])
        def f(a): a['price']=pr; a['room_type']=nb; a['rooms']=rooms; a['cost']=pr*rooms
        return f
    def S(self,typ,poi,mode,dur,earliest,fill):
        return {'type':typ,'poi':poi,'mode':mode,'dur':dur,'earliest':earliest,'_fill':fill}
    def schedule(self, stops, arrival_pos, arrival_end):
        prev_pos=arrival_pos; cur=self.t2m(arrival_end) if isinstance(arrival_end,str) else arrival_end; acts=[]
        for s in stops:
            transports=[]
            if s.get('mode') is None:
                st=cur
            else:
                transports,tend=self.build_transport(prev_pos,s['poi'],self.m2t(cur),s['mode'])
                st=self.t2m(tend)
            if s.get('earliest') is not None and s['earliest']>st: st=s['earliest']
            en=st+s['dur']
            act={'type':s['type'],'position':s['poi'],'start_time':self.m2t(st),'end_time':self.m2t(en),'transports':transports}
            s['_fill'](act); acts.append(act); cur=en; prev_pos=s['poi']
        return acts, prev_pos, cur
    def intercity(self, direction, flight_or_train_id, is_air, transports=None):
        frm,to=(self.START,self.CITY) if direction=='go' else (self.CITY,self.START)
        df=self.it.select(frm,to,'airplane' if is_air else 'train')
        idc='FlightID' if is_air else 'TrainID'
        row=df[df[idc]==flight_or_train_id].iloc[0]
        act={'type':'airplane' if is_air else 'train','start':row['From'],'end':row['To'],idc:flight_or_train_id,
             'start_time':row['BeginTime'],'end_time':row['EndTime'],
             'price':float(row['Cost']),'tickets':self.PPL,'cost':float(row['Cost'])*self.PPL,
             'transports':transports if transports else []}
        return act, row
