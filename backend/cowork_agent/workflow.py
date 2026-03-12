"""Workflow state-transition guardrails for the CS cowork agent.

These rules enforce valid state sequencing at the infrastructure level.
They do NOT drive the user-facing conversation — that is handled entirely
by the LLM consultant persona in prompt_builder / orchestrator.
"""

from __future__ import annotations

from cowork_agent.models import EventType, WorkflowState


def next_state(current: WorkflowState, event: EventType, *, has_draft: bool) -> WorkflowState:
    if current == WorkflowState.ERROR:
        return WorkflowState.ERROR

    if event == EventType.CONFIRM_PPT_FILL and has_draft:
        return WorkflowState.READY_FOR_PPT_FILL

    if current == WorkflowState.INIT:
        return WorkflowState.LOAD_TEMPLATE_CONTEXT

    if event == EventType.FILES_ATTACHED:
        return WorkflowState.FILE_PREPROCESSING

    if event == EventType.WEB_PERMISSION_GRANTED:
        return WorkflowState.RETRIEVING_EVIDENCE

    if current in {
        WorkflowState.FILE_PREPROCESSING,
        WorkflowState.RETRIEVING_EVIDENCE,
        WorkflowState.DRAFTING_CONTENT,
    } and has_draft:
        return WorkflowState.REVIEWING_WITH_USER

    # When no draft yet, stay in a waiting state so the orchestrator can
    # signal the front-end that content has not been generated yet.
    # The LLM conversation continues regardless — the user experience is
    # driven by ConversationPhase, not by this state.
    if not has_draft:
        return WorkflowState.WAITING_FOR_SUPPORT_FILES

    return WorkflowState.REVIEWING_WITH_USER
