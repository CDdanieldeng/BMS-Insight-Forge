"""FastAPI router for voice input (ASR) via DashScope realtime API."""

import base64
import json
import logging
import queue
import threading

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .dashscope_asr_client import transcribe_wav_bytes

logger = logging.getLogger("voice")

router = APIRouter(prefix="/voice", tags=["voice"])


class TranscribeRequest(BaseModel):
    """Request body for REST transcribe endpoint."""

    audio_b64: str = Field(..., description="Base64-encoded WAV audio bytes")
    language: str = Field("en", description="Language code (en, zh, etc.)")


class TranscribeResponse(BaseModel):
    transcript: str
    is_final: bool = True


def _transcribe_with_streaming(wav_bytes: bytes, language: str = "en"):
    """
    Generator that yields SSE events for partial and final transcripts.
    Queue items: ("partial", str) | ("final_segment", str) | ("done", full_result)
    """
    q: queue.Queue[tuple[str | None, str | None]] = queue.Queue()
    result_holder: list[str] = []

    def on_partial(t: str):
        if t:
            q.put(("partial", t))

    def on_final(t: str):
        if t:
            q.put(("final_segment", t))

    def run_transcribe():
        try:
            full = transcribe_wav_bytes(
                wav_bytes,
                language=language,
                on_partial=on_partial,
                on_final=on_final,
            )
            q.put(("done", full))
        except Exception as e:
            logger.exception("ASR transcription error: %s", e)
            q.put(("done", str(e)))
        finally:
            q.put((None, None))  # Sentinel to stop generator

    thread = threading.Thread(target=run_transcribe, daemon=True)
    thread.start()

    final_transcript = ""
    while True:
        try:
            kind, payload = q.get(timeout=60)
        except queue.Empty:
            break
        if kind is None:
            break
        if kind == "partial":
            yield f"data: {json.dumps({'type': 'partial', 'transcript': payload})}\n\n"
        elif kind == "final_segment":
            yield f"data: {json.dumps({'type': 'final_segment', 'transcript': payload})}\n\n"
            final_transcript = (final_transcript + " " + payload).strip()
        elif kind == "done":
            final_transcript = payload or final_transcript
            yield f"data: {json.dumps({'type': 'final', 'transcript': final_transcript})}\n\n"
            break


@router.post("/transcribe", response_model=TranscribeResponse)
def transcribe(req: TranscribeRequest):
    """Transcribe WAV audio (base64) and return final transcript."""
    try:
        wav_bytes = base64.b64decode(req.audio_b64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {e}")

    if not wav_bytes:
        raise HTTPException(status_code=400, detail="Empty audio data")

    try:
        transcript = transcribe_wav_bytes(wav_bytes, language=req.language)
        return TranscribeResponse(transcript=transcript, is_final=True)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Transcribe error: %s", e)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")


@router.post("/transcribe/stream")
def transcribe_stream(req: TranscribeRequest):
    """
    Transcribe WAV audio and stream partial + final results via Server-Sent Events.
    Frontend can consume the stream to show live transcription in the chatbox.
    """
    try:
        wav_bytes = base64.b64decode(req.audio_b64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {e}")

    if not wav_bytes:
        raise HTTPException(status_code=400, detail="Empty audio data")

    def gen():
        for chunk in _transcribe_with_streaming(wav_bytes, req.language):
            yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/transcribe/upload", response_model=TranscribeResponse)
async def transcribe_upload(
    file: UploadFile,
    language: str = "en",
):
    """Transcribe uploaded WAV file (e.g. from multipart form)."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        transcript = transcribe_wav_bytes(content, language=language)
        return TranscribeResponse(transcript=transcript, is_final=True)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Transcribe upload error: %s", e)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
