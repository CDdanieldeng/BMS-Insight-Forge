"""Default adapters bridging cowork orchestration to existing services."""

from __future__ import annotations

from typing import Any

from cowork_agent.interfaces import (
    DraftingService,
    FilePreparationService,
    PPTFillAdapter,
    RetrievalService,
    TemplateService,
    WebSearchServicePlaceholder,
)
from cowork_agent.models import TemplateMetadata, UploadedFileMeta
from generation.orchestrator import _get_context_content, run_fill
from generation.query_enhancer import enhance_query


class ExistingTemplateService(TemplateService):
    def load(self, slide_idx: int, table_structure: dict[str, Any]) -> TemplateMetadata:
        columns = [str(c) for c in (table_structure.get("columns") or [])[1:]]
        rows = [str(r) for r in (table_structure.get("indexes") or [])]
        return TemplateMetadata(slide_idx=slide_idx, row_indexes=rows, segment_columns=columns)


class ExistingFilePreparationService(FilePreparationService):
    """Placeholder file preparation adapter for current retriever pipeline."""

    def preprocess(self, file_ids: list[str]) -> list[UploadedFileMeta]:
        return [
            UploadedFileMeta(file_id=fid, filename=f"file_{idx + 1}", preprocessing_status="ready")
            for idx, fid in enumerate(file_ids)
        ]


class ExistingRetrievalService(RetrievalService):
    def retrieve(
        self,
        module: str,
        file_ids: list[str],
        table_structure: dict[str, Any],
        user_message: str,
    ) -> str:
        query = f"{enhance_query(module, table_structure)}; user ask: {user_message}".strip("; ")
        return _get_context_content(
            file_ids=file_ids,
            query=query,
            module=module,
            table_structure=table_structure,
        )


class ExistingDraftingService(DraftingService):
    def draft(
        self,
        slide_idx: int,
        module: str,
        file_ids: list[str],
        table_structure: dict[str, Any],
    ) -> tuple[list[list[str]], list[str]]:
        result = run_fill(
            slide_idx=slide_idx,
            module=module,
            file_ids=file_ids,
            table_structure=table_structure,
        )
        return result.get("table_data", []), result.get("column_headers") or []


class StubWebSearchService(WebSearchServicePlaceholder):
    def search(self, query: str) -> str:
        return (
            "Web search placeholder is enabled for this session, but live crawling is "
            "not implemented in this iteration. Query captured: "
            + query
        )


class ExistingPPTFillAdapter(PPTFillAdapter):
    def build_payload(
        self,
        slide_idx: int,
        table_data: list[list[str]],
        column_headers: list[str],
    ) -> dict[str, Any]:
        return {
            "slide_idx": slide_idx,
            "table_data": table_data,
            "column_headers": column_headers,
        }

