

import argparse
import shutil

import numpy as np

import sys
import os
import json

project_root_path = os.path.dirname(os.path.abspath(__file__))
if project_root_path not in sys.path: sys.path.insert(0, project_root_path)


from chinatravel.data.load_datasets import load_query
from chinatravel.evaluation.utils import load_json_file, validate_json

from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints
from chinatravel.evaluation.hard_constraint import evaluate_hard_constraints, evaluate_hard_constraints_v2
from chinatravel.evaluation.preference import evaluate_preference, evaluate_preference_v2




DEFAULT_ATTRACTION_PR="""
attraction_count = 0
for activity in allactivities(plan):
    if activity_type(activity) == 'attraction':
        attraction_count += 1
result=attraction_count/(4*day_count(plan))
"""


DEFAULT_TRANS_PR="""
time_cost = 0
transport_count = 0
for activity in allactivities(plan):
    transports = activity_transports(activity)
    if transports!=[]:
        transport_count += 1
        time_cost += innercity_transport_time(transports)
average_time_cost = time_cost / transport_count if transport_count > 0 else -1
result= (-1/105) * average_time_cost + 8/7
"""
DEFAULT_RES_PR="""
res_count=0
for activity in allactivities(plan):
    if activity_type(activity) in ['breakfast', 'lunch', 'dinner']:
        res_count+=1
res_count=res_count/(day_count(plan))
result=res_count/3
"""
DEFAULT_PR=[
    DEFAULT_ATTRACTION_PR,
    DEFAULT_TRANS_PR,
    DEFAULT_RES_PR
]

METHOD_LIST = [
]

from tqdm import tqdm
from chinatravel.symbol_verification.concept_func import func_dict
from copy import deepcopy

def cal_default_pr_score(query_index, query_data, result_data,all_pass_id):
    all_score=[]
    def clamp(value):
        return max(0.0, min(1.0, value))

    for ii, idx in enumerate(tqdm(query_index)):
        symbolic_input, plan = query_data[idx], result_data[idx]
        results = []
        if idx not in all_pass_id:
            results=np.zeros(len(DEFAULT_PR))
            continue
        for constraint in DEFAULT_PR:
            vars_dict = deepcopy(func_dict)
            vars_dict["plan"] = plan

            # exec(constraint, {"__builtins__": {"set": set, "print": print}}, vars_dict)
            # results.append(vars_dict.get("result", False))
            try:
                # Evaluate the constraint in a safe manner
                exec(
                    constraint,
                    {
                        "__builtins__": {
                            "set": set,
                        }
                    },
                    vars_dict,
                )
                res_i = vars_dict.get("result", False)
                # print("result: ", res_i)
                # print(type(res_i))
                results.append(clamp(res_i))
            except Exception as e:
                results.append(0.)
        all_score.append(np.array(results))
    if len(all_score)==0:
        return np.zeros(len(DEFAULT_PR))
    print(np.mean(all_score,axis=0))
    return np.mean(all_score,axis=0)


def cal_per_query_pr_scores(query_index, result_data, all_pass_id):
    """Return a dict mapping query_id -> np.array of per-query DEFAULT_PR scores.

    Queries not in all_pass_id receive zeros (consistent with cal_default_pr_score).
    """
    def clamp(value):
        return max(0.0, min(1.0, value))

    per_query = {}
    for idx in query_index:
        if idx not in all_pass_id:
            per_query[idx] = np.zeros(len(DEFAULT_PR))
            continue
        plan = result_data[idx]
        results = []
        for constraint in DEFAULT_PR:
            vars_dict = deepcopy(func_dict)
            vars_dict["plan"] = plan
            try:
                exec(
                    constraint,
                    {"__builtins__": {"set": set}},
                    vars_dict,
                )
                res_i = vars_dict.get("result", False)
                results.append(clamp(res_i))
            except Exception:
                results.append(0.)
        per_query[idx] = np.array(results)
    return per_query


def load_result(args, query_index,path, verbose=False):

    def load_result_for_method(path):
        plans = {}
        for query_id in query_index:
            result_file = os.path.join(
                path, "{}.json".format(query_id)
            )

            try:
                if os.path.exists(result_file):
                    result = load_json_file(result_file)
                    plans[query_id] = result
                else:
                    plans[query_id] = {}
            except:
                plans[query_id] = {}
        return plans

    result = {}

    result['default'] = load_result_for_method(path)

    if verbose:
        print(result)

    return ['default'], result

