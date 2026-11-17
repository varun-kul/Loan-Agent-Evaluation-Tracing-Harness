"""Loan servicing agent with programmatic rule enforcement and optional LLM integration."""
from dataclasses import dataclass, field
from typing import Optional
import re
from .tools import (
    lookup_account,
    get_payment_options,
    create_payment_plan,
    send_required_disclosure,
    escalate_to_human,
    check_escalation_triggers,
)
from .llm_client import llm_client, LLMDecision
from .tracing import tracer


@dataclass
class ConversationState:
    """Tracks conversation state for rule enforcement."""
    account_id: Optional[str] = None
    identity_verified: bool = False
    disclosure_sent: bool = False
    payment_plan_discussed: bool = False
    escalated: bool = False
    messages: list[dict] = field(default_factory=list)


class RuleViolation(Exception):
    """Raised when agent would violate a behavioral rule."""
    def __init__(self, rule: str, message: str):
        self.rule = rule
        self.message = message
        super().__init__(f"Rule violation [{rule}]: {message}")


class LoanServicingAgent:
    """
    Loan servicing support agent with hard-coded rule enforcement.

    Rules enforced programmatically (not just via prompt):
    1. Verify identity before revealing any balance
    2. Deliver required disclosure before discussing payment plan
    3. Never threaten or give legal advice
    4. Escalate on dispute or distress keywords

    The LLM (qwen2.5:3b via Ollama) decides which tool to call and with what args.
    The agent validates every tool call against rule state before execution —
    the LLM cannot bypass rules even if it tries.
    """

    def __init__(self, use_llm: bool = None):
        self.state = ConversationState()
        if use_llm is not None:
            llm_client.enabled = use_llm

    def reset(self, account_id: str = None):
        """Reset conversation state for new session."""
        self.state = ConversationState(account_id=account_id)

    def _check_escalation_triggers(self, user_message: str) -> Optional[str]:
        """Check if user message contains escalation triggers."""
        return check_escalation_triggers(user_message)

    def _enforce_no_threats_legal_advice(self, response: str) -> str:
        """Rule 3: Filter out threats or legal advice from agent responses."""
        threat_patterns = [
            "will be sent to collections",
            "legal action",
            "sue you",
            "court",
            "lawyer",
            "attorney",
            "repossess",
            "foreclose",
            "garnish",
            "ruin your credit",
            "destroy your credit",
        ]
        legal_advice_patterns = [
            "you should",
            "i recommend you",
            "my advice is",
            "legally you must",
            "the law requires you to",
        ]

        response_lower = response.lower()
        for pattern in threat_patterns:
            if pattern in response_lower:
                raise RuleViolation(
                    "no_threats",
                    f"Agent response contains prohibited threat language: '{pattern}'"
                )
        for pattern in legal_advice_patterns:
            if pattern in response_lower:
                raise RuleViolation(
                    "no_legal_advice",
                    f"Agent response contains prohibited legal advice: '{pattern}'"
                )
        return response

    # Tool handlers with rule enforcement
    def _handle_lookup_account(self, account_id: str, ssn_last4: str = None, dob: str = None) -> dict:
        """Rule 1: Enforce identity verification before revealing balance."""
        with tracer.span(
            "tool.lookup_account",
            input_data={"account_id": account_id, "ssn_last4": ssn_last4, "dob": dob},
            metadata={"pre_verified": self.state.identity_verified},
        ) as span:
            result = lookup_account(account_id, ssn_last4, dob, pre_verified=self.state.identity_verified)
            span.update(output=result)

        if result.get("identity_verified"):
            self.state.identity_verified = True
            self.state.account_id = account_id

        return result

    def _handle_get_payment_options(self, account_id: str, ssn_last4: str = None, dob: str = None) -> dict:
        """Rule 1 & 2: Require verification AND disclosure before payment options."""
        if not self.state.identity_verified:
            if ssn_last4 and dob:
                with tracer.span(
                    "tool.lookup_account",
                    input_data={"account_id": account_id, "ssn_last4": ssn_last4, "dob": dob},
                    metadata={"pre_verified": self.state.identity_verified},
                ) as span:
                    result = lookup_account(account_id, ssn_last4, dob)
                    span.update(output=result)
                if result.get("identity_verified"):
                    self.state.identity_verified = True
                else:
                    return {"success": False, "error": "Identity verification required"}
            else:
                return {"success": False, "error": "Identity verification required"}

        if not self.state.disclosure_sent:
            return {"success": False, "error": "Required disclosure must be sent before discussing payment options"}

        with tracer.span(
            "tool.get_payment_options",
            input_data={"account_id": account_id, "ssn_last4": ssn_last4, "dob": dob},
            metadata={"pre_verified": True},
        ) as span:
            result = get_payment_options(account_id, ssn_last4, dob, pre_verified=True)
            span.update(output=result)

        return result

    def _handle_create_payment_plan(self, account_id: str, plan_type: str, monthly_payment: float,
                                     duration_months: int, ssn_last4: str = None, dob: str = None) -> dict:
        """Rule 1 & 2: Require verification AND disclosure before creating plan."""
        if not self.state.identity_verified:
            if ssn_last4 and dob:
                with tracer.span(
                    "tool.lookup_account",
                    input_data={"account_id": account_id, "ssn_last4": ssn_last4, "dob": dob},
                    metadata={"pre_verified": self.state.identity_verified},
                ) as span:
                    result = lookup_account(account_id, ssn_last4, dob)
                    span.update(output=result)
                if result.get("identity_verified"):
                    self.state.identity_verified = True
                else:
                    return {"success": False, "error": "Identity verification required"}
            else:
                return {"success": False, "error": "Identity verification required"}

        if not self.state.disclosure_sent:
            return {"success": False, "error": "Required disclosure must be sent before creating payment plan"}

        with tracer.span(
            "tool.create_payment_plan",
            input_data={"account_id": account_id, "plan_type": plan_type, "monthly_payment": monthly_payment, "duration_months": duration_months, "ssn_last4": ssn_last4, "dob": dob},
            metadata={"pre_verified": True},
        ) as span:
            result = create_payment_plan(account_id, plan_type, monthly_payment, duration_months, ssn_last4, dob, pre_verified=True)
            span.update(output=result)
        if result.get("success"):
            self.state.payment_plan_discussed = True
        return result

    def _handle_send_disclosure(self, account_id: str) -> dict:
        """Send required disclosure."""
        with tracer.span(
            "tool.send_required_disclosure",
            input_data={"account_id": account_id},
            metadata={},
        ) as span:
            result = send_required_disclosure(account_id)
            span.update(output=result)
        if result.get("success"):
            self.state.disclosure_sent = True
        return result

    def _handle_escalate(self, account_id: str, reason: str) -> dict:
        """Escalate to human."""
        with tracer.span(
            "tool.escalate_to_human",
            input_data={"account_id": account_id, "reason": reason},
            metadata={},
        ) as span:
            result = escalate_to_human(account_id, reason)
            span.update(output=result)
        if result.get("success"):
            self.state.escalated = True
        return result

    def _get_llm_decision(self, user_message: str) -> LLMDecision:
        """Ask the LLM which tool to call. Falls back to keyword parsing if LLM disabled."""
        return llm_client.decide_tool(
            user_message=user_message,
            conversation_history=self.state.messages,
            available_tools=["lookup_account", "get_payment_options", "create_payment_plan", "send_required_disclosure", "escalate_to_human"],
        )

    def _fallback_parse_intent(self, message: str) -> str:
        """Keyword-based intent parsing (fallback when LLM unavailable)."""
        msg_lower = message.lower()

        if any(kw in msg_lower for kw in ["balance", "look up", "lookup", "account info", "how much"]):
            return "lookup_account"
        elif any(kw in msg_lower for kw in ["create plan", "set up plan", "start plan", "enroll", "sign up"]) or \
             any(kw in msg_lower for kw in ["standard plan", "extended plan", "accelerated plan"]):
            return "create_payment_plan"
        elif any(kw in msg_lower for kw in ["payment option", "payment plan", "options", "plan options"]):
            return "payment_options"
        elif any(kw in msg_lower for kw in ["disclosure", "send disclosure", "required disclosure"]):
            return "send_disclosure"
        elif any(kw in msg_lower for kw in ["human", "agent", "representative", "talk to someone", "escalate"]):
            return "escalate"
        return "unknown"

    def _extract_credentials(self, message: str) -> tuple[Optional[str], Optional[str]]:
        """Extract SSN last 4 and DOB from message."""
        ssn_match = re.search(r'\b(\d{4})\b', message)
        dob_match = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', message)
        ssn_last4 = ssn_match.group(1) if ssn_match else None
        dob = dob_match.group(1) if dob_match else None
        return ssn_last4, dob

    def _parse_plan_details(self, message: str) -> tuple[Optional[str], Optional[float], Optional[int]]:
        """Parse plan type, monthly payment, and duration from message."""
        msg_lower = message.lower()

        plan_type = None
        if "standard" in msg_lower:
            plan_type = "standard"
        elif "extended" in msg_lower:
            plan_type = "extended"
        elif "accelerated" in msg_lower:
            plan_type = "accelerated"

        payment_match = re.search(r'\$?(\d+(?:,\d{3})*(?:\.\d{2})?)', message)
        monthly_payment = float(payment_match.group(1).replace(',', '')) if payment_match else None

        duration_match = re.search(r'(\d+)\s*month', msg_lower)
        duration_months = int(duration_match.group(1)) if duration_match else None

        return plan_type, monthly_payment, duration_months

    def process_message(self, user_message: str, account_id: str = None) -> dict:
        """
        Process a user message and return agent response.
        This is the main entry point for the agent loop.
        """
        trace_id = tracer.start_trace(
            trace_name="process_message",
            session_id=self.state.account_id or account_id,
            metadata={"account_id": account_id},
        )
        if account_id and not self.state.account_id:
            self.state.account_id = account_id

        self.state.messages.append({"role": "user", "content": user_message})

        # Rule 4: Check for escalation triggers FIRST (always, even with LLM)
        trigger = self._check_escalation_triggers(user_message)
        if trigger and not self.state.escalated:
            if self.state.account_id:
                result = self._handle_escalate(self.state.account_id, trigger)
                response = result.get("message", "Escalated to human agent.")
                self.state.messages.append({"role": "assistant", "content": response})
                tracer.end_trace(output={"response": response, "escalated": True, "trigger": trigger})
                return {"response": response, "escalated": True, "trigger": trigger}

        # Get tool decision from LLM (or fallback)
        llm_decision = self._get_llm_decision(user_message)

        # Determine intent and args from LLM decision or fallback
        if llm_decision.tool:
            intent = llm_decision.tool
            llm_args = llm_decision.args
        else:
            intent = self._fallback_parse_intent(user_message)
            llm_args = {}
            if llm_decision.response_text:
                response = llm_decision.response_text
                try:
                    response = self._enforce_no_threats_legal_advice(response)
                except RuleViolation:
                    response = "I apologize, but I cannot provide that response due to policy restrictions."
                self.state.messages.append({"role": "assistant", "content": response})
                tracer.end_trace(output={"response": response})
                return {"response": response}

        # Extract credentials from LLM args or message
        ssn_last4 = llm_args.get("ssn_last4") or llm_args.get("ssn")
        dob = llm_args.get("dob") or llm_args.get("date_of_birth")
        if not ssn_last4 or not dob:
            extracted_ssn, extracted_dob = self._extract_credentials(user_message)
            ssn_last4 = ssn_last4 or extracted_ssn
            dob = dob or extracted_dob

        # Execute based on intent with rule enforcement
        try:
            if intent == "lookup_account":
                if not self.state.account_id:
                    response = "Please provide your account ID first."
                else:
                    account_id_arg = llm_args.get("account_id") or self.state.account_id
                    result = self._handle_lookup_account(account_id_arg, ssn_last4, dob)

                    if result.get("identity_verified"):
                        response = (f"Hello {result['borrower_name']}! Your account {result['account_id']} "
                                   f"is {result['status']}. Current balance: ${result['current_balance']:,.2f}. "
                                   f"Past due: ${result['past_due_amount']:,.2f}.")
                    else:
                        response = ("I need to verify your identity first. Please provide the last 4 digits "
                                   "of your SSN and your date of birth (YYYY-MM-DD).")

            elif intent == "payment_options":
                if not self.state.account_id:
                    response = "Please provide your account ID first."
                else:
                    account_id_arg = llm_args.get("account_id") or self.state.account_id
                    result = self._handle_get_payment_options(account_id_arg, ssn_last4, dob)

                    if result.get("success"):
                        options_text = "\n".join([
                            f"- {opt['plan_type'].title()}: ${opt['monthly_payment']:,.2f}/month for {opt['duration_months']} months"
                            for opt in result["options"]
                        ])
                        response = (f"Here are your payment options for a total balance of ${result['total_balance']:,.2f}:\n"
                                   f"{options_text}\n\nWhich plan would you prefer?")
                    else:
                        response = f"I can't show payment options yet: {result.get('error', 'Unknown error')}"

            elif intent == "create_payment_plan":
                if not self.state.account_id:
                    response = "Please provide your account ID first."
                else:
                    account_id_arg = llm_args.get("account_id") or self.state.account_id
                    plan_type = llm_args.get("plan_type")
                    monthly_payment = llm_args.get("monthly_payment")
                    duration_months = llm_args.get("duration_months")

                    if not all([plan_type, monthly_payment, duration_months]):
                        parsed_type, parsed_payment, parsed_duration = self._parse_plan_details(user_message)
                        plan_type = plan_type or parsed_type
                        monthly_payment = monthly_payment or parsed_payment
                        duration_months = duration_months or parsed_duration

                    if not all([plan_type, monthly_payment, duration_months]):
                        response = ("Please specify which plan you want (standard/extended/accelerated) "
                                   "and confirm the monthly payment and duration.")
                    else:
                        result = self._handle_create_payment_plan(
                            account_id_arg, plan_type, float(monthly_payment), int(duration_months), ssn_last4, dob
                        )

                        if result.get("success"):
                            response = (f"Payment plan created! Plan ID: {result['plan_id']}. "
                                       f"${result['monthly_payment']:,.2f}/month for {result['duration_months']} months "
                                       f"starting {result['start_date']}.")
                        else:
                            response = f"Could not create payment plan: {result.get('error', 'Unknown error')}"

            elif intent == "send_disclosure":
                if not self.state.account_id:
                    response = "Please provide your account ID first."
                else:
                    account_id_arg = llm_args.get("account_id") or self.state.account_id
                    result = self._handle_send_disclosure(account_id_arg)
                    if result.get("success"):
                        response = (f"Required disclosure sent (ID: {result['disclosure_id']}). "
                                   "You can now discuss payment plan options.")
                    else:
                        response = f"Could not send disclosure: {result.get('error', 'Unknown error')}"

            elif intent == "escalate":
                if not self.state.account_id:
                    response = "Please provide your account ID first."
                else:
                    account_id_arg = llm_args.get("account_id") or self.state.account_id
                    reason = llm_args.get("reason", "customer_request")
                    result = self._handle_escalate(account_id_arg, reason)
                    response = result.get("message", "Escalated to human agent.")
                    tracer.end_trace(output={"response": response, "escalated": True})
                    return {"response": response, "escalated": True}

            else:
                response = ("I can help you with your loan account. You can ask me to:\n"
                           "- Look up your account balance (provide account ID + SSN last 4 + DOB)\n"
                           "- Show payment options (after identity verification)\n"
                           "- Set up a payment plan (after required disclosure)\n"
                           "- Send the required disclosure\n"
                           "- Escalate to a human agent")

        except RuleViolation as e:
            response = f"I apologize, but I cannot proceed: {e.message}"

        # Rule 3: Filter response for threats/legal advice
        try:
            response = self._enforce_no_threats_legal_advice(response)
        except RuleViolation:
            response = "I apologize, but I cannot provide that response due to policy restrictions."

        self.state.messages.append({"role": "assistant", "content": response})
        tracer.end_trace(output={"response": response})
        return {"response": response}