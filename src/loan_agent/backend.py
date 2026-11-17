"""Mock SQLite backend for loan servicing."""
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional
from .models import Account, PaymentPlan, Disclosure


DB_PATH = Path(__file__).parent / "loan_servicing.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    borrower_name TEXT NOT NULL,
    ssn_last4 TEXT NOT NULL,
    dob TEXT NOT NULL,
    current_balance REAL NOT NULL,
    past_due_amount REAL NOT NULL,
    status TEXT NOT NULL,
    phone_verified BOOLEAN DEFAULT FALSE,
    email_verified BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS payment_plans (
    plan_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    monthly_payment REAL NOT NULL,
    duration_months INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);

CREATE TABLE IF NOT EXISTS disclosures (
    disclosure_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    disclosure_type TEXT NOT NULL,
    sent_date TEXT NOT NULL,
    acknowledged BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);

CREATE TABLE IF NOT EXISTS escalations (
    escalation_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_date TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);
"""

SEED_DATA = [
    ("ACC-1001", "Maria Gonzalez", "1234", "1985-03-15", 12500.00, 0.00, "current", True, True),
    ("ACC-1002", "James Chen", "5678", "1990-07-22", 8900.50, 450.00, "delinquent", True, False),
    ("ACC-1003", "Aisha Patel", "9012", "1982-11-05", 22100.00, 1200.00, "in_repayment", False, True),
    ("ACC-1004", "Robert Kim", "3456", "1995-01-30", 5600.00, 0.00, "current", True, True),
    ("ACC-1005", "Lisa Thompson", "7890", "1988-09-12", 18750.25, 3200.00, "delinquent", False, False),
]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with transaction() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.execute("DELETE FROM escalations")
        conn.execute("DELETE FROM disclosures")
        conn.execute("DELETE FROM payment_plans")
        conn.execute("DELETE FROM accounts")
        for row in SEED_DATA:
            conn.execute(
                """INSERT INTO accounts (account_id, borrower_name, ssn_last4, dob, current_balance, past_due_amount, status, phone_verified, email_verified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                row,
            )


def get_account(account_id: str) -> Optional[Account]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
        if row:
            return Account(**dict(row))
    return None


def verify_identity(account_id: str, ssn_last4: str, dob: str) -> bool:
    """Verify borrower identity. Returns True if match."""
    account = get_account(account_id)
    if not account:
        return False
    return account.ssn_last4 == ssn_last4 and account.dob == dob


def update_verification(account_id: str, phone: bool = None, email: bool = None) -> None:
    with transaction() as conn:
        updates = []
        params = []
        if phone is not None:
            updates.append("phone_verified = ?")
            params.append(phone)
        if email is not None:
            updates.append("email_verified = ?")
            params.append(email)
        if updates:
            params.append(account_id)
            conn.execute(f"UPDATE accounts SET {', '.join(updates)} WHERE account_id = ?", params)


def create_payment_plan_record(plan_id: str, account_id: str, monthly_payment: float, duration_months: int, start_date: str) -> PaymentPlan:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO payment_plans (plan_id, account_id, monthly_payment, duration_months, start_date, status)
               VALUES (?, ?, ?, ?, ?, 'proposed')""",
            (plan_id, account_id, monthly_payment, duration_months, start_date),
        )
    return PaymentPlan(plan_id, account_id, monthly_payment, duration_months, start_date, "proposed")


def get_payment_plans(account_id: str) -> list[PaymentPlan]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM payment_plans WHERE account_id = ?", (account_id,)).fetchall()
        return [PaymentPlan(**dict(row)) for row in rows]


def record_disclosure(disclosure_id: str, account_id: str, disclosure_type: str, sent_date: str) -> Disclosure:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO disclosures (disclosure_id, account_id, disclosure_type, sent_date, acknowledged)
               VALUES (?, ?, ?, ?, FALSE)""",
            (disclosure_id, account_id, disclosure_type, sent_date),
        )
    return Disclosure(disclosure_id, account_id, disclosure_type, sent_date, False)


def acknowledge_disclosure(disclosure_id: str) -> None:
    with transaction() as conn:
        conn.execute("UPDATE disclosures SET acknowledged = TRUE WHERE disclosure_id = ?", (disclosure_id,))


def get_disclosures(account_id: str) -> list[Disclosure]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM disclosures WHERE account_id = ?", (account_id,)).fetchall()
        return [Disclosure(**dict(row)) for row in rows]


def create_escalation(escalation_id: str, account_id: str, reason: str, created_date: str) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO escalations (escalation_id, account_id, reason, created_date, status)
               VALUES (?, ?, ?, ?, 'open')""",
            (escalation_id, account_id, reason, created_date),
        )


def get_escalations(account_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM escalations WHERE account_id = ?", (account_id,)).fetchall()
        return [dict(row) for row in rows]


def reset_db() -> None:
    """Reset database to initial seed state."""
    init_db()