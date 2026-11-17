"""Tests for the LLM-as-judge calibration module."""
import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

mock_langfuse = types.ModuleType("langfuse")
mock_langfuse.model = types.ModuleType("langfuse.model")
sys.modules["langfuse"] = mock_langfuse
sys.modules["langfuse.model"] = mock_langfuse.model

from src.loan_agent.llm_judge import (
    HumanLabel,
    LLMMajorJudgeResult,
    CalibrationResult,
    LLMJudge,
    cohen_kappa,
    agreement_rate,
    calibrate_judge,
    ERROR_TAXONOMY,
    ERROR_CODES,
    load_human_labels,
)


class TestErrorTaxonomy(unittest.TestCase):
    """Test the error taxonomy definitions."""

    def test_taxonomy_has_expected_codes(self):
        expected = {
            "R1_IDENTITY_BYPASS",
            "R2_DISCLOSURE_BYPASS",
            "R3_THREAT_OR_LEGAL_ADVICE",
            "R4_ESCALATION_MISS",
            "TOOL_ARG_ERROR",
            "WRONG_INTENT",
            "TASK_FAILURE",
            "FALSE_POSITIVE",
        }
        self.assertEqual(ERROR_CODES, expected)

    def test_each_code_has_name_and_description(self):
        for code, info in ERROR_TAXONOMY.items():
            self.assertIn("name", info)
            self.assertIn("description", info)
            self.assertIn("severity", info)
            self.assertIn(info["severity"], {"low", "medium", "high", "critical"})


class TestHumanLabel(unittest.TestCase):
    """Test HumanLabel dataclass."""

    def test_creation(self):
        label = HumanLabel(
            scenario_id="HP-001",
            judge="annotator_1",
            task_success=True,
            rule_violations=[],
            notes="Looks good",
            confidence=0.95,
        )
        self.assertEqual(label.scenario_id, "HP-001")
        self.assertEqual(label.judge, "annotator_1")
        self.assertTrue(label.task_success)
        self.assertEqual(label.rule_violations, [])
        self.assertEqual(label.notes, "Looks good")
        self.assertEqual(label.confidence, 0.95)


class TestLLMMajorJudgeResult(unittest.TestCase):
    """Test LLMMajorJudgeResult dataclass."""

    def test_creation(self):
        result = LLMMajorJudgeResult(
            scenario_id="HP-001",
            task_success=True,
            rule_violations=["R3_THREAT_OR_LEGAL_ADVICE"],
            reasoning="Agent used threat language",
            confidence=0.9,
            model="llama-3.1-8b-instant",
        )
        self.assertEqual(result.scenario_id, "HP-001")
        self.assertTrue(result.task_success)
        self.assertEqual(result.rule_violations, ["R3_THREAT_OR_LEGAL_ADVICE"])
        self.assertEqual(result.confidence, 0.9)


class TestCohenKappa(unittest.TestCase):
    """Test Cohen's kappa calculation."""

    def test_perfect_agreement(self):
        ratings_a = [["R1_IDENTITY_BYPASS"], [], ["R2_DISCLOSURE_BYPASS"]]
        ratings_b = [["R1_IDENTITY_BYPASS"], [], ["R2_DISCLOSURE_BYPASS"]]
        kappa = cohen_kappa(ratings_a, ratings_b)
        self.assertEqual(kappa, 1.0)

    def test_empty_ratings(self):
        kappa = cohen_kappa([], [])
        self.assertEqual(kappa, 0.0)

    def test_partial_agreement(self):
        ratings_a = [["R1"], ["R1"], [], ["R2"]]
        ratings_b = [["R1"], [], ["R2"], ["R2"]]
        kappa = cohen_kappa(ratings_a, ratings_b, categories=["R1", "R2"])
        self.assertIsInstance(kappa, float)
        self.assertGreaterEqual(kappa, -1.0)
        self.assertLessEqual(kappa, 1.0)

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            cohen_kappa([["R1"]], [["R1"], ["R2"]])


class TestAgreementRate(unittest.TestCase):
    """Test simple agreement rate."""

    def test_perfect_agreement(self):
        ratings_a = [["R1"], [], ["R2"]]
        ratings_b = [["R1"], [], ["R2"]]
        rate = agreement_rate(ratings_a, ratings_b)
        self.assertEqual(rate, 1.0)

    def test_no_agreement(self):
        ratings_a = [["R1"], []]
        ratings_b = [[], ["R1"]]
        rate = agreement_rate(ratings_a, ratings_b)
        self.assertEqual(rate, 0.0)


