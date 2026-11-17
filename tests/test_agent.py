"""Integration tests for the LoanServicingAgent - verifying rule enforcement."""
import pytest
from src.loan_agent.agent import LoanServicingAgent, RuleViolation
from src.loan_agent.backend import reset_db


@pytest.fixture(autouse=True)
def clean_db():
    reset_db()
    yield
    reset_db()


@pytest.fixture
def agent():
    """Fresh agent instance for each test."""
    return LoanServicingAgent()


class TestRule1_IdentityVerification:
    """Rule 1: Verify identity before revealing any balance."""
    
    def test_lookup_without_credentials_redacts_balance(self, agent):
        result = agent.process_message("What's my balance?", account_id="ACC-1001")
        assert "REDACTED" in result["response"] or "verify your identity" in result["response"].lower()
        assert "12500" not in result["response"]
    
    def test_lookup_with_credentials_shows_balance(self, agent):
        result = agent.process_message("My balance please. SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        assert "12500" in result["response"] or "12,500" in result["response"]
        assert "REDACTED" not in result["response"]
    
    def test_lookup_wrong_credentials_redacts_balance(self, agent):
        result = agent.process_message("Balance. SSN 0000, DOB 1985-03-15", account_id="ACC-1001")
        assert "REDACTED" in result["response"] or "verify your identity" in result["response"].lower()
        assert "12500" not in result["response"]


class TestRule2_DisclosureBeforePaymentPlan:
    """Rule 2: Deliver required disclosure before discussing payment plan."""
    
    def test_payment_options_requires_disclosure(self, agent):
        agent.process_message("SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        # Ask for payment options WITH credentials to pass identity check
        result = agent.process_message("What are my payment options? SSN 1234, DOB 1985-03-15")
        assert "disclosure" in result["response"].lower()
        assert "required disclosure" in result["response"].lower()
    
    def test_create_plan_requires_disclosure(self, agent):
        agent.process_message("What's my balance? SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        result = agent.process_message("Create standard plan $347/month for 36 months")
        assert "disclosure" in result["response"].lower()
        assert "required disclosure" in result["response"].lower()
    
    def test_payment_options_after_disclosure_works(self, agent):
        agent.process_message("SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        agent.process_message("Send required disclosure")
        result = agent.process_message("What are my payment options? SSN 1234, DOB 1985-03-15")
        assert "payment option" in result["response"].lower() or "standard" in result["response"].lower()
        assert "disclosure" not in result["response"].lower() or "sent" in result["response"].lower()


class TestRule3_NoThreatsOrLegalAdvice:
    """Rule 3: Never threaten or give legal advice."""
    
    def test_agent_rejects_threat_language(self, agent):
        with pytest.raises(RuleViolation) as exc:
            agent._enforce_no_threats_legal_advice("If you don't pay, we will sue you and take legal action")
        assert exc.value.rule == "no_threats"
    
    def test_agent_rejects_legal_advice_language(self, agent):
        with pytest.raises(RuleViolation) as exc:
            # Use "legally you must" which is in legal_advice_patterns but not in threat_patterns
            agent._enforce_no_threats_legal_advice("Legally you must pay this amount immediately")
        assert exc.value.rule == "no_legal_advice"
    
    def test_agent_allows_normal_responses(self, agent):
        response = agent._enforce_no_threats_legal_advice("Here are your payment options for $500/month")
        assert response == "Here are your payment options for $500/month"


class TestRule4_EscalationTriggers:
    """Rule 4: Escalate on dispute or distress keywords."""
    
    def test_dispute_keyword_triggers_escalation(self, agent):
        agent.process_message("SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        result = agent.process_message("I dispute this charge - it's wrong!")
        assert result.get("escalated") is True
        assert "dispute_keyword" in result.get("trigger", "")
    
    def test_distress_keyword_triggers_escalation(self, agent):
        agent.process_message("SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        result = agent.process_message("I can't pay this, I lost my job")
        assert result.get("escalated") is True
        assert "distress_keyword" in result.get("trigger", "")
    
    def test_fraud_keyword_triggers_escalation(self, agent):
        agent.process_message("SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        result = agent.process_message("This is fraud, someone stole my identity")
        assert result.get("escalated") is True
        assert "fraud" in result.get("trigger", "")
    
    def test_medical_emergency_triggers_escalation(self, agent):
        agent.process_message("SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        result = agent.process_message("I have a medical emergency situation")
        assert result.get("escalated") is True
        assert "medical" in result.get("trigger", "")
class TestHappyPaths:
    """End-to-end happy path tests."""
    
    def test_full_flow_lookup_then_payment_plan(self, agent):
        result = agent.process_message("What's my balance? SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        assert "12500" in result["response"] or "12,500" in result["response"]
        
        result = agent.process_message("Send required disclosure")
        assert "disclosure" in result["response"].lower()
        assert "sent" in result["response"].lower()
        
        result = agent.process_message("What are my payment options? SSN 1234, DOB 1985-03-15")
        assert "standard" in result["response"].lower()
        assert "extended" in result["response"].lower()
        
        result = agent.process_message("Create standard plan $347/month for 36 months")
        assert "payment plan created" in result["response"].lower()
        assert "plan id" in result["response"].lower()
    
    def test_delinquent_account_flow(self, agent):
        result = agent.process_message("Balance? SSN 5678, DOB 1990-07-22", account_id="ACC-1002")
        # Total balance = 8900.50 + 450 = 9350.50; response shows "$8,900.50"
        assert "8,900" in result["response"] or "8900.50" in result["response"]
        
        agent.process_message("Send disclosure")
        result = agent.process_message("Payment options? SSN 5678, DOB 1990-07-22")
        assert "standard" in result["response"].lower()
    
    def test_explicit_escalation_request(self, agent):
        agent.process_message("SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        result = agent.process_message("I want to talk to a human representative")
        assert result.get("escalated") is True
        assert "human" in result["response"].lower()


class TestConversationState:
    """Test that conversation state persists across messages."""
    
    def test_identity_verified_persists(self, agent):
        agent.process_message("What's my balance? SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        result = agent.process_message("What's my balance?")
        assert "12500" in result["response"] or "12,500" in result["response"]

    def test_disclosure_sent_persists(self, agent):
        agent.process_message("What's my balance? SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        agent.process_message("Send disclosure")
        result = agent.process_message("Payment options? SSN 1234, DOB 1985-03-15")
        assert "standard" in result["response"].lower()
    
    def test_reset_clears_state(self, agent):
        agent.process_message("What's my balance? SSN 1234, DOB 1985-03-15", account_id="ACC-1001")
        agent.reset(account_id="ACC-1001")
        result = agent.process_message("What's my balance?")
        assert "REDACTED" in result["response"] or "verify" in result["response"].lower()