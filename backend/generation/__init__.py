# Generation service (slide table fill pipeline + LLM) for Insight Forge

from shared.llm_client import set_llm_usage_callback
from shared.stage_metrics import record_llm_usage

# Register LLM usage callback for stage metrics (must run before any LLM calls)
set_llm_usage_callback(record_llm_usage)
