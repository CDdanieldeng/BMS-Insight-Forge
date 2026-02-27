"""Insight Forge - Streamlit frontend for GenAI-powered business plan slide filling."""

import base64
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv

import requests

# Load .env from project root (parent of frontend/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
import streamlit as st
from st_pptx_viewer import pptx_viewer, PptxViewerConfig

# Use a dedicated session for local backend calls.
# This avoids accidental routing through corporate/system HTTP proxies.
API_SESSION = requests.Session()
API_SESSION.trust_env = False

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
# Template path: backend resolves this when we call slide-info/table-structure.
# Docker: /app/example_files/example slides.pptx. Local: set via env or use default.
TEMPLATE_PATH = os.getenv(
    "TEMPLATE_PPTX_PATH",
    "/app/example_files/example slides.pptx",
)
# Resolve to absolute path so backend (which may run from backend/) can find it
_template_candidate = Path(TEMPLATE_PATH)
if not _template_candidate.is_absolute() or not _template_candidate.exists():
    _local = Path(__file__).resolve().parent.parent / "example_files" / "example slides.pptx"
    if _local.exists():
        TEMPLATE_PATH = str(_local.resolve())
elif _template_candidate.exists():
    TEMPLATE_PATH = str(_template_candidate.resolve())


def init_session_state():
    """Initialize session state."""
    if "started" not in st.session_state:
        st.session_state.started = False
    if "slide_info" not in st.session_state:
        st.session_state.slide_info = []
    if "fillable_indices" not in st.session_state:
        st.session_state.fillable_indices = []
    if "current_fillable_idx" not in st.session_state:
        st.session_state.current_fillable_idx = 0
    if "pptx_bytes" not in st.session_state:
        st.session_state.pptx_bytes = None
    if "file_ids" not in st.session_state:
        st.session_state.file_ids = []
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = {}
    if "filled_slides" not in st.session_state:
        st.session_state.filled_slides = set()
    if "table_data_by_slide" not in st.session_state:
        st.session_state.table_data_by_slide = {}
    if "slide_png_cache" not in st.session_state:
        st.session_state.slide_png_cache = {}
    if "key_question_answers" not in st.session_state:
        st.session_state.key_question_answers = {}


