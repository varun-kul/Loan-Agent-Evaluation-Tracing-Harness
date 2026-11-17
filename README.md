# Loan Agent Evaluation & Tracing Harness

A behavioral evaluation and tracing harness for a loan servicing AI agent. Tests 105 scenarios across 5 categories, enforces 4 hard behavioral rules programmatically, instruments every run with Langfuse traces, and blocks regressions via CI gate.

## Features

| Capability | Description |
|------------|-------------|
| **105 scenarios** | 25 happy_path, 25 edge_case, 25 adversarial, 15 ambiguous, 15 prompt_injection |
| **4 hard rules** | Identity verification, disclosure-before-plan, no threats/legal advice, escalation triggers — enforced in Python, not prompts |
| **LLM-as-judge** | Cohen's κ calibration, 8-code error taxonomy, deterministic fallback when LLM unavailable |
| **Langfuse tracing** | Distributed traces for every tool call: inputs, outputs, latency, rule violations |
| **CI gate** | GitHub Actions workflow blocks PRs below 85% task success or above 15% violation rate |
| **Regression demo** | Simulated bad change drops from 105/105 → 77/105 with 28 violations; CI gate correctly BLOCKS |
| **Open-source only** | Ollama `qwen2.5:3b` (local) + Groq `llama-3.1-8b-instant` (free tier); no paid APIs |

## Architecture

```
LLM (Ollama/Groq) decides tool + args
         ↓
Agent validates against ConversationState (rules enforced in Python)
         ↓
Tool executes (lookup_account, get_payment_options, create_payment_plan,
           send_required_disclosure, escalate_to_human)
         ↓
Langfuse traces every span with input/output/latency
         ↓
eval.py checks rules + metrics; CI gate blocks if thresholds breached
```

**LLM proposes, agent disposes** — the LLM suggests tool calls, but the agent validates every call against conversation state before execution. The LLM is untrusted; rules cannot be bypassed via prompt injection.

## Quick Start

### 1. Clone and configure

```bash
git clone <your-repo>
cd <repo>
cp .env.example .env
```

Edit `.env`:
```ini
LLM_PROVIDER=ollama          # or "groq"
USE_LLM=true                 # set to false for deterministic fallback
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
GROQ_API_KEY=your_groq_key   # only if using Groq
GROQ_MODEL=llama-3.1-8b-instant

# Optional Langfuse tracing (free tier at cloud.langfuse.com)
LANGFUSE_ENABLED=false
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
```

### 2. Run tests (no LLM provider required)

All tests mock the LLM, so they run without any API key:

```bash
python -m pytest tests/ -v
# Expected: 93 passed
```

### 3. Run the evaluation harness

```bash
python eval.py
# Expected: 105 scenarios, 100% pass, 0 violations, CI GATE: PASSED
```

### 4. Run the regression demo

```bash
python eval.py --regression-demo
# Step 1: Good state → CI GATE: PASSED
# Step 2: Simulated Rule 1 bypass → CI GATE: BLOCKED
```

### 5. Generate human labels for LLM-as-judge calibration

```bash
python -m src.loan_agent.llm_judge --generate-template --n-per-category 10
# Writes human_labels.jsonl — fill in rule_violations for each scenario
```

## Project Structure

```
loan-agent-eval-harness/
├── .github/workflows/ci.yml     # GitHub Actions CI pipeline
├── .env.example                 # Environment variable template
├── eval.py                      # Deterministic evaluator + CI gate + regression demo
├── PROGRESS.md                  # Development progress & resume highlights
├── SETUP.md                     # Detailed setup instructions
├── src/
│   └── loan_agent/
│       ├── agent.py             # LoanServicingAgent with rule enforcement + tracing
│       ├── backend.py           # Mock SQLite backend
│       ├── llm_client.py        # LLMClient (Ollama + Groq)
│       ├── llm_judge.py         # LLM-as-judge calibration framework
│       ├── scenarios.py         # Scenario schema, loading, validation
│       ├── scenarios.jsonl      # 105 evaluation scenarios
│       └── tools.py             # 5 tool functions
│       └── tracing.py           # Langfuse tracer wrapper
└── tests/
    ├── test_agent.py            # Rule enforcement tests
    ├── test_backend.py          # Backend tests
    ├── test_llm_agent.py        # LLM integration tests
    ├── test_llm_judge.py        # LLM-as-judge tests (16)
    ├── test_scenarios.py        # Scenario validation tests
    ├── test_tools.py            # Tool function tests
    └── test_tracing.py          # Tracing instrumentation tests (7)
```

## Milestones

| Milestone | Status | Description |
|-----------|--------|-------------|
| M1 | ✅ | Mock backend & 5 tools |
| M2 | ✅ | Agent loop + 4 programmatic rule checks |
| M2.5 | ✅ | LLM agent: Ollama local / Groq cloud |
| M3 | ✅ | 105 scenarios across 5 categories |
| M4 | ✅ | Deterministic evaluator with CI gate |
| M5 | ✅ | Langfuse tracing instrumentation |
| M6 | ✅ | LLM-as-judge calibration (Cohen's κ) |
| M7 | ✅ | GitHub Actions CI workflow |
| M8 | ✅ | Regression demo |

## Test Results

```
93 passed across 7 test files:
  test_agent.py       19 tests
  test_backend.py     13 tests
  test_tools.py       19 tests
  test_scenarios.py   10 tests
  test_llm_agent.py   9 tests
  test_tracing.py     7 tests
  test_llm_judge.py   16 tests
```

```
Evaluation: 105/105 scenarios pass (100%), 0 rule violations, CI gate: PASSED
```

## CI Pipeline

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every push and PR:

1. **test** — Runs `pytest tests/ -v`
2. **eval-gate** — Runs `eval.py` and blocks if task success < 85% or rule violation rate > 15%
3. **trace-artifact** — Uploads test results and evaluation metrics as artifacts

## License

MIT License. See LICENSE file for details.

## Resume Highlights

- **100% pass rate** on 105 behavioral scenarios with 0 rule violations
- **LLM-as-judge** with Cohen's κ inter-rater agreement and deterministic fallback
- **Langfuse distributed tracing** across all agent tool handlers
- **CI/CD pipeline** that automatically blocks regressions
- **Open-source stack** — no paid APIs required