from src.loan_agent.llm_client import LLMClient

lc = LLMClient()
print('provider:', lc.provider)
print('model:', lc.model)
print('api_key set:', bool(lc.api_key))
print('enabled:', lc.enabled)
print('is_available:', lc.is_available())
