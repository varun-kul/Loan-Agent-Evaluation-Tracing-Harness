"""Tests for LLM agent integration - mocked, no Ollama required."""
import pytest
from unittest.mock import MagicMock, patch
from src.loan_agent.agent import LoanServicingAgent
from src.loan_agent.llm_client import LLMDecision
from src.loan_agent.backend import reset_db


@pytest.fixture(autouse=True)
def clean_db():
    reset_db()
    yield
    reset_db()


@pytest.fixture
def agent_no_llm():
    """Agent with LLM disabled (keyword fallback)."""
    return LoanServicingAgent(use_llm=False)


@pytest.fixture
def agent_llm_mock():
    """Agent with LLM enabled flag."""
    return LoanServicingAgent(use_llm=True)


class TestLLMClientDisabled:
    """Test that LLM client gracefully handles being disabled."""

    def test_llm_disabled_returns_none_decision(self):
        from src.loan_agent.llm_client import LLMClient
        client = LLMClient()
        client.enabled = False
        decision = client.decide_tool(
            user_message="What's my balance?",
            conversation_history=[],
            available_tools=["lookup_account"],
        )
        assert decision.tool is None
        assert decision.args == {}
        assert "disabled" in decision.reasoning.lower()

    def test_llm_not_available_when_ollama_not_running(self):
        from src.loan_agent.llm_client import LLMClient
        client = LLMClient()
        client.enabled = True
        client.provider = "ollama"  # Force ollama (not running)
        client.api_key = None
        assert client.is_available() is False


class TestAgentWithLLMDisabled:
    """Agent falls back to keyword parsing when LLM disabled."""

    def test_lookup_with_credentials(self, agent_no_llm):
        result = agent_no_llm.process_message(
            "What's my balance? SSN 1234, DOB 1985-03-15", account_id="ACC-1001"
        )
        assert "12500" in result["response"] or "12,500" in result["response"]

    def test_disclosure_before_payment_options(self, agent_no_llm):
        agent_no_llm.process_message("SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        result = agent_no_llm.process_message(
            "What are my payment options? SSN 1234, DOB 1985-03-15"
        )
        assert "disclosure" in result["response"].lower()

    def test_escalation_on_dispute(self, agent_no_llm):
        agent_no_llm.process_message("SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        result = agent_no_llm.process_message("I dispute this charge")
        assert result.get("escalated") is True


class TestAgentWithMockedLLM:
    """Test agent behavior when LLM returns specific decisions."""

    def test_llm_decides_lookup_account(self, agent_llm_mock):
        from src.loan_agent import llm_client as lc_module
        lc_module.llm_client.decide_tool = MagicMock(return_value=LLMDecision(
            tool="lookup_account",
            args={"account_id": "ACC-1001", "ssn_last4": "1234", "dob": "1985-03-15"},
            reasoning="User wants balance, has credentials",
            response_text=None,
        ))
        result = agent_llm_mock.process_message(
            "What's my balance?", account_id="ACC-1001"
        )
        assert "12500" in result["response"] or "12,500" in result["response"]

    def test_llm_decides_no_tool_with_response_text(self, agent_llm_mock):
        from src.loan_agent import llm_client as lc_module
        lc_module.llm_client.decide_tool = MagicMock(return_value=LLMDecision(
            tool=None,
            args={},
            reasoning="Greeting, no tool needed",
            response_text="Hello! How can I help you with your loan today?",
        ))
        result = agent_llm_mock.process_message("Hello", account_id="ACC-1001")
        assert "Hello!" in result["response"]

    def test_llm_decides_escalate(self, agent_llm_mock):
        from src.loan_agent import llm_client as lc_module
        lc_module.llm_client.decide_tool = MagicMock(return_value=LLMDecision(
            tool="escalate_to_human",
            args={"account_id": "ACC-1001", "reason": "distress_keyword:desperate"},
            reasoning="User expressed distress",
            response_text=None,
        ))
        result = agent_llm_mock.process_message(
            "I'm desperate, help me", account_id="ACC-1001"
        )
        assert result.get("escalated") is True

    def test_llm_cannot_bypass_disclosure_rule(self, agent_llm_mock):
        """Even if LLM tries to create a plan without disclosure, agent blocks it."""
        from src.loan_agent import llm_client as lc_module
        lc_module.llm_client.decide_tool = MagicMock(return_value=LLMDecision(
            tool="create_payment_plan",
            args={
                "account_id": "ACC-1001",
                "plan_type": "standard",
                "monthly_payment": 347.22,
                "duration_months": 36,
                "ssn_last4": "1234",
                "dob": "1985-03-15",
            },
            reasoning="User wants payment plan",
            response_text=None,
        ))
        agent_llm_mock.process_message(
            "SSN 1234, DOB 1985-03-15", account_id="ACC-1001"
        )
        result = agent_llm_mock.process_message(
            "Create standard plan $347/month for 36 months"
        )
        assert "disclosure" in result["response"].lower()
        assert "required disclosure" in result["response"].lower()