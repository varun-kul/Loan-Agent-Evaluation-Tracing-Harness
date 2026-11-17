"""Unit tests for the tool functions."""
import pytest
from src.loan_agent.tools import (
    lookup_account,
    get_payment_options,
    create_payment_plan,
    send_required_disclosure,
    escalate_to_human,
    check_escalation_triggers,
)
from src.loan_agent.backend import reset_db


@pytest.fixture(autouse=True)
def clean_db():
    reset_db()
    yield
    reset_db()


class TestLookupAccount:
    def test_lookup_without_verification_redacts_balance(self):
        result = lookup_account("ACC-1001")
        assert result["success"] is True
        assert result["identity_verified"] is False
        assert result["current_balance"] == "REDACTED - verify identity first"
        assert result["past_due_amount"] == 0.00

    def test_lookup_with_verification_shows_balance(self):
        result = lookup_account("ACC-1001", ssn_last4="1234", dob="1985-03-15")
        assert result["success"] is True
        assert result["identity_verified"] is True
        assert result["current_balance"] == 12500.00

    def test_lookup_wrong_credentials(self):
        result = lookup_account("ACC-1001", ssn_last4="0000", dob="1985-03-15")
        assert result["identity_verified"] is False
        assert result["current_balance"] == "REDACTED - verify identity first"

    def test_lookup_nonexistent_account(self):
        result = lookup_account("ACC-9999")
        assert result["success"] is False
        assert result["error"] == "Account not found"


class TestGetPaymentOptions:
    def test_get_options_requires_verification(self):
        result = get_payment_options("ACC-1001")
        assert result["success"] is False
        assert result["error"] == "Identity verification required"

    def test_get_options_with_verification(self):
        result = get_payment_options("ACC-1001", ssn_last4="1234", dob="1985-03-15")
        assert result["success"] is True
        assert "options" in result
        assert len(result["options"]) >= 2  # standard and extended at minimum
        assert result["total_balance"] == 12500.00

    def test_get_options_delinquent_account(self):
        # ACC-1002 has past_due_amount
        result = get_payment_options("ACC-1002", ssn_last4="5678", dob="1990-07-22")
        assert result["success"] is True
        assert result["total_balance"] == 9350.50  # 8900.50 + 450.00


class TestCreatePaymentPlan:
    def test_create_plan_requires_verification(self):
        result = create_payment_plan("ACC-1001", "standard", 347.22, 36)
        assert result["success"] is False
        assert result["error"] == "Identity verification required"

    def test_create_plan_requires_disclosure_first(self):
        result = create_payment_plan("ACC-1001", "standard", 347.22, 36, ssn_last4="1234", dob="1985-03-15")
        assert result["success"] is False
        assert result["error"] == "Required disclosure must be sent before creating payment plan"

    def test_create_plan_after_disclosure(self):
        send_required_disclosure("ACC-1001")
        result = create_payment_plan("ACC-1001", "standard", 347.22, 36, ssn_last4="1234", dob="1985-03-15")
        assert result["success"] is True
        assert "plan_id" in result
        assert result["monthly_payment"] == 347.22
        assert result["duration_months"] == 36


class TestSendRequiredDisclosure:
    def test_send_disclosure(self):
        result = send_required_disclosure("ACC-1001")
        assert result["success"] is True
        assert result["disclosure_type"] == "required_disclosure"
        assert "disclosure_id" in result

    def test_send_disclosure_nonexistent_account(self):
        result = send_required_disclosure("ACC-9999")
        assert result["success"] is False
        assert result["error"] == "Account not found"


class TestEscalateToHuman:
    def test_escalate_creates_record(self):
        result = escalate_to_human("ACC-1001", "customer_request")
        assert result["success"] is True
        assert "escalation_id" in result
        assert result["reason"] == "customer_request"

    def test_escalate_nonexistent_account(self):
        result = escalate_to_human("ACC-9999", "test")
        assert result["success"] is False
        assert result["error"] == "Account not found"


class TestEscalationTriggers:
    def test_dispute_keyword_detected(self):
        assert check_escalation_triggers("I dispute this charge") == "dispute_keyword:dispute"
        assert check_escalation_triggers("This is incorrect") == "dispute_keyword:incorrect"
        assert check_escalation_triggers("I think there's an error") == "dispute_keyword:error"
        assert check_escalation_triggers("This is fraud") == "dispute_keyword:fraud"

    def test_distress_keyword_detected(self):
        assert check_escalation_triggers("I can't pay this") == "distress_keyword:can't pay"
        assert check_escalation_triggers("I lost my job") == "distress_keyword:lost my job"
        assert check_escalation_triggers("Medical emergency") == "distress_keyword:medical"
        assert check_escalation_triggers("I'm desperate") == "distress_keyword:desperate"

    def test_no_trigger_returns_none(self):
        assert check_escalation_triggers("Hello, I'd like to know my balance") is None
        assert check_escalation_triggers("What are my payment options?") is None