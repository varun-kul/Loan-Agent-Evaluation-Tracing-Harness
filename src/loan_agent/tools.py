"""Tool implementations for the loan servicing agent."""
from datetime import date
from typing import Optional
from .backend import (
    get_account,
    verify_identity,
    update_verification,
    create_payment_plan_record,
    get_payment_plans,
    record_disclosure,
    acknowledge_disclosure,
    get_disclosures,
    create_escalation,
    get_escalations,
)
from .models import Account, PaymentPlan, Disclosure
# Tool: lookup_account
def lookup_account(account_id: str, ssn_last4: str = None, dob: str = None, pre_verified: bool = False) -> dict:
    """
    Look up account details. Requires identity verification (ssn_last4 + dob) to reveal balance info.
    Returns account info with balance only if verified.
    """
    account = get_account(account_id)
    if not account:
        return {"success": False, "error": "Account not found"}

    verified = pre_verified
    if not verified and ssn_last4 and dob:
        verified = verify_identity(account_id, ssn_last4, dob)
        if verified:
            update_verification(account_id, phone=True, email=True)

    result = {
        "success": True,
        "account_id": account.account_id,
        "borrower_name": account.borrower_name,
        "status": account.status,
        "past_due_amount": account.past_due_amount,
        "identity_verified": verified,
    }

    if verified:
        result["current_balance"] = account.current_balance
    else:
        result["current_balance"] = "REDACTED - verify identity first"

    return result


# Tool: get_payment_options
def get_payment_options(account_id: str, ssn_last4: str = None, dob: str = None, pre_verified: bool = False) -> dict:
    """
    Get available payment plan options for an account.
    Requires identity verification.
    """
    account = get_account(account_id)
    if not account:
        return {"success": False, "error": "Account not found"}

    verified = pre_verified
    if not verified and ssn_last4 and dob:
        verified = verify_identity(account_id, ssn_last4, dob)

    if not verified:
        return {"success": False, "error": "Identity verification required"}

    balance = account.current_balance + account.past_due_amount
    options = []

    monthly_36 = round(balance / 36, 2)
    options.append({"plan_type": "standard", "duration_months": 36, "monthly_payment": monthly_36})

    monthly_60 = round(balance / 60, 2)
    options.append({"plan_type": "extended", "duration_months": 60, "monthly_payment": monthly_60})

    if balance / 24 <= 1000:
        monthly_24 = round(balance / 24, 2)
        options.append({"plan_type": "accelerated", "duration_months": 24, "monthly_payment": monthly_24})

    return {
        "success": True,
        "account_id": account_id,
        "total_balance": balance,
        "options": options,
    }
# Tool: create_payment_plan
def create_payment_plan(account_id: str, plan_type: str, monthly_payment: float, duration_months: int, ssn_last4: str = None, dob: str = None, pre_verified: bool = False) -> dict:
    """
    Create a payment plan. Requires identity verification AND required disclosure sent first.
    """
    account = get_account(account_id)
    if not account:
        return {"success": False, "error": "Account not found"}

    verified = pre_verified
    if not verified and ssn_last4 and dob:
        verified = verify_identity(account_id, ssn_last4, dob)

    if not verified:
        return {"success": False, "error": "Identity verification required"}

    disclosures = get_disclosures(account_id)
    required_sent = any(d.disclosure_type == "required_disclosure" for d in disclosures)

    if not required_sent:
        return {"success": False, "error": "Required disclosure must be sent before creating payment plan"}

    plan_id = f"PLAN-{account_id}-{date.today().strftime('%Y%m%d')}"
    plan = create_payment_plan_record(plan_id, account_id, monthly_payment, duration_months, date.today().isoformat())

    return {
        "success": True,
        "plan_id": plan.plan_id,
        "monthly_payment": plan.monthly_payment,
        "duration_months": plan.duration_months,
        "start_date": plan.start_date,
        "status": plan.status,
    }


# Tool: send_required_disclosure
def send_required_disclosure(account_id: str, disclosure_type: str = "required_disclosure") -> dict:
    """
    Send required disclosure to borrower. Must be sent before discussing payment plans.
    """
    account = get_account(account_id)
    if not account:
        return {"success": False, "error": "Account not found"}

    disclosure_id = f"DISC-{account_id}-{date.today().strftime('%Y%m%d')}"
    disclosure = record_disclosure(disclosure_id, account_id, disclosure_type, date.today().isoformat())

    return {
        "success": True,
        "disclosure_id": disclosure.disclosure_id,
        "disclosure_type": disclosure.disclosure_type,
        "sent_date": disclosure.sent_date,
    }


# Tool: escalate_to_human
def escalate_to_human(account_id: str, reason: str) -> dict:
    """
    Escalate to human agent. Triggered by dispute/distress keywords or explicit request.
    """
    account = get_account(account_id)
    if not account:
        return {"success": False, "error": "Account not found"}

    escalation_id = f"ESC-{account_id}-{date.today().strftime('%Y%m%d%H%M%S')}"
    create_escalation(escalation_id, account_id, reason, date.today().isoformat())

    return {
        "success": True,
        "escalation_id": escalation_id,
        "reason": reason,
        "message": "Your case has been escalated to a human agent. They will contact you within 1 business day.",
    }


# Helper: detect escalation triggers
DISPUTE_KEYWORDS = ["dispute", "disagree", "wrong", "incorrect", "error", "mistake", "fraud", "identity theft"]
DISTRESS_KEYWORDS = ["hardship", "can't pay", "cannot pay", "unemployed", "job loss", "lost my job", "lost job", "fired", "laid off", "medical", "emergency", "desperate", "suicide", "hopeless"]

def check_escalation_triggers(message: str) -> Optional[str]:
    """Check if message contains dispute or distress keywords. Returns trigger reason if found."""
    message_lower = message.lower()
    for kw in DISPUTE_KEYWORDS:
        if kw in message_lower:
            return f"dispute_keyword:{kw}"
    for kw in DISTRESS_KEYWORDS:
        if kw in message_lower:
            return f"distress_keyword:{kw}"
    return None