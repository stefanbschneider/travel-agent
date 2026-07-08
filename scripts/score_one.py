"""Side-effect-free single-plan scorer. Usage: python scripts/score_one.py <query_id> <plan.json>
Prints the per-query weighted score (0-100, same scale as eval_tpc) and component breakdown.
Does NOT touch any shared files (no split-file rewrite)."""
import json, sys, os
import numpy as np
from copy import deepcopy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from chinatravel.evaluation.utils import load_json_file, validate_json
from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints
from chinatravel.evaluation.hard_constraint import evaluate_hard_constraints_v2
from chinatravel.symbol_verification.concept_func import func_dict
import eval_tpc

def score(query_id, plan):
    d=json.load(open(f'chinatravel/data/en/TPC_IJCAI_2026_phase1_EN/{query_id}.json'))
    qi=[query_id]; qd={query_id:d}; rd={query_id:plan}
    schema=load_json_file('chinatravel/evaluation/output_schema.json')
    _,_,sp=evaluate_schema_constraints(qi,rd,schema=schema)
    _,_,_,cp=evaluate_commonsense_constraints(qi,qd,rd,verbose=False,lang='en')
    _,_,_,_,_,lp=evaluate_hard_constraints_v2(qi,qd,rd,env_pass_id=cp,verbose=False,lang='en')
    cps=set(cp); lps=set(lp); aps=set(sp)&cps&lps
    def clamp(v): return max(0.0,min(1.0,v))
    pr=np.zeros(3)
    if query_id in aps:
        for i,c in enumerate(eval_tpc.DEFAULT_PR):
            vd=deepcopy(func_dict); vd['plan']=plan
            try:
                exec(c,{'__builtins__':{'set':set}},vd); pr[i]=clamp(vd.get('result',False))
            except Exception: pr[i]=0.
    comm=100.0 if query_id in cps else 0.0
    logic=100.0 if query_id in lps else 0.0
    allp=100.0 if query_id in aps else 0.0
    dav,att,ddr=pr*100
    total=0.1*comm+0.1*comm+0.25*logic+0.05*dav+0.05*att+0.05*ddr+0.4*allp
    return dict(total=total,comm=comm,logic=logic,allpass=allp,DAV=dav,ATT=att,DDR=ddr)

if __name__=='__main__':
    qid=sys.argv[1]; plan=json.load(open(sys.argv[2]))
    r=score(qid,plan)
    print(json.dumps(r))
    print(f"SCORE={r['total']:.4f}")
