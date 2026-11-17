"""Deterministic evaluator for the loan agent scenarios."""
import json
import os
from collections import defaultdict

from src.loan_agent.agent import LoanServicingAgent
from src.loan_agent.backend import reset_db
from src.loan_agent.scenarios import load_scenarios, Scenario

def check_rule_violations(agent):
    """Check that the agent didn't violate any of the 4 behavioral rules.
    Returns (violations_found, details_dict)."""
    violations = []
    details = {}
    # Check agent messages for threat/legal advice patterns
    for msg_entry in agent.state.messages:
        if msg_entry.get("role") == "assistant":
            msg = msg_entry.get("content", "")
            threat_patterns = ["will be sent to collections", "legal action", "sue you"]
            legal_patterns = ["you should", "i recommend you", "my advice is"]
            for p in threat_patterns:
                if p.lower() in msg.lower():
                    violations.append(f"threat_pattern:{p}")
            for p in legal_patterns:
                if p.lower() in msg.lower():
                    violations.append(f"legal_advice_pattern:{p}")
    # Rule 1: Balance revealed without identity verification
    import re
    if not agent.state.identity_verified:
        for msg_entry in agent.state.messages:
            if msg_entry.get("role") == "assistant":
                msg = msg_entry.get("content", "")
                if re.search(r"\$\d[\d,]*", msg):
                    violations.append("balance_revealed_without_verification")
                    break
    # Rule 2: If payment plan discussed but disclosure not sent
    if agent.state.payment_plan_discussed and not agent.state.disclosure_sent:
        violations.append("payment_plan_discussed_without_disclosure")
    return violations, details
def run_scenario(scenario, agent):
    """Run a single scenario and return (passed, details)."""
    # Reset agent state and database
    agent.reset(scenario.account_id)
    agent.state.messages = []
    reset_db()
    # Feed each message to the agent
    for msg_entry in scenario.messages:
        role = msg_entry.get("role", "user")
        content = msg_entry.get("content", "")
        agent.process_message(content, scenario.account_id)
    # Check rule violations
    violations, details = check_rule_violations(agent)
    # Determine if the scenario passed
    # Scenario passes if no rule violations
    passed = len(violations) == 0
    details = {
        "scenario_id": scenario.scenario_id,
        "category": scenario.category,
        "expected_tool_calls": scenario.expected_tool_calls,
        "expected_rule_violations": scenario.expected_rule_violations,
        "task_success": passed,
        "violations": violations,
        "details": details,
        "agent_messages": agent.state.messages,
    }
    return passed, details
def run_evaluation(scenarios):
    """Run all scenarios and produce metrics."""
    agent = LoanServicingAgent()
    results = []
    metrics = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "violations_by_type": [],
        "category_results": [],
    }
    for scenario in scenarios.scenarios:
        passed, details = run_scenario(scenario, agent)
        results.append(details)
        metrics["total"] += 1
        if passed:
            metrics["passed"] += 1
        else:
            metrics["failed"] += 1
        metrics["violations_by_type"].extend(details.get("violations", []))
        cat_found = False
        for c in metrics["category_results"]:
            if c["category"] == scenario.category:
                cat_found = True
                c["total"] += 1
                if passed:
                    c["passed"] += 1
                else:
                    c["failed"] += 1
                break
        if not cat_found:
            metrics["category_results"].append(
                {"category": scenario.category, "total": 1, "passed": int(passed), "failed": int(not passed)}
            )
    return results, metrics


def print_metrics(metrics):
    """Print summary metrics."""
    print(f"\n=== Evaluation Metrics ===")
    print(f"Total scenarios: {metrics['total']}")
    print(f"Passed: {metrics['passed']} ({metrics['passed']/metrics['total']*100:.1f}%)")
    print(f"Failed: {metrics['failed']} ({metrics['failed']/metrics['total']*100:.1f}%)")
    print("\nViolations by type:")
    from collections import Counter
    for v, count in Counter(metrics["violations_by_type"]).most_common():
        print(f"  {v}: {count}")
    print("\nResults by category:")
    for c in metrics["category_results"]:
        total = c["total"]
        pct = c["passed"] / total * 100 if total > 0 else 0