def load_slide_info():
    """Fetch slide info from backend."""
    try:
        resp = API_SESSION.post(
            f"{BACKEND_URL}/fill-engine/slide-info-from-path",
            data={"path": TEMPLATE_PATH},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Failed to load template: {e}")
        return []


def load_template_bytes() -> bytes | None:
    """Load template pptx bytes."""
    path = Path(TEMPLATE_PATH)
    if path.exists():
        return path.read_bytes()
    return None


def fetch_slide_png(
    slide_idx: int,
    pptx_bytes: bytes | None = None,
    path: str | None = None,
) -> bytes | None:
    """
    Fetch slide PNG from backend renderer.
    Uses in-memory pptx if provided; otherwise backend reads from template path.
    """
    try:
        data = {"slide_idx": str(slide_idx)}
        files = None
        if pptx_bytes:
            files = {"file": ("deck.pptx", pptx_bytes)}
        else:
            data["path"] = path or TEMPLATE_PATH
        resp = API_SESSION.post(
            f"{BACKEND_URL}/fill-engine/render-slide-png",
            data=data,
            files=files,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.content
    except Exception:
        return None


def main():
    st.set_page_config(
        page_title="Insight Forge",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    init_session_state()

    # Welcome page
    if not st.session_state.started:
        st.markdown(
            """
            <style>
            @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600&family=Source+Sans+3:wght@400;600&display=swap');
            .title { font-family: 'Playfair Display', serif; font-size: 3.5rem; font-weight: 600; text-align: center; margin: 2rem 0; color: #1a1a2e; }
            .desc { font-family: 'Source Sans 3', sans-serif; font-size: 1.2rem; text-align: center; color: #4a4a6a; max-width: 600px; margin: 0 auto 2rem; line-height: 1.6; }
            .center { display: flex; justify-content: center; align-items: center; min-height: 40vh; }
            </style>
            <div class="title">Insight Forge</div>
            <div class="desc">Use GenAI to fill your business plan slide deck. Upload support documents, answer key business questions, and let AI populate Customer Segmentation and Messaging Strategy modules.</div>
            """,
            unsafe_allow_html=True,
        )
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("Start", type="primary", use_container_width=True):
                st.session_state.started = True
                st.session_state.slide_info = load_slide_info()
                st.session_state.fillable_indices = [
                    s["idx"] for s in st.session_state.slide_info if s.get("is_fillable")
                ]
                st.session_state.pptx_bytes = load_template_bytes()
                st.rerun()
        return

    # Main flow
    slide_info = st.session_state.slide_info
    fillable_indices = st.session_state.fillable_indices
    if not fillable_indices:
        st.warning("No fillable slides found in template.")
        return

    current_idx = st.session_state.current_fillable_idx
    slide_idx = fillable_indices[current_idx]
    slide_meta = next((s for s in slide_info if s["idx"] == slide_idx), {})
    module = slide_meta.get("module", "Unknown")

    # Progress bar
    total = len(fillable_indices)
    progress = (current_idx + 1) / total
    st.progress(progress, text=f"Slide {current_idx + 1} of {total}")

    # Layout: 3/4 slide, 1/4 controls
    col_slide, col_ctrl = st.columns([3, 1])

    with col_slide:
        pptx_bytes = st.session_state.pptx_bytes
        if pptx_bytes:
            deck_hash = hashlib.sha1(pptx_bytes).hexdigest()[:12]
            cache_key = f"{slide_idx}:{deck_hash}"
            png_cache = st.session_state.slide_png_cache
            slide_png = png_cache.get(cache_key)
            if slide_png is None:
                slide_png = fetch_slide_png(slide_idx=slide_idx, pptx_bytes=pptx_bytes)
                if slide_png:
                    png_cache.clear()
                    png_cache[cache_key] = slide_png

            if slide_png:
                st.image(slide_png, use_container_width=True)
            else:
                st.caption("PNG render unavailable, fallback to PPTX viewer.")
                config = PptxViewerConfig(
                    width=900,
                    initial_slide=slide_idx,
                    show_toolbar=True,
                    show_slide_counter=True,
                    enable_keyboard=True,
                )
                pptx_viewer(pptx_bytes, config=config, key=f"viewer_{slide_idx}")

    with col_ctrl:
        st.subheader("Support Files")
        uploaded = st.file_uploader(
            "Upload pptx or docx",
            type=["pptx", "docx", "doc"],
            accept_multiple_files=True,
        )

        if uploaded:
            if st.button("Ingest Files"):
                with st.spinner("Ingesting..."):
                    resp = API_SESSION.post(
                        f"{BACKEND_URL}/retriever/ingest",
                        files=[("files", (f.name, f.getvalue())) for f in uploaded],
                        timeout=30,
                    )
                    if resp.ok:
                        data = resp.json()
                        st.session_state.file_ids = data.get("file_ids", [])
                        st.session_state.key_question_answers = {}
                        st.success(f"Ingested {len(st.session_state.file_ids)} file(s)")
                        errors = data.get("errors", [])
                        if errors:
                            for err in errors:
                                file_name = err.get("file", "unknown")
                                message = err.get("error", "unknown error")
                                st.warning(f"Ingest failed for {file_name}: {message}")
                    else:
                        st.error(resp.text)

        st.subheader("Key Questions")
        try:
            r = API_SESSION.get(f"{BACKEND_URL}/generation/key-questions/{module}", timeout=5)
            if r.ok:
                questions = r.json().get("questions", [])
                for i, q in enumerate(questions, 1):
                    st.caption(f"{i}. {q}")

                if st.session_state.file_ids:
                    if st.button("Generate Key Question Answers", use_container_width=True):
                        with st.spinner("Generating answers..."):
                            try:
                                ans_r = API_SESSION.post(
                                    f"{BACKEND_URL}/generation/key-answers",
                                    json={
                                        "module": module,
                                        "file_ids": st.session_state.file_ids,
                                    },
                                    timeout=90,
                                )
                                ans_r.raise_for_status()
                                st.session_state.key_question_answers[module] = ans_r.json().get("answers", [])
                            except Exception as e:
                                st.error(f"Failed to generate answers: {e}")

                    answers = st.session_state.key_question_answers.get(module, [])
                    if answers:
                        st.markdown("**LLM Answers**")
                        for idx, item in enumerate(answers, 1):
                            q = item.get("question", "")
                            a = item.get("answer", "")
                            with st.expander(f"Q{idx}: {q[:90]}"):
                                st.write(a)
                else:
                    st.caption("Ingest support files to generate LLM answers.")
            else:
                st.caption("(Unable to load)")
        except Exception:
            st.caption("(Backend unavailable)")

        if st.button("Fill Slide Template", type="primary", use_container_width=True):
            if not st.session_state.file_ids:
                st.warning("Upload and ingest support files first.")
            else:
                table_structure = slide_meta.get("table_structure")
                if not table_structure:
                    with st.spinner("Getting table structure..."):
                        try:
                            r = API_SESSION.post(
                                f"{BACKEND_URL}/fill-engine/table-structure",
                                data={"slide_idx": slide_idx, "path": TEMPLATE_PATH},
                                timeout=10,
                            )
                            r.raise_for_status()
                            table_structure = r.json()
                        except Exception as e:
                            st.error(f"Table structure: {e}")
                            table_structure = None

                if table_structure:
                    with st.spinner("Generating content..."):
                        try:
                            fill_resp = API_SESSION.post(
                                f"{BACKEND_URL}/generation/fill",
                                json={
                                    "slide_idx": slide_idx,
                                    "module": module,
                                    "file_ids": st.session_state.file_ids,
                                    "table_structure": table_structure,
                                },
                                timeout=60,
                            )
                            fill_resp.raise_for_status()
                            table_data = fill_resp.json().get("table_data", [])
                        except Exception as e:
                            st.error(f"Generation: {e}")
                            table_data = []

                    if table_data and st.session_state.pptx_bytes:
                        try:
                            fill_r = API_SESSION.post(
                                f"{BACKEND_URL}/fill-engine/fill-table",
                                data={
                                    "slide_idx": slide_idx,
                                    "table_data_b64": base64.b64encode(
                                        json.dumps(table_data).encode()
                                    ).decode(),
                                },
                                files={"file": ("deck.pptx", st.session_state.pptx_bytes)},
                                timeout=30,
                            )
                            fill_r.raise_for_status()
                            new_bytes = base64.b64decode(fill_r.json()["pptx_base64"])
                            st.session_state.pptx_bytes = new_bytes
                            st.session_state.filled_slides.add(slide_idx)
                            st.session_state.table_data_by_slide[slide_idx] = table_data
                            st.success("Slide filled!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fill: {e}")

        st.subheader("Agent Chat")
        user_msg = st.text_area("Adjustments (e.g., make Segment 1 more concise)")
        if st.button("Apply Feedback") and user_msg:
            table_structure = slide_meta.get("table_structure")
            current_data = st.session_state.table_data_by_slide.get(slide_idx)
            if not table_structure or not current_data:
                st.warning("Fill the slide first, then use chat to refine.")
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
                            timeout=60,
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
                                timeout=30,
                            )
                            fill_r.raise_for_status()
                            st.session_state.pptx_bytes = base64.b64decode(
                                fill_r.json()["pptx_base64"]
                            )
                            st.session_state.table_data_by_slide[slide_idx] = updated
                            st.success("Feedback applied!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Feedback failed: {e}")

        st.divider()

        # Navigation
        prev_col, next_col = st.columns(2)
        with prev_col:
            if st.button("Previous", use_container_width=True) and current_idx > 0:
                st.session_state.current_fillable_idx -= 1
                st.rerun()
        with next_col:
            if st.button("Next", use_container_width=True):
                if current_idx < total - 1:
                    st.session_state.current_fillable_idx += 1
                    st.rerun()
                else:
                    st.balloons()
                    st.success("All slides complete!")

        # Download
        if current_idx >= total - 1 and st.session_state.pptx_bytes:
            st.download_button(
                "Download Deck",
                data=st.session_state.pptx_bytes,
                file_name="insight_forge_deck.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
