"""Session persistence abstraction for cowork agent."""

from __future__ import annotations

from typing import Protocol

from cowork_agent.models import CoworkSessionState


class SessionStore(Protocol):
    def get(self, session_id: str) -> CoworkSessionState | None:
        ...

    def upsert(self, state: CoworkSessionState) -> None:
        ...


class InMemorySessionStore:
    """Simple in-memory store for initial iteration."""

    def __init__(self) -> None:
        self._store: dict[str, CoworkSessionState] = {}

    def get(self, session_id: str) -> CoworkSessionState | None:
        return self._store.get(session_id)

    def upsert(self, state: CoworkSessionState) -> None:
        self._store[state.session_id] = state

