"""Insight Forge - Streamlit frontend for GenAI-powered business plan slide filling."""

import base64
import json
import os
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd
import requests

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
import streamlit as st

API_SESSION = requests.Session()
API_SESSION.trust_env = False

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
TEMPLATE_PATH = os.getenv("TEMPLATE_PPTX_PATH", "/app/example_files/example slides.pptx")

# API timeouts (configurable via .env)
TIMEOUT_QUICK = float(os.getenv("TIMEOUT_QUICK", "10"))
TIMEOUT_KEY_QUESTIONS = float(os.getenv("TIMEOUT_KEY_QUESTIONS", "5"))
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

MODULES = ["Customer Segmentation", "Messaging Strategy"]
MODULE_ICONS = {"Customer Segmentation": "👥", "Messaging Strategy": "💬"}
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
}


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────

def init_session_state():
    defaults = {
        "started": False,
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
        "key_question_answers": {},
        "column_headers_by_slide": {},
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _module_file_ids(module: str) -> list[str]:
    """Return the ingested file_ids for the given module."""
    return st.session_state.file_ids_by_module.get(module, [])


def _rerun_in_module(module: str):
    """Rerun while explicitly preserving the currently active module."""
    st.session_state.active_module = module
    st.rerun()


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


def fetch_key_questions(module: str) -> list[str]:
    try:
        r = API_SESSION.get(f"{BACKEND_URL}/generation/key-questions/{module}", timeout=TIMEOUT_KEY_QUESTIONS)
        if r.ok:
            return r.json().get("questions", [])
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Module Landing Page  (page index = 0)
# ─────────────────────────────────────────────────────────────────────────────

def _ingest_and_answer(module: str, uploaded_files) -> bool:
    """
    Step 1: ingest uploaded files into the retriever store (scoped to this module).
    Step 2: immediately call LLM to answer key questions for this module.
    Returns True on success.
    Files from OTHER modules are unaffected.
    """
    # 1. Ingest
    resp = API_SESSION.post(
        f"{BACKEND_URL}/retriever/ingest",
        files=[("files", (f.name, f.getvalue())) for f in uploaded_files],
        timeout=TIMEOUT_INGEST,
    )
    if not resp.ok:
        st.error(f"Ingest failed: {resp.text}")
        return False

    data = resp.json()
    file_ids: list[str] = data.get("file_ids", [])
    # Store only for this module; leave other modules untouched
    st.session_state.file_ids_by_module[module] = file_ids
    # Clear stale answers for THIS module only
    st.session_state.key_question_answers.pop(module, None)

    for err in data.get("errors", []):
        st.warning(f"Skipped {err.get('file', '?')}: {err.get('error', '')}")

    if not file_ids:
        st.warning("No files were successfully ingested.")
        return False

    # 2. Generate LLM answers for this module
    try:
        ans_r = API_SESSION.post(
            f"{BACKEND_URL}/generation/key-answers",
            json={"module": module, "file_ids": file_ids},
            timeout=TIMEOUT_LLM_GENERATION,
        )
        ans_r.raise_for_status()
        st.session_state.key_question_answers[module] = ans_r.json().get("answers", [])
    except Exception as e:
        st.warning(f"Files ingested, but answer generation failed: {e}")

    return True


def _ingest_only(module: str, uploaded_files) -> bool:
    """
    Ingest new files on a slide page (no answer regeneration).
    Replaces the current module's file_ids.
    Returns True on success.
    """
    resp = API_SESSION.post(
        f"{BACKEND_URL}/retriever/ingest",
        files=[("files", (f.name, f.getvalue())) for f in uploaded_files],
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
    """Module home page: hero header, Q&A panel, file upload panel."""

    icon = MODULE_ICONS.get(module, "📋")
    desc = MODULE_DESC.get(module, "")
    n_slides = len(slides)
    n_filled = sum(1 for s in slides if s["idx"] in st.session_state.filled_slides)
    answers = st.session_state.key_question_answers.get(module, [])
    has_answers = bool(answers)

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
        .kq-wrap {{ margin-bottom: 1rem; }}
        .kq-card {{
            background: #f8f9ff; border: 1px solid #e2e6f3; border-radius: 12px;
            padding: 1rem 1.2rem; margin-bottom: 0.75rem;
        }}
        .kq-card.answered {{ background: #f0faf4; border-color: #b7dfc8; }}
        .kq-header {{ display: flex; align-items: flex-start; gap: 0.6rem; margin-bottom: 0; }}
        .kq-num {{
            flex-shrink: 0; background: #1a1a2e; color: white; border-radius: 50%;
            width: 24px; height: 24px; text-align: center; line-height: 24px;
            font-size: 0.75rem; font-weight: 700;
        }}
        .kq-num.done {{ background: #1a7a4a; }}
        .kq-text  {{ font-size: 0.95rem; color: #2c2c4a; line-height: 1.5; font-weight: 600; }}
        .kq-answer {{
            margin-top: 0.6rem; padding-top: 0.6rem;
            border-top: 1px solid #d0e8d8;
            font-size: 0.9rem; color: #2a4a35; line-height: 1.6;
        }}
        .file-panel {{
            background: #fafafa; border: 1px solid #e8e8f0; border-radius: 14px;
            padding: 1.4rem 1.4rem 1rem;
        }}
        .step-label {{
            font-size: 0.75rem; font-weight: 700; text-transform: uppercase;
            letter-spacing: 1px; color: #888; margin-bottom: 0.3rem;
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

    # ── Two-column body ────────────────────────────────────────────────────
    col_q, col_f = st.columns([3, 2], gap="large")

    # ── Left: Key Questions + LLM Answers ─────────────────────────────────
    with col_q:
        st.markdown("#### 🔑 Key Business Questions")

        if not has_answers:
            st.caption(
                "Upload your support documents on the right and click **Ingest & Analyze** "
                "— the AI will answer each question based on your files."
            )

        questions = fetch_key_questions(module)
        answer_map = {item.get("question", ""): item.get("answer", "") for item in answers}

        if questions:
            cards_html = '<div class="kq-wrap">'
            for i, q in enumerate(questions, 1):
                import html as _html
                ans_text = answer_map.get(q, "")
                answered = bool(
                    ans_text and ans_text != "Insufficient evidence in uploaded documents."
                )
                card_cls = "kq-card answered" if answered else "kq-card"
                num_cls = "kq-num done" if answered else "kq-num"
                answer_part = (
                    f'<div class="kq-answer">💡 {_html.escape(ans_text)}</div>'
                    if ans_text
                    else ""
                )
                cards_html += (
                    f'<div class="{card_cls}">'
                    f'<div class="kq-header">'
                    f'<span class="{num_cls}">{i}</span>'
                    f'<span class="kq-text">{_html.escape(q)}</span>'
                    f"</div>"
                    f"{answer_part}"
                    f"</div>"
                )
            cards_html += "</div>"
            st.markdown(cards_html, unsafe_allow_html=True)
        else:
            st.caption("(Could not load questions — is the backend running?)")

    # ── Right: File upload + analyze ──────────────────────────────────────
    with col_f:
        st.markdown("#### 📂 Support Files")

        module_fids = _module_file_ids(module)

        # Status badge
        if module_fids:
            status_label = (
                f"✅ {len(module_fids)} file(s) ingested"
                + (" · answers ready" if has_answers else " · answers not yet generated")
            )
            st.success(status_label)

        uploaded = st.file_uploader(
            "Upload .pptx or .docx support documents",
            type=["pptx", "docx", "doc"],
            accept_multiple_files=True,
            key=f"uploader_{module}",
            help="Files are scoped to this module and will not affect other modules.",
        )

        if uploaded:
            btn_label = f"Ingest & Analyze ({len(uploaded)} file{'s' if len(uploaded) > 1 else ''})"
            if st.button(
                btn_label,
                type="primary",
                use_container_width=True,
                key=f"ingest_{module}",
            ):
                with st.spinner(
                    "Step 1/2 — Ingesting files…  \n"
                    "Step 2/2 — AI is answering key questions…"
                ):
                    ok = _ingest_and_answer(module, uploaded)
                if ok:
                    _rerun_in_module(module)

        # Re-generate answers without re-uploading
        elif module_fids and not has_answers:
            st.caption("Files already ingested. Generate answers:")
            if st.button(
                "Generate Key Question Answers",
                use_container_width=True,
                key=f"regen_answers_{module}",
            ):
                with st.spinner("AI is answering key questions from uploaded documents…"):
                    try:
                        ans_r = API_SESSION.post(
                            f"{BACKEND_URL}/generation/key-answers",
                            json={"module": module, "file_ids": module_fids},
                            timeout=TIMEOUT_LLM_GENERATION,
                        )
                        ans_r.raise_for_status()
                        st.session_state.key_question_answers[module] = (
                            ans_r.json().get("answers", [])
                        )
                        _rerun_in_module(module)
                    except Exception as e:
                        st.error(f"Failed: {e}")

        # Navigate to slides
        if n_slides:
            st.divider()
            ready = bool(module_fids)
            if not ready:
                st.caption("⬆ Ingest support files before filling slides.")
            if st.button(
                "Start filling slides →",
                type="primary" if ready else "secondary",
                use_container_width=True,
                key=f"goto_slides_{module}",
                disabled=not ready,
            ):
                st.session_state.current_page_by_module[module] = 1
                _rerun_in_module(module)


# ─────────────────────────────────────────────────────────────────────────────
# Slide page  (page index = 1..N)
# ─────────────────────────────────────────────────────────────────────────────

def render_slide_content(slide_meta: dict):
    slide_idx = slide_meta["idx"]
    filled = slide_idx in st.session_state.filled_slides
    table_structure = slide_meta.get("table_structure", {})
    row_labels = table_structure.get("indexes", [])
    template_col_names = table_structure.get("columns", [])[1:]  # skip corner cell

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
    slide_idx = slide_meta["idx"]
    module_fids = _module_file_ids(module)

    # ── Support files (compact, for slide page) ────────────────────────────
    with st.expander(
        f"📂 Support Files — {len(module_fids)} ingested" if module_fids else "📂 Support Files (none)",
        expanded=not bool(module_fids),
    ):
        new_files = st.file_uploader(
            "Replace / add files for this module",
            type=["pptx", "docx", "doc"],
            accept_multiple_files=True,
            key=f"slide_uploader_{slide_idx}",
            help="Uploading new files replaces the current set for this module only.",
        )
        if new_files:
            if st.button(
                f"Ingest {len(new_files)} file{'s' if len(new_files) > 1 else ''}",
                use_container_width=True,
                key=f"slide_ingest_{slide_idx}",
            ):
                with st.spinner("Ingesting files…"):
                    ok = _ingest_only(module, new_files)
                if ok:
                    st.success(
                        f"Ingested {len(st.session_state.file_ids_by_module[module])} file(s). "
                        "Re-fill the slide to use the new documents."
                    )
                    _rerun_in_module(module)

    st.divider()

    # ── Fill Slide ─────────────────────────────────────────────────────────
    if st.button(
        "Fill Slide Template",
        type="primary",
        use_container_width=True,
        key=f"fill_{slide_idx}",
    ):
        if not module_fids:
            st.warning("No files ingested for this module yet. Upload files above.")
        else:
            table_structure = slide_meta.get("table_structure")
            if not table_structure:
                with st.spinner("Fetching table structure..."):
                    try:
                        r = API_SESSION.post(
                            f"{BACKEND_URL}/fill-engine/table-structure",
                            data={"slide_idx": slide_idx, "path": TEMPLATE_PATH},
                            timeout=TIMEOUT_QUICK,
                        )
                        r.raise_for_status()
                        table_structure = r.json()
                    except Exception as e:
                        st.error(f"Table structure error: {e}")

            if table_structure:
                with st.spinner("Generating content…"):
                    try:
                        fill_resp = API_SESSION.post(
                            f"{BACKEND_URL}/generation/fill",
                            json={
                                "slide_idx": slide_idx,
                                "module": module,
                                "file_ids": module_fids,
                                "table_structure": table_structure,
                            },
                            timeout=TIMEOUT_LLM_GENERATION,
                        )
                        fill_resp.raise_for_status()
                        fill_result = fill_resp.json()
                        table_data = fill_result.get("table_data", [])
                        column_headers = fill_result.get("column_headers")  # list[str] | None
                    except Exception as e:
                        st.error(f"Generation error: {e}")
                        table_data = []
                        column_headers = None

                if column_headers:
                    st.info(f"Segments identified: {', '.join(column_headers)}")

                if table_data and st.session_state.pptx_bytes:
                    try:
                        form_data: dict = {
                            "slide_idx": slide_idx,
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
                        # Cache headers so the chat refinement flow can show them
                        if column_headers:
                            st.session_state.setdefault("column_headers_by_slide", {})[
                                slide_idx
                            ] = column_headers
                        st.success("Slide filled!")
                        _rerun_in_module(module)
                    except Exception as e:
                        st.error(f"Fill error: {e}")

    st.divider()

    # ── Agent Chat ─────────────────────────────────────────────────────────
    st.subheader("Refine with AI")
    user_msg = st.text_area(
        "Describe adjustments (e.g., make Segment 1 more concise)",
        key=f"chat_input_{slide_idx}",
    )
    if st.button("Apply Feedback", key=f"apply_{slide_idx}") and user_msg:
        table_structure = slide_meta.get("table_structure")
        current_data = st.session_state.table_data_by_slide.get(slide_idx)
        if not table_structure or not current_data:
            st.warning("Fill the slide first before refining.")
        else:
            with st.spinner("Applying feedback..."):
                try:
                    r = API_SESSION.post(
                        f"{BACKEND_URL}/generation/chat",
                        json={
                            "slide_idx": slide_idx,
                            "module": module,
                            "current_content": current_data,
                            "table_structure": table_structure,
                            "user_message": user_msg,
                        },
                        timeout=TIMEOUT_LLM_GENERATION,
                    )
                    r.raise_for_status()
                    updated = r.json().get("table_data", [])
                    if updated and st.session_state.pptx_bytes:
                        fill_r = API_SESSION.post(
                            f"{BACKEND_URL}/fill-engine/fill-table",
                            data={
                                "slide_idx": slide_idx,
                                "table_data_b64": base64.b64encode(
                                    json.dumps(updated).encode()
                                ).decode(),
                            },
                            files={"file": ("deck.pptx", st.session_state.pptx_bytes)},
                            timeout=TIMEOUT_FILL_TABLE,
                        )
                        fill_r.raise_for_status()
                        st.session_state.pptx_bytes = base64.b64decode(
                            fill_r.json()["pptx_base64"]
                        )
                        st.session_state.table_data_by_slide[slide_idx] = updated
                        st.success("Feedback applied!")
                        _rerun_in_module(module)
                except Exception as e:
                    st.error(f"Feedback failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Module tab  (landing page + N slide pages)
# ─────────────────────────────────────────────────────────────────────────────

def render_module_tab(module: str, slides: list):
    """
    Page layout within a module tab:
      page 0          → Landing page (key questions + file upload)
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
            disabled=cur == 0,
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
            disabled=cur == total_pages - 1,
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

        # Slide page header
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

        col_slide, col_ctrl = st.columns([3, 1])
        with col_slide:
            render_slide_content(slide_meta)
        with col_ctrl:
            render_controls_panel(slide_meta, module)

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

    # ── Welcome page ───────────────────────────────────────────────────────
    if not st.session_state.started:
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
                GenAI-powered business plan slide filling. Answer key business questions,
                upload support documents, and let AI populate every module of your deck.
            </div>
            <div class="if-modules">
                <div class="if-mod-card"><div class="ic">👥</div><div class="lb">Customer Segmentation</div></div>
                <div class="if-mod-card"><div class="ic">💬</div><div class="lb">Messaging Strategy</div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _, col, _ = st.columns([1, 1, 1])
        with col:
            if st.button("Start", type="primary", use_container_width=True):
                st.session_state.started = True
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
        if st.button("Restart"):
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
    if n_total > 0 and n_filled == n_total and st.session_state.pptx_bytes:
        st.balloons()
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
