"""Customer Segmentation module."""

from modules._common import get_shared_fix_table_agent
from modules._registry import register_module

from . import slides  # noqa: F401 - registers prompt builders
from .config import CONFIG
from .cowork_agent import CustomerSegmentationCoworkAgent
from .table_fill_agent import CustomerSegmentationTableFillAgent


class CustomerSegmentationProvider:
    """Module provider for Customer Segmentation."""

    def __init__(self) -> None:
        self._table_fill_agent: CustomerSegmentationTableFillAgent | None = None
        self._cowork_agent: CustomerSegmentationCoworkAgent | None = None

    def get_config(self):
        return CONFIG

    def get_table_fill_agent(self):
        if self._table_fill_agent is None:
            self._table_fill_agent = CustomerSegmentationTableFillAgent()
        return self._table_fill_agent

    def get_cowork_agent(self):
        if self._cowork_agent is None:
            self._cowork_agent = CustomerSegmentationCoworkAgent()
        return self._cowork_agent

    def get_fix_table_agent(self):
        return get_shared_fix_table_agent()


register_module(CustomerSegmentationProvider())
