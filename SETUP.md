# Setup: LLM Configuration (Ollama OR Groq)

This project supports two LLM providers for open-source models. Choose one:

| Provider | Cost | Setup | Best for |
|----------|------|-------|----------|
| **Ollama** (local) | $0 | Install Ollama, pull model | No API key, full privacy |
| **Groq** (cloud API) | Free tier | Get API key at console.groq.com | Fast inference, no local install |

## Step 1: Create `.env` from `.env.example`

```bash
cp .env.example .env
```

Then edit `.env` and set:
- `LLM_PROVIDER=ollama` (local) or `groq` (cloud)
- `USE_LLM=true`
- `GROQ_API_KEY=your_key` (only if using Groq)

## Step 2: Provider-specific setup

### Option A: Ollama (Local, Zero Cost)

```bash
# Install Ollama from https://ollama.com
ollama serve &
ollama pull qwen2.5:3b
```

In `.env`:
```
LLM_PROVIDER=ollama
USE_LLM=true
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
```

### Option B: Groq (Cloud API, Open Source)

1. Get a free API key: https://console.groq.com/keys
2. In `.env`:
```
LLM_PROVIDER=groq
USE_LLM=true
GROQ_API_KEY=your_groq_key_here
GROQ_MODEL=llama-3.1-8b-instant
GROQ_BASE_URL=https://api.groq.com/openai/v1
```

## Step 3: Verify Configuration

```bash
python check_llm.py
```

Expected output for Groq:
```
provider: groq
model: llama-3.1-8b-instant
api_key set: True
enabled: True
is_available: False  # False with fake key; True with real key
```

## Step 4: Run Tests (No LLM Provider Required)

All tests mock the LLM, so they run without any provider:

```bash
python -m pytest tests/ -v
```

## Architecture: LLM Proposes, Agent Disposes

| Component | Responsibility |
|-----------|---------------|
| **LLM (qwen/llama via API)** | Decides which tool to call and with what arguments |
| **Agent (Python)** | Validates every tool call against `ConversationState` before executing |
| **Rules** | Enforced in Python code — the LLM cannot bypass them |

This means even if you use a different model or the LLM hallucinates, rule violations are impossible at the execution layer.

## Cost

| Provider | Model | Cost |
|----------|-------|------|
| Ollama | qwen2.5:3b | $0 (local) |
| Groq | llama-3.1-8b-instant | Free tier (~50 req/day) |
| Groq | llama-3.1-70b-versatile | Paid tier |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `.env` not loading | Ensure file has real newlines (not `` `n `` from PowerShell) |
| `is_available: False` | Groq API key invalid or Ollama not running |
| `USE_LLM` not recognized | Set `USE_LLM=true` in `.env` |

## Step 5: Langfuse Tracing (Optional)

Langfuse provides observability for agent runs — traces every tool call, latency, inputs/outputs, and rule evaluations.

1. Create a free account at [cloud.langfuse.com](https://cloud.langfuse.com)
2. Create a project and copy your `Public Key` and `Secret Key`
3. In `.env`:

```
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=your_public_key
LANGFUSE_SECRET_KEY=your_secret_key
LANGFUSE_HOST=https://cloud.langfuse.com
```

4. Run tests — traces will appear in your Langfuse dashboard automatically

The free tier is generous for local eval runs (traces are retained for analysis, no cost for typical dev usage).