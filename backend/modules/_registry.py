"""Module registry: discover and dispatch by module.

To add a new module: create modules/<name>/ with ModuleProvider impl,
call register_module() in __init__.py.
"""

from __future__ import annotations

from typing import Any, Protocol


def _normalize_module_id(name: str) -> str:
    """Normalize module name for lookup: lowercase, spaces → underscores."""
    return (name or "").strip().lower().replace(" ", "_")


class ModuleConfig:
    """Static config for a module."""

    def __init__(
        self,
        module_id: str,
        display_name: str,
    ) -> None:
        self.module_id = module_id
        self.display_name = display_name


class TableFillAgent(Protocol):
    """Generates table content from documents + context."""

    def run(
        self,
        *,
        file_ids: list[str],
        n_segments: int,
        indexes: list[str],
        module: str,
        trace_capture: dict[str, Any] | None = None,
        cowork_guidance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run segment identification and table generation. Returns segment_names, table_data, etc."""
        ...


class CoworkAgent(Protocol):
    """Starter consultant: gather brief, files, segment names."""

    def handle_turn(self, req: Any) -> dict[str, Any]:
        """Process one cowork turn."""
        ...


class FixTableAgent(Protocol):
    """Applies user feedback to refine table content."""

    def apply_feedback(
        self,
        *,
        module: str,
        current_content: list[list[str]],
        table_structure: dict[str, Any],
        user_message: str,
        file_ids: list[str],
        current_column_headers: list[str] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Apply feedback and return updated content + assistant message."""
        ...


class ModuleProvider(Protocol):
    """Provides agents and config for a module."""

    def get_config(self) -> ModuleConfig:
        ...

    def get_table_fill_agent(self) -> TableFillAgent | None:
        """Returns agent for placeholder-based table fill (e.g. CS slide 1). None if not applicable."""
        ...

    def get_cowork_agent(self) -> CoworkAgent | None:
        """Returns cowork orchestrator. None if module has no cowork mode."""
        ...

    def get_fix_table_agent(self) -> FixTableAgent | None:
        """Returns fix-table agent. None to use shared default."""
        ...


REGISTRY: dict[str, ModuleProvider] = {}


def register_module(provider: ModuleProvider) -> None:
    """Register a module provider. Called from each module's __init__.py."""
    cfg = provider.get_config()
    REGISTRY[cfg.module_id] = provider


def get_module(module_name: str) -> ModuleProvider | None:
    """Look up module by display name or module_id."""
    normalized = _normalize_module_id(module_name)
    # Also try with spaces for "customer segmentation" -> "customer_segmentation"
    if normalized in REGISTRY:
        return REGISTRY[normalized]
    # Fallback: try display-name style "customer segmentation"
    alt = (module_name or "").strip().lower()
    for pid, prov in REGISTRY.items():
        if prov.get_config().display_name.lower() == alt:
            return prov
    return None
