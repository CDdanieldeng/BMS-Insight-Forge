"""Service interfaces for decoupled cowork orchestration."""

from __future__ import annotations

from typing import Any, Protocol

from modules.cowork.models import TemplateMetadata, UploadedFileMeta


class TemplateService(Protocol):
    def load(self, slide_idx: int, table_structure: dict[str, Any]) -> TemplateMetadata:
        ...


class FilePreparationService(Protocol):
    def preprocess(self, file_ids: list[str]) -> list[UploadedFileMeta]:
        ...


class RetrievalService(Protocol):
    def retrieve(
        self,
        module: str,
        file_ids: list[str],
        table_structure: dict[str, Any],
        user_message: str,
    ) -> str:
        ...


class DraftingService(Protocol):
    def draft(
        self,
        slide_idx: int,
        module: str,
        file_ids: list[str],
        table_structure: dict[str, Any],
    ) -> tuple[list[list[str]], list[str]]:
        ...


class WebSearchServicePlaceholder(Protocol):
    def search(self, query: str) -> str:
        ...


class PPTFillAdapter(Protocol):
    def build_payload(
        self,
        slide_idx: int,
        table_data: list[list[str]],
        column_headers: list[str],
    ) -> dict[str, Any]:
        ...
