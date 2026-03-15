# Generation service (Orchestrator + LLM) for Insight Forge

from shared.llm_client import set_llm_usage_callback
from generation.stage_metrics import record_llm_usage

# Register LLM usage callback for stage metrics (must run before any LLM calls)
set_llm_usage_callback(record_llm_usage)
