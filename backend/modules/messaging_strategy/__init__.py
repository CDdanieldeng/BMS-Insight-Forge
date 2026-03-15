"""Messaging Strategy module."""

from modules._common import get_shared_fix_table_agent
from modules._registry import register_module

from .config import CONFIG
from . import slides  # noqa: F401 - triggers prompt registration


class MessagingStrategyProvider:
    """Module provider for Messaging Strategy."""

    def __init__(self) -> None:
        pass

    def get_config(self):
        return CONFIG

    def get_table_fill_agent(self):
        return None  # Uses standard orchestrator path

    def get_cowork_agent(self):
        return None  # No cowork mode for Messaging Strategy yet

    def get_fix_table_agent(self):
        return get_shared_fix_table_agent()


register_module(MessagingStrategyProvider())
