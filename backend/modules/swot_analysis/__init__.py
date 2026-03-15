"""SWOT Analysis module."""

from modules._common import get_shared_fix_table_agent
from modules._registry import register_module

from .config import CONFIG
from . import slides  # noqa: F401 - triggers prompt registration
from .cowork_agent import SwotAnalysisCoworkAgent


class SwotAnalysisProvider:
    """Module provider for SWOT Analysis."""

    def __init__(self) -> None:
        self._cowork_agent: SwotAnalysisCoworkAgent | None = None

    def get_config(self):
        return CONFIG

    def get_table_fill_agent(self):
        return None  # Uses standard orchestrator path for now

    def get_cowork_agent(self):
        if self._cowork_agent is None:
            self._cowork_agent = SwotAnalysisCoworkAgent()
        return self._cowork_agent

    def get_fix_table_agent(self):
        return get_shared_fix_table_agent()


register_module(SwotAnalysisProvider())
