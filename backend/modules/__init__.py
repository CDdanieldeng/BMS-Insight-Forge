"""Module registry and module implementations.

Import submodules to trigger registration.
"""

from modules._registry import get_module, register_module

# Import modules to register them
from modules import customer_segmentation  # noqa: F401
from modules import swot_analysis  # noqa: F401
from modules import messaging_strategy  # noqa: F401

__all__ = ["get_module", "register_module", "customer_segmentation", "swot_analysis", "messaging_strategy"]
