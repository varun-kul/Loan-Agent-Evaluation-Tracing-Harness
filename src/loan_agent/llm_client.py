"""LLM client for the loan servicing agent.

Supports two providers:
- Ollama (local, zero cost) — set LLM_PROVIDER=ollama
- Groq (cloud API, open source models, free tier) — set LLM_PROVIDER=groq + GROQ_API_KEY

Set USE_LLM=true to enable; falls back to keyword-based parsing when disabled.
"""
import os
import json
from typing import Optional, Dict, Any
from dataclasses import dataclass

# Load .env file if present
if os.path.exists(os.path.join(os.path.dirname(__file__), "..", "..", ".env")):
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    except ImportError:
        pass
from .tools import *


@dataclass
class LLMDecision:
    """Structured decision from the LLM about which tool to call."""
    tool: Optional[str]
    args: Dict[str, Any]
    reasoning: str
    response_text: Optional[str]
class LLMClient:
    """Wrapper around LLM providers with fallback behavior.

    Supports Ollama (local) and Groq (cloud API). Both use the same
    LLMDecision interface so the agent code doesn't change.
    """

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "ollama").lower()
        self.enabled = os.getenv("USE_LLM", "false").lower() == "true"

        if self.provider == "groq":
            self.model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
            self.api_key = os.getenv("GROQ_API_KEY", "")
            self.base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
            self._client = None
        else:
            self.model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
            self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            self.api_key = None
            self._client = None

    def is_available(self) -> bool:
        """Check if the LLM provider is reachable."""
        if not self.enabled:
            return False
        try:
            if self.provider == "groq":
                if not self.api_key:
                    return False
                import httpx
                client = httpx.Client(base_url=self.base_url, timeout=10.0)
                resp = client.get("/models", headers={"Authorization": f"Bearer {self.api_key}"})
                return resp.status_code == 200
            else:
                import ollama
                client = ollama.Client(host=self.host)
                client.list()
                return True
        except Exception:
            return False

    def decide_tool(self, user_message: str, conversation_history: list[dict], available_tools: list[str]) -> LLMDecision:
        """Ask the LLM which tool to call and with what arguments."""
        if not self.enabled:
            return LLMDecision(
                tool=None,
                args={},
                reasoning="LLM disabled — using keyword fallback",
                response_text=None,
            )

        system_prompt = self._build_system_prompt(available_tools)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history[-6:])
        messages.append({"role": "user", "content": user_message})

        try:
            if self.provider == "groq":
                content = self._call_groq(messages)
            else:
                content = self._call_ollama(messages)
            decision = self._parse_llm_response(content)
            return decision
        except Exception as e:
            return LLMDecision(
                tool=None,
                args={},
                reasoning=f"LLM error: {str(e)} — falling back to keyword parsing",
                response_text=None,
            )

    def _call_ollama(self, messages: list[dict]) -> str:
        import ollama
        client = ollama.Client(host=self.host)
        response = client.chat(
            model=self.model,
            messages=messages,
            format="json",
            options={"temperature": 0.1},
        )
        return response["message"]["content"]

    def _call_groq(self, messages: list[dict]) -> str:
        import httpx
        client = httpx.Client(base_url=self.base_url, timeout=30.0)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        resp = client.post("/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _build_system_prompt(self, available_tools: list[str]) -> str:
        tools_desc = "\n".join(f"- {t}" for t in available_tools)
        return f"""You are a loan servicing support agent. You must decide which tool to call based on the user's message.

Available tools:
{tools_desc}

Rules you MUST follow:
1. Verify identity (SSN last 4 + DOB) before revealing any balance
2. Send required disclosure before discussing payment plans
3. Never threaten or give legal advice
4. Escalate on dispute or distress keywords

Respond with valid JSON only:
{{
  "tool": "tool_name_or_null",
  "args": {{...}},
  "reasoning": "why you chose this tool",
  "response_text": "text to send user if no tool needed, or null"
}}

If the user needs to verify identity, set tool to "lookup_account" with their account_id and credentials if provided.
If identity is already verified and disclosure already sent, you can call payment tools.
If you detect dispute/distress keywords, set tool to "escalate_to_human".
If unsure, set tool to null and provide response_text.
"""

    def _parse_llm_response(self, content: str) -> LLMDecision:
        """Parse LLM JSON response into LLMDecision."""
        try:
            data = json.loads(content)
            return LLMDecision(
                tool=data.get("tool"),
                args=data.get("args", {}),
                reasoning=data.get("reasoning", ""),
                response_text=data.get("response_text"),
            )
        except (json.JSONDecodeError, TypeError):
            content_lower = content.lower()
            for tool in ["lookup_account", "get_payment_options", "create_payment_plan", "send_required_disclosure", "escalate_to_human"]:
                if tool in content_lower:
                    return LLMDecision(tool=tool, args={}, reasoning="extracted from text", response_text=None)
            return LLMDecision(tool=None, args={}, reasoning="failed to parse LLM response", response_text=content)


# Global client instance
llm_client = LLMClient()