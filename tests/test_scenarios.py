"""Tests for scenario schema, loading, and validation."""
import pytest
from src.loan_agent.scenarios import (
    load_scenarios,
    save_scenarios,
    ScenarioSuite,
    Scenario,
    SCENARIO_CATEGORIES,
    VALID_TOOLS,
    VALID_RULES,
)
from src.loan_agent.backend import reset_db
import os
import tempfile


@pytest.fixture(autouse=True)
def clean_db():
    reset_db()
    yield
    reset_db()


def test_load_scenarios():
    """Test that the scenario file loads correctly."""
    suite = load_scenarios("src/loan_agent/scenarios.jsonl")
    assert len(suite.scenarios) == 105
    assert len(suite.scenarios) > 100


def test_scenario_validation():
    """Test that all scenarios pass schema validation."""
    suite = load_scenarios("src/loan_agent/scenarios.jsonl")
    errors = suite.validate_all()
    assert errors == [], f"Validation errors: {errors}"


def test_category_counts():
    """Test that each category has the expected number of scenarios."""
    suite = load_scenarios("src/loan_agent/scenarios.jsonl")
    counts = {}
    for s in suite.scenarios:
        counts[s.category] = counts.get(s.category, 0) + 1
    assert counts.get("happy_path", 0) >= 20
    assert counts.get("edge_case", 0) >= 20
    assert counts.get("adversarial", 0) >= 20
    assert counts.get("ambiguous", 0) >= 10
    assert counts.get("prompt_injection", 0) >= 10


def test_unique_scenario_ids():
    """Test that all scenario IDs are unique."""
    suite = load_scenarios("src/loan_agent/scenarios.jsonl")
    ids = [s.scenario_id for s in suite.scenarios]
    assert len(ids) == len(set(ids))


def test_valid_categories():
    """Test that all scenarios use valid categories."""
    suite = load_scenarios("src/loan_agent/scenarios.jsonl")
    for s in suite.scenarios:
        assert s.category in SCENARIO_CATEGORIES


def test_valid_tools():
    """Test that all scenarios use valid tool names."""
    suite = load_scenarios("src/loan_agent/scenarios.jsonl")
    for s in suite.scenarios:
        for tool in s.expected_tool_calls:
            assert tool in VALID_TOOLS


def test_valid_rules():
    """Test that all scenarios use valid rule names."""
    suite = load_scenarios("src/loan_agent/scenarios.jsonl")
    for s in suite.scenarios:
        for rule in s.expected_rule_violations:
            assert rule in VALID_RULES


def test_save_and_reload(tmp_path):
    """Test that saving and reloading scenarios preserves data."""
    suite = load_scenarios("src/loan_agent/scenarios.jsonl")
    tmp_file = os.path.join(tmp_path, "test_scenarios.jsonl")
    save_scenarios(suite, tmp_file)

    suite2 = load_scenarios(tmp_file)
    assert len(suite2.scenarios) == len(suite.scenarios)

    for s1, s2 in zip(suite.scenarios, suite2.scenarios):
        assert s1.scenario_id == s2.scenario_id
        assert s1.category == s2.category
        assert s1.messages == s2.messages
        assert s1.expected_tool_calls == s2.expected_tool_calls


def test_scenario_dataclass_validation():
    """Test that invalid scenarios are caught by validate()."""
    # Invalid category
    s = Scenario(
        scenario_id="TEST-001",
        category="invalid_category",
        description="test",
        account_id="ACC-1001",
        messages=[{"role": "user", "content": "hello"}],
        expected_tool_calls=[],
        expected_rule_violations=[],
        expected_db_state={},
        expected_task_success=True,
    )
    errors = s.validate()
    assert any("category" in e for e in errors)

    # Invalid tool
    s2 = Scenario(
        scenario_id="TEST-002",
        category="happy_path",
        description="test",
        account_id="ACC-1001",
        messages=[{"role": "user", "content": "hello"}],
        expected_tool_calls=["invalid_tool"],
        expected_rule_violations=[],
        expected_db_state={},
        expected_task_success=True,
    )
    errors2 = s2.validate()
    assert any("tool" in e for e in errors2)

    # Invalid rule
    s3 = Scenario(
        scenario_id="TEST-003",
        category="happy_path",
        description="test",
        account_id="ACC-1001",
        messages=[{"role": "user", "content": "hello"}],
        expected_tool_calls=[],
        expected_rule_violations=["invalid_rule"],
        expected_db_state={},
        expected_task_success=True,
    )
    errors3 = s3.validate()
    assert any("rule" in e for e in errors3)


def test_by_category():
    """Test filtering scenarios by category."""
    suite = load_scenarios("src/loan_agent/scenarios.jsonl")
    happy = suite.by_category("happy_path")
    assert len(happy) == 25
    adv = suite.by_category("adversarial")
    assert len(adv) == 25
    pi = suite.by_category("prompt_injection")
    assert len(pi) == 15