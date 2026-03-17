"""Insight Forge - Streamlit frontend for GenAI-powered business plan slide filling."""

import base64
import hashlib
import html
import json
import markdown
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd
import requests

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
import streamlit as st
try:
    from streamlit_mic_recorder import mic_recorder, speech_to_text
except Exception:
    mic_recorder = None
    speech_to_text = None

API_SESSION = requests.Session()
API_SESSION.trust_env = False

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
TEMPLATE_PATH = os.getenv("TEMPLATE_PPTX_PATH", "/app/example_files/example slides.pptx")
VOICE_INPUT_LANGUAGE = os.getenv("VOICE_INPUT_LANGUAGE", "zh")

# API timeouts (configurable via .env)
TIMEOUT_QUICK = float(os.getenv("TIMEOUT_QUICK", "10"))
TIMEOUT_INGEST = float(os.getenv("TIMEOUT_INGEST", "60"))
TIMEOUT_LLM_GENERATION = float(os.getenv("TIMEOUT_LLM_GENERATION", "200"))
TIMEOUT_FILL_TABLE = float(os.getenv("TIMEOUT_FILL_TABLE", "30"))
_template_candidate = Path(TEMPLATE_PATH)
if not _template_candidate.is_absolute() or not _template_candidate.exists():
    _local = Path(__file__).resolve().parent.parent / "example_files" / "example slides.pptx"
    if _local.exists():
        TEMPLATE_PATH = str(_local.resolve())
elif _template_candidate.exists():
    TEMPLATE_PATH = str(_template_candidate.resolve())

