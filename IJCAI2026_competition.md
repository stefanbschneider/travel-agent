# The 2nd Travel Planning Challenge with Agentic AI

Source: https://chinatravel-competition.github.io/IJCAI2026/

## Overview

TPC 2026 is the second edition of the Travel Planning Challenge. It focuses on real-world travel planning in China, where language agents must convert open-ended traveler intent into feasible, preference-aligned, multi-day itineraries.

The competition emphasizes three main properties:

- Real-world grounding: queries and constraints are based on authentic Chinese travel scenarios, with transport networks, POIs, hotels, and opening hours modeled faithfully.
- Preference alignment: systems should infer, negotiate, and adapt to user preferences through natural language and tool use.
- Verifiable plans: generated itineraries are checked automatically for correctness, constraint satisfaction, and executability.

## News and Updates

- Registration interest form is open.
- 1 June 2026: Phase 1 data released, including the public training set, submission index, and evaluation code.

## Important Dates

- Data release and submission opens: 1 June 2026
- Stage 1 submission deadline: 1 August 2026
- Stage 2 evaluation: 1 August to 7 August 2026
- Technical report deadline: 7 August 2026
- Final results announced: 10 August 2026

## Track Structure

The 2026 edition has one track: Agentic AI.

### Phase 1: Public Leaderboard

Teams generate prediction files on the official data released by the organizers and submit them to the public leaderboard. Any method may be used, including any LLM, prompting strategy, toolchain, or local system.

### Phase 2: Final Test

The top 5 Phase 1 teams submit a self-contained harness that includes agent code, prompts, scaffolding, and the files needed to run it. Organizers evaluate each harness on Qwen3.6-27B, deployed via SGLang on 2x A800 80G GPUs without NVLink. Final rankings determine 1st, 2nd, and 3rd place.

## Data

The challenge includes curated traveler queries and a tool environment that models transportation, POIs, hotels, restaurants, and opening hours across many Chinese cities.

### Phase 1 Data Links

- Phase 1 data: https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase1_EN.zip
- Phase 1 data index: https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase1.txt
- Evaluation code: https://github.com/LAMDASZ-ML/ChinaTravel/blob/main/eval_tpc.py

### Phase 2 Baseline

- Phase 2 baseline code: coming soon

## Phase 2: Agent Environment & Harness Evaluation

### How the Harness Is Called

- **Query Mode**: Agents are called **per individual query**, not in batch.
- **Harness Script**: `scripts/solve_script_with_harness.py` is the baseline harness that:
  - Loads queries individually (with optional limit and resume)
  - Removes oracle-only verifier fields
  - Asks agent to solve through `agent_env.cli`
  - Parses the itinerary JSON output
  - Saves results in official `results/<method>/<uid>.json` format
  - Runs official evaluators

### Supported Agent Runners

- **`opencode`**: calls `opencode run` with generated per-run configuration
- **`codex`**: calls `codex exec` with configurable model and provider overrides

### Timeout & Time Constraints

- Timeout is **configurable per runner** in the harness config file (`agent_env/config.toml`):
  - Under `[opencode]` section: set `timeout` field
  - Under `[codex]` section: set `timeout` field
- Each query receives its own **independent timeout** — the harness processes queries sequentially

### Key Configuration Fields

For Phase 2 harness configuration (`agent_env/config.toml`):
- `[run].split`: benchmark split to load
- `[run].limit`: number of split queries to solve (useful for testing)
- `[run].method`: output method name
- `[run].tool_python`: Python command for CLI calls
- `[run].resume`: skip queries with existing result files
- `[opencode]` and `[codex]`: model, **timeout**, API key environment variable, provider, parsing settings

### Output Structure

For each query, the harness writes:
- `prompt.txt`: exact prompt sent to agent
- `output.txt`: final agent message
- `output.json`: parsed itinerary
- `results/<method>/<uid>.json`: official result file
- `evaluation.json`: schema, commonsense, and logical evaluation results

For a full split: `agent_env/runs/<method>/<split>_summary.json` containing aggregated results.

### Agent Interface

Agents communicate through `agent_env` which provides:
- **Query Tools**: list splits, load query metadata, call WorldEnv commands
- **Attraction Tools**: list types, search, filter, check opening hours, find nearby
- **Accommodation Tools**: search, filter, find nearby
- **Restaurant Tools**: search by food, cuisine, filter, check opening hours
- **Transport Tools**: query in-city transport (walk/taxi/metro), intercity transport (train/airplane), POI lookup

Expected answer format: JSON object matching `chinatravel/evaluation/output_schema.json`, usually wrapped in `<output>...</output>` tags.

### Running the Harness

```bash
# Basic usage
python agent_env/scripts/solve_script_with_harness.py

# Common overrides
python agent_env/scripts/solve_script_with_harness.py --split easy --limit 1
python agent_env/scripts/solve_script_with_harness.py --split easy --uid <uid>
python agent_env/scripts/solve_script_with_harness.py --harness opencode --model dashscope/qwen3.6-27b
python agent_env/scripts/solve_script_with_harness.py --harness codex --model qwen3.6-35b-a3b
python agent_env/scripts/solve_script_with_harness.py --resume
```

