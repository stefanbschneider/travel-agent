## Current upstream evaluation state

These notes track the organizers' benchmark (github.com/LAMDASZ-ML/ChinaTravel) and the
leaderboard scoring server so local evaluation stays aligned with current upstream
behavior.

1. Concept-name canonicalization is fixed in current upstream main.
    The verifier now normalizes equivalent labels such as "Swimming pool" / "Swimming Pool",
    "cafe" / "coffee shop", and "university campus" / "University campus" before evaluation,
    so the earlier case-sensitive unsatisfiable-query issue no longer applies to the latest
    competition code.

2. Overall score still double-counts EPR-micro on the leaderboard.
    eval_tpc.py:343 computes 0.1*EPR_micro + 0.1*EPR_micro instead of the documented
    0.1*EPR_micro + 0.1*EPR_macro, so the leaderboard "overall" weights EPR-micro twice
    and ignores EPR-macro. We keep this verbatim as `overall` for leaderboard parity and
    additionally report the corrected `overall_official` (eval_tpc.py:345). The two differ
    only when EPR-micro != EPR-macro.

**Important links:**

- Competition website: https://chinatravel-competition.github.io/IJCAI2026/
- ChinaTravel GitHub repo: https://github.com/LAMDA-NeSy/ChinaTravel
- Local upstream divergence report: `docs/upstream_divergence.md`

**Competition docs in this repo:**

- `docs/tpc_phase1_playbook.md` — Phase 1 public-leaderboard strategy, workflows, and operating commands
- `docs/tpc_phase2_design.md` — Phase 2 rules interpretation, harness architecture, and no-oracle approach
- `docs/tpc_phase2_eval.md` — Phase 2 evaluation methodology (three axes, attribution, regression gate)
- `docs/tpc_phase2_implementation_plan.md` — step-by-step build plan for the Phase 2 skeleton harness + eval pipeline
- `docs/tpc_phase2_hf_dataset.md` — note on the Hugging Face `LAMDA-NeSy/ChinaTravel` dataset vs local data
- `AGENT_DESIGN.md` — shared overview of the current TPCAgent stack and how it bridges both phases
- `IJCAI2026_competition.md` — source-based summary of the official competition pages

**Important commands:**

The commands and score snapshots in the next section are primarily for **Phase 1** work.
Phase 1 is an offline prediction-generation problem on the released dataset, where the
current workflow intentionally uses oracle hard constraints (`hard_logic_py`) to maximize
public leaderboard score. Phase 2 has a different execution model: per-query harness runs,
held-out queries, no oracle verifier fields visible to the agent, and bounded runtime.

## Phase 1 Operations

Latest verified score snapshot (`results/best`, 2026-06-22):

- Overall: 95.4340 (official: 95.4340)
- FPR: 98.9000
- C-LPR: 99.5796
- MicEPR/MacEPR: 100.0000 / 100.0000
- DAV/ATT/DDR: 67.5720 / 82.4808 / 69.5298

`TPCAgent` runs a per-query oracle-guided search. Drive it with the resumable scripts in
`scripts/` (run from the repo root); they wrap `run_tpc.py`/`eval_tpc.py` and keep all state on
disk, so every step is kill/resume-safe.

Heavy resumable search over the still-unsolved queries (stops when a round adds nothing).
`--workers` defaults to all cores and runs that many `run_tpc.py` processes over disjoint
query shards:
```
python scripts/iterate_unsolved.py --rounds 10 --restarts 800 --budget 240 --workers 8
```

Execution profiles (recommended):

- Short local run (~10 min, M1 MacBook):
```
make short-local
```

- Long local overnight (~7 h, M1 MacBook):
```
make overnight-local
```

- Local preference-only optimization on already-valid plans:
```
make preference-local
```

- Quick local preference pass (single round):
```
make preference-quick
```

- Long overnight HPC run via SLURM:
```
make hpc-tail-submit
```
See `slurm/README_tail_hpc.md` for resource/profile overrides.

- Two-phase HPC workflow (recommended for preference pushing):
```
# Phase A: solve unresolved hard-constraint tail
make hpc-unsolved

# Phase B: improve preference on already-solved plans (constraint-safe densify)
make hpc-preference

# Same Phase B submitted as one SLURM controller job
make hpc-preference-submit
```
The two-phase split avoids spending all rounds on the same hard-unsolved IDs and
lets preference optimization focus on accepted plans.

