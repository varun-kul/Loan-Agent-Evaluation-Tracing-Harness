"""Data models for loan servicing."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Account:
    account_id: str
    borrower_name: str
    ssn_last4: str
    dob: str  # YYYY-MM-DD
    current_balance: float
    past_due_amount: float
    status: str  # current, delinquent, in_repayment, paid_off
    phone_verified: bool = False
    email_verified: bool = False

    def __post_init__(self):
        # SQLite returns 1/0 for booleans, convert to bool
        self.phone_verified = bool(self.phone_verified)
        self.email_verified = bool(self.email_verified)


@dataclass
class PaymentPlan:
    plan_id: str
    account_id: str
    monthly_payment: float
    duration_months: int
    start_date: str
    status: str  # proposed, active, completed, cancelled


@dataclass
class Disclosure:
    disclosure_id: str
    account_id: str
    disclosure_type: str  # required_disclosure, payment_plan_terms
    sent_date: str
    acknowledged: bool = False

    def __post_init__(self):
        self.acknowledged = bool(self.acknowledged)