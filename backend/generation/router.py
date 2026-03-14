"""FastAPI router for the generation service (orchestrator)."""

from typing import Any
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from generation.agent import apply_feedback, answer_question
from generation.key_questions import get_questions_for_module
from generation.orchestrator import run_fill, generate_key_question_answers

router = APIRouter(prefix="/generation", tags=["generation"])
logger = __import__("logging").getLogger("generation")


class FillRequest(BaseModel):
    slide_idx: int
    module: str
    file_ids: list[str]
    table_structure: dict[str, Any]
    cowork_guidance: dict[str, Any] | None = None  # {"summary": str, "segment_names": list[str]}


class ChatRequest(BaseModel):
    slide_idx: int
    module: str
    file_ids: list[str]
    current_content: list[list[str]]
    table_structure: dict[str, Any]
    current_column_headers: list[str] | None = None
    user_message: str
    conversation_history: list[dict[str, str]] | None = None
    mode: Literal["ask", "modify"] = "modify"  # decay: ask mode scheduled for removal


class KeyQuestionsResponse(BaseModel):
    module: str
    questions: list[str]


class KeyAnswerItem(BaseModel):
    question: str
    answer: str


class KeyAnswersRequest(BaseModel):
    module: str
    file_ids: list[str]


class KeyAnswersResponse(BaseModel):
    module: str
    answers: list[KeyAnswerItem]


@router.get("/key-questions/{module}")
async def key_questions(module: str) -> KeyQuestionsResponse:
    """Return key business questions for a module."""
    try:
        questions = get_questions_for_module(module)
        return KeyQuestionsResponse(module=module, questions=questions)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/key-answers")
async def key_answers(req: KeyAnswersRequest) -> KeyAnswersResponse:
    """Answer key business questions for a module using uploaded files."""
    try:
        answers = generate_key_question_answers(req.module, req.file_ids)
        return KeyAnswersResponse(
            module=req.module,
            answers=[KeyAnswerItem(**item) for item in answers],
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Key answers failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fill")
async def fill(req: FillRequest) -> dict[str, Any]:
    """
    Orchestrate fill: enhance query -> retriever -> (optionally) extract segment
    names -> LLM generate table.

    Returns:
        table_data:     2-D array of cell values
        column_headers: list of real segment names (replaces placeholder headers),
                        or null if columns were not placeholders
    """
    try:
        result = run_fill(
            slide_idx=req.slide_idx,
            module=req.module,
            file_ids=req.file_ids,
            table_structure=req.table_structure,
            cowork_guidance=req.cowork_guidance,
        )
        return result  # {"table_data": [...], "column_headers": [...] | None}
    except Exception as e:
        logger.exception("Fill failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat")
async def chat(req: ChatRequest) -> dict[str, Any]:
    """
    Apply user feedback to update table content via agent.
    """
    try:
        if req.mode == "ask":  # decay: ask mode scheduled for removal
            answer = answer_question(
                module=req.module,
                current_content=req.current_content,
                table_structure=req.table_structure,
                user_message=req.user_message,
                file_ids=req.file_ids,
                current_column_headers=req.current_column_headers,
                conversation_history=req.conversation_history,
            )
            return {"mode": "ask", **answer}

        updated = apply_feedback(
            module=req.module,
            current_content=req.current_content,
            table_structure=req.table_structure,
            user_message=req.user_message,
            file_ids=req.file_ids,
            current_column_headers=req.current_column_headers,
            conversation_history=req.conversation_history,
        )
        return {"mode": "modify", **updated}
    except Exception as e:
        logger.exception("Chat failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