class TestCalibrateJudge(unittest.TestCase):
    """Test judge calibration."""

    def test_calibration_with_matching_data(self):
        human_labels = [
            HumanLabel("HP-001", "judge1", True, [], "", 1.0),
            HumanLabel("HP-002", "judge1", True, [], "", 1.0),
            HumanLabel("ADV-001", "judge1", False, ["R3_THREAT_OR_LEGAL_ADVICE"], "", 1.0),
        ]
        llm_results = [
            LLMMajorJudgeResult("HP-001", True, [], "ok", 0.9, "model"),
            LLMMajorJudgeResult("HP-002", True, [], "ok", 0.9, "model"),
            LLMMajorJudgeResult("ADV-001", False, ["R3_THREAT_OR_LEGAL_ADVICE"], "threat", 0.9, "model"),
        ]
        cal = calibrate_judge(human_labels, llm_results)
        self.assertEqual(cal.n_scenarios, 3)
        self.assertEqual(cal.cohen_kappa, 1.0)
        self.assertEqual(cal.agreement_rate, 1.0)

    def test_calibration_with_mismatch(self):
        human_labels = [
            HumanLabel("HP-001", "judge1", True, [], "", 1.0),
            HumanLabel("ADV-001", "judge1", False, ["R3_THREAT_OR_LEGAL_ADVICE"], "", 1.0),
        ]
        llm_results = [
            LLMMajorJudgeResult("HP-001", True, [], "ok", 0.9, "model"),
            LLMMajorJudgeResult("ADV-001", False, ["R1_IDENTITY_BYPASS"], "wrong", 0.9, "model"),
        ]
        cal = calibrate_judge(human_labels, llm_results)
        self.assertEqual(cal.n_scenarios, 2)
        self.assertIsInstance(cal.cohen_kappa, float)

    def test_calibration_empty(self):
        cal = calibrate_judge([], [])
        self.assertEqual(cal.n_scenarios, 0)
        self.assertEqual(cal.cohen_kappa, 0.0)
        self.assertEqual(cal.agreement_rate, 0.0)


class TestLLMJudge(unittest.TestCase):
    """Test LLMJudge class."""

    def test_judge_not_available_by_default(self):
        judge = LLMJudge(enabled=False)
        self.assertFalse(judge.is_available())

    def test_deterministic_fallback_no_violations(self):
        from src.loan_agent.agent import LoanServicingAgent
        from src.loan_agent.scenarios import Scenario

        judge = LLMJudge(enabled=False)
        agent = LoanServicingAgent()
        scenario = Scenario(
            scenario_id="HP-001",
            category="happy_path",
            description="Test",
            account_id="ACC-1001",
            messages=[{"role": "user", "content": "Hello"}],
            expected_tool_calls=[],
            expected_rule_violations=[],
            expected_db_state={},
            expected_task_success=True,
        )
        result = judge.judge_scenario(scenario, agent, [], [])
        self.assertIsInstance(result, LLMMajorJudgeResult)
        self.assertEqual(result.model, "deterministic_fallback")


class TestLoadHumanLabels(unittest.TestCase):
    """Test loading human labels from JSONL."""

    def test_load_labels(self):
        test_path = "test_human_labels_tmp.jsonl"
        try:
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"scenario_id": "HP-001", "judge": "j1", "task_success": True, "rule_violations": [], "notes": "", "confidence": 1.0}) + "\n")
                f.write(json.dumps({"scenario_id": "HP-002", "judge": "j1", "task_success": False, "rule_violations": ["R3_THREAT_OR_LEGAL_ADVICE"], "notes": "threat", "confidence": 0.9}) + "\n")

            labels = load_human_labels(test_path)
            self.assertEqual(len(labels), 2)
            self.assertEqual(labels[0].scenario_id, "HP-001")
            self.assertTrue(labels[0].task_success)
            self.assertEqual(labels[1].scenario_id, "HP-002")
            self.assertFalse(labels[1].task_success)
            self.assertEqual(labels[1].rule_violations, ["R3_THREAT_OR_LEGAL_ADVICE"])
        finally:
            if os.path.exists(test_path):
                os.remove(test_path)


if __name__ == "__main__":
    unittest.main()