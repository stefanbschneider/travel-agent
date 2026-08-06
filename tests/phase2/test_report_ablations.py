"""Hermetic tests for the report-ablation runner (scripts/phase2_report_ablations.py).

No network, no API key, no real ``WorldEnv``: every test drives the script's own ``stub`` backend or
a locally injected fake client. What is pinned here is the contract the report depends on:

* subset selection is deterministic and matches ``phase2_quick_eval.py``'s convention;
* the telemetry proves whether the LLM fired, and a zero-call arm is UNMEASURED rather than a null
  result;
* plans land at ``results/<method>/<uid>.json`` (the layout ``eval_tpc.py`` scores);
* one failing query is recorded as a failure, never raised out of the run;
* the hard bounds (per-call timeout classification, max calls per query) are enforced;
* library defaults are untouched -- importing the module makes no LLM call and needs no key.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import phase2_report_ablations as abl

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# --- subset determinism ---------------------------------------------------


class TestSubsetSelection:
    def test_subset_is_deterministic_and_matches_quick_eval_convention(self):
        import rehearse_phase2 as reh
        import make_phase2_splits as splits

        split = "tpc_phase2_familiar_100_val"
        got = abl.select_subset(split, n=24, seed=abl.DEFAULT_SEED)
        again = abl.select_subset(split, n=24, seed=abl.DEFAULT_SEED)
        expected = reh.select_fold(
            splits.read_split(split), fold=0, folds=1, seed=abl.DEFAULT_SEED
        )[:24]
        assert got == again == expected
        assert len(got) == 24

    def test_seed_matters_only_when_the_split_is_actually_partitioned(self):
        """``select_fold`` sorts the fold it returns, so at ``folds=1`` the seed cannot matter.

        This mirrors ``phase2_quick_eval.py`` exactly (same helper, same defaults): with one fold
        the subset is the first ``n`` uids of the sorted split and is seed-independent. The seed
        chooses *which* uids land in which fold, so it only bites once ``--folds > 1``. Pinned here
        because "same --n/seed convention" is a comparability claim, and a reader must not conclude
        that changing ``--seed`` at ``--folds 1`` resamples the subset.
        """
        split = "tpc_phase2_familiar_100_val"
        assert abl.select_subset(split, n=24, seed=abl.DEFAULT_SEED) == abl.select_subset(
            split, n=24, seed=abl.DEFAULT_SEED + 1
        )
        a = abl.select_subset(split, n=10, seed=abl.DEFAULT_SEED, fold=0, folds=4)
        b = abl.select_subset(split, n=10, seed=abl.DEFAULT_SEED + 1, fold=0, folds=4)
        assert a != b

    def test_materialize_writes_the_uid_list_under_the_derived_name(self, tmp_path):
        uids = ["uid_b", "uid_a", "uid_c"]
        name = abl.materialize_subset_split("some_split", uids, splits_dir=tmp_path)
        assert name == "some_split_n3"
        written = (tmp_path / "some_split_n3.txt").read_text(encoding="utf-8").split()
        # Order is the subset order, not re-sorted: eval and the run must agree uid-for-uid.
        assert written == uids

    def test_select_subset_reads_a_custom_splits_dir(self, tmp_path):
        (tmp_path / "mini.txt").write_text("u1\nu2\nu3\nu4\n", encoding="utf-8")
        got = abl.select_subset("mini", n=2, seed=7, splits_dir=tmp_path)
        assert len(got) == 2
        assert set(got) <= {"u1", "u2", "u3", "u4"}


# --- arm / agent catalogue ------------------------------------------------


class TestArmCatalogue:
    def test_defaults_per_arm(self):
        assert abl.resolve_agent(abl.LLM_ONLY_ARM, None) == "Act"
        assert abl.resolve_agent(abl.UPSTREAM_ARM, None) == "RuleNeSy"

    def test_agent_must_belong_to_the_arm(self):
        with pytest.raises(ValueError) as exc:
            abl.resolve_agent(abl.LLM_ONLY_ARM, "RuleNeSy")
        assert "upstream" in str(exc.value)

    def test_llm_modulo_is_not_offered_because_it_requires_the_oracle(self):
        every = {a for agents in abl.ARM_AGENTS.values() for a in agents}
        assert "LLM-modulo" not in every

    def test_backend_defaults_to_the_offline_stub(self, monkeypatch):
        monkeypatch.delenv("TPC_P2_LLM_BACKEND", raising=False)
        assert abl.resolve_backend(None) == "stub"
        monkeypatch.setenv("TPC_P2_LLM_BACKEND", "deepinfra")
        assert abl.resolve_backend(None) == "deepinfra"
        # An explicit flag always wins.
        assert abl.resolve_backend("stub") == "stub"

    def test_backend_none_is_not_treated_as_a_live_provider(self, monkeypatch):
        monkeypatch.setenv("TPC_P2_LLM_BACKEND", "none")
        assert abl.resolve_backend(None) == "stub"


# --- English prompt glue --------------------------------------------------


class TestEnglishPrompts:
    def test_act_instruction_en_has_english_cities_and_upstream_tool_doc(self):
        prompt = abl.act_instruction_en(30)
        assert "Shanghai" in prompt and "Hangzhou" in prompt
        # The defect this glue exists for: upstream's Act prompt hard-codes the Chinese city list,
        # which the English WorldEnv rejects on every call.
        assert "上海" not in prompt
        assert "attractions_select" in prompt  # upstream's own func_doc, reused verbatim
        assert "within 30 steps" in prompt

    def test_plan_prompt_is_the_english_direct_prompt_for_en(self):
        assert "You are a proficient planner" in abl.plan_prompt_for("en")


# --- telemetry / verdict contract ----------------------------------------


def _summary(**over):
    base = {
        "llm_backend": "deepinfra",
        "queries": 24,
        "plans_written": 24,
        "llm_calls_total": 500,
        "llm_failures_total": 0,
        "llm_timeouts_total": 0,
    }
    base.update(over)
    return base


class TestAssessArm:
    def test_zero_calls_is_unmeasured_not_a_null_result(self):
        reportable, verdict = abl.assess_arm(_summary(llm_calls_total=0))
        assert reportable is False
        assert verdict.startswith("UNMEASURED")
        assert "never fired" in verdict

    def test_stub_backend_is_never_reportable(self):
        reportable, verdict = abl.assess_arm(_summary(llm_backend="stub"))
        assert reportable is False
        assert verdict.startswith("UNMEASURED (stub backend)")

    def test_no_plans_written_is_unmeasured(self):
        reportable, _ = abl.assess_arm(_summary(plans_written=0))
        assert reportable is False

    def test_all_calls_failing_is_unmeasured(self):
        reportable, verdict = abl.assess_arm(
            _summary(llm_calls_total=10, llm_failures_total=8, llm_timeouts_total=2)
        )
        assert reportable is False
        assert "degradation path" in verdict

    def test_partial_failures_are_reportable_but_degraded(self):
        reportable, verdict = abl.assess_arm(
            _summary(llm_calls_total=100, llm_failures_total=30)
        )
        assert reportable is True
        assert verdict.startswith("MEASURED but DEGRADED")

    def test_clean_run_is_measured(self):
        reportable, verdict = abl.assess_arm(_summary())
        assert reportable is True
        assert verdict.startswith("MEASURED:")
        assert "never as a promotion row" in verdict


class TestSummarize:
    def test_totals_and_cost_are_derived_from_per_query_records(self):
        records = [
            {"uid": "a", "ok": True, "llm_calls": 4, "prompt_tokens": 1_000_000,
             "completion_tokens": 100_000, "plan_written": True, "plan_nonempty": True,
             "wall_sec": 10.0, "agent_success": True},
            {"uid": "b", "ok": False, "llm_calls": 2, "llm_failures": 1, "timed_out": True,
             "prompt_tokens": 0, "completion_tokens": 0, "plan_written": False,
             "plan_nonempty": False, "wall_sec": 20.0},
        ]
        s = abl.summarize(records, base={"llm_backend": "deepinfra"},
                          price_in=1.0, price_out=10.0)
        assert s["queries"] == 2
        assert s["ok"] == 1 and s["failed"] == 1 and s["timed_out"] == 1
        assert s["llm_calls_total"] == 6
        assert s["llm_calls_per_query"] == 3.0
        assert s["plans_written"] == 1
        assert s["est_cost_usd"] == pytest.approx(1.0 + 1.0)
        assert s["est_cost_usd_per_query"] == pytest.approx(1.0)
        assert s["wall_sec_mean"] == 15.0
        assert s["reportable"] is True

    def test_a_zero_call_summary_is_flagged_unmeasured(self):
        records = [{"uid": "a", "ok": True, "llm_calls": 0, "plan_written": True}]
        s = abl.summarize(records, base={"llm_backend": "deepinfra"})
        assert s["reportable"] is False
        assert s["verdict"].startswith("UNMEASURED")


# --- the adapter's hard bounds -------------------------------------------


class _FakeCompletion:
    def __init__(self, content: str, prompt_tokens: int = 11, completion_tokens: int = 7):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]
        self.usage = type("U", (), {"prompt_tokens": prompt_tokens,
                                    "completion_tokens": completion_tokens})()


class _FakeClient:
    """Minimal ``openai.OpenAI`` stand-in; no socket is ever opened."""

    def __init__(self, responses=None, raises=None):
        self._responses = list(responses or ["ok"])
        self._raises = raises
        self.requests = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.requests.append(kwargs)
                if outer._raises is not None:
                    raise outer._raises
                idx = min(len(outer.requests) - 1, len(outer._responses) - 1)
                return _FakeCompletion(outer._responses[idx])

        self.chat = type("Chat", (), {"completions": _Completions()})()


class _Timeout(Exception):
    """Named so ``_is_timeout`` classifies it as a timeout, like ``openai.APITimeoutError``."""


_Timeout.__name__ = "APITimeoutError"


def _llm(*, client, max_calls=5, retries=0):
    return abl.make_budgeted_llm(
        model="Qwen/Qwen3.6-27B",
        base_url="http://127.0.0.1:1/v1",
        api_key="not-used",
        timeout_sec=1.0,
        max_calls=max_calls,
        retries=retries,
        max_tokens=64,
        extra_body=None,
        client_factory=lambda **kw: client,
    )


class TestBudgetedLLM:
    def test_counts_calls_and_tokens_and_honours_one_line(self, no_network):
        client = _FakeClient(["Action: goto(...)"])
        llm = _llm(client=client)
        out = llm([{"role": "user", "content": "hi"}], one_line=True)
        assert out == "Action: goto(...)"
        assert llm.telemetry.calls == 1
        assert llm.telemetry.prompt_tokens == 11
        assert llm.telemetry.completion_tokens == 7
        assert client.requests[0]["stop"] == ["\n"]
        assert client.requests[0]["temperature"] == 0.0

    def test_json_mode_requests_a_json_object(self, no_network):
        client = _FakeClient(['{"itinerary": []}'])
        llm = _llm(client=client)
        out = llm([{"role": "user", "content": "hi"}], one_line=False, json_mode=True)
        assert json.loads(out) == {"itinerary": []}
        assert client.requests[0]["response_format"] == {"type": "json_object"}

    def test_max_calls_is_a_hard_per_query_ceiling(self, no_network):
        llm = _llm(client=_FakeClient(["ok"]), max_calls=2)
        llm([{"role": "user", "content": "1"}])
        llm([{"role": "user", "content": "2"}])
        with pytest.raises(abl.CallBudgetExhausted):
            llm([{"role": "user", "content": "3"}])
        assert llm.telemetry.budget_exhausted is True

    def test_a_timeout_is_counted_and_degrades_instead_of_raising(self, no_network):
        llm = _llm(client=_FakeClient(raises=_Timeout("too slow")), retries=0)
        out = llm([{"role": "user", "content": "hi"}])
        assert out == abl.LLM_ERROR_SENTINEL
        assert llm.telemetry.timeouts == 1
        assert llm.telemetry.failures == 0
        assert llm.telemetry.calls == 0  # a failed call is not a fired call

    def test_a_provider_error_is_counted_as_a_failure_and_retried(self, no_network):
        llm = _llm(client=_FakeClient(raises=RuntimeError("500")), retries=2)
        out = llm([{"role": "user", "content": "hi"}])
        assert out == abl.LLM_ERROR_SENTINEL
        assert llm.telemetry.failures == 3  # 1 attempt + 2 retries
        assert llm.telemetry.retries == 2

    def test_the_scratchpad_is_never_mutated_by_role_merging(self, no_network):
        client = _FakeClient(["ok"])
        llm = _llm(client=client)
        scratchpad = [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ]
        before = json.dumps(scratchpad)
        llm(scratchpad)
        assert json.dumps(scratchpad) == before
        # ...but the request itself carries the merged form the providers expect.
        assert len(client.requests[0]["messages"]) == 1


class TestAgentConstruction:
    """``init_agent`` is bypassed on purpose; pin the three defects that forced it."""

    def test_rulenesy_actually_gets_lang_en(self, tmp_path, no_network):
        agent = abl.build_agent(
            "RuleNeSy",
            env=abl.StubEnv(),
            llm=abl.StubChatLLM(),
            lang="en",
            max_steps=4,
            cache_dir=tmp_path / "cache",
            log_dir=tmp_path / "logs",
        )
        # Upstream's init_agent drops `lang` here, leaving agent.lang == "zh" and sending Chinese
        # nl2sl prompts for English queries. Constructing the class directly is the fix.
        assert agent.lang == "en"
        assert agent.method == "RuleNeSy"

    def test_upstream_init_agent_still_has_the_lang_defect(self, tmp_path, no_network):
        """Guard: if upstream ever fixes this, the glue can be dropped -- so notice."""
        from chinatravel.agent.load_model import init_agent

        agent = init_agent(
            {
                "method": "RuleNeSy",
                "env": abl.StubEnv(),
                "backbone_llm": abl.StubChatLLM(),
                "cache_dir": str(tmp_path / "cache"),
                "log_dir": str(tmp_path / "logs"),
                "debug": False,
                "lang": "en",
            }
        )
        assert agent.lang == "zh", (
            "upstream init_agent no longer drops lang -- build_agent's RuleNeSy branch can be "
            "simplified to init_agent again."
        )

    def test_act_agent_gets_the_english_prompt_and_english_plan_prompt(self, tmp_path, no_network):
        agent = abl.build_agent(
            "Act",
            env=abl.StubEnv(),
            llm=abl.StubChatLLM(),
            lang="en",
            max_steps=7,
            cache_dir=tmp_path / "cache",
            log_dir=tmp_path / "logs",
        )
        assert "上海" not in agent.prompt
        assert "Shanghai" in agent.prompt
        assert "You are a proficient planner" in agent.plan_prompt
        assert agent.max_steps == 7


# --- end-to-end, offline -------------------------------------------------


def _stub_config(tmp_path: Path, **over) -> abl.ArmConfig:
    kwargs = dict(
        arm=abl.LLM_ONLY_ARM,
        agent="Act",
        lang="en",
        model="stub",
        llm_backend="stub",
        base_url=None,
        max_steps=4,
        budget_sec=30.0,
        call_timeout_sec=5.0,
        max_calls=16,
        retries=0,
        max_tokens=64,
        enable_thinking=False,
        results_dir=str(tmp_path / "results" / "m"),
        telemetry_dir=str(tmp_path / "telemetry"),
        cache_dir=str(tmp_path / "cache"),
        log_dir=str(tmp_path / "cache" / "logs"),
        load_translation_cache=False,
        debug=False,
    )
    kwargs.update(over)
    return abl.ArmConfig(**kwargs)


def _queries(one_query: dict) -> dict[str, dict]:
    q = dict(one_query)
    q["uid"] = "u1"
    # Prove the oracle strip really happens on the way in.
    q["hard_logic_py"] = ["must_not_be_visible"]
    return {"u1": abl._visible(q)}


class TestOfflineRun:
    def test_stub_arm_writes_plans_and_telemetry_in_the_scoreable_layout(
        self, tmp_path, one_query, no_network
    ):
        config = _stub_config(tmp_path)
        queries = _queries(one_query)
        assert "hard_logic_py" not in queries["u1"]

        records = abl.run_arm(config, queries, ["u1"], workers=1)

        assert len(records) == 1
        rec = records[0]
        assert rec["ok"] is True
        assert rec["llm_calls"] >= 2  # one action + the plan call
        plan_path = tmp_path / "results" / "m" / "u1.json"
        assert plan_path.exists()
        assert "itinerary" in json.loads(plan_path.read_text(encoding="utf-8"))
        telem = json.loads((tmp_path / "telemetry" / "u1.json").read_text(encoding="utf-8"))
        assert telem["uid"] == "u1"
        assert telem["llm_calls"] == rec["llm_calls"]

        summary = abl.summarize(records, base={"llm_backend": "stub"})
        # The stub proved the plumbing, and must still refuse to be a result.
        assert summary["reportable"] is False

    def test_the_stub_never_reaches_the_real_worldenv(self, tmp_path, one_query, no_network):
        env = abl.build_env(_stub_config(tmp_path))
        assert isinstance(env, abl.StubEnv)

    def test_one_failing_query_is_recorded_not_raised(self, tmp_path, one_query, no_network):
        config = _stub_config(tmp_path)
        queries = _queries(one_query)

        class _Exploding:
            backbone_llm = None

            def __call__(self, *a, **k):
                raise RuntimeError("boom")

        plan, record = abl.run_one_query(_Exploding(), "Act", queries["u1"], budget_sec=0)
        assert plan is None
        assert record["ok"] is False
        assert "RuntimeError: boom" in record["error"]
        assert record["plan_written"] is False
        assert record["llm_calls"] == 0

    def test_a_query_over_budget_is_recorded_as_a_timeout(self, tmp_path, one_query, no_network):
        pytest.importorskip("func_timeout")

        class _Slow:
            backbone_llm = None

            def __call__(self, *a, **k):
                import time

                time.sleep(5)

        plan, record = abl.run_one_query(_Slow(), "Act", {"uid": "u1", "nature_language": "x"},
                                         budget_sec=0.2)
        assert plan is None
        assert record["timed_out"] is True
        assert record["ok"] is False

    def test_call_budget_exhaustion_fails_only_that_query(self, tmp_path, one_query, no_network):
        class _Budget:
            backbone_llm = None

            def __call__(self, *a, **k):
                raise abl.CallBudgetExhausted("over")

        plan, record = abl.run_one_query(_Budget(), "Act", {"uid": "u1", "nature_language": "x"},
                                         budget_sec=0)
        assert plan is None
        assert "call budget exhausted" in record["error"]

    def test_run_arm_across_worker_processes(self, tmp_path, one_query):
        """The parallel path: one agent per worker, records still complete and written."""
        config = _stub_config(tmp_path)
        queries = _queries(one_query)
        queries["u2"] = dict(queries["u1"], uid="u2")

        records = abl.run_arm(config, queries, ["u1", "u2"], workers=2)

        assert {r["uid"] for r in records} == {"u1", "u2"}
        assert all(r["ok"] for r in records)
        for uid in ("u1", "u2"):
            assert (tmp_path / "results" / "m" / f"{uid}.json").exists()
            assert (tmp_path / "telemetry" / f"{uid}.json").exists()

    def test_run_one_query_restores_stdout(self, tmp_path, one_query, no_network):
        """``NesyAgent.run`` replaces the global stdout/stderr and never puts them back."""

        class _Hijack:
            backbone_llm = None

            def __call__(self, *a, **k):
                sys.stdout = object()  # type: ignore[assignment]
                raise RuntimeError("after hijack")

        original = sys.stdout
        abl.run_one_query(_Hijack(), "Act", {"uid": "u1", "nature_language": "x"}, budget_sec=0)
        assert sys.stdout is original


class TestCli:
    def test_dry_run_resolves_the_subset_without_solving(self, capsys):
        rc = abl.main(["--arm", "llm-only", "--n", "3", "--dry-run", "--llm-backend", "stub",
                       "--no-materialize-split"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry run: would solve 3 queries" in out
        assert "arm=llm-only agent=Act backend=stub" in out
        assert "NOT a reportable arm" in out

    def test_upstream_arm_dry_run_defaults_to_rulenesy(self, capsys):
        rc = abl.main(["--arm", "upstream", "--n", "2", "--dry-run", "--llm-backend", "stub",
                       "--no-materialize-split"])
        assert rc == 0
        assert "agent=RuleNeSy" in capsys.readouterr().out

    def test_help_mentions_both_arms(self):
        text = abl.build_parser().format_help()
        assert "llm-only" in text and "upstream" in text

    def test_method_name_is_stable_and_path_safe(self):
        name = abl.default_method("llm-only", "Act", "Qwen/Qwen3.6-27B", "en")
        assert name == "report_ablation_llm_only_Act_Qwen-Qwen3.6-27B_en"
        assert "/" not in name


class TestNoDefaultChanged:
    def test_importing_the_module_needs_no_key_and_makes_no_call(self, monkeypatch, no_network):
        monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
        import importlib

        importlib.reload(abl)
        assert abl.resolve_backend(None) in {"stub", "deepinfra", "openai"}

    def test_the_shipped_solver_packages_are_not_imported_for_a_stub_arm(self, tmp_path):
        config = _stub_config(tmp_path)
        assert config.llm_backend == "stub"
        # build_llm for the stub backend must not touch the phase2 LLM client at all.
        assert isinstance(abl.build_llm(config), abl.StubChatLLM)