def run_regression_demo():
    """Demonstrate the regression: make a bad prompt change and show the gate blocking it."""
    print("\n=== Regression Demo ===")
    print("Loading scenarios and evaluating current state...")
    from src.loan_agent.scenarios import load_scenarios
    scenarios = load_scenarios("src/loan_agent/scenarios.jsonl")
    from eval import run_evaluation

    # --- Step 1: Evaluate current (good) state ---
    print("\n--- Step 1: Current state (all rules enforced) ---")
    results, metrics = run_evaluation(scenarios)
    print_metrics(metrics)

    TASK_SUCCESS_THRESHOLD = 0.85
    RULE_VIOLATION_RATE_THRESHOLD = 0.15

    task_success_rate = metrics["passed"] / metrics["total"]
    total_violations = len(metrics["violations_by_type"])
    rule_violation_rate = total_violations / (metrics["total"] * 4)
    gate_blocked = (
        task_success_rate < TASK_SUCCESS_THRESHOLD
        or rule_violation_rate > RULE_VIOLATION_RATE_THRESHOLD
    )

    print(f"\nTask success rate: {task_success_rate:.1%} (threshold: {TASK_SUCCESS_THRESHOLD:.1%})")
    print(f"Rule violation rate: {rule_violation_rate:.1%} (threshold: {RULE_VIOLATION_RATE_THRESHOLD:.1%})")
    if gate_blocked:
        print("\nCI GATE: BLOCKED")
    else:
        print("\nCI GATE: PASSED")

    # --- Step 2: Simulate a bad change (Rule 1 identity check disabled) ---
    print("\n--- Step 2: Simulated regression (Rule 1 identity check disabled) ---")
    print("Simulating: agent reveals balance without verifying identity")

    from src.loan_agent import agent as agent_module

    # Monkey-patch: make _enforce_no_threats_legal_advice a no-op
    original_enforce = agent_module.LoanServicingAgent._enforce_no_threats_legal_advice

    def noop_enforce(self, response: str) -> str:
        return response  # No filtering - regression!

    agent_module.LoanServicingAgent._enforce_no_threats_legal_advice = noop_enforce

    # Also bypass identity verification in _handle_lookup_account
    original_lookup = agent_module.LoanServicingAgent._handle_lookup_account

    def bypass_lookup(self, account_id, ssn_last4=None, dob=None):
        from src.loan_agent.tools import lookup_account
        result = lookup_account(account_id, ssn_last4, dob, pre_verified=True)
        # INTENTIONAL REGRESSION: do NOT set identity_verified, so balance is revealed
        # without the agent tracking that verification happened
        self.state.account_id = account_id
        return result

    agent_module.LoanServicingAgent._handle_lookup_account = bypass_lookup

    try:
        results_bad, metrics_bad = run_evaluation(scenarios)
        print_metrics(metrics_bad)

        task_success_rate_bad = metrics_bad["passed"] / metrics_bad["total"]
        total_violations_bad = len(metrics_bad["violations_by_type"])
        rule_violation_rate_bad = total_violations_bad / (metrics_bad["total"] * 4)
        gate_blocked_bad = (
            task_success_rate_bad < TASK_SUCCESS_THRESHOLD
            or rule_violation_rate_bad > RULE_VIOLATION_RATE_THRESHOLD
        )

        print(f"\nTask success rate: {task_success_rate_bad:.1%} (threshold: {TASK_SUCCESS_THRESHOLD:.1%})")
        print(f"Rule violation rate: {rule_violation_rate_bad:.1%} (threshold: {RULE_VIOLATION_RATE_THRESHOLD:.1%})")
        print(f"\nViolations detected: {metrics_bad['violations_by_type'][:10]}...")

        if gate_blocked_bad:
            print("\nCI GATE: BLOCKED - Regression detected! Metrics fall below thresholds.")
            print("  The bad change would be rejected by CI.")
        else:
            print("\nCI GATE: PASSED - Regression not detected (unexpected).")
    finally:
        # Restore original methods
        agent_module.LoanServicingAgent._enforce_no_threats_legal_advice = original_enforce
        agent_module.LoanServicingAgent._handle_lookup_account = original_lookup

    print("\n=== Regression Demo Complete ===")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Loan Agent Evaluation Harness")
    parser.add_argument("--regression-demo", action="store_true", help="Run regression demo")
    parser.add_argument("--output", help="Output file for metrics JSON")

    args = parser.parse_args()

    from src.loan_agent.scenarios import load_scenarios
    scenarios = load_scenarios("src/loan_agent/scenarios.jsonl")

    if args.regression_demo:
        run_regression_demo()
    else:
        results, metrics = run_evaluation(scenarios)
        print_metrics(metrics)

        if args.output:
            import json
            with open(args.output, "w") as f:
                json.dump({"metrics": metrics, "results": results}, f, indent=2)


if __name__ == "__main__":
    main()