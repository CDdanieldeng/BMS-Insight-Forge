"""Stage-level timing and token accounting for AI-assisted pipeline steps."""

from __future__ import annotations

import json
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared.logging_config import setup_logging

logger = setup_logging("generation")

_LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "ai_stage_metrics.jsonl"

_CURRENT_RUN: ContextVar["StageRun | None"] = ContextVar("_CURRENT_RUN", default=None)
_CURRENT_STAGE: ContextVar[str] = ContextVar("_CURRENT_STAGE", default="unscoped")


@dataclass(slots=True)
class StageStat:
    elapsed_ms_total: int = 0
    stage_calls: int = 0
    llm_calls: int = 0
    prompt_tokens_total: int = 0
    completion_tokens_total: int = 0
    total_tokens_total: int = 0
    llm_elapsed_ms_total: int = 0


@dataclass(slots=True)
class StageRun:
    operation: str
    module: str = ""
    slide_idx: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at_epoch_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    _started_perf: float = field(default_factory=time.perf_counter)
    _stages: dict[str, StageStat] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    status: str = "ok"
    error: str = ""

    def _stage(self, name: str) -> StageStat:
        if name not in self._stages:
            self._stages[name] = StageStat()
        return self._stages[name]

    @contextmanager
    def stage(self, name: str):
        stage_name = (name or "").strip() or "unscoped"
        token = _CURRENT_STAGE.set(stage_name)
        stage_start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = int((time.perf_counter() - stage_start) * 1000)
            stat = self._stage(stage_name)
            stat.stage_calls += 1
            stat.elapsed_ms_total += max(elapsed, 0)
            _CURRENT_STAGE.reset(token)

    def record_llm_call(
        self,
        *,
        provider: str,
        model: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        elapsed_ms: int,
    ) -> None:
        _ = provider, model  # reserved for future fine-grained logs
        stage_name = _CURRENT_STAGE.get()
        with self._lock:
            stat = self._stage(stage_name)
            stat.llm_calls += 1
            stat.llm_elapsed_ms_total += max(int(elapsed_ms or 0), 0)
            stat.prompt_tokens_total += int(prompt_tokens or 0)
            stat.completion_tokens_total += int(completion_tokens or 0)
            stat.total_tokens_total += int(total_tokens or 0)

    def mark_failed(self, exc: Exception) -> None:
        self.status = "failed"
        self.error = f"{exc.__class__.__name__}: {exc}"

    def flush(self) -> None:
        elapsed_total = int((time.perf_counter() - self._started_perf) * 1000)
        stages = {
            name: {
                "elapsed_ms_total": stat.elapsed_ms_total,
                "stage_calls": stat.stage_calls,
                "llm_calls": stat.llm_calls,
                "prompt_tokens_total": stat.prompt_tokens_total,
                "completion_tokens_total": stat.completion_tokens_total,
                "total_tokens_total": stat.total_tokens_total,
                "llm_elapsed_ms_total": stat.llm_elapsed_ms_total,
            }
            for name, stat in sorted(self._stages.items())
        }
        event = {
            "run_id": self.run_id,
            "operation": self.operation,
            "module": self.module,
            "slide_idx": self.slide_idx,
            "status": self.status,
            "error": self.error,
            "started_at_epoch_ms": self.started_at_epoch_ms,
            "elapsed_ms_total": elapsed_total,
            "metadata": self.metadata,
            "stages": stages,
            "totals": {
                "llm_calls": sum(s.llm_calls for s in self._stages.values()),
                "prompt_tokens_total": sum(s.prompt_tokens_total for s in self._stages.values()),
                "completion_tokens_total": sum(
                    s.completion_tokens_total for s in self._stages.values()
                ),
                "total_tokens_total": sum(s.total_tokens_total for s in self._stages.values()),
            },
        }
        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=True) + "\n")
            logger.info(
                "Stage metrics written operation=%s module=%s slide_idx=%s run_id=%s path=%s",
                self.operation,
                self.module,
                self.slide_idx,
                self.run_id,
                _LOG_PATH,
            )
        except Exception as exc:
            logger.warning("Failed to write stage metrics run_id=%s err=%s", self.run_id, exc)


@contextmanager
def run_scope(
    *,
    operation: str,
    module: str = "",
    slide_idx: int | None = None,
    metadata: dict[str, Any] | None = None,
):
    """Create an isolated stage-metrics run and flush to logs on exit."""
    run = StageRun(
        operation=operation,
        module=module,
        slide_idx=slide_idx,
        metadata=dict(metadata or {}),
    )
    token = _CURRENT_RUN.set(run)
    try:
        yield run
    except Exception as exc:
        run.mark_failed(exc)
        raise
    finally:
        _CURRENT_RUN.reset(token)
        run.flush()


@contextmanager
def stage_scope(name: str):
    """Attach timing and LLM token accounting to one logical stage."""
    run = _CURRENT_RUN.get()
    if run is None:
        yield
        return
    with run.stage(name):
        yield


def record_llm_usage(
    *,
    provider: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    elapsed_ms: int,
) -> None:
    """Record one LLM call usage into the current run/stage, if any."""
    run = _CURRENT_RUN.get()
    if run is None:
        return
    run.record_llm_call(
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        elapsed_ms=elapsed_ms,
    )