def write_file(file, content):
    """ Write content in file.
    """
    with open(file, 'a', encoding="utf-8") as f:
        f.write(content)


def remove_query_ids_from_split_file(split_file_path, query_ids):
    """Remove query IDs from a split file and return the count removed."""
    if not query_ids or not os.path.exists(split_file_path):
        return 0

    query_id_set = {str(query_id).strip() for query_id in query_ids}
    if not query_id_set:
        return 0

    with open(split_file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines()]

    removed_count = 0
    kept_lines = []
    for line in lines:
        if line and line in query_id_set:
            removed_count += 1
            continue
        kept_lines.append(line)

    if removed_count > 0:
        with open(split_file_path, "w", encoding="utf-8") as f:
            if kept_lines:
                f.write("\n".join(kept_lines) + "\n")
            else:
                f.write("")

    return removed_count


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--splits", "-s", type=str, default="example")
    parser.add_argument(
        "--method", "-m", type=str, default="travel_agent"
    )  # , choices=METHOD_LIST)
    parser.add_argument("--index", "-id", type=str, default=None,
                        help="Evaluate only this single query ID")
    parser.add_argument("--preference", "-p", action="store_true", default=False)
    parser.add_argument("--lang", "--locale", choices=["zh", "en"], default="zh")
    parser.add_argument("--update_best", action="store_true", default=False,
                        help="Auto-update results/best and results/constraints_solved")
    args = parser.parse_args()
    if args.lang == "en" and not args.method.endswith("_en"):
        args.method += "_en"

    # print(args.splits)


    query_index, query_data = load_query(args)

    # Optionally restrict to a single query
    if args.index is not None:
        if args.index not in query_index:
            raise ValueError("Query ID '{}' not found in split '{}'".format(args.index, args.splits))
        query_index = [args.index]

    results_dir = os.path.join("results", args.method)
    method_list, result_data = load_result(args, query_index, results_dir)

    schema_file_path = 'chinatravel/evaluation/output_schema.json'
    schema = load_json_file(schema_file_path)


    scores = {}
    for method in method_list:




        print("Method: {}".format(args.method))

        if not os.path.exists("eval_res/splits_{}/{}/".format(args.splits, method)):
            os.makedirs("eval_res/splits_{}/{}/".format(args.splits, method))

        schema_rate, schema_result_agg, schema_pass_id = evaluate_schema_constraints(
            query_index, result_data[method], schema=schema
        )
        # print("Schema Pass Rate:", schema_rate)

        macro_comm, micro_comm, common_result_agg, commonsense_pass_id = evaluate_commonsense_constraints(
            query_index, query_data, result_data[method], verbose=False, lang=args.lang
        )

        # print("Commonsense constraints:")
        print("Mic.EPR {}".format(micro_comm))
        scores['MicEPR'] = micro_comm
        print("Mac.EPR: {}".format(macro_comm))
        scores['MacEPR'] = macro_comm

        # print("Logical constraints (python version):")
        macro_logi, micro_logi, conditional_macro_logi, conditional_micro_logi, logi_result_agg, logi_pass_id = evaluate_hard_constraints_v2(
            query_index, query_data, result_data[method], env_pass_id=commonsense_pass_id, verbose=False, lang=args.lang
        )




        print("C-LPR: {}".format(conditional_micro_logi))
        scores['C-LPR'] = conditional_micro_logi

        # record the index of the queries that pass the logical constraints
        logical_pass_info = logi_result_agg.iloc[:, 1:]
        id_list = logi_result_agg.iloc[:, 0].tolist()

        all_pass_id = list(set(schema_pass_id) & set(commonsense_pass_id) & set(logi_pass_id))


        print("FPR: ", 1. * len(all_pass_id) / len(query_index) * 100)
        fpr= 1. * len(all_pass_id) / len(query_index) * 100
        scores['FPR'] = fpr

        pre_res=cal_default_pr_score(query_index,query_data,result_data[method],all_pass_id)
        scores['DAV']=pre_res[0]*100
        scores['ATT']=pre_res[1]*100
        scores['DDR']=pre_res[2]*100

        final_score=0.1*micro_comm+0.1*micro_comm+0.25*conditional_micro_logi+0.05*scores['DAV']+0.05*scores['ATT']+0.05*scores['DDR']+0.4*fpr
        print('Overall Score: ',final_score)
        scores['overall'] = final_score
        print(scores)

        score_file = os.path.join('your_tpc_scores.json')
        write_file(score_file, json.dumps(scores))
        if args.preference:
            print("Preference:")
            result_agg = evaluate_preference_v2(
                query_index,
                query_data,
                result_data[method],
                list(set(commonsense_pass_id) & set(logi_pass_id)),
            )

        # ------------------------------------------------------------------ #
        # Auto-update results/constraints_solved and results/best             #
        # ------------------------------------------------------------------ #
        if not args.update_best:
            continue

        constraints_solved_dir = os.path.join(project_root_path, "results", "constraints_solved")
        best_dir = os.path.join(project_root_path, "results", "best")
        unsolved_split_file = os.path.join(
            project_root_path,
            "chinatravel",
            "evaluation",
            "default_splits",
            "tpc_phase1_constraints_unsolved.txt",
        )
        os.makedirs(constraints_solved_dir, exist_ok=True)
        os.makedirs(best_dir, exist_ok=True)

        # Per-query weighted score using the same weights as final_score above:
        #   0.1*commonsense + 0.1*commonsense + 0.25*logic + 0.05*DAV + 0.05*ATT + 0.05*DDR + 0.4*all_pass
        # (expressed in the 0-100 scale that matches micro_comm/conditional_micro_logi/fpr)
        commonsense_pass_set = set(commonsense_pass_id)
        logi_pass_set = set(logi_pass_id)
        all_pass_set = set(all_pass_id)

        per_query_pr = cal_per_query_pr_scores(query_index, result_data[method], all_pass_set)

        updated_constraints = 0
        updated_best = 0
        solved_query_ids = set()

        for query_id in query_index:
            src_file = os.path.join(project_root_path, "results", args.method, "{}.json".format(query_id))
            if not os.path.exists(src_file):
                continue

            comm_score = 100.0 if query_id in commonsense_pass_set else 0.0
            logic_score = 100.0 if query_id in logi_pass_set else 0.0
            all_pass_score = 100.0 if query_id in all_pass_set else 0.0
            pr = per_query_pr.get(query_id, np.zeros(len(DEFAULT_PR)))
            dav_score = pr[0] * 100
            att_score = pr[1] * 100
            ddr_score = pr[2] * 100

            current_score = (
                0.1 * comm_score
                + 0.1 * comm_score
                + 0.25 * logic_score
                + 0.05 * dav_score
                + 0.05 * att_score
                + 0.05 * ddr_score
                + 0.4 * all_pass_score
            )

            # -- constraints_solved: save if all hard constraints pass -------
            if query_id in all_pass_set:
                dest = os.path.join(constraints_solved_dir, "{}.json".format(query_id))
                shutil.copy2(src_file, dest)
                updated_constraints += 1
                solved_query_ids.add(query_id)

            # -- best: save if no previous result or current score is higher -
            best_file = os.path.join(best_dir, "{}.json".format(query_id))
            previous_score = -1.0
            if os.path.exists(best_file):
                try:
                    with open(best_file) as f:
                        stored = json.load(f)
                    previous_score = float(stored.get("_eval_score", 0))
                except Exception:
                    previous_score = -1.0

            if current_score > previous_score:
                try:
                    with open(src_file) as f:
                        result_copy = json.load(f)
                    result_copy["_eval_score"] = current_score
                    with open(best_file, "w") as f:
                        json.dump(result_copy, f, ensure_ascii=False, indent=2)
                except Exception:
                    shutil.copy2(src_file, best_file)
                updated_best += 1

        removed_unsolved = remove_query_ids_from_split_file(unsolved_split_file, solved_query_ids)
        print("constraints_solved: {} results saved/updated in {}".format(
            updated_constraints, constraints_solved_dir))
        print("constraints_unsolved: {} query IDs removed from {}".format(
            removed_unsolved, unsolved_split_file))
        print("best: {} results updated in {}".format(updated_best, best_dir))
