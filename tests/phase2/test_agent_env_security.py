from __future__ import annotations

import pytest

from agent_env.adapter import ChinaTravelEnvAdapter, TOOL_SPECS
from chinatravel.environment.world_env import _execute_world_command


def test_query_tool_contract_has_no_oracle_override():
    properties = TOOL_SPECS["china_travel_load_query"].input_schema["properties"]
    assert set(properties) == {"split", "uid"}

    result = ChinaTravelEnvAdapter().call_tool(
        "china_travel_load_query",
        {"split": "easy", "uid": "example", "oracle_translation": True},
    )

    assert result["success"] is False
    assert "oracle_translation" in result["error"]


def test_query_loader_forces_visible_data(monkeypatch):
    from chinatravel.data import load_datasets

    observed = {}

    def fake_load_query(args):
        observed.update(vars(args))
        return ["visible-uid"], {
            "visible-uid": {
                "uid": "visible-uid",
                "nature_language": "Plan a safe trip.",
                "hard_logic": "secret",
                "hard_logic_py": ["result=False"],
                "hard_logic_nl": "secret",
            }
        }

    monkeypatch.setattr(load_datasets, "load_query", fake_load_query)

    result = ChinaTravelEnvAdapter().load_query("held-out", uid="visible-uid")

    assert observed["oracle_translation"] is False
    assert result["success"] is True
    assert result["query"] == {
        "uid": "visible-uid",
        "nature_language": "Plan a safe trip.",
    }


def test_world_command_allows_literals_keywords_and_safe_predicates():
    values = ["故宫博物院", "闭馆", "国家博物馆"]

    def select(*, city, key, func):
        assert city == "北京"
        assert key == "name"
        return [value for value in values if func(value)]

    result = _execute_world_command(
        "attractions_select(city='北京', key='name', "
        "func=lambda x: '博物' in str(x) and x != '闭馆')",
        {"attractions_select": select},
    )

    assert result == ["故宫博物院", "国家博物馆"]


@pytest.mark.parametrize(
    "command, handlers",
    [
        ("__import__('os').getcwd()", {}),
        ("allowed(open('/etc/passwd').read())", {"allowed": lambda value: value}),
        ("(lambda: 1)()", {}),
        ("Results[-1].next_page()", {}),
        (
            "select(lambda x: __import__('os').system('echo unsafe'))",
            {"select": lambda predicate: predicate("value")},
        ),
    ],
)
def test_world_command_rejects_executable_python(command, handlers):
    with pytest.raises(ValueError):
        _execute_world_command(command, handlers)