PRODUCTS = ["Select a product...", "Sotyktu", "Product B", "Product C", "Product D"]
MODULES = ["Customer Segmentation", "SWOT Analysis", "Messaging Strategy"]
MODULE_ICONS = {
    "Customer Segmentation": "👥",
    "Messaging Strategy": "💬",
    "SWOT Analysis": "📈",
}
MODULE_DESC = {
    "Customer Segmentation": (
        "Identify and define the key stakeholders along the patient journey, "
        "segment them by value and receptivity, and pinpoint the specific "
        "behavior changes needed at each leverage point."
    ),
    "Messaging Strategy": (
        "Craft targeted messages that support behavior change objectives, "
        "pull through the Unified Brand Story, and address drivers and barriers "
        "versus the competitive set."
    ),
    "SWOT Analysis": (
        "Assess internal strengths and weaknesses alongside external "
        "opportunities and threats to surface strategic priorities and "
        "key risks."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────

def init_session_state():
    defaults = {
        "started": False,
        "selected_product": PRODUCTS[0],
        "slide_info": [],
        "fillable_indices": [],
        "active_module": MODULES[0],
        # 0 = module landing page; 1..N = slide pages
        "current_page_by_module": {m: 0 for m in MODULES},
        "pptx_bytes": None,
        # Per-module file ids — files are NOT shared across modules
        "file_ids_by_module": {m: [] for m in MODULES},
        "filled_slides": set(),
        "table_data_by_slide": {},
        "column_headers_by_slide": {},
        # Chat history is isolated by slide_idx (no cross-slide memory sharing)
        "chat_history_by_slide": {},
        "chat_input_nonce_by_slide": {},
        "last_voice_transcript_by_slide": {},
        "last_voice_id_by_slide": {},
        "cowork_session_id_by_slide": {},
        "cowork_ready_by_slide": {},
        "cowork_draft_by_slide": {},
        "cowork_web_permission_by_slide": {},
        "cowork_direct_docs_count_by_slide": {},
        # Cowork summary + segment names for fill-slide guidance (from End conversation)
        "cowork_summary_by_slide": {},
        "cowork_segment_names_by_slide": {},
        # Trigger completion celebration only once per completion transition.
        "completion_celebrated": False,
        # Web search state: per-slide search results and last query
        "web_search_results_by_slide": {},
        "web_search_query_by_slide": {},
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ─────────────────────────────────────────────────────────────────────────────
# Processing lock (block UI when long-running operations in progress)
# ─────────────────────────────────────────────────────────────────────────────

PROCESSING_OVERLAY_HTML = """
<div id="if-processing-overlay" style="
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    z-index: 99999; background: rgba(255,255,255,0.75);
    display: flex; align-items: center; justify-content: center;
    pointer-events: auto; cursor: not-allowed;
">
    <div style="text-align: center;">
        <div style="font-size: 1.2rem; font-weight: 600; color: #1a1a2e; margin-bottom: 0.5rem;">
            Processing…
        </div>
        <div style="font-size: 0.9rem; color: #666;">Please wait, do not click.</div>
    </div>
</div>
"""


def _is_processing() -> bool:
    """True when a long-running operation is pending (blocks button responses)."""
    return bool(st.session_state.get("pending_action"))


def _set_pending_and_rerun(action: dict):
    """Queue a long-running action and rerun to show overlay + execute."""
    st.session_state["pending_action"] = action
    st.rerun()


def _execute_pending_action():
    """Run the queued action (called when pending_action is set)."""
    action = st.session_state.get("pending_action")
    if not action:
        return
    action_type = action.get("type")
    module = action.get("module")
    slide_idx = action.get("slide_idx")

    with st.spinner(action.get("message", "Processing…")):
        try:
            if action_type == "ingest":
                files_data = st.session_state.pop("pending_ingest_files", [])
                if files_data:
                    from io import BytesIO

                    class _FileLike:
                        def __init__(self, name: str, data: bytes):
                            self.name = name
                            self._data = data

                        def getvalue(self):
                            return self._data

                    fake_files = [_FileLike(n, b) for n, b in files_data]
                    ok = _ingest_only(module, fake_files)
                    if ok:
                        st.caption(
                            f"Updated files: {len(st.session_state.file_ids_by_module[module])}"
                        )
                _rerun_in_module(module)

            elif action_type == "fill_slide":
                slide_info = st.session_state.get("slide_info", [])
                slides_by_module = get_slides_by_module(slide_info)
                module_slides = slides_by_module.get(module, [])
                slide_meta = next((s for s in module_slides if s["idx"] == slide_idx), None)
                module_fids = _module_file_ids(module)
                if slide_meta and module_fids and st.session_state.pptx_bytes:
                    table_structure = slide_meta.get("table_structure")
                    if not table_structure:
                        r = API_SESSION.post(
                            f"{BACKEND_URL}/fill-engine/table-structure",
                            data={"slide_idx": slide_idx, "path": TEMPLATE_PATH},
                            timeout=TIMEOUT_QUICK,
                        )
                        r.raise_for_status()
                        table_structure = r.json()
                    cowork_summary = st.session_state.setdefault("cowork_summary_by_slide", {}).get(
                        slide_idx
                    )
                    cowork_segments = st.session_state.setdefault(
                        "cowork_segment_names_by_slide", {}
                    ).get(slide_idx)
                    cowork_guidance = (
                        {"summary": cowork_summary, "segment_names": cowork_segments or []}
                        if cowork_summary
                        else None
                    )
                    fill_payload = {
                        "slide_idx": slide_idx,
                        "module": module,
                        "file_ids": module_fids,
                        "table_structure": table_structure,
                    }
                    if cowork_guidance:
                        fill_payload["cowork_guidance"] = cowork_guidance
                    fill_resp = API_SESSION.post(
                        f"{BACKEND_URL}/generation/fill",
                        json=fill_payload,
                        timeout=TIMEOUT_LLM_GENERATION,
                    )
                    fill_resp.raise_for_status()
                    fill_result = fill_resp.json()
                    table_data = fill_result.get("table_data", [])
                    column_headers = fill_result.get("column_headers")
                    if table_data:
                        form_data = {
                            "slide_idx": slide_idx,
                            "module": module,
                            "table_data_b64": base64.b64encode(
                                json.dumps(table_data).encode()
                            ).decode(),
                        }
                        if column_headers:
                            form_data["column_headers_b64"] = base64.b64encode(
                                json.dumps(column_headers).encode()
                            ).decode()
                        fill_r = API_SESSION.post(
                            f"{BACKEND_URL}/fill-engine/fill-table",
                            data=form_data,
                            files={"file": ("deck.pptx", st.session_state.pptx_bytes)},
                            timeout=TIMEOUT_FILL_TABLE,
                        )
                        fill_r.raise_for_status()
                        st.session_state.pptx_bytes = base64.b64decode(
                            fill_r.json()["pptx_base64"]
                        )
                        st.session_state.filled_slides.add(slide_idx)
                        st.session_state.table_data_by_slide[slide_idx] = table_data
                        if column_headers:
                            st.session_state.setdefault("column_headers_by_slide", {})[
                                slide_idx
                            ] = column_headers
                        st.success("Slide filled!")
                    _rerun_in_module(module)

            elif action_type == "web_search":
                q = action.get("query", "").strip()
                if q:
                    resp = API_SESSION.post(
                        f"{BACKEND_URL}/web-search/search",
                        json={"query": q, "max_results": 5},
                        timeout=20,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    st.session_state.setdefault("web_search_results_by_slide", {})[
                        slide_idx
                    ] = data.get("results", [])
                    st.session_state.setdefault("web_search_query_by_slide", {})[
                        slide_idx
                    ] = q
                _rerun_in_module(module)

            else:
                _run_chat_or_cowork_action(action)
        except Exception as e:
            st.error(str(e))
        finally:
            st.session_state.pop("pending_action", None)
            st.rerun()


def _run_chat_or_cowork_action(action: dict):
    """Execute chat/cowork/end_conversation/cowork_fill actions."""
    action_type = action.get("type")
    module = action.get("module")
    slide_idx = action.get("slide_idx")
    slide_info = st.session_state.get("slide_info", [])
    slides_by_module = get_slides_by_module(slide_info)
    module_slides = slides_by_module.get(module, [])
    slide_meta = next((s for s in module_slides if s["idx"] == slide_idx), None)
    if not slide_meta:
        return
    module_fids = _module_file_ids(module)
    table_structure = slide_meta.get("table_structure") or {}
    chat_history = list(_get_slide_chat_history(slide_idx))

    if action_type == "end_conversation":
        sess_map = st.session_state.setdefault("cowork_session_id_by_slide", {})
        if slide_idx not in sess_map:
            sess_map[slide_idx] = str(uuid.uuid4())
        chat_endpoint = (
            f"{BACKEND_URL}/cowork-agent/swot/chat"
            if module == "SWOT Analysis"
            else f"{BACKEND_URL}/cowork-agent/cs/chat"
        )
        end_payload = {
            "session_id": sess_map[slide_idx],
            "module": module,
            "slide_idx": slide_idx,
            "file_ids": module_fids,
            "table_structure": table_structure,
            "user_message": "",
            "conversation_history": chat_history,
            "allow_web_search": False,
            "action": "end_conversation",
        }
        if module == "SWOT Analysis":
            cs_summary, cs_table, cs_headers = _get_cs_context_for_swot()
            if cs_summary:
                end_payload["cs_cowork_summary"] = cs_summary
            if cs_table:
                end_payload["cs_filled_table"] = cs_table
            if cs_headers:
                end_payload["cs_filled_headers"] = cs_headers
        r = API_SESSION.post(chat_endpoint, json=end_payload, timeout=TIMEOUT_LLM_GENERATION)
        r.raise_for_status()
        payload = r.json()
        summary = payload.get("assistant_message", "Summary not available.")
        _append_slide_chat_message(slide_idx, "assistant", summary)
        st.session_state.setdefault("cowork_summary_by_slide", {})[slide_idx] = summary
        seg_names = payload.get("draft_column_headers") or []
        st.session_state.setdefault("cowork_segment_names_by_slide", {})[slide_idx] = (
            seg_names if isinstance(seg_names, list) else []
        )
        input_nonce_by_slide = st.session_state.setdefault("chat_input_nonce_by_slide", {})
        input_nonce_by_slide[slide_idx] = input_nonce_by_slide.get(slide_idx, 0) + 1
        st.success(
            "Conversation ended. Summary added to chat. "
            + (
                "Use Fill Slide to apply this guidance."
                if module == "Customer Segmentation"
                else "Summary will guide downstream SWOT generation."
            )
        )
        _rerun_in_module(module)
        return

    if action_type == "cowork_fill":
        draft = action.get("draft", {})
        draft_data = draft.get("table_data") or []
        draft_headers = draft.get("column_headers") or []
        if draft_data and st.session_state.pptx_bytes:
            fill_payload = {
                "slide_idx": slide_idx,
                "module": module,
                "table_data_b64": base64.b64encode(json.dumps(draft_data).encode()).decode(),
            }
            if draft_headers:
                fill_payload["column_headers_b64"] = base64.b64encode(
                    json.dumps(draft_headers).encode()
                ).decode()
            fill_r = API_SESSION.post(
                f"{BACKEND_URL}/fill-engine/fill-table",
                data=fill_payload,
                files={"file": ("deck.pptx", st.session_state.pptx_bytes)},
                timeout=TIMEOUT_FILL_TABLE,
            )
            fill_r.raise_for_status()
            st.session_state.pptx_bytes = base64.b64decode(fill_r.json()["pptx_base64"])
            st.session_state.table_data_by_slide[slide_idx] = draft_data
            if draft_headers:
                st.session_state.setdefault("column_headers_by_slide", {})[slide_idx] = (
                    draft_headers
                )
            st.session_state.filled_slides.add(slide_idx)
            st.session_state.setdefault("cowork_ready_by_slide", {})[slide_idx] = False
            st.success("Slide filled from cowork draft!")
        _rerun_in_module(module)
        return

    if action_type == "chat_send":
        user_msg = action.get("user_msg", "").strip()
        chat_mode = action.get("chat_mode", "modify")
        if not user_msg:
            return
        _append_slide_chat_message(slide_idx, "user", user_msg)
        current_data = st.session_state.table_data_by_slide.get(slide_idx)

        if chat_mode == "modify":
            if not table_structure or not current_data:
                _append_slide_chat_message(
                    slide_idx,
                    "assistant",
                    "Please fill this slide first, then I can help you refine it.",
                )
                st.session_state.setdefault("chat_input_nonce_by_slide", {})[slide_idx] = (
                    st.session_state.setdefault("chat_input_nonce_by_slide", {}).get(
                        slide_idx, 0
                    )
                    + 1
                )
                st.warning("Fill the slide first before refining.")
                _rerun_in_module(module)
                return

        if chat_mode == "cowork":
            sess_map = st.session_state.setdefault("cowork_session_id_by_slide", {})
            if slide_idx not in sess_map:
                sess_map[slide_idx] = str(uuid.uuid4())
            web_allowed = bool(st.session_state.get(f"cowork_web_permission_{slide_idx}", False))
            chat_endpoint = (
                f"{BACKEND_URL}/cowork-agent/swot/chat"
                if module == "SWOT Analysis"
                else f"{BACKEND_URL}/cowork-agent/cs/chat"
            )
            chat_payload = {
                "session_id": sess_map[slide_idx],
                "module": module,
                "slide_idx": slide_idx,
                "file_ids": module_fids,
                "table_structure": table_structure,
                "user_message": user_msg,
                "conversation_history": chat_history,
                "allow_web_search": web_allowed,
            }
            if module == "SWOT Analysis":
                cs_summary, cs_table, cs_headers = _get_cs_context_for_swot()
                if cs_summary:
                    chat_payload["cs_cowork_summary"] = cs_summary
                if cs_table:
                    chat_payload["cs_filled_table"] = cs_table
                if cs_headers:
                    chat_payload["cs_filled_headers"] = cs_headers
            r = API_SESSION.post(chat_endpoint, json=chat_payload, timeout=TIMEOUT_LLM_GENERATION)
        else:
            r = API_SESSION.post(
                f"{BACKEND_URL}/generation/chat",
                json={
                    "slide_idx": slide_idx,
                    "module": module,
                    "file_ids": module_fids,
                    "current_content": current_data or [],
                    "table_structure": table_structure,
                    "current_column_headers": st.session_state.get("column_headers_by_slide", {}).get(
                        slide_idx
                    ),
                    "user_message": user_msg,
                    "conversation_history": chat_history,
                    "mode": chat_mode,
                },
                timeout=TIMEOUT_LLM_GENERATION,
            )
        r.raise_for_status()
        payload = r.json()

        if chat_mode == "cowork":
            workflow = payload.get("workflow", {}) or {}
            assistant_msg = payload.get(
                "assistant_message",
                "I am ready to help you complete this table step by step.",
            )
            thinking_msg = payload.get("thinking") or None
            draft_data = payload.get("draft_table_data") or []
            draft_headers = payload.get("draft_column_headers") or []
            st.session_state.setdefault("cowork_draft_by_slide", {})[slide_idx] = {
                "table_data": draft_data,
                "column_headers": draft_headers,
            }
            st.session_state.setdefault("cowork_ready_by_slide", {})[slide_idx] = bool(
                workflow.get("ready_for_ppt_fill")
            )
        else:
            thinking_msg = None
            resolved_mode = payload.get("mode", chat_mode)
            updated = payload.get("table_data", [])
            updated_headers = payload.get("column_headers")
            assistant_msg = payload.get(
                "assistant_message",
                (
                    "Thanks for your feedback. I have updated this slide."
                    if resolved_mode == "modify"
                    else "Here is what I found based on your question."
                ),
            )
            if (
                resolved_mode == "modify"
                and updated
                and st.session_state.pptx_bytes
            ):
                fill_payload = {
                    "slide_idx": slide_idx,
                    "module": module,
                    "table_data_b64": base64.b64encode(json.dumps(updated).encode()).decode(),
                }
                if updated_headers:
                    fill_payload["column_headers_b64"] = base64.b64encode(
                        json.dumps(updated_headers).encode()
                    ).decode()
                fill_r = API_SESSION.post(
                    f"{BACKEND_URL}/fill-engine/fill-table",
                    data=fill_payload,
                    files={"file": ("deck.pptx", st.session_state.pptx_bytes)},
                    timeout=TIMEOUT_FILL_TABLE,
                )
                fill_r.raise_for_status()
                st.session_state.pptx_bytes = base64.b64decode(fill_r.json()["pptx_base64"])
                st.session_state.table_data_by_slide[slide_idx] = updated
                if updated_headers:
                    st.session_state.setdefault("column_headers_by_slide", {})[
                        slide_idx
                    ] = updated_headers

        _append_slide_chat_message(
            slide_idx, "assistant", assistant_msg, thinking_msg
        )
        st.session_state.setdefault("chat_input_nonce_by_slide", {})[slide_idx] = (
            st.session_state.setdefault("chat_input_nonce_by_slide", {}).get(slide_idx, 0) + 1
        )
        _rerun_in_module(module)


def _module_file_ids(module: str) -> list[str]:
    """Return the ingested file_ids for the given module."""
    return st.session_state.file_ids_by_module.get(module, [])


def _rerun_in_module(module: str):
    """Rerun while explicitly preserving the currently active module."""
    st.session_state.active_module = module
    st.rerun()


def _get_slide_chat_history(slide_idx: int) -> list[dict[str, str]]:
    by_slide = st.session_state.setdefault("chat_history_by_slide", {})
    if slide_idx not in by_slide:
        by_slide[slide_idx] = []
    return by_slide[slide_idx]


def _append_slide_chat_message(slide_idx: int, role: str, content: str, thinking: str | None = None):
    content = str(content).strip()
    if role not in {"user", "assistant"} or not content:
        return
    history = _get_slide_chat_history(slide_idx)
    msg: dict[str, str | None] = {"role": role, "content": content}
    if thinking and str(thinking).strip():
        msg["thinking"] = str(thinking).strip()
    history.append(msg)


# ─────────────────────────────────────────────────────────────────────────────
# Backend helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_slide_info() -> list:
    try:
        resp = API_SESSION.post(
            f"{BACKEND_URL}/fill-engine/slide-info-from-path",
            data={"path": TEMPLATE_PATH},
            timeout=TIMEOUT_QUICK,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Failed to load template: {e}")
        return []


def load_template_bytes() -> bytes | None:
    path = Path(TEMPLATE_PATH)
    return path.read_bytes() if path.exists() else None



def get_slides_by_module(slide_info: list) -> dict[str, list]:
    grouped: dict[str, list] = {m: [] for m in MODULES}
    for s in slide_info:
        if s.get("is_fillable"):
            m = s.get("module", "Unknown")
            if m in grouped:
                grouped[m].append(s)
    return grouped


def _get_cs_context_for_swot() -> tuple[str | None, list[list[str]] | None, list[str] | None]:
    """Gather CS cowork summary and filled table from Customer Segmentation slides."""
    slide_info = st.session_state.get("slide_info", [])
    slides_by_module = get_slides_by_module(slide_info)
    cs_slides = slides_by_module.get("Customer Segmentation", [])
    if not cs_slides:
        return None, None, None
    # Use first CS slide
    cs_slide_idx = cs_slides[0]["idx"]
    summary = st.session_state.setdefault("cowork_summary_by_slide", {}).get(cs_slide_idx)
    table = st.session_state.setdefault("table_data_by_slide", {}).get(cs_slide_idx, [])
    headers = st.session_state.setdefault("column_headers_by_slide", {}).get(cs_slide_idx, [])
    return summary, table if table else None, headers if headers else None


# ─────────────────────────────────────────────────────────────────────────────
# Module Landing Page  (page index = 0)
# ─────────────────────────────────────────────────────────────────────────────

def _ingest_only(module: str, uploaded_files) -> bool:
    """
    Ingest new files on a slide page (no answer regeneration).
    Replaces the current module's file_ids.
    Returns True on success.
    """
    # Use BytesIO so requests sends proper multipart; (name, bytes) may not work
    # for all server implementations when multiple files share the same form key.
    from io import BytesIO

    resp = API_SESSION.post(
        f"{BACKEND_URL}/retriever/ingest",
        files=[("files", (f.name, BytesIO(f.getvalue()))) for f in uploaded_files],
        timeout=TIMEOUT_INGEST,
    )
    if not resp.ok:
        st.error(f"Ingest failed: {resp.text}")
        return False

    data = resp.json()
    file_ids: list[str] = data.get("file_ids", [])
    st.session_state.file_ids_by_module[module] = file_ids

    for err in data.get("errors", []):
        st.warning(f"Skipped {err.get('file', '?')}: {err.get('error', '')}")

    if not file_ids:
        st.warning("No files were successfully ingested.")
        return False

    return True


def render_landing_page(module: str, slides: list):
    """Module home page: hero card only (module separator). Navigator/progress bar in parent."""

    icon = MODULE_ICONS.get(module, "📋")
    desc = MODULE_DESC.get(module, "")
    n_slides = len(slides)
    n_filled = sum(1 for s in slides if s["idx"] in st.session_state.filled_slides)

    # ── Module hero header ─────────────────────────────────────────────────
    st.markdown(
        f"""
        <style>
        .lp-hero {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
            border-radius: 16px; padding: 2.5rem 3rem 2rem;
            margin-bottom: 1.8rem; color: white;
        }}
        .lp-icon  {{ font-size: 2.8rem; margin-bottom: 0.4rem; }}
        .lp-title {{ font-size: 2.2rem; font-weight: 700; margin: 0 0 0.5rem; letter-spacing: -0.5px; }}
        .lp-desc  {{ font-size: 1rem; opacity: 0.8; max-width: 680px; line-height: 1.6; }}
        .lp-badge {{
            display: inline-block; background: rgba(255,255,255,0.15);
            border-radius: 20px; padding: 0.25rem 0.9rem;
            font-size: 0.85rem; margin-top: 1rem;
        }}
        </style>
        <div class="lp-hero">
            <div class="lp-icon">{icon}</div>
            <div class="lp-title">{module}</div>
            <div class="lp-desc">{desc}</div>
            <div class="lp-badge">{'✅ ' + str(n_filled) + '/' + str(n_slides) + ' slides filled' if n_slides else 'No slides configured'}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Slide page  (page index = 1..N)
# ─────────────────────────────────────────────────────────────────────────────

def render_slide_content(slide_meta: dict):
    slide_idx = slide_meta["idx"]
    filled = slide_idx in st.session_state.filled_slides
    table_structure = slide_meta.get("table_structure", {})
    row_labels = table_structure.get("indexes", [])
    # SWOT has no index column; all 4 columns are data columns. CS/others have corner cell.
    module = slide_meta.get("module", "")
    is_swot = (module or "").strip().lower() == "swot analysis"
    template_col_names = (
        table_structure.get("columns", [])
        if is_swot
        else table_structure.get("columns", [])[1:]  # skip corner cell
    )

    if filled:
        table_data = st.session_state.table_data_by_slide.get(slide_idx, [])
        col_headers = st.session_state.column_headers_by_slide.get(slide_idx)

        # Normalize ragged/misaligned LLM output so dataframe construction
        # never fails when row/column counts differ from template metadata.
        normalized_rows = [list(r) for r in table_data if isinstance(r, list)]
        n_data_rows = len(normalized_rows)
        n_data_cols = max((len(r) for r in normalized_rows), default=len(template_col_names))
        n_data_cols = max(1, n_data_cols)

        # Pad/truncate each data row to a consistent width.
        normalized_rows = [r[:n_data_cols] + [""] * (n_data_cols - len(r)) for r in normalized_rows]

        # Build robust column names: prefer LLM-detected headers only when shape matches.
        if col_headers and len(col_headers) == n_data_cols:
            col_names = col_headers
        else:
            base_cols = template_col_names[:n_data_cols]
            if len(base_cols) < n_data_cols:
                base_cols += [f"Column {i + 1}" for i in range(len(base_cols), n_data_cols)]
            col_names = base_cols

        # Build robust row labels: trim or pad template index labels to match data rows.
        if row_labels:
            idx_names = row_labels[:n_data_rows]
            if len(idx_names) < n_data_rows:
                idx_names += [f"Row {i + 1}" for i in range(len(idx_names), n_data_rows)]
        else:
            idx_names = [f"Row {i + 1}" for i in range(n_data_rows)]

        if normalized_rows:
            df = pd.DataFrame(normalized_rows, index=idx_names, columns=col_names)
        else:
            # Filled state but no rows returned: show table skeleton instead of crashing.
            fallback_rows = row_labels if row_labels else ["(no rows)"]
            fallback_cols = template_col_names if template_col_names else ["(no columns)"]
            df = pd.DataFrame("", index=fallback_rows, columns=fallback_cols)
    else:
        # Show empty template structure so users can see what will be filled
        df = pd.DataFrame(
            "",
            index=row_labels,
            columns=template_col_names if template_col_names else ["(fill to see columns)"],
        )

    # Render as HTML so text wraps inside cells (vertical growth) instead of
    # forcing horizontal scrolling like the interactive grid.
    styler = (
        df.style
        .set_properties(**{
            "white-space": "pre-wrap",
            "word-break": "break-word",
            "text-align": "left",
            "vertical-align": "top",
        })
        .set_table_styles([
            {
                "selector": "table",
                "props": [
                    ("table-layout", "fixed"),
                    ("width", "100%"),
                    ("border-collapse", "collapse"),
                ],
            },
            {
                "selector": "thead th",
                "props": [
                    ("background-color", "#1B3A5C"),
                    ("color", "white"),
                    ("font-weight", "bold"),
                    ("font-size", "12px"),
                    ("line-height", "1.3"),
                    ("padding", "8px"),
                    ("border", "1px solid #D7DEEA"),
                ],
            },
            {
                "selector": "th.row_heading",
                "props": [
                    ("background-color", "#E8EDF2"),
                    ("color", "#1B3A5C"),
                    ("font-weight", "bold"),
                    ("text-align", "left"),
                    ("font-size", "12px"),
                    ("line-height", "1.35"),
                    ("width", "220px"),
                    ("min-width", "220px"),
                    ("padding", "8px"),
                    ("border", "1px solid #D7DEEA"),
                ],
            },
            {
                "selector": "td",
                "props": [
                    ("width", "180px"),
                    ("min-width", "180px"),
                    ("max-width", "220px"),
                    ("font-size", "9px"),
                    ("line-height", "1.35"),
                    ("padding", "8px"),
                    ("border", "1px solid #D7DEEA"),
                ],
            },
        ])
    )
    st.markdown(
        "<div style='max-height:520px; overflow-y:auto; overflow-x:auto;'>"
        f"{styler.to_html()}"
        "</div>",
        unsafe_allow_html=True,
    )

    if not filled:
        st.caption("Fill this slide to populate the table.")


def render_controls_panel(slide_meta: dict, module: str):
    """File upload expander + Fill Slide button (right column, compact)."""
    slide_idx = slide_meta["idx"]
    module_fids = _module_file_ids(module)

    # ── Support files (compact, for slide page) ────────────────────────────
    with st.expander(
        f"📂 Files ({len(module_fids)})" if module_fids else "📂 Files (0)",
        expanded=False,
    ):
        new_files = st.file_uploader(
            "Replace/add files for this module",
            type=["pptx", "docx", "doc", "md", "pdf"],
            accept_multiple_files=True,
            key=f"slide_uploader_{slide_idx}",
            help="New upload replaces this module's current file set.",
        )
        if new_files:
            if st.button(
                f"Ingest {len(new_files)} file{'s' if len(new_files) > 1 else ''}",
                use_container_width=True,
                key=f"slide_ingest_{slide_idx}",
                disabled=_is_processing(),
            ):
                st.session_state["pending_ingest_files"] = [
                    (f.name, f.getvalue()) for f in new_files
                ]
                _set_pending_and_rerun({
                    "type": "ingest",
                    "module": module,
                    "message": "Ingesting files…",
                })

    st.markdown("<div style='height:0.1rem'></div>", unsafe_allow_html=True)

    # ── Fill Slide ─────────────────────────────────────────────────────────
    if st.button(
        "Fill Slide",
        type="primary",
        use_container_width=True,
        key=f"fill_{slide_idx}",
        disabled=_is_processing(),
    ):
        if not module_fids:
            st.warning("No files ingested for this module yet. Upload files above.")
        else:
            _set_pending_and_rerun({
                "type": "fill_slide",
                "module": module,
                "slide_idx": slide_idx,
                "message": "Generating content…",
            })


# ─────────────────────────────────────────────────────────────────────────────
# Web Search Panel  (below Fill Slide button, per slide)
# ─────────────────────────────────────────────────────────────────────────────

def render_web_search_panel(slide_meta: dict):
    """Internet search bar + collapsible result cards, isolated per slide."""
    slide_idx = slide_meta["idx"]
    results_store = st.session_state.setdefault("web_search_results_by_slide", {})
    query_store = st.session_state.setdefault("web_search_query_by_slide", {})

    st.markdown(
        """
        <style>
        .ws-header {
            font-size: 0.85rem; font-weight: 600; color: #1B3A5C;
            letter-spacing: 0.03em; margin: 0.6rem 0 0.3rem;
        }
        .ws-result-url {
            font-size: 0.72rem; color: #1a73e8; word-break: break-all; margin-bottom: 0.4rem;
        }
        .ws-result-body {
            font-size: 0.8rem; line-height: 1.5; color: #333;
            white-space: pre-wrap; word-break: break-word;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='ws-header'>🌐 Internet Search</div>", unsafe_allow_html=True)

    search_col, btn_col = st.columns([5, 1])
    with search_col:
        query_val = st.text_input(
            "web_search_input",
            value=query_store.get(slide_idx, ""),
            placeholder="Search the web for insights…",
            label_visibility="collapsed",
            key=f"ws_input_{slide_idx}",
            autocomplete="off",
        )
    with btn_col:
        do_search = st.button(
            "Search",
            use_container_width=True,
            key=f"ws_btn_{slide_idx}",
            disabled=_is_processing(),
        )

    if do_search:
        q = query_val.strip()
        if not q:
            st.warning("Enter a query before searching.")
        else:
            _set_pending_and_rerun({
                "type": "web_search",
                "module": slide_meta.get("module", st.session_state.active_module),
                "slide_idx": slide_idx,
                "query": q,
                "message": "Searching the web…",
            })

    results = results_store.get(slide_idx, [])
    if results:
        last_q = query_store.get(slide_idx, "")
        col_cap, col_clr = st.columns([4, 1])
        with col_cap:
            st.caption(f"Top results for: *{html.escape(last_q)}*")
        with col_clr:
            if st.button("Clear", key=f"ws_clear_{slide_idx}", use_container_width=True, disabled=_is_processing()):
                results_store.pop(slide_idx, None)
                query_store.pop(slide_idx, None)
                st.rerun()

        for i, r in enumerate(results[:5]):
            title = r.get("title") or f"Result {i + 1}"
            url = r.get("url", "")
            content = r.get("content", "")
            with st.expander(title, expanded=False):
                if url:
                    st.markdown(
                        f"<div class='ws-result-url'><a href='{url}' target='_blank'>{url}</a></div>",
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    f"<div class='ws-result-body'>{html.escape(content)}</div>",
                    unsafe_allow_html=True,
                )


def render_chat_panel(slide_meta: dict, module: str):
    """Full-width unified AI chat dialog rendered below the slide table."""
    slide_idx = slide_meta["idx"]
    module_fids = _module_file_ids(module)
    chat_history = _get_slide_chat_history(slide_idx)
    cowork_ready = st.session_state.setdefault("cowork_ready_by_slide", {}).get(slide_idx, False)
    cowork_draft = st.session_state.setdefault("cowork_draft_by_slide", {}).get(slide_idx, {})

    st.markdown(
        """
        <style>
        /* keep button labels on one line */
        div[data-testid="stButton"] button,
        div[data-testid="stFormSubmitButton"] button {
            white-space: nowrap;
            word-break: keep-all;
        }
        /* chat mode dropdown: keep only the caret visible when collapsed */
        [class*="st-key-chat_mode_"] [data-baseweb="select"] span,
        [class*="st-key-chat_mode_"] [data-baseweb="select"] p {
            display: none !important;
        }
        [class*="st-key-chat_mode_"] [data-baseweb="select"] > div {
            min-width: 2.2rem !important;
            padding-left: 0.15rem !important;
            padding-right: 0.15rem !important;
        }
        .ai-msg {
            font-size: 0.85rem;
            line-height: 1.4;
            padding: 0.55rem 0.7rem;
            border-radius: 10px;
            margin-bottom: 0.4rem;
            word-break: break-word;
            width: fit-content;
        }
        .ai-msg.user {
            background: #eaf4ff;
            border: 1px solid #d3e7ff;
            margin-left: auto;
        }
        .ai-msg.assistant {
            background: #e8e0f5;
            border: 1px solid #d4c8e8;
        }
        .ai-msg-wrap { display: flex; align-items: flex-start; gap: 0.5rem; margin-bottom: 0.5rem; }
        .ai-msg-wrap.user { justify-content: flex-end; }
        .ai-msg-wrap.assistant { justify-content: flex-start; }
        .ai-msg-icon { flex-shrink: 0; font-size: 1.1rem; margin-top: 0.15rem; }
        .ai-msg-wrap.user .ai-msg-icon { color: #1a73e8; order: 2; }
        .ai-msg-wrap.user .ai-msg-body { order: 1; }
        .ai-msg-wrap.assistant .ai-msg-icon { color: #6b4c9a; }
        .ai-msg-wrap.assistant .ai-msg { order: 2; }
        .ai-msg-thinking { margin-bottom: 0.35rem; }
        .ai-msg-thinking details {
            font-size: 0.8rem; color: #5a4a6a; background: #f5f0fa; border: 1px solid #d4c8e8;
            border-radius: 6px; padding: 0; overflow: hidden; cursor: pointer;
        }
        .ai-msg-thinking summary {
            padding: 0.35rem 0.5rem; font-weight: 600; font-size: 0.76rem; color: #6b5b7b;
            list-style: none; display: flex; align-items: center; gap: 0.35rem;
        }
        .ai-msg-thinking summary::-webkit-details-marker { display: none; }
        .ai-msg-thinking summary::before { content: "▶"; font-size: 0.6rem; transition: transform 0.2s; }
        .ai-msg-thinking details[open] summary::before { transform: rotate(90deg); }
        .ai-msg-thinking-content {
            padding: 0.45rem 0.6rem; font-size: 0.8rem; line-height: 1.45; font-style: italic;
            border-top: 1px solid #e8e0f0; background: linear-gradient(180deg, #faf8fc 0%, #f5f0fa 100%);
            font-family: "SF Mono", "Consolas", "Monaco", monospace; white-space: pre-wrap; word-break: break-word;
            animation: think-fadein 0.25s ease-out;
        }
        @keyframes think-fadein { from { opacity: 0; } to { opacity: 1; } }
        .ai-msg-thinking-stream {
            display: inline; position: relative;
        }
        .ai-msg-thinking-stream::after {
            content: "▋"; animation: think-blink 1s step-end infinite; color: #9a8ab8; font-weight: normal;
        }
        @keyframes think-blink { 70% { opacity: 0; } }
        .ai-msg-body { min-width: 0; max-width: 70%; }
        /* Markdown-rendered content inside assistant bubbles */
        .ai-msg.assistant p { margin: 0.25em 0; }
        .ai-msg.assistant p:first-child { margin-top: 0; }
        .ai-msg.assistant p:last-child { margin-bottom: 0; }
        .ai-msg.assistant ul, .ai-msg.assistant ol { margin: 0.35em 0; padding-left: 1.25em; }
        .ai-msg.assistant li { margin: 0.15em 0; }
        .ai-msg.assistant code { background: rgba(0,0,0,0.06); padding: 0.1em 0.35em; border-radius: 4px; font-size: 0.9em; }
        .ai-msg.assistant pre { margin: 0.4em 0; padding: 0.5em 0.6em; background: rgba(0,0,0,0.06); border-radius: 6px; overflow-x: auto; font-size: 0.82em; }
        .ai-msg.assistant pre code { background: none; padding: 0; }
        .ai-msg.assistant strong { font-weight: 700; }
        .ai-msg.assistant h1, .ai-msg.assistant h2, .ai-msg.assistant h3 { margin: 0.5em 0 0.25em; font-size: 1em; font-weight: 600; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='font-size:0.9rem;font-weight:600;margin:0.1rem 0 0.35rem 0'>"
        "Insight Forge - helping your business plan come to life</div>",
        unsafe_allow_html=True,
    )

    # ── Single unified chat box ─────────────────────────────────────────────
    mode_key = f"chat_mode_{slide_idx}"
    default_mode = "cowork" if module in ("Customer Segmentation", "SWOT Analysis") else "modify"
    if mode_key not in st.session_state:
        st.session_state[mode_key] = default_mode
    current_mode = st.session_state.get(mode_key, default_mode)
    with st.container(border=True):
        # Scrollable message history (larger chat area)
        with st.container(height=440, border=False):
            # Always show default first bot bubble in cowork mode (CS or SWOT)
            default_bot_msg = None
            if module == "Customer Segmentation" and current_mode == "cowork":
                default_bot_msg = (
                    "You are now in the Customer Segmentation module for BP insight generation. "
                    "Let's chat and co-work on the guideline to do customer segmentation."
                    "To get started, can you share what the main commercial goal is for this segmentation effort? "
                )
            elif module == "SWOT Analysis" and current_mode == "cowork":
                default_bot_msg = (
                    "You are now in the SWOT Analysis module for BP insight generation. "
                    "Is there anything you'd like me to emphasise when doing the analysis? Let's align and co-work on it."
                )
            if default_bot_msg:
                content_escaped = html.escape(default_bot_msg).replace("\n", "<br>")
                st.markdown(
                    f"<div class='ai-msg-wrap assistant'>"
                    f"<span class='ai-msg-icon' title='AI'>🤖</span>"
                    f"<div class='ai-msg assistant'>{content_escaped}</div></div>",
                    unsafe_allow_html=True,
                )
            has_cowork_default = (
                (module == "Customer Segmentation" and current_mode == "cowork")
                or (module == "SWOT Analysis" and current_mode == "cowork")
            )
            if not chat_history and not has_cowork_default:
                st.markdown(
                    "<div style='text-align:center;color:#aaa;padding:2.5rem 0;"
                    "font-size:0.88rem'>Choose cowork mode to get step-by-step guidance, or fill the slide then refine it with AI.</div>",
                    unsafe_allow_html=True,
                )
            for msg in chat_history:
                role = msg.get("role", "assistant")
                css_role = "user" if role == "user" else "assistant"
                icon = "👤" if role == "user" else "🤖"
                raw_content = str(msg.get("content", ""))
                # Render markdown for assistant messages; escape only for user messages
                if role == "assistant":
                    content = markdown.markdown(raw_content, extensions=["nl2br"])
                else:
                    content = html.escape(raw_content).replace("\n", "<br>")
                thinking = msg.get("thinking", "")
                thinking_html = ""
                if thinking and role == "assistant":
                    thinking_escaped = html.escape(str(thinking)).replace("\n", "<br>")
                    thinking_html = (
                        f"<div class='ai-msg-thinking'>"
                        f"<details><summary>💭 Thinking</summary>"
                        f"<div class='ai-msg-thinking-content'>"
                        f"<span class='ai-msg-thinking-stream'>{thinking_escaped}</span>"
                        f"</div></details></div>"
                    )
                body_html = f"{thinking_html}<div class='ai-msg {css_role}'>{content}</div>" if thinking_html else f"<div class='ai-msg {css_role}'>{content}</div>"
                st.markdown(
                    f"<div class='ai-msg-wrap {css_role}'>"
                    f"<span class='ai-msg-icon' title={'You' if role == 'user' else 'AI'}>{icon}</span>"
                    f"<div class='ai-msg-body'>{body_html}</div></div>",
                    unsafe_allow_html=True,
                )

        input_nonce_by_slide = st.session_state.setdefault("chat_input_nonce_by_slide", {})
        input_nonce = input_nonce_by_slide.get(slide_idx, 0)
        input_key = f"chat_input_{slide_idx}_{input_nonce}"
        pending_voice_prefill = st.session_state.setdefault("pending_voice_prefill_by_slide", {})
        if pending_voice_prefill.get(slide_idx):
            # Prefill before widget creation; Streamlit ignores/blocks late writes.
            st.session_state[input_key] = pending_voice_prefill[slide_idx]
            pending_voice_prefill.pop(slide_idx, None)
        mode_col, input_col, voice_col = st.columns([1, 3.6, 0.8], gap="small")
        with mode_col:
            if module == "Customer Segmentation" or module == "SWOT Analysis":
                mode_options = {"cowork": "🤝 co-work", "modify": "🛠 modify"}
            else:
                mode_options = {"modify": "🛠 modify"}
            chat_mode = st.selectbox(
                "Mode",
                options=list(mode_options.keys()),
                format_func=lambda m: mode_options.get(m, m),
                key=mode_key,
                label_visibility="collapsed",
            )
        with input_col:
            user_msg = st.text_input(
                "msg",
                key=input_key,
                placeholder=(
                    "Collaborate with AI to complete CS step by step..."
                    if chat_mode == "cowork" and module == "Customer Segmentation"
                    else
                    "Align on SWOT analysis emphasis..."
                    if chat_mode == "cowork" and module == "SWOT Analysis"
                    else "Ask AI to refine this slide..."
                ),
                label_visibility="collapsed",
                autocomplete="off",
            )
        with voice_col:
            def _process_voice_bytes(audio_bytes: bytes, audio_id: str):
                last_processed = st.session_state.setdefault("last_voice_id_by_slide", {})
                if not audio_bytes or not audio_id or last_processed.get(slide_idx) == audio_id:
                    return
                transcript_placeholder = st.empty()
                transcript_placeholder.caption("🎤 Transcribing...")
                try:
                    payload = {
                        "audio_b64": base64.b64encode(audio_bytes).decode("utf-8"),
                        "language": VOICE_INPUT_LANGUAGE,
                    }
                    with API_SESSION.post(
                        f"{BACKEND_URL}/voice/transcribe/stream",
                        json=payload,
                        stream=True,
                        timeout=TIMEOUT_LLM_GENERATION,
                    ) as resp:
                        resp.raise_for_status()
                        final_transcript = ""
                        for line in resp.iter_lines(decode_unicode=True):
                            if line and line.startswith("data: "):
                                try:
                                    data = json.loads(line[6:])
                                    if data.get("type") == "error":
                                        transcript_placeholder.caption(
                                            f"❌ {data.get('message', 'Transcription failed')}"
                                        )
                                        break
                                    t = data.get("transcript", "")
                                    if t:
                                        transcript_placeholder.caption(f"🎤 {t}")
                                        if data.get("type") == "final":
                                            final_transcript = t
                                except json.JSONDecodeError:
                                    pass
                    if final_transcript:
                        pending_voice_prefill = st.session_state.setdefault("pending_voice_prefill_by_slide", {})
                        pending_voice_prefill[slide_idx] = final_transcript
                        last_voice = st.session_state.setdefault("last_voice_transcript_by_slide", {})
                        last_voice[slide_idx] = final_transcript
                except Exception as e:
                    transcript_placeholder.caption(f"❌ Voice error: {e}")
                finally:
                    # Always mark as processed to prevent infinite retry on error
                    last_processed[slide_idx] = audio_id
                st.rerun()

            # Prefer Streamlit native recorder: explicit start/stop recording button.
            if hasattr(st, "audio_input"):
                voice_key = f"voice_input_{slide_idx}"
                audio_file = st.audio_input(
                    "Voice input",
                    key=voice_key,
                    label_visibility="collapsed",
                )
                if audio_file:
                    audio_bytes = audio_file.getvalue()
                    audio_id = hashlib.sha1(audio_bytes).hexdigest() if audio_bytes else ""
                    _process_voice_bytes(audio_bytes, audio_id)
            elif mic_recorder is None:
                st.button("🎤", disabled=True, help="Install streamlit-mic-recorder to enable voice input.")
            else:
                voice_key = f"voice_input_{slide_idx}"
                audio_out = st.session_state.get(voice_key + "_output")
                audio_bytes = audio_out.get("bytes") if isinstance(audio_out, dict) else None
                audio_id = audio_out.get("id") if isinstance(audio_out, dict) else None
                _process_voice_bytes(audio_bytes, str(audio_id or ""))
                mic_recorder(
                    start_prompt="🎤",
                    stop_prompt="⏹",
                    just_once=True,
                    key=voice_key,
                )
    # Send, Clear, and (in cowork mode) End conversation in one horizontal row
    if chat_mode == "cowork":
        action_l, action_m, action_r = st.columns(3)
    else:
        action_l, action_r = st.columns(2)
        action_m = None
    with action_l:
        send_clicked = st.button(
            "Send",
            type="primary",
            use_container_width=True,
            key=f"send_chat_{slide_idx}",
            disabled=_is_processing(),
        )
    with (action_m if action_m is not None else action_r):
        clear_clicked = st.button(
            "Clear",
            type="secondary",
            use_container_width=True,
            key=f"clear_chat_{slide_idx}",
            disabled=_is_processing(),
        )
    end_conversation_clicked = False
    if action_m is not None:
        with action_r:
            end_conversation_clicked = st.button(
                "End conversation",
                type="secondary",
                use_container_width=True,
                key=f"end_conversation_{slide_idx}",
                help="Generate a summary of what was discussed.",
                disabled=_is_processing(),
            )
    if cowork_ready and cowork_draft:
        if st.button(
            "Ready to fill the template?",
            type="primary",
            use_container_width=True,
            key=f"cowork_fill_{slide_idx}",
            disabled=_is_processing(),
        ):
            draft_data = cowork_draft.get("table_data") or []
            draft_headers = cowork_draft.get("column_headers") or []
            if draft_data and st.session_state.pptx_bytes:
                _set_pending_and_rerun({
                    "type": "cowork_fill",
                    "module": module,
                    "slide_idx": slide_idx,
                    "draft": {"table_data": draft_data, "column_headers": draft_headers},
                    "message": "Filling slide…",
                })
            else:
                st.warning("Cowork draft is not ready yet.")

    if chat_mode == "cowork" and end_conversation_clicked:
        _set_pending_and_rerun({
            "type": "end_conversation",
            "module": module,
            "slide_idx": slide_idx,
            "message": "Generating summary…",
        })
        return

    if clear_clicked:
        if slide_idx not in sess_map:
            sess_map[slide_idx] = str(uuid.uuid4())
        with st.spinner("Generating summary…"):
            try:
                chat_endpoint = (
                    f"{BACKEND_URL}/cowork-agent/swot/chat"
                    if module == "SWOT Analysis"
                    else f"{BACKEND_URL}/cowork-agent/cs/chat"
                )
                end_payload = {
                    "session_id": sess_map[slide_idx],
                    "module": module,
                    "slide_idx": slide_idx,
                    "file_ids": module_fids,
                    "table_structure": slide_meta.get("table_structure") or {},
                    "user_message": "",
                    "conversation_history": list(chat_history),
                    "allow_web_search": False,
                    "action": "end_conversation",
                }
                if module == "SWOT Analysis":
                    cs_summary, cs_table, cs_headers = _get_cs_context_for_swot()
                    if cs_summary:
                        end_payload["cs_cowork_summary"] = cs_summary
                    if cs_table:
                        end_payload["cs_filled_table"] = cs_table
                    if cs_headers:
                        end_payload["cs_filled_headers"] = cs_headers
                r = API_SESSION.post(
                    chat_endpoint,
                    json=end_payload,
                    timeout=TIMEOUT_LLM_GENERATION,
                )
                r.raise_for_status()
                payload = r.json()
                summary = payload.get("assistant_message", "Summary not available.")
                _append_slide_chat_message(slide_idx, "assistant", summary)
                st.session_state.setdefault("cowork_summary_by_slide", {})[slide_idx] = summary
                seg_names = payload.get("draft_column_headers") or []
                st.session_state.setdefault("cowork_segment_names_by_slide", {})[
                    slide_idx
                ] = seg_names if isinstance(seg_names, list) else []
                st.session_state.setdefault("chat_input_nonce_by_slide", {})[slide_idx] = input_nonce + 1
                st.success(
                    "Conversation ended. Summary added to chat. "
                    + ("Use Fill Slide to apply this guidance." if module == "Customer Segmentation" else "Summary will guide downstream SWOT generation.")
                )
                _rerun_in_module(module)
            except Exception as e:
                st.error(f"End conversation failed: {e}")
        return

    if clear_clicked:
        st.session_state.setdefault("chat_history_by_slide", {})[slide_idx] = []
        st.session_state.setdefault("chat_input_nonce_by_slide", {})[slide_idx] = input_nonce + 1
        _rerun_in_module(module)
        return

    # ── Handle submission ───────────────────────────────────────────────────
    if not (send_clicked and user_msg and user_msg.strip()):
        if send_clicked:
            st.warning("Please enter a message.")
        return

    # Queue chat send for deferred execution (overlay + no button response during processing)
    clean_user_msg = user_msg.strip()
    _set_pending_and_rerun({
        "type": "chat_send",
        "module": module,
        "slide_idx": slide_idx,
        "user_msg": clean_user_msg,
        "chat_mode": chat_mode,
        "message": "Thinking…",
    })
    return

    if False:  # chat_send now uses pending
        table_structure = slide_meta.get("table_structure")
        current_data = st.session_state.table_data_by_slide.get(slide_idx)
        history_snapshot = list(chat_history)
        _append_slide_chat_message(slide_idx, "user", clean_user_msg)

    if chat_mode == "modify":
        if not table_structure or not current_data:
            _append_slide_chat_message(
                slide_idx, "assistant",
                "Please fill this slide first, then I can help you refine it.",
            )
            st.session_state.setdefault("chat_input_nonce_by_slide", {})[slide_idx] = input_nonce + 1
            st.warning("Fill the slide first before refining.")
            _rerun_in_module(module)
            return
    with st.spinner("Thinking…"):
        try:
            if chat_mode == "cowork":
                sess_map = st.session_state.setdefault("cowork_session_id_by_slide", {})
                if slide_idx not in sess_map:
                    sess_map[slide_idx] = str(uuid.uuid4())
                web_allowed = bool(st.session_state.get(f"cowork_web_permission_{slide_idx}", False))
                chat_endpoint = (
                    f"{BACKEND_URL}/cowork-agent/swot/chat"
                    if module == "SWOT Analysis"
                    else f"{BACKEND_URL}/cowork-agent/cs/chat"
                )
                chat_payload = {
                    "session_id": sess_map[slide_idx],
                    "module": module,
                    "slide_idx": slide_idx,
                    "file_ids": module_fids,
                    "table_structure": table_structure or {},
                    "user_message": clean_user_msg,
                    "conversation_history": history_snapshot,
                    "allow_web_search": web_allowed,
                }
                if module == "SWOT Analysis":
                    cs_summary, cs_table, cs_headers = _get_cs_context_for_swot()
                    if cs_summary:
                        chat_payload["cs_cowork_summary"] = cs_summary
                    if cs_table:
                        chat_payload["cs_filled_table"] = cs_table
                    if cs_headers:
                        chat_payload["cs_filled_headers"] = cs_headers
                r = API_SESSION.post(
                    chat_endpoint,
                    json=chat_payload,
                    timeout=TIMEOUT_LLM_GENERATION,
                )
            else:
                r = API_SESSION.post(
                    f"{BACKEND_URL}/generation/chat",
                    json={
                        "slide_idx": slide_idx,
                        "module": module,
                        "file_ids": module_fids,
                        "current_content": current_data or [],
                        "table_structure": table_structure or {},
                        "current_column_headers": st.session_state.get(
                            "column_headers_by_slide", {}
                        ).get(slide_idx),
                        "user_message": clean_user_msg,
                        "conversation_history": history_snapshot,
                        "mode": chat_mode,
                    },
                    timeout=TIMEOUT_LLM_GENERATION,
                )
            r.raise_for_status()
            payload = r.json()
            if chat_mode == "cowork":
                workflow = payload.get("workflow", {}) or {}
                assistant_msg = payload.get(
                    "assistant_message",
                    "I am ready to help you complete this table step by step.",
                )
                thinking_msg = payload.get("thinking") or None
                draft_data = payload.get("draft_table_data") or []
                draft_headers = payload.get("draft_column_headers") or []
                st.session_state.setdefault("cowork_draft_by_slide", {})[slide_idx] = {
                    "table_data": draft_data,
                    "column_headers": draft_headers,
                }
                st.session_state.setdefault("cowork_ready_by_slide", {})[slide_idx] = bool(
                    workflow.get("ready_for_ppt_fill")
                )
            else:
                thinking_msg = None
                resolved_mode = payload.get("mode", chat_mode)
                updated = payload.get("table_data", [])
                updated_headers = payload.get("column_headers")
                assistant_msg = payload.get(
                    "assistant_message",
                    (
                        "Thanks for your feedback. I have updated this slide."
                        if resolved_mode == "modify"
                        else "Here is what I found based on your question."
                    ),
                )
            if chat_mode != "cowork" and resolved_mode == "modify" and updated and st.session_state.pptx_bytes:
                fill_payload = {
                    "slide_idx": slide_idx,
                    "module": module,
                    "table_data_b64": base64.b64encode(
                        json.dumps(updated).encode()
                    ).decode(),
                }
                if updated_headers:
                    fill_payload["column_headers_b64"] = base64.b64encode(
                        json.dumps(updated_headers).encode()
                    ).decode()
                fill_r = API_SESSION.post(
                    f"{BACKEND_URL}/fill-engine/fill-table",
                    data=fill_payload,
                    files={"file": ("deck.pptx", st.session_state.pptx_bytes)},
                    timeout=TIMEOUT_FILL_TABLE,
                )
                fill_r.raise_for_status()
                st.session_state.pptx_bytes = base64.b64decode(
                    fill_r.json()["pptx_base64"]
                )
                st.session_state.table_data_by_slide[slide_idx] = updated
                if updated_headers:
                    st.session_state.setdefault("column_headers_by_slide", {})[
                        slide_idx
                    ] = updated_headers
                st.success("Slide updated!")
            st.session_state.setdefault("chat_input_nonce_by_slide", {})[slide_idx] = input_nonce + 1
            _append_slide_chat_message(
                slide_idx,
                "assistant",
                assistant_msg,
                thinking=thinking_msg if chat_mode == "cowork" else None,
            )
            _rerun_in_module(module)
        except Exception as e:
            _append_slide_chat_message(
                slide_idx,
                "assistant",
                "Sorry, I couldn't apply this refinement due to a system error. "
                "Please try again and I will assist right away.",
            )
            st.error(f"Feedback failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Module tab  (landing page + N slide pages)
# ─────────────────────────────────────────────────────────────────────────────

def render_module_tab(module: str, slides: list):
    """
    Page layout within a module tab:
      page 0          → Landing page (support files + navigate to slides)
      page 1 .. N     → Slide fill pages
    """
    n_slides = len(slides)
    # total pages = landing (1) + slides
    total_pages = 1 + n_slides

    cur = st.session_state.current_page_by_module[module]
    cur = max(0, min(cur, total_pages - 1))
    st.session_state.current_page_by_module[module] = cur

    # ── Pagination bar ─────────────────────────────────────────────────────
    pg_l, pg_mid, pg_r = st.columns([1, 5, 1])
    with pg_l:
        if st.button(
            "← Back",
            use_container_width=True,
            key=f"prev_{module}_{cur}",
            disabled=(cur == 0) or _is_processing(),
        ):
            st.session_state.current_page_by_module[module] -= 1
            _rerun_in_module(module)
    with pg_mid:
        # Build indicator dots: 🏠 for landing, ● / ✓ / ○ for slides
        dots = []
        for i in range(total_pages):
            if i == 0:
                label = "🏠" if cur != 0 else "📍"
            else:
                s_idx = slides[i - 1]["idx"]
                if i == cur:
                    label = "●"
                elif s_idx in st.session_state.filled_slides:
                    label = "✓"
                else:
                    label = "○"
            dots.append(label)
        page_label = "Home" if cur == 0 else f"Slide {cur} / {n_slides}"
        st.markdown(
            f"<div style='text-align:center;font-size:1rem;letter-spacing:5px;"
            f"color:#444;padding:4px 0'>{' '.join(dots)}</div>"
            f"<div style='text-align:center;font-size:0.8rem;color:#888;margin-top:2px'>"
            f"{page_label}</div>",
            unsafe_allow_html=True,
        )
    with pg_r:
        if st.button(
            "Next →",
            use_container_width=True,
            key=f"next_{module}_{cur}",
            disabled=(cur == total_pages - 1) or _is_processing(),
        ):
            st.session_state.current_page_by_module[module] += 1
            _rerun_in_module(module)

    st.divider()

    # ── Page content ───────────────────────────────────────────────────────
    if cur == 0:
        render_landing_page(module, slides)
    else:
        slide_meta = slides[cur - 1]
        slide_idx = slide_meta["idx"]
        filled = slide_idx in st.session_state.filled_slides

        # 50/50 split: left = chat, divider, right = table (top) + upload (bottom)
        col_left, col_divider, col_right = st.columns([1, 0.02, 1], gap="small")
        with col_left:
            render_chat_panel(slide_meta, module)
        with col_divider:
            st.markdown(
                "<div style='border-left: 2px solid #e0e0e0; min-height: 480px; margin: 0;'></div>",
                unsafe_allow_html=True,
            )
        with col_right:
            # Top right: slide header + table
            icon = MODULE_ICONS.get(module, "📋")
            fill_badge = (
                "<span style='background:#d4edda;color:#155724;border-radius:8px;"
                "padding:2px 10px;font-size:0.8rem;margin-left:10px'>✅ Filled</span>"
                if filled else ""
            )
            st.markdown(
                f"<h3 style='margin-bottom:0.2rem'>{icon} {module} &mdash; Slide {cur}"
                f"{fill_badge}</h3>",
                unsafe_allow_html=True,
            )
            render_slide_content(slide_meta)
            st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
            # Bottom right: upload + Fill Slide + web search
            render_controls_panel(slide_meta, module)
            render_web_search_panel(slide_meta)

        # Download when all slides in module are done
        all_filled = all(s["idx"] in st.session_state.filled_slides for s in slides)
        if all_filled and st.session_state.pptx_bytes:
            st.divider()
            st.success(f"All {module} slides complete!")
            st.download_button(
                f"Download Deck",
                data=st.session_state.pptx_bytes,
                file_name="insight_forge_deck.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                use_container_width=True,
                key=f"dl_{module}",
            )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Insight Forge",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    init_session_state()

    # ── Processing lock: when a long-running action is queued, show overlay and execute ──
    pending = st.session_state.get("pending_action")
    if pending:
        st.markdown(PROCESSING_OVERLAY_HTML, unsafe_allow_html=True)
        _execute_pending_action()
        return

    # ── Welcome page ───────────────────────────────────────────────────────
    if not st.session_state.started:
        if "welcome_product" not in st.session_state:
            st.session_state.welcome_product = PRODUCTS[0]

        module_cards_html = "".join(
            (
                '<div class="if-mod-card">'
                f'<div class="ic">{MODULE_ICONS.get(module, "📋")}</div>'
                f'<div class="lb">{module}</div>'
                "</div>"
            )
            for module in MODULES
        )
        st.markdown(
            """
            <style>
            @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600&family=Source+Sans+3:wght@400;600&display=swap');
            .if-title { font-family:'Playfair Display',serif; font-size:3.5rem;
                        font-weight:600; text-align:center; margin:2rem 0 0.5rem; color:#1a1a2e; }
            .if-desc  { font-family:'Source Sans 3',sans-serif; font-size:1.15rem;
                        text-align:center; color:#4a4a6a; max-width:640px;
                        margin:0 auto 2.5rem; line-height:1.7; }
            .if-modules { display:flex; justify-content:center; gap:2rem; margin-bottom:2.5rem; }
            .if-mod-card { background:#f7f7fb; border:1px solid #e0e0f0; border-radius:14px;
                           padding:1.4rem 2rem; text-align:center; min-width:220px; }
            .if-mod-card .ic { font-size:2.2rem; }
            .if-mod-card .lb { font-size:1rem; font-weight:600; color:#1a1a2e; margin-top:0.5rem; }
            </style>
            <div class="if-title">Insight Forge</div>
            <div class="if-desc">
                GenAI-powered business plan slide filling. Upload support documents
                and let AI populate every module of your deck.
            </div>
            <div class="if-modules">
            """
            + module_cards_html
            + """
            </div>
            """,
            unsafe_allow_html=True,
        )
        _, col, _ = st.columns([1, 1, 1])
        with col:
            selected_product = st.selectbox(
                "Products",
                options=PRODUCTS,
                index=PRODUCTS.index(st.session_state.welcome_product),
                key="welcome_product_select",
            )
            st.session_state.welcome_product = selected_product
            product_picked = selected_product and selected_product != "Select a product..."
            if st.button(
                "Start",
                type="primary",
                use_container_width=True,
                disabled=(not product_picked) or _is_processing(),
            ):
                st.session_state.started = True
                st.session_state.selected_product = selected_product
                st.session_state.slide_info = load_slide_info()
                st.session_state.fillable_indices = [
                    s["idx"] for s in st.session_state.slide_info if s.get("is_fillable")
                ]
                st.session_state.pptx_bytes = load_template_bytes()
                st.rerun()
        return

    # ── Main app ───────────────────────────────────────────────────────────
    slide_info = st.session_state.slide_info
    if not slide_info:
        st.warning("No slide info loaded.")
        if st.button("Restart", disabled=_is_processing()):
            st.session_state.started = False
            st.rerun()
        return

    slides_by_module = get_slides_by_module(slide_info)
    all_fillable = [s for sl in slides_by_module.values() for s in sl]
    n_filled = sum(1 for s in all_fillable if s["idx"] in st.session_state.filled_slides)
    n_total = len(all_fillable)

    # App header + overall progress
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600&display=swap');
        .if-header { font-family:'Playfair Display',serif; font-size:1.7rem;
                     font-weight:600; color:#1a1a2e; margin-bottom:0.2rem; }
        </style>
        <div class="if-header">📊 Insight Forge</div>
        """,
        unsafe_allow_html=True,
    )
    if n_total > 0:
        pct = int(100 * n_filled / n_total)
        st.progress(
            n_filled / n_total,
            text=f"Overall: {n_filled}/{n_total} slides filled ({pct}%)",
        )

    st.divider()

    # ── Module selector (persists across reruns) ───────────────────────────
    done_by_module: dict[str, int] = {}
    for m in MODULES:
        sl = slides_by_module[m]
        done_by_module[m] = sum(1 for s in sl if s["idx"] in st.session_state.filled_slides)

    default_idx = MODULES.index(st.session_state.active_module) if st.session_state.active_module in MODULES else 0
    active_module = st.radio(
        "Module",
        options=MODULES,
        index=default_idx,
        horizontal=True,
        format_func=lambda m: (
            f"{MODULE_ICONS.get(m, '')} {m} ({done_by_module[m]}/{len(slides_by_module[m])})"
        ),
    )
    st.session_state.active_module = active_module

    render_module_tab(active_module, slides_by_module[active_module])

    # ── Final download ─────────────────────────────────────────────────────
    is_complete = n_total > 0 and n_filled == n_total and bool(st.session_state.pptx_bytes)
    if not is_complete:
        st.session_state.completion_celebrated = False

    if is_complete:
        if not st.session_state.completion_celebrated:
            st.balloons()
            st.session_state.completion_celebrated = True
        st.divider()
        st.success("🎉 All modules complete!")
        st.download_button(
            "Download Complete Deck",
            data=st.session_state.pptx_bytes,
            file_name="insight_forge_deck.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