Light pass + constraint-safe packing across all 1000 (lifts DAV/DDR; the monotonic merge keeps
the heavy gains):
```
python scripts/solve.py --split tpc_phase1 --restarts 40 --budget 30 --workers 8
python scripts/merge.py --split tpc_phase1
```

Tail-prioritized rerun queue (score gap + hard-logic failure signature), then solve/merge only
the highest-leverage IDs:
```
python scripts/rank_tail.py --split tpc_phase1 --method best --top-k 150 --min-score 99
python scripts/solve.py --split tpc_phase1_tail_focus --restarts 1200 --budget 300 --workers 8
python scripts/merge.py --split tpc_phase1_tail_focus
```
`scripts/rank_tail.py` writes:
- ranking report: `cache/tail_rankings/<split>_<method>_tail_ranking.csv`
- focused split: `chinatravel/evaluation/default_splits/<split>_tail_focus.txt`
- incremental scan cache: `cache/tail_rankings/<split>_<method>_ms<min_score>_rank_cache.json`

`scripts/rank_tail.py` now supports explicit modes:
- `--mode tail`: mixed low-score tail (legacy behavior)
- `--mode unsolved`: prioritize unresolved hard-constraint failures
- `--mode preference`: prioritize already-accepted plans with the most preference headroom

`scripts/iterate_tail.py` can now run either solver search or preference densification per round:
- `--runner solve`: call `scripts/solve.py` on the focused split
- `--runner densify`: call `scripts/densify.py` on the focused split

Recommended tail-optimization loop (repeat cached rank -> solve -> merge until progress flattens, then score the full set once):
```
# 1) Refresh the lowest-score queue from current results/best; unchanged plans reuse the rank cache
python scripts/rank_tail.py --split tpc_phase1 --method best --top-k 120 --min-score 99

# 2) Run heavier search only on this focused split
python scripts/solve.py --split tpc_phase1_tail_focus --restarts 1200 --budget 300 --workers 8

# 3) Monotonic merge; merge evaluates the focus split and appends per-round metrics
python scripts/merge.py --split tpc_phase1_tail_focus

# 4) After the loop, score results/best once on the base split
python scripts/score.py --split tpc_phase1
```

How to read the ranking report (`cache/tail_rankings/...csv`):
- `score`: current per-query `_eval_score` from `results/best/<uid>.json`.
- `priority`: ranking objective used to build the focused split (higher means more leverage).
- `failed_clauses`: number of failed `hard_logic_py` clauses under current plan.
- `top_signature` / `top_failed_funcs`: dominant failure pattern for targeted repairs.

Or run the default preference pipeline (preference optimize -> score -> zip) with one command
(see the `Makefile` for tunable variables):
```
make
```

Print the headline metrics for `results/best`, build the submission zip, then upload it to the
competition portal (Seafile at box.nju.edu.cn):
```
python scripts/score.py
python scripts/assemble_submission.py   # build submissions/fabiundstefan_v<N>.zip
python scripts/submit.py                # upload the newest built zip to the portal
```
Or with make: `make submission` then `make upload` (preview the target first with `make upload-check`).

> After uploading `submissions/fabiundstefan_v<N>.zip`, freeze that version with a git tag so it is
> never mutated again, then share it: `git tag v<N> && git push origin --tags`. Rebuild a previously
> submitted version with `python scripts/assemble_submission.py --version v<N>`.

Low-level equivalents (the scripts add the required flags for you). The oracle path MUST pass
`--oracle_translation`, otherwise `run_tpc.py` strips `hard_logic_py` from the query dict and the
search runs blind:
```
python run_tpc.py --splits tpc_phase1 --agent TPCAgent --llm TPCLLM --lang en --oracle_translation
python eval_tpc.py --splits tpc_phase1 --method best --lang en
```

Knobs (env vars, read by `TPCAgent`): `TPC_MAX_RESTARTS`, `TPC_SOLVE_BUDGET_SEC`, `TPC_SEED_SALT`,
`TPC_USE_ORACLE` (`0` enables the Phase-2 path: constraints parsed live from the query text and
checked by `chinatravel/agent/tpc_agent/parsed_verifier.py`; `scripts/solve.py --no-oracle`).
`scripts/diagnose_failures.py` (read-only) tallies which constraint clauses still fail.
`scripts/rank_tail.py` (does not mutate `results/best`) ranks low-score queries by score gap + hard-logic failure
signature, writes a focused split for targeted reruns, and caches per-query scan primitives in
`cache/tail_rankings/<split>_<method>_ms<min_score>_rank_cache.json`.
`scripts/slack_report.py` (read-only) estimates per-passing-plan DAV slack (idle daytime weighed
against budget/time constraints) to show where more attractions can be packed safely.
`eval_tpc.py` / `scripts/score.py` report two overall scores: `overall` (the current
leaderboard formula, which still doubles EPR-micro) and `overall_official` (the documented
10% EPR-micro + 10% EPR-macro).