### Phase 2 Evaluation Details

- **Model**: All harnesses evaluated on Qwen3.6-27B (same as final eval)
- **Deployment**: SGLang on 2x A800 80G GPUs without NVLink
- **Runs**: Each harness run 5 times; scores averaged
- **Test Set**: Held-out test set (not released publicly in Phase 1)

## Rules

### Eligibility

- Open to teams from universities, research institutions, and companies worldwide.
- At least one team member must register for IJCAI-ECAI 2026.

### Team Size

- No fixed team-size limit.
- Each participant may join at most one team per track.

### Track 1: Prediction

- Teams may use any method to generate predictions.
- Only prediction results are submitted, not code or models.
- Submissions must be packaged as a zip file named `{TeamName}_v{x}.zip`.

### Track 2: Harness

- The top 5 Phase 1 teams submit a self-contained harness.
- Teams may develop and debug against the ChinaTravel dataset.
- All harnesses run on a held-out test set.
- Final evaluation uses Qwen3.6-27B deployed via SGLang on 2x A800 80G GPUs without NVLink.

### Evaluation Schedule

- Submissions received before 20:00 Beijing Time (UTC+8) each day are evaluated and published on the leaderboard before 20:00 Beijing Time the following day.
- Phase 1: all submitted predictions are evaluated daily; only the latest submission per team is scored and shown.
- Phase 2: each harness is run five times on the held-out test set and the scores are averaged.

### Conduct

- Participants must follow the IJCAI 2026 code of conduct and the competition's full terms.
- Cheating, plagiarism, attacks on the evaluation system, and sharing non-public answers are strictly prohibited and may result in disqualification.

## Registration

Team registration is open via Google Forms:

- https://docs.google.com/forms/d/e/1FAIpQLSdobQls23x6L2APaJektE85TqCFvUgESCkg8ZcSnb3NvLyzhg/viewform?usp=dialog

## Submission

### Round 1: Prediction

- Teams generate predictions on the official data and submit the prediction file.
- Submission portal: https://box.nju.edu.cn/u/d/998d62d9bd8747ea8659/

### Round 2: Harness

- The top 5 Phase 1 teams submit a self-contained harness.
- The Round 2 submission portal and format will be announced later.

### Final Ranking

- Phase 2 results determine the 1st, 2nd, and 3rd place winners.
- Top-ranked teams are also invited to submit a short system description paper for the proceedings.

### Packaging Rule

- Use the exact zip name `{TeamName}_v{x}.zip`.
- Example: `NJUTravel_v1.zip`.
- The example submission package is available at:
  - https://chinatravel-competition.github.io/IJCAI2026/official_test_0000.zip

## Scoring

Phase 1 evaluation uses the following weighted score:

- 10% EPR-micro
- 10% EPR-macro
- 25% C-LPR
- 40% FPR
- 5% DAV-Score
- 5% ATT-Score
- 5% DDR-Score

### Metric Summary

- EPR-micro: environmental pass ratio across all plans.
- EPR-macro: fraction of plans where every environment constraint is satisfied.
- C-LPR: constraint pass ratio conditioned on environmental pass.
- FPR: fraction of plans that pass all environment and logical constraints.
- DAV: daily average attractions visited, normalized to [0, 4].
- ATT: attraction-related preference metric.
- DDR: another preference-related metric used in the official evaluation.

## Leaderboard

The public Phase 1 leaderboard shows the top teams, with team names partially masked.

Observed top 3 on the site:

- #1 C**C96.27v3
- #2 Co***os90.14v3
- #3 ge***o189.82v3

Leaderboard page:

- https://chinatravel-competition.github.io/IJCAI2026/leaderboard.html

## Organizers

The site lists the following organizers from Nanjing University:

- Lan-Zhe Guo
- Yu-Feng Li
- Jie-Jing Shao
- Bo-Wen Zhang
- Peng-Yu Hua
- Jia-Wei Cao
- Jin Ye
- Song-Lin Lv

## FAQ Highlights

- TPC is an open competition for evaluating language agents on real-world travel planning in China.
- The 2026 edition is the second iteration and is co-located with IJCAI-ECAI 2026 in Bremen.
- The top 5 Phase 1 teams advance to Phase 2, subject to eligibility verification and compliance with the rules.
- Awards are presented to the 1st, 2nd, and 3rd place teams.
- Phase 1 allows any method; Phase 2 requires a reproducible harness run by the organizers.
- This is a continuation of the 2025 edition and has been expanded in scope, difficulty, and evaluation rigor.

## Contact

- Email: chinatravel454@gmail.com
- IJCAI 2026 site: https://2026.ijcai.org/
- GitHub: https://github.com/LAMDA-NeSy/ChinaTravel

## Conference Details

- IJCAI-ECAI 2026
- Bremen, Germany
- 15 to 21 August 2026

## Last Updated

- June 2026, v2026.1