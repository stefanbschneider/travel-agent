

import argparse
import shutil

import numpy as np

import sys
import os
import json
import fcntl
from concurrent.futures import ThreadPoolExecutor

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


def _method_has_en_suffix(method):
    base_method = method.split("_oracletranslation")[0].split("_oracle_translation")[0]
    return base_method.endswith("_en")


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
        def _load_one(query_id):
            result_file = os.path.join(path, "{}.json".format(query_id))
            try:
                if os.path.exists(result_file):
                    return query_id, load_json_file(result_file)
            except Exception:
                pass
            return query_id, {}

        max_workers = min(32, (os.cpu_count() or 4) * 4)
        plans = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for query_id, result in pool.map(_load_one, query_index):
                plans[query_id] = result
        return plans

    result = {}

    result['default'] = load_result_for_method(path)

    if verbose:
        print(result)

    return ['default'], result

def write_file(file, content):
    """Append content to file under a process lock."""
    lock_dir = os.path.join(project_root_path, "cache", "eval_locks")
    os.makedirs(lock_dir, exist_ok=True)
    lock_file_path = os.path.join(lock_dir, "{}.lock".format(os.path.basename(file)))
    with open(lock_file_path, "a", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            with open(file, 'a', encoding="utf-8") as f:
                f.write(content)
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def remove_query_ids_from_split_file(split_file_path, query_ids):
    """Remove query IDs from a split file and return the count removed."""
    if not query_ids or not os.path.exists(split_file_path):
        return 0

    query_id_set = {str(query_id).strip() for query_id in query_ids}
    if not query_id_set:
        return 0

    lock_dir = os.path.join(project_root_path, "cache", "eval_locks")
    os.makedirs(lock_dir, exist_ok=True)
    lock_file_path = os.path.join(lock_dir, "{}.lock".format(os.path.basename(split_file_path)))

    with open(lock_file_path, "a", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
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
                tmp_file_path = "{}.{}.tmp".format(split_file_path, os.getpid())
                with open(tmp_file_path, "w", encoding="utf-8") as f:
                    if kept_lines:
                        f.write("\n".join(kept_lines) + "\n")
                    else:
                        f.write("")
                os.replace(tmp_file_path, split_file_path)
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)

    return removed_count


def write_suboptimal_split_file(source_split_path, suboptimal_split_path, solved_query_ids):
    """Write a split copy excluding solved/optimal query IDs, preserving order."""
    if not os.path.exists(source_split_path):
        return 0, 0

    solved_set = {str(query_id).strip() for query_id in solved_query_ids}

    lock_dir = os.path.join(project_root_path, "cache", "eval_locks")
    os.makedirs(lock_dir, exist_ok=True)
    lock_file_path = os.path.join(lock_dir, "{}.lock".format(os.path.basename(suboptimal_split_path)))

    with open(lock_file_path, "a", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            with open(source_split_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines()]

            kept_lines = []
            removed_count = 0
            for line in lines:
                if not line:
                    continue
                if line in solved_set:
                    removed_count += 1
                    continue
                kept_lines.append(line)

            tmp_file_path = "{}.{}.tmp".format(suboptimal_split_path, os.getpid())
            with open(tmp_file_path, "w", encoding="utf-8") as f:
                if kept_lines:
                    f.write("\n".join(kept_lines) + "\n")
                else:
                    f.write("")
            os.replace(tmp_file_path, suboptimal_split_path)
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)

    return len(kept_lines), removed_count


def _resolve_method_dir(method, lang):
    """Pick the results directory name for a method under a locale.

    For English runs, many methods use an `_en` suffix. However, shared
    aggregate directories like `best` and `constraints_solved` typically do not.
    Prefer an existing directory if available.
    """
    if lang != "en" or method.endswith("_en"):
        return method

    method_dir = os.path.join("results", method)
    method_en = "{}_en".format(method)
    method_en_dir = os.path.join("results", method_en)

    if os.path.exists(method_dir):
        return method
    if os.path.exists(method_en_dir):
        return method_en

    # Keep unsuffixed names for common aggregate folders even if not created yet.
    if method in {"best", "constraints_solved", "optimal"}:
        return method

    return method_en


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--splits", "-s", type=str, default="tpc_phase1")
    parser.add_argument(
        "--method", "-m", type=str, default="TPCAgent_TPCLLM_en"
    )  # , choices=METHOD_LIST)
    parser.add_argument("--index", "-id", type=str, default=None,
                        help="Evaluate only this single query ID")
    parser.add_argument("--preference", "-p", action="store_true", default=False)
    parser.add_argument("--lang", "--locale", choices=["zh", "en"], default="en")
    parser.add_argument("--update_best", action="store_true", default=False,
                        help="Auto-update results/best and results/constraints_solved")
    args = parser.parse_args()
    # Commented out to properly score our best results (without _en suffix). This is different upstream! Check phase 2 harness against upstream scoring.
    # if args.lang == "en" and not _method_has_en_suffix(args.method):
    #     args.method += "_en"

    # print(args.splits)


    query_index, query_data = load_query(args)

    missing_query_ids = [query_id for query_id in query_index if query_id not in query_data]

    # If default zh loading misses IDs but English data exists, auto-fallback.
    if missing_query_ids and args.lang != "en":
        args_for_en = argparse.Namespace(**vars(args))
        args_for_en.lang = "en"
        en_query_index, en_query_data = load_query(args_for_en)
        en_missing = [query_id for query_id in query_index if query_id not in en_query_data]
        if not en_missing:
            args.lang = "en"
            query_index, query_data = en_query_index, en_query_data
            missing_query_ids = []

    if missing_query_ids:
        sample_missing = ", ".join(missing_query_ids[:5])
        raise RuntimeError(
            "Failed to load all query files for split '{}'. Missing {} IDs (examples: {}). "
            "Check dataset files under chinatravel/data and use --lang en if your data is English.".format(
                args.splits, len(missing_query_ids), sample_missing
            )
        )

    args.method = _resolve_method_dir(args.method, args.lang)

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

        # Leaderboard-parity weighting: the current competition scorer still doubles EPR-micro.
        final_score=0.1*micro_comm+0.1*micro_comm+0.25*conditional_micro_logi+0.05*scores['DAV']+0.05*scores['ATT']+0.05*scores['DDR']+0.4*fpr
        # Official documented weights: 10% EPR-micro + 10% EPR-macro.
        final_score_official=0.1*micro_comm+0.1*macro_comm+0.25*conditional_micro_logi+0.05*scores['DAV']+0.05*scores['ATT']+0.05*scores['DDR']+0.4*fpr
        print('Overall Score (leaderboard 2x-micro): ', final_score)
        print('Overall Score (official micro+macro): ', final_score_official)
        scores['overall'] = final_score
        scores['overall_official'] = final_score_official
        print(scores)

        # ------------------------------------------------------------------ #
        # Auto-promote optimal best plans and maintain a suboptimal split     #
        # ------------------------------------------------------------------ #
        if args.method == "best":
            optimal_dir = os.path.join(project_root_path, "results", "optimal")
            os.makedirs(optimal_dir, exist_ok=True)

            source_split_file = os.path.join(
                project_root_path,
                "chinatravel",
                "evaluation",
                "default_splits",
                "{}.txt".format(args.splits),
            )
            suboptimal_split_file = os.path.join(
                project_root_path,
                "chinatravel",
                "evaluation",
                "default_splits",
                "{}_suboptimal.txt".format(args.splits),
            )

            commonsense_pass_set = set(commonsense_pass_id)
            logi_pass_set = set(logi_pass_id)
            all_pass_set = set(all_pass_id)
            per_query_pr_for_best = cal_per_query_pr_scores(query_index, result_data[method], set(all_pass_id))

            optimal_query_ids = set()
            optimal_copied = 0
            optimal_already_present = 0
            max_workers = min(32, (os.cpu_count() or 4) * 4)

            def _is_optimal(query_id):
                comm_score = 100.0 if query_id in commonsense_pass_set else 0.0
                logic_score = 100.0 if query_id in logi_pass_set else 0.0
                all_pass_score = 100.0 if query_id in all_pass_set else 0.0
                pr = per_query_pr_for_best.get(query_id, np.zeros(len(DEFAULT_PR)))
                dav_score = pr[0] * 100
                att_score = pr[1] * 100
                ddr_score = pr[2] * 100
                score = (
                    0.1 * comm_score
                    + 0.1 * comm_score
                    + 0.25 * logic_score
                    + 0.05 * dav_score
                    + 0.05 * att_score
                    + 0.05 * ddr_score
                    + 0.4 * all_pass_score
                )
                return query_id, score >= (100.0 - 1e-9)

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for query_id, is_optimal in pool.map(_is_optimal, query_index):
                    if is_optimal:
                        optimal_query_ids.add(query_id)

            for query_id in optimal_query_ids:
                src_file = os.path.join(project_root_path, "results", "best", "{}.json".format(query_id))
                dest_file = os.path.join(optimal_dir, "{}.json".format(query_id))
                if not os.path.exists(src_file):
                    continue
                if os.path.exists(dest_file):
                    optimal_already_present += 1
                    continue
                shutil.copy2(src_file, dest_file)
                optimal_copied += 1

            remaining_suboptimal = -1
            removed_suboptimal = 0
            if os.path.exists(source_split_file):
                remaining_suboptimal, removed_suboptimal = write_suboptimal_split_file(
                    source_split_file,
                    suboptimal_split_file,
                    optimal_query_ids,
                )
            else:
                print("suboptimal split skipped: source split file missing ({})".format(source_split_file))

            print(
                "optimal: {} total optimal ids in eval, {} newly copied, {} already present in {}".format(
                    len(optimal_query_ids), optimal_copied, optimal_already_present, optimal_dir
                )
            )
            if remaining_suboptimal >= 0:
                print(
                    "suboptimal split: {} ids remaining in {} ({} removed this run)".format(
                        remaining_suboptimal, suboptimal_split_file, removed_suboptimal
                    )
                )

        score_file = os.path.join('your_tpc_scores.json')
        write_file(score_file, json.dumps(scores))
        if args.preference:
            print("Preference:")
            result_agg = evaluate_preference_v2(
                query_index,
                query_data,
                result_data[method],
                list(set(commonsense_pass_id) & set(logi_pass_id)),
                lang=args.lang,
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

        def _prev_score(query_id):
            best_file = os.path.join(best_dir, "{}.json".format(query_id))
            if not os.path.exists(best_file):
                return query_id, -1.0
            try:
                with open(best_file) as f:
                    stored = json.load(f)
                return query_id, float(stored.get("_eval_score", 0))
            except Exception:
                return query_id, -1.0

        prev_scores = {}
        with ThreadPoolExecutor(max_workers=min(32, (os.cpu_count() or 4) * 4)) as pool:
            for query_id, score in pool.map(_prev_score, query_index):
                prev_scores[query_id] = score

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
                solved_query_ids.add(query_id)
                dest = os.path.join(constraints_solved_dir, "{}.json".format(query_id))
                if not os.path.exists(dest):
                    shutil.copy2(src_file, dest)
                    updated_constraints += 1

            # -- best: save if no previous result or current score is higher -
            best_file = os.path.join(best_dir, "{}.json".format(query_id))
            previous_score = prev_scores.get(query_id, -1.0)

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
