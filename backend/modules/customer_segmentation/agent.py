"""Customer Segmentation agent: per-cell retrieval + concurrent LLM fill.

Pipeline:
  1. Planner: cartesian product of segments × row labels → one retrieval query per cell.
  2. run_retrieval_pipeline(raw_query, recall_top_k=48, rerank_top_k=16).
  3. Single-cell LLM with row-mapped prompts from slides/slide1.py.
  4. Assemble table_data; empty or failed evidence → exact fallback phrase.
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from shared.logging_config import setup_logging

from shared.stage_metrics import record_llm_usage, stage_scope
from retriever.retrieval_pipeline import IndexedRetrievalCorpus

from modules.customer_segmentation.fill_session_logger import (
    create_fill_session_dir,
    logging_enabled as cs_fill_logging_enabled,
    write_cell_llm_log,
    write_run_meta,
    write_segments_intake,
    write_segments_llm_audit,
)

logger = setup_logging("cs_agent_generation")

# Padded filler labels from orchestrator / extract_segment_names ("Segment 1", …).
_GENERIC_SEGMENT_NAME_RE = re.compile(r"^\s*segment\s+\d+\s*$", re.IGNORECASE)

CS_RECALL_TOP_K = int(os.getenv("CS_CELL_RECALL_TOP_K", "48"))
CS_RERANK_TOP_K = int(os.getenv("CS_CELL_RERANK_TOP_K", "16"))
CS_MAX_CELL_WORKERS = max(1, int(os.getenv("CS_MAX_CELL_WORKERS", "6")))


def is_generic_segment_placeholder(name: str) -> bool:
    """True when *name* is a structural placeholder like 'Segment 4', not a real segment."""
    return bool(_GENERIC_SEGMENT_NAME_RE.match((name or "").strip()))


@dataclass(frozen=True)
class CellTask:
    row_idx: int
    col_idx: int
    segment_name: str
    row_label: str
    raw_query: str


def plan_cell_tasks(segments: list[str], indexes: list[str]) -> list[CellTask]:
    """Expand segments × row labels into ordered cell tasks (row outer, column inner).

    Skips ``Segment <n>`` padding labels so retrieval + LLM are not run for template-only columns.
    """
    tasks: list[CellTask] = []
    for row_idx, row_label in enumerate(indexes):
        for col_idx, segment_name in enumerate(segments):
            if is_generic_segment_placeholder(segment_name):
                continue
            rq = f'HCP customer segment "{segment_name}": {row_label}'
            tasks.append(
                CellTask(
                    row_idx=row_idx,
                    col_idx=col_idx,
                    segment_name=segment_name,
                    row_label=row_label,
                    raw_query=rq,
                )
            )
    return tasks


def _record_langchain_usage(msg: Any, elapsed_ms: int) -> None:
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    model = (
        os.getenv("QWEN_MODEL", "qwen-max")
        if provider == "qwen"
        else os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    )
    prompt_tokens = completion_tokens = total_tokens = None

    usage_meta = getattr(msg, "usage_metadata", None)
    if isinstance(usage_meta, dict):
        prompt_tokens = usage_meta.get("input_tokens")
        completion_tokens = usage_meta.get("output_tokens")
        total_tokens = usage_meta.get("total_tokens")

    if prompt_tokens is None:
        token_usage = (getattr(msg, "response_metadata", {}) or {}).get("token_usage") or {}
        prompt_tokens = token_usage.get("prompt_tokens")
        completion_tokens = token_usage.get("completion_tokens")
        total_tokens = token_usage.get("total_tokens")

    record_llm_usage(
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        elapsed_ms=elapsed_ms,
    )


def _build_langchain_llm(
    max_tokens: int | None = None,
    temperature: float = 0.0,
) -> ChatOpenAI:
    verify_env = os.getenv("LLM_SSL_VERIFY", "true").strip().lower()
    ca_bundle = (
        os.getenv("LLM_CA_BUNDLE")
        or os.getenv("SSL_CERT_FILE")
        or os.getenv("REQUESTS_CA_BUNDLE")
    )
    timeout = float(os.getenv("LLM_HTTP_TIMEOUT", "180"))

    verify: bool | str = True
    if verify_env in {"0", "false", "no", "off"}:
        verify = False
    elif ca_bundle:
        verify = ca_bundle

    http_client = httpx.Client(timeout=timeout, verify=verify)

    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "qwen":
        kwargs: dict[str, Any] = dict(
            api_key=os.getenv("QWEN_API_KEY", ""),
            base_url=os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            model=os.getenv("QWEN_MODEL", "qwen-max"),
            temperature=temperature,
            http_client=http_client,
        )
    else:
        kwargs = dict(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=temperature,
            http_client=http_client,
        )

    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    return ChatOpenAI(**kwargs)


def _parse_single_cell_response(raw: str, not_found: str) -> str:
    cleaned = (raw or "").strip()
    if "```" in cleaned:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
        if m:
            cleaned = m.group(1).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and data.get("cell") is not None:
            cell = str(data["cell"]).strip()
            return cell if cell else not_found
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\"cell\"[\s\S]*\}", cleaned)
        if m:
            try:
                data = json.loads(m.group(0))
                if isinstance(data, dict) and data.get("cell") is not None:
                    cell = str(data["cell"]).strip()
                    return cell if cell else not_found
            except json.JSONDecodeError:
                pass
    return not_found


class CustomerSegmentationAgent:
    """Per-cell retrieval + LangChain LLM fill for Customer Segmentation slide 1."""

    @staticmethod
    def _write_cell_session_log(
        session_dir: Path | None,
        *,
        task: CellTask,
        system_prompt: str,
        user_prompt: str,
        raw_llm: str,
        parsed: str,
        pipe_meta: dict[str, Any] | None,
    ) -> None:
        if session_dir is None or not cs_fill_logging_enabled():
            return
        try:
            write_cell_llm_log(
                session_dir,
                row_idx=task.row_idx,
                col_idx=task.col_idx,
                segment_name=task.segment_name,
                row_label=task.row_label,
                retrieval_raw_query=task.raw_query,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                llm_raw_response=raw_llm,
                parsed_cell_value=parsed,
                pipe_meta=pipe_meta,
            )
        except Exception as e:
            logger.warning("CS fill cell log write failed row=%d col=%d err=%s", task.row_idx, task.col_idx, e)

    def __init__(self) -> None:
        self._cell_llm = _build_langchain_llm(max_tokens=800)
        self._cell_prompt = ChatPromptTemplate.from_messages([
            ("system", "{system}"),
            ("human", "{user}"),
        ])
        self._cell_chain = self._cell_prompt | self._cell_llm

    def _run_one_cell(
        self,
        task: CellTask,
        *,
        file_ids: list[str],
        session_upload_docs: list[dict[str, Any]] | None,
        indexes: list[str],
        module: str,
        methodology: str | None,
        not_found: str,
        correlation_prefix: str,
        indexed_corpus: IndexedRetrievalCorpus | None,
        session_dir: Path | None,
    ) -> tuple[int, int, str, str, str, str]:
        """Returns (row_idx, col_idx, value, system_prompt, user_prompt, raw_llm)."""
        from retriever.retrieval_pipeline import run_retrieval_pipeline
        from modules.customer_segmentation.slides.slide1 import (
            build_methodology_block,
            build_single_cell_prompts,
            row_definition_for_index,
        )

        correlation_key = f"{correlation_prefix}_r{task.row_idx}_c{task.col_idx}"
        evidence_text, pipe_meta = run_retrieval_pipeline(
            raw_query=task.raw_query,
            file_ids=file_ids,
            session_upload_docs=session_upload_docs,
            recall_top_k=CS_RECALL_TOP_K,
            rerank_top_k=CS_RERANK_TOP_K,
            correlation_key=correlation_key,
            indexed_corpus=indexed_corpus,
        )

        row_def = row_definition_for_index(indexes, task.row_idx)
        meth_block = build_methodology_block(methodology)
        system_prompt, user_prompt = build_single_cell_prompts(
            segment_name=task.segment_name,
            row_label=task.row_label,
            row_definition=row_def,
            evidence_text=evidence_text,
            methodology_block=meth_block,
        )

        raw = ""
        try:
            start = time.perf_counter()
            _msg = self._cell_chain.invoke({"system": system_prompt, "user": user_prompt})
            _record_langchain_usage(_msg, elapsed_ms=int((time.perf_counter() - start) * 1000))
            raw = _msg.content if hasattr(_msg, "content") else str(_msg)
            value = _parse_single_cell_response(raw, not_found)
            self._write_cell_session_log(
                session_dir,
                task=task,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_llm=raw,
                parsed=value,
                pipe_meta=pipe_meta,
            )
            return task.row_idx, task.col_idx, value, system_prompt, user_prompt, raw
        except Exception as exc:
            logger.warning(
                "CS agent cell LLM failed module=%s row=%d col=%d err=%s",
                module,
                task.row_idx,
                task.col_idx,
                exc,
            )
            err_tail = raw or str(exc)
            self._write_cell_session_log(
                session_dir,
                task=task,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_llm=err_tail,
                parsed=not_found,
                pipe_meta=pipe_meta,
            )
            return task.row_idx, task.col_idx, not_found, system_prompt, user_prompt, err_tail

    def _fill_table_concurrent(
        self,
        segments: list[str],
        indexes: list[str],
        *,
        file_ids: list[str],
        module: str,
        methodology: str | None,
        session_upload_docs: list[dict[str, Any]] | None,
        trace_capture: dict[str, Any] | None,
        session_dir: Path | None,
    ) -> list[list[str]]:
        from modules.customer_segmentation.slides.slide1 import NOT_FOUND_CELL_TEXT
        from retriever.retrieval_pipeline import build_indexed_retrieval_corpus

        not_found = NOT_FOUND_CELL_TEXT
        n_rows = len(indexes)
        n_cols = len(segments)
        table_data: list[list[str]] = [
            [not_found for _ in range(n_cols)] for _ in range(n_rows)
        ]

        tasks = plan_cell_tasks(segments, indexes)
        correlation_prefix = re.sub(
            r"[^a-zA-Z0-9_-]+", "_", (module or "cs").strip().lower()
        ).strip("_") or "cs"

        indexed_corpus = build_indexed_retrieval_corpus(
            file_ids,
            session_upload_docs,
            correlation_key=f"{correlation_prefix}_corpus",
        )

        last_system = ""
        last_user = ""
        last_raw = ""

        with ThreadPoolExecutor(max_workers=min(CS_MAX_CELL_WORKERS, max(1, len(tasks)))) as pool:
            futures = [
                pool.submit(
                    self._run_one_cell,
                    t,
                    file_ids=file_ids,
                    session_upload_docs=session_upload_docs,
                    indexes=indexes,
                    module=module,
                    methodology=methodology,
                    not_found=not_found,
                    correlation_prefix=correlation_prefix,
                    indexed_corpus=indexed_corpus,
                    session_dir=session_dir,
                )
                for t in tasks
            ]
            for fut in as_completed(futures):
                row_idx, col_idx, value, sys_p, usr_p, raw_llm = fut.result()
                table_data[row_idx][col_idx] = value
                last_system, last_user, last_raw = sys_p, usr_p, raw_llm

        if trace_capture is not None:
            trace_capture["system_prompt"] = last_system
            trace_capture["user_prompt"] = last_user
            trace_capture["llm_raw_response"] = f"(per-cell batch; last cell sample)\n{last_raw}"

        logger.info(
            "CS agent per-cell fill done module=%s rows=%d cols=%d tasks=%d",
            module,
            n_rows,
            n_cols,
            len(tasks),
        )
        return table_data

    def run(
        self,
        file_ids: list[str],
        n_segments: int,
        indexes: list[str],
        module: str = "customer segmentation",
        trace_capture: dict[str, Any] | None = None,
        cowork_guidance: dict[str, Any] | None = None,
        segment_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Fill the slide-1 matrix using per-cell retrieval and LLM.

        *segment_names* must be supplied by the orchestrator (cowork brief or cache).
        *cowork_guidance* may carry *summary* (methodology) and *session_upload_docs*.
        """
        methodology: str | None = None
        session_upload_docs: list[dict[str, Any]] | None = None
        if cowork_guidance:
            summ = cowork_guidance.get("summary")
            if summ and str(summ).strip():
                methodology = str(summ).strip()
            raw_docs = cowork_guidance.get("session_upload_docs")
            if raw_docs and isinstance(raw_docs, list):
                session_upload_docs = [
                    d
                    if isinstance(d, dict)
                    else {
                        "filename": getattr(d, "filename", ""),
                        "markdown_content": getattr(d, "markdown_content", ""),
                    }
                    for d in raw_docs
                ]

        resolved: list[str] = []
        if segment_names:
            resolved = [str(s).strip() for s in segment_names if str(s).strip()]
        elif cowork_guidance and isinstance(cowork_guidance.get("segment_names"), list):
            resolved = [
                str(s).strip()
                for s in cowork_guidance["segment_names"]
                if str(s).strip()
            ]

        resolved = resolved[:n_segments]
        while len(resolved) < n_segments:
            resolved.append(f"Segment {len(resolved) + 1}")
        segments = resolved[:n_segments]
        display_segment_names = [
            "" if is_generic_segment_placeholder(s) else s for s in segments
        ]
        n_placeholder_cols = sum(1 for s in segments if is_generic_segment_placeholder(s))
        if n_placeholder_cols:
            logger.info(
                "CS agent: %d column(s) are Segment-<n> placeholders — skipping per-cell fill for those",
                n_placeholder_cols,
            )

        if segment_names is not None and any(str(s).strip() for s in segment_names):
            segment_source = (
                "orchestrator `segment_names` argument (cowork brief, cached headers, or UI)"
            )
        elif cowork_guidance and isinstance(cowork_guidance.get("segment_names"), list):
            segment_source = "cowork_guidance.segment_names (no non-null orchestrator list)"
        else:
            segment_source = "orchestrator-resolved list (may include padded placeholders)"

        cowork_keys = sorted(cowork_guidance.keys()) if isinstance(cowork_guidance, dict) else None

        session_dir: Path | None = None
        if cs_fill_logging_enabled():
            try:
                session_dir = create_fill_session_dir(module=module)
                tasks_preview = plan_cell_tasks(segments, indexes)
                write_run_meta(
                    session_dir,
                    module=module,
                    file_ids=file_ids,
                    indexes=indexes,
                    segment_names=display_segment_names,
                    n_cells=len(tasks_preview),
                    methodology_present=bool(methodology and methodology.strip()),
                    recall_top_k=CS_RECALL_TOP_K,
                    rerank_top_k=CS_RERANK_TOP_K,
                    max_cell_workers=CS_MAX_CELL_WORKERS,
                    extra={"segment_source": segment_source},
                )
                intake_segment_labels = [
                    s
                    if str(s).strip()
                    else "_(unused column; skipped generic Segment N placeholder)_"
                    for s in display_segment_names
                ]
                write_segments_intake(
                    session_dir,
                    segment_names=intake_segment_labels,
                    methodology=methodology,
                    segment_source=segment_source,
                    raw_cowork_keys=cowork_keys,
                )
                write_segments_llm_audit(session_dir, segment_source=segment_source)
                if trace_capture is not None:
                    trace_capture["cs_fill_log_dir"] = str(session_dir.resolve())
                logger.info("CS fill session logs at %s", session_dir)
            except Exception as e:
                logger.warning("CS fill session log initialization failed: %s", e)
                session_dir = None

        with stage_scope("cs_agent_per_cell_table"):
            table_data = self._fill_table_concurrent(
                segments,
                indexes,
                file_ids=file_ids,
                module=module,
                methodology=methodology,
                session_upload_docs=session_upload_docs,
                trace_capture=trace_capture,
                session_dir=session_dir,
            )

        return {
            "segment_names": display_segment_names,
            "table_data": table_data,
            "maturity": "per_cell_retrieval",
            "facet_cache_hit": False,
        }
