"""Unit tests for the mock backend."""
import pytest
from src.loan_agent.backend import init_db, reset_db, get_account, verify_identity, update_verification
from src.loan_agent.backend import create_payment_plan_record, get_payment_plans, record_disclosure, get_disclosures
from src.loan_agent.backend import create_escalation, get_escalations
from src.loan_agent.models import Account, PaymentPlan, Disclosure


@pytest.fixture(autouse=True)
def clean_db():
    """Reset database before each test."""
    reset_db()
    yield
    reset_db()


class TestAccountOperations:
    def test_get_account_exists(self):
        account = get_account("ACC-1001")
        assert account is not None
        assert account.account_id == "ACC-1001"
        assert account.borrower_name == "Maria Gonzalez"
        assert account.current_balance == 12500.00
        assert account.status == "current"

    def test_get_account_not_found(self):
        account = get_account("ACC-9999")
        assert account is None

    def test_verify_identity_success(self):
        assert verify_identity("ACC-1001", "1234", "1985-03-15") is True

    def test_verify_identity_wrong_ssn(self):
        assert verify_identity("ACC-1001", "0000", "1985-03-15") is False

    def test_verify_identity_wrong_dob(self):
        assert verify_identity("ACC-1001", "1234", "1990-01-01") is False

    def test_verify_identity_nonexistent_account(self):
        assert verify_identity("ACC-9999", "1234", "1985-03-15") is False

    def test_update_verification(self):
        update_verification("ACC-1001", phone=True, email=True)
        account = get_account("ACC-1001")
        assert account.phone_verified is True
        assert account.email_verified is True


class TestPaymentPlans:
    def test_create_payment_plan_record(self):
        plan = create_payment_plan_record("PLAN-TEST", "ACC-1001", 250.00, 36, "2024-01-15")
        assert plan.plan_id == "PLAN-TEST"
        assert plan.monthly_payment == 250.00
        assert plan.duration_months == 36
        assert plan.status == "proposed"

    def test_get_payment_plans(self):
        create_payment_plan_record("PLAN-1", "ACC-1001", 250.00, 36, "2024-01-15")
        create_payment_plan_record("PLAN-2", "ACC-1001", 150.00, 60, "2024-02-01")
        plans = get_payment_plans("ACC-1001")
        assert len(plans) == 2
        assert plans[0].monthly_payment == 250.00
        assert plans[1].monthly_payment == 150.00

    def test_get_payment_plans_empty(self):
        plans = get_payment_plans("ACC-1001")
        assert plans == []


class TestDisclosures:
    def test_record_disclosure(self):
        disc = record_disclosure("DISC-TEST", "ACC-1001", "required_disclosure", "2024-01-15")
        assert disc.disclosure_id == "DISC-TEST"
        assert disc.disclosure_type == "required_disclosure"
        assert disc.acknowledged is False

    def test_get_disclosures(self):
        record_disclosure("DISC-1", "ACC-1001", "required_disclosure", "2024-01-15")
        record_disclosure("DISC-2", "ACC-1001", "payment_plan_terms", "2024-01-20")
        discs = get_disclosures("ACC-1001")
        assert len(discs) == 2
        assert discs[0].disclosure_type == "required_disclosure"
        assert discs[1].disclosure_type == "payment_plan_terms"


class TestEscalations:
    def test_create_escalation(self):
        create_escalation("ESC-TEST", "ACC-1001", "dispute_keyword:fraud", "2024-01-15")
        escalations = get_escalations("ACC-1001")
        assert len(escalations) == 1
        assert escalations[0]["reason"] == "dispute_keyword:fraud"
        assert escalations[0]["status"] == "open"

    def test_get_escalations_empty(self):
        escalations = get_escalations("ACC-1001")
        assert escalations == []


class TestDatabaseReset:
    def test_reset_db_restores_seed_data(self):
        # Modify data
        create_payment_plan_record("PLAN-TEST", "ACC-1001", 100.00, 12, "2024-01-01")
        reset_db()
        # Should be back to seed state
        plans = get_payment_plans("ACC-1001")
        assert plans == []
        account = get_account("ACC-1001")
        assert account.current_balance == 12500.00