For the detailed Phase 1 operating model and what transfers cleanly to Phase 2, see
`docs/tpc_phase1_playbook.md`.

## Phase 2 Operations

Phase 2 is the final harness: per-query, held-out queries, **no oracle**, bounded per-query budget,
fixed Qwen model. Our harness does no-oracle parsing + orchestration around the deterministic
TPCAgent. **The LLM is off by default, so none of these commands make API calls.** All Python entry
points use the venv interpreter (`.venv/bin/python`); the `make` targets already do. See
`docs/tpc_phase2_design.md` and `docs/tpc_phase2_eval.md`, and run `make phase2-help` for the full
target list.

Suggested first pass: run the tests, then the parsing report (fast, shows the parsing gap without the
solver), then a small end-to-end solve.

Tests (fast; no solver/LLM):
```
make phase2-test                            # unit suite (LLM/WorldEnv-free)
.venv/bin/python -m pytest -m integration   # opt-in: real WorldEnv + TPCAgent (~1-2 min)
```

Create the validation / held-out-test split files (one-time, idempotent):
```
make phase2-splits
```

Parsing-quality report — fastest real signal (no solver, seconds). Shows how well the no-oracle
parser recovers constraints vs the oracle (precision / recall / value-accuracy, disjunction
flattening, and behavioral equivalence):
```
.venv/bin/python scripts/parser_vs_oracle.py --split-set val --limit 20 --behavioral
make phase2-parser-report P2_LIMIT=20
```

Run the harness end-to-end (invokes the real solver; use a small `--limit`/`--budget-sec` locally —
the 900s default is the full Phase-2 budget):
```
.venv/bin/python agent_env/scripts/solve_phase2.py --split tpc_phase1 --limit 3 --budget-sec 60
make phase2-solve P2_LIMIT=3 P2_BUDGET=60
```
Outputs: `results/<method>/<uid>.json` plus per-query
`agent_env/runs/<method>/<uid>/{output,telemetry,evaluation}.json`.

Rehearsal + three-way attribution (heaviest: runs both the no-oracle and oracle-fed solver). Prints
`ceiling | solver-only | end-to-end (solver headroom, parsing loss)`. Folds are drawn from the
validation split; add `--split-set test` (sparingly) for the held-out set:
```
# quick smoke: 1-query fold, small budget
.venv/bin/python scripts/rehearse_phase2.py --mode both --split-set val --fold 0 --folds 850 --budget-sec 30
# full dashboard (rehearse -> parser report -> timing)
make phase2-rehearse FOLD=0 P2_FOLDS=850 P2_LIMIT=1 P2_BUDGET=30
```

Timing / reliability from a completed run dir, and the monotonic regression gate:
```
.venv/bin/python scripts/phase2_timing.py --work-dir agent_env/runs/phase2_skeleton --budget-sec 900
.venv/bin/python scripts/phase2_gate.py --baseline base.json --candidate cand.json
```

Compare the Hugging Face `LAMDA-NeSy/ChinaTravel` dataset (generalization set) to local data
(network):
```
.venv/bin/python scripts/compare_hf_dataset.py --hf-config default
```

The (currently no-op) LLM stubs are exercised by setting `TPC_P2_LLM_BACKEND=fixture` plus the
relevant `TPC_P2_LLM_PARSE` / `TPC_P2_DISJUNCTION` / `TPC_P2_LLM_REFINE=1`.

**Notes:**

Fixed setup:

- I downloaded and added the environment datasets in English and Chinese from Google Drive and put them into the enviornment folder
- I downloaded and put the competition queries into the correct data/en/ folder
- I added the competition eval split to `chinatravel/evaluation/default_splits/tpc_phase1.txt`
- I removed all these files from gitignore, so that I can easily add and commit them




<center>
  <h1> [ICLR'26] ChinaTravel: A Real-World Benchmark for Language Agents in Chinese Travel Planning 
</h1>
</center>

Official codebase for the paper "ChinaTravel: A Real-World Benchmark for Language Agents in Chinese Travel Planning".

<!-- | [Webpage](https://www.lamda.nju.edu.cn/shaojj/chinatravel/) | [Paper](https://arxiv.org/abs/2412.13682) | [Dataset(Huggingface)](https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel)| -->

[![Webpage](https://img.shields.io/badge/Webpage-Visit-blue)](https://www.lamda.nju.edu.cn/shaojj/chinatravel/)
[![Paper](https://img.shields.io/badge/Paper-View-red)](https://arxiv.org/abs/2412.13682)
[![Dataset(Huggingface)](https://img.shields.io/badge/Dataset-Huggingface-yellow)](https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel)
[![Competition(TPC@IJCAI2025)](https://img.shields.io/badge/IJCAI%20Competition-TPC@IJCAI2025-green)](https://chinatravel-competition.github.io/IJCAI2025/)
[![Competition(TPC@AIC2025)](https://img.shields.io/badge/AIC%20Competition-TPC@AIC2025-green)](TPC@AIC2025/readme.md)
[![Competition(TPC@IJCAI2026)](https://img.shields.io/badge/IJCAI%20Competition-TPC@IJCAI2026-green)](https://chinatravel-competition.github.io/IJCAI2026/)


<!-- 
![Overview](images/overview.png) -->

## 🏆 IJCAI 2026 Travel Planning Challenge (TPC@IJCAI)

We are proud to announce that ChinaTravel has been selected as the official benchmark for the **Travel Planning Challenge (TPC) @ IJCAI 2026**!

**Official Competition Website**:
[https://chinatravel-competition.github.io/IJCAI2026/](https://chinatravel-competition.github.io/IJCAI2026/)

Participants are invited to develop novel agentic system that can tackle real-world travel planning scenarios under practical requirements. This competition will showcase state-of-the-art approaches in agentic AI research.


## 🏆 IJCAI 2025 Travel Planning Challenge (TPC@IJCAI)

We are proud to announce that ChinaTravel has been selected as the official benchmark for the **Travel Planning Challenge (TPC) @ IJCAI 2025**!

**Official Competition Website**:
[https://chinatravel-competition.github.io/IJCAI2025/](https://chinatravel-competition.github.io/IJCAI2025/)

Participants are invited to develop novel agents that can tackle real-world travel planning scenarios under complex constraints. This competition will showcase state-of-the-art approaches in language agent research.

## 📝 ChangeLog

### 2025.09
1. Upload the champion solution of TPC@IJCAI2025 DSL track. Thanks the [@evergreenee](https://github.com/evergreenee) for their contributions.  


### 2025.06

1. Fix error collection in the evaluation code of commonsense. 
2. Fix pure-neuro agent's pipeline
3. Fix load_datasets from huggingface
4. Update exception handling in syntax verification


### 2025.05

1. Update logs for the latest version.
2. Provide the evaluation code for the TPC.

### 2025.04

1. Added local data loader. Users can now load custom queries locally. When specifying non-default splits_name values (e.g., "abc") for "run_exp.py", the system will automatically load corresponding files from evaluation/default_splits/abc.txt, where the TXT file contains the target query filenames.
2. Detailed constraints classification. See detailed docs at [Evaluation README](chinatravel/symbol_verification/readme.md)
3. Introduced LLM-modulo baseline
   Implement the LLM-modulo pipeline with a ground-truth symbolic verifier.
   Based on methodology from:
   Paper: Robust Planning with Compound LLM Architectures: An LLM-Modulo Approach
   Codebase: https://github.com/Atharva-Gundawar/LLM-Modulo-prompts
4. Support local LLMs inference with Qwen3-8B/4B.

## 🚀 Quick Start

### ⚙️ Setup

1. Create a conda environment and install dependencies:

```bash
conda create -n chinatravel python=3.9  
conda activate chinatravel  
pip install -r requirements.txt  
```

2. Download the database and unzip it to the "chinatravel/environment/" directory

Download Links: [Google Drive](https://drive.google.com/drive/folders/1bJ7jA5cfExO_NKxKfi9qgcxEbkYeSdAU), [NJU Drive](https://box.nju.edu.cn/d/dd83e5a4a9e242ed8eb4/)

3. Download the open-source LLMs (optional).

```bash
bash download_llm.sh
```

4. Download the tokenizers.

```bash
wget https://cdn.deepseek.com/api-docs/deepseek_v3_tokenizer.zip -P chinatravel/local_llm/
unzip chinatravel/local_llm/deepseek_v3_tokenizer.zip -d chinatravel/local_llm/
```

### ▶️ Running

We support the deepseek (offical API from deepseek), gpt-4o (chatgpt-4o-latest), glm4-plus, and local inferences with Qwen (Qwen3-8B), llama, mistral (Mistral-7B-Instruct-v0.3), etc.

```bash
export OPENAI_API_KEY=""

python run_exp.py --splits easy --agent LLMNeSy --llm deepseek --oracle_translation
python run_exp.py --splits medium --agent LLMNeSy --llm deepseek --oracle_translation
python run_exp.py --splits human --agent LLMNeSy --llm deepseek --oracle_translation

python run_exp.py --splits human --agent LLMNeSy --llm Qwen3-8B --oracle_translation


python run_exp.py --splits human --agent LLMNeSy --llm deepseek 
python run_exp.py --splits human --agent LLMNeSy --llm Qwen3-8B 


python run_exp.py --splits human --agent LLM-modulo --llm deepseek --refine_steps 10 --oracle_translation
python run_exp.py --splits human --agent LLM-modulo --llm Qwen3-8B --refine_steps 10 --oracle_translation
```

**Note**:

- The `--oracle_translation` flag enables access to annotated ground truth including:

  - `hard_logic_py`: Executable verification DSL code
  - `hard_logic_nl`: The corrsponding constraint descriptions
  - Example annotation structure:

  ```python
  {
    "hard_logic_py": [
      "
      total_cost=0 
      for activity in allactivities(plan):
          total_cost+=activity_cost(activity)
              total_cost += innercity_transport_cost(activity_transports(activity))
      result=(total_cost<=1000)
      ", 
      "
      innercity_transport_set=set()
      for activity in allactivities(plan):
          if activity_transports(activity)!=[]:              
              innercity_transport_set.add(innercity_transport_type(activity_transports(activity)))
      result=(innercity_transport_set<={'taxi'})
      "
    ], 
    "hard_logic_nl": ["总预算为1800元", "市内交通选择taxi"], 
  }
  ```
- LLM-modulo method **requires** oracle_translation mode for its symbolic refinement process

### 📊 Evaluation

```bash
python eval_exp.py --splits human --method LLMNeSy_deepseek_oracletranslation
python eval_exp.py --splits human --method LLMNeSy_deepseek
python eval_exp.py --splits human --method LLM-modulo_deepseek_10steps_oracletranslation
python eval_exp.py --splits human --method LLM-modulo_Qwen3-8B_10steps_oracletranslation

```

In TPC@IJCAI2025, the evaluation code is provided in the `eval_tpc.py` file. You can run the evaluation code as follows:

```bash
python eval_tpc.py --splits tpc_phase1 --method YOUR_METHOD_NAME
```

### Evaluation Metrics

The overall score is a weighted combination of the following metrics, evaluated in a cascading fashion (each level gates the next):

#### 1. Schema Constraint (gate)

Validates that the output JSON conforms to the expected structure (`chinatravel/evaluation/output_schema.json`). Plans that fail are immediately invalid and score 0 on all downstream metrics.

#### 2. Commonsense Constraints — Mic.EPR / Mac.EPR (weight: 0.2)

Checks that the plan is factually consistent with the environment database across 7 categories:

| Check | What it verifies |
|-------|-----------------|
| Intercity transport | Flight/train ID exists with correct times and endpoints |
| Attractions | Named attractions exist in the target city's database |
| Hotels | Named hotel exists |
| Restaurants | Named restaurant exists |
| Inner-city transport | Metro/taxi/walk routes are valid |
| Time | No overlapping activities, correct chronological ordering |
| Space | Sequential locations are reachable from the prior position |

- **Mic.EPR** (micro): percentage of individual constraint checks passed across all queries.
- **Mac.EPR** (macro): average per-query pass rate.

#### 3. Conditional Logical Pass Rate — C-LPR (weight: 0.25)

Evaluates query-specific hard constraints (budget limits, required transport types, must-visit attractions, hotel/room requirements, etc.) encoded as executable DSL snippets in `hard_logic_py`. Only evaluated on queries that already pass all commonsense constraints.

#### 4. Full Pass Rate — FPR (weight: 0.4)

Percentage of queries that pass **all three** constraint levels (schema ∩ commonsense ∩ logical). This is the strictest and highest-weighted metric.

#### 5. Preference / Quality Scores (weight: 0.05 each, only for fully-passing plans)

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| **DAV** (Daily Attraction Visits) | `attraction_count / (4 × days)` | Targets 4 attractions per day |
| **ATT** (Average Transport Time) | `(-1/105) × avg_minutes + 8/7` | Penalizes long commutes; shorter is better |
| **DDR** (Daily Dining Rate) | `(meals_per_day) / 3` | Targets 3 meals (breakfast + lunch + dinner) per day |

All preference scores are clamped to [0, 1] then reported as percentages (0–100).

#### Overall Score Formula

```
Overall = 0.1×Mic.EPR + 0.1×Mic.EPR + 0.25×C-LPR + 0.05×DAV + 0.05×ATT + 0.05×DDR + 0.4×FPR
```

> **Note:** The leaderboard formula double-counts Mic.EPR (0.1 + 0.1) instead of using 0.1×Mic.EPR + 0.1×Mac.EPR as documented. We replicate this for leaderboard parity. See "Current upstream evaluation state" at the top of this file.

## 📚 Docs

[Environment](chinatravel/environment/readme.md)
[Constraints](chinatravel/symbol_verification/readme.md)

## 🛠️ Advanced Development

### 1. Develop Your Own Agent Algorithm

To develop your own agent algorithm, you need to inherit the `BaseAgent` class from `chinatravel/agent/base.py` and add the logic for your algorithm to the `init_agent` function in `chinatravel/agent/load_model.py`. We provide an empty agent example named `TPCAgent`.

Steps:

- **Inherit the `BaseAgent` class**: Create a new Python file in the `chinatravel/agent` directory and define your own agent class, inheriting from `BaseAgent`.

```python:chinatravel/agent/your_agent.py
from .base import BaseAgent

class YourAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Initialization logic

    def act(self, observation):
        # Implement the decision - making logic of the agent
        pass
```

- **Add code to the init_agent function**: Open the chinatravel/agent/load_model.py file and add support for your new agent in the init_agent function.

```python:
def init_agent(kwargs):
    # ... existing code ...
    elif kwargs["method"] == "YourMethodName":
        agent = YourAgent(
            **kwargs
        )
    # ... existing code ...
    return agent
```

### 2. Develop Your Own Local LLM

To develop your own local large - language model (LLM), you need to inherit the AbstractLLM class from chinatravel/agent/llms.py and add the corresponding local LLM inference code in llms.py. We provide an empty LLM example named TPCLLM.
Steps:

- **Inherit the AbstractLLM class**:  Define your own LLM class in the chinatravel/agent/llms.py file, inheriting from AbstractLLM.

```python
class YourLLM(AbstractLLM):
    def __init__(self):
        super().__init__()
        # Initialization logic
        self.name = "YourLLMName"

    def _get_response(self, messages, one_line, json_mode):
        # Implement the response logic of the LLM
        response = "Your LLM response"
        if json_mode:
            # Handle JSON mode
            pass
        elif one_line:
            # Handle one - line mode
            response = response.split("\n")[0]
        return response
```

- **Add code to the init_agent function**: Open the chinatravel/agent/load_model.py file and add support for your new llm in the init_llm function.

```python:
def init_llm(kwargs):
    # ... existing code ...
    elif llm_name == "glm4-plus":
        llm = YourLLM()
    # ... existing code ...
    return llm
```

### 3. Run Your Code Using Experiment Scripts

After completing the above development, you can use the experiment scripts to run your code.

Example of running:

```bash
python run_tpc.py --splits easy --agent TPCAgent --llm TPCLLM
python run_exp.py --splits easy --agent YourMethodName --llm YourLLMName
```

The results will be saved in the `results/YourMethodName_YourLLMName_xxx` directory, e.g., `results/TPCAgent_TPCLLM`.

## ✉️ Contact

If you have any problems, please contact [Jie-Jing Shao](shaojj@lamda.nju.edu.cn), [Bo-Wen Zhang](221900200@smail.nju.edu.cn), [Xiao-Wen Yang](yangxw@lamda.nju.edu.cn).

## 📌 Citation

If our paper or related resources prove valuable to your research, we kindly ask for citation.

```
@inproceedings{
shao2026chinatravel,
title={ChinaTravel: An Open-Ended Travel Planning Benchmark with Compositional Constraint Validation for Language Agents},
author={Jie-Jing Shao and Bo-Wen Zhang and Xiao-Wen Yang and Baizhi Chen and Siyu Han and Pang Jinghao and Wen-Da Wei and Guohao Cai and Zhenhua Dong and Lan-Zhe Guo and Yu-Feng Li},
booktitle={The Fourteenth International Conference on Learning Representations},
year={2026},
url={https://openreview.net/forum?id=0YRVlxY9BH}
}
```
