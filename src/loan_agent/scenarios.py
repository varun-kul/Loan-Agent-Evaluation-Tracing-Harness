"""Scenario schema, loading, and validation for the loan agent eval harness.

Scenarios are defined as JSONL — one JSON object per line. Each scenario
describes a conversation, expected tool calls, rule checks, and final DB state.
"""

from dataclasses import dataclass, field
from typing import Optional
import json
import os


# Valid categories
SCENARIO_CATEGORIES = {
    "happy_path",
    "edge_case",
    "adversarial",
    "ambiguous",
    "prompt_injection",
}

# Valid tool names
VALID_TOOLS = {
    "lookup_account",
    "get_payment_options",
    "create_payment_plan",
    "send_required_disclosure",
    "escalate_to_human",
}

# Valid rule names
VALID_RULES = {
    "identity_verification",   # Rule 1: verify identity before balance
    "disclosure_before_plan",  # Rule 2: disclosure before payment plan
    "no_threats_or_legal_advice",  # Rule 3
    "escalation_triggers",     # Rule 4: escalate on dispute/distress
}


@dataclass
class Scenario:
    """A single evaluation scenario."""
    scenario_id: str
    category: str
    description: str
    account_id: Optional[str]
    messages: list[dict]  # [{"role": "user", "content": "..."}, ...]
    expected_tool_calls: list[str]  # tool names expected to be called, in order
    expected_rule_violations: list[str]  # rules that should NOT be violated
    expected_db_state: dict  # expected DB assertions
    expected_task_success: bool

    def validate(self) -> list[str]:
        """Return list of validation errors (empty if valid)."""
        errors = []

        if self.category not in SCENARIO_CATEGORIES:
            errors.append(f"invalid category: {self.category}")

        for tool in self.expected_tool_calls:
            if tool not in VALID_TOOLS:
                errors.append(f"invalid tool: {tool}")

        for rule in self.expected_rule_violations:
            if rule not in VALID_RULES:
                errors.append(f"invalid rule: {rule}")

        for msg in self.messages:
            if "role" not in msg or "content" not in msg:
                errors.append(f"invalid message: missing role or content")
            if msg["role"] not in ("user", "assistant"):
                errors.append(f"invalid message role: {msg['role']}")

        return errors


@dataclass
class ScenarioSuite:
    """A collection of scenarios loaded from a JSONL file."""
    scenarios: list[Scenario] = field(default_factory=list)

    def validate_all(self) -> list[str]:
        """Validate all scenarios. Returns list of errors."""
        errors = []
        ids = set()
        for s in self.scenarios:
            errors.extend([f"{s.scenario_id}: {e}" for e in s.validate()])
            if s.scenario_id in ids:
                errors.append(f"duplicate scenario_id: {s.scenario_id}")
            ids.add(s.scenario_id)
        return errors

    def by_category(self, category: str) -> list[Scenario]:
        return [s for s in self.scenarios if s.category == category]


def load_scenarios(path: str) -> ScenarioSuite:
    """Load scenarios from a JSONL file."""
    suite = ScenarioSuite()
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                data = json.loads(line)
                scenario = Scenario(
                    scenario_id=data["scenario_id"],
                    category=data["category"],
                    description=data["description"],
                    account_id=data.get("account_id"),
                    messages=data["messages"],
                    expected_tool_calls=data.get("expected_tool_calls", []),
                    expected_rule_violations=data.get("expected_rule_violations", []),
                    expected_db_state=data.get("expected_db_state", {}),
                    expected_task_success=data.get("expected_task_success", True),
                )
                suite.scenarios.append(scenario)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                raise ValueError(f"Line {line_num}: {e}")
    return suite


def save_scenarios(suite: ScenarioSuite, path: str) -> None:
    """Save scenarios to a JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for s in suite.scenarios:
            data = {
                "scenario_id": s.scenario_id,
                "category": s.category,
                "description": s.description,
                "account_id": s.account_id,
                "messages": s.messages,
                "expected_tool_calls": s.expected_tool_calls,
                "expected_rule_violations": s.expected_rule_violations,
                "expected_db_state": s.expected_db_state,
                "expected_task_success": s.expected_task_success,
            }
            f.write(json.dumps(data) + "\n")