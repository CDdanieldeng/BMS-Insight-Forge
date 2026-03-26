"""
DashScope Qwen ASR Realtime client — uses official dashscope SDK for speech-to-text.

Connects via dashscope.audio.qwen_omni to wss://dashscope.aliyuncs.com/api-ws/v1/realtime
and transcribes PCM 16kHz mono audio. Supports partial and final results via callbacks.
"""

import base64
import io
import logging
import os
import time

import dashscope
from websocket import WebSocketConnectionClosedException

logger = logging.getLogger(__name__)

# API key: support DASHSCOPE_API_KEY or QWEN_API_KEY for compatibility
API_KEY = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
QWEN_MODEL = os.environ.get("QWEN_ASR_MODEL", "qwen3-asr-flash-realtime")
ASR_DEBUG = os.environ.get("ASR_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
# Beijing region; use wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime for Singapore
BASE_URL = os.environ.get("DASHSCOPE_REALTIME_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
CHUNK_SIZE = 3200
CHUNK_DELAY_FACTOR = float(os.environ.get("ASR_CHUNK_DELAY_FACTOR", "1.0"))
END_SESSION_WAIT_SECONDS = float(os.environ.get("ASR_END_SESSION_WAIT_SECONDS", "3.0"))
SESSION_READY_WAIT_SECONDS = float(os.environ.get("ASR_SESSION_READY_WAIT_SECONDS", "2.0"))


def _debug(msg: str, *args):
    """Best-effort ASR debug output even when logger isn't configured."""
    if not ASR_DEBUG:
        return
    try:
        text = msg % args if args else msg
    except Exception:
        text = f"{msg} {args}"
    print(f"[ASR_DEBUG] {text}", flush=True)


def _init_api_key():
    """Initialize DashScope API key."""
    dashscope.api_key = API_KEY or "YOUR_API_KEY"
    if dashscope.api_key == "YOUR_API_KEY":
        logger.warning(
            "DASHSCOPE_API_KEY not set. Set DASHSCOPE_API_KEY or QWEN_API_KEY environment variable."
        )


class _ASRCallback:
    """
    Callback handler for DashScope OmniRealtime ASR events.
    Collects partial (stash) and final (transcript) results and invokes user callbacks.
    """

    def __init__(self, on_partial=None, on_final=None, final_transcript=None):
        self.on_partial = on_partial
        self.on_final = on_final
        self.final_transcript = final_transcript or []
        self.last_partial = ""
        self.close_reason: str | None = None
        self.session_ready = False
        self.session_finished = False
        self.handlers = {
            "session.created": self._handle_session_created,
            "session.updated": self._handle_session_updated,
            "session.finished": self._handle_session_finished,
            "conversation.item.input_audio_transcription.completed": self._handle_final_text,
            "conversation.item.input_audio_transcription.text": self._handle_stash_text,
        }

    def on_open(self):
        logger.debug("ASR connection opened")

    def on_close(self, code, msg):
        # WebSocket close frame: optionally 2-byte code + UTF-8 reason. Extract readable text.
        if isinstance(msg, bytes) and len(msg) > 2:
            msg = msg[2:].decode("utf-8", errors="replace")  # skip close code
        raw = msg if isinstance(msg, str) else (msg.decode("utf-8", errors="replace") if msg else None)
        if raw:
            raw = "".join(c for c in raw if c.isprintable() or c in " \t").strip()
        self.close_reason = raw or (f"code={code}" if code else "Connection closed by server")
        logger.debug("ASR connection closed: code=%s reason=%s", code, self.close_reason)

    def on_event(self, response):
        try:
            event_type = response.get("type")
            handler = self.handlers.get(event_type)
            if handler:
                handler(response)
            elif ASR_DEBUG:
                _debug("ASR unhandled event: %s", event_type)
        except Exception as e:
            logger.warning("ASR callback error: %s", e)

    def _handle_session_created(self, response):
        logger.debug("ASR session started: %s", response.get("session", {}).get("id", ""))

    def _handle_session_updated(self, response):
        self.session_ready = True
        if ASR_DEBUG:
            _debug("ASR session updated event received (ready for audio)")

    def _handle_session_finished(self, response):
        self.session_finished = True
        if ASR_DEBUG:
            _debug("ASR session finished event received")

    def _handle_final_text(self, response):
        transcript = response.get("transcript", "")
        if transcript:
            self.final_transcript.append(transcript)
            if self.on_final:
                self.on_final(transcript)
            logger.debug("ASR final: %s", transcript)

    def _handle_stash_text(self, response):
        stash = response.get("stash", "")
        if stash:
            self.last_partial = stash
            if self.on_partial:
                self.on_partial(stash)
            logger.debug("ASR partial: %s", stash)


def _read_audio_chunks(pcm_bytes: bytes, chunk_size: int = CHUNK_SIZE):
    """Yield PCM audio in chunks."""
    offset = 0
    while offset < len(pcm_bytes):
        chunk = pcm_bytes[offset : offset + chunk_size]
        if chunk:
            yield chunk
        offset += chunk_size


def transcribe_audio_stream(
    pcm_bytes: bytes,
    *,
    sample_rate: int = 16000,
    sample_width_bytes: int = 2,
    language: str = "en",
    enable_vad: bool = True,
    on_partial=None,
    on_final=None,
) -> str:
    """
    Send PCM audio to DashScope ASR via official SDK and collect transcription.

    Args:
        pcm_bytes: Raw PCM 16-bit mono audio.
        sample_rate: Must be 16000 (DashScope requirement).
        language: Language code, e.g. "en" or "zh".
        enable_vad: Use server-side voice activity detection.
        on_partial: Optional callback(transcript: str) for partial results.
        on_final: Optional callback(transcript: str) for final results.

    Returns:
        Final transcript string.
    """
    if not API_KEY:
        raise ValueError("DASHSCOPE_API_KEY or QWEN_API_KEY environment variable is not set.")

    _init_api_key()

    final_transcript: list[str] = []
    if ASR_DEBUG:
        bytes_per_second = sample_rate * max(sample_width_bytes, 1)
        approx_seconds = len(pcm_bytes) / float(bytes_per_second) if bytes_per_second > 0 else 0.0
        _debug(
            "ASR request: model=%s language=%s sample_rate=%s sample_width=%s bytes=%s approx_duration=%.2fs",
            QWEN_MODEL,
            language,
            sample_rate,
            sample_width_bytes,
            len(pcm_bytes),
            approx_seconds,
        )
    callback = _ASRCallback(
        on_partial=on_partial,
        on_final=on_final,
        final_transcript=final_transcript,
    )

    try:
        from dashscope.audio.qwen_omni import OmniRealtimeConversation, OmniRealtimeCallback
        from dashscope.audio.qwen_omni.omni_realtime import TranscriptionParams
        from dashscope.audio.qwen_omni import MultiModality
    except ImportError as e:
        raise ImportError(
            "dashscope SDK with qwen_omni is required. Install with: pip install dashscope>=1.23.9"
        ) from e

    class _CallbackImpl(OmniRealtimeCallback):
        def __init__(self, inner: _ASRCallback):
            self._inner = inner

        def on_open(self):
            self._inner.on_open()

        def on_close(self, code, msg):
            self._inner.on_close(code, msg)

        def on_event(self, response):
            self._inner.on_event(response)

    callback_impl = _CallbackImpl(callback)
    conversation = OmniRealtimeConversation(
        model=QWEN_MODEL,
        url=BASE_URL,
        callback=callback_impl,
    )

    conversation.connect()

    transcription_params = TranscriptionParams(
        language=language,
        sample_rate=sample_rate,
        input_audio_format="pcm",
    )

    conversation.update_session(
        output_modalities=[MultiModality.TEXT],
        enable_input_audio_transcription=True,
        transcription_params=transcription_params,
    )

    try:
        # Wait for session.updated before sending audio; otherwise early chunks can be dropped.
        ready_deadline = time.time() + max(0.2, SESSION_READY_WAIT_SECONDS)
        while time.time() < ready_deadline and not callback.session_ready:
            if callback.close_reason:
                raise ValueError(
                    f"ASR connection closed: {callback.close_reason}. "
                    "Check DASHSCOPE_API_KEY permissions and region (Beijing URL vs Singapore)."
                )
            time.sleep(0.05)
        if ASR_DEBUG and not callback.session_ready:
            _debug(
                "ASR warning: no session.updated within %.2fs; streaming anyway.",
                max(0.2, SESSION_READY_WAIT_SECONDS),
            )

        for chunk in _read_audio_chunks(pcm_bytes):
            if callback.close_reason:
                raise ValueError(
                    f"ASR connection closed: {callback.close_reason}. "
                    "Check DASHSCOPE_API_KEY permissions and region (Beijing URL vs Singapore)."
                )
            audio_b64 = base64.b64encode(chunk).decode("ascii")
            conversation.append_audio(audio_b64)
            # Pace chunks close to realtime; sending too fast can truncate tail transcription.
            chunk_seconds = len(chunk) / float(sample_rate * max(sample_width_bytes, 1))
            time.sleep(max(0.01, chunk_seconds * max(0.1, CHUNK_DELAY_FACTOR)))
        conversation.end_session()
        # Give server time to flush trailing transcription events after end_session.
        wait_deadline = time.time() + max(0.5, END_SESSION_WAIT_SECONDS)
        while time.time() < wait_deadline and not callback.session_finished:
            time.sleep(0.1)
    except WebSocketConnectionClosedException as e:
        reason = callback.close_reason or "Connection closed by server"
        hint = (
            "Model access denied - ensure your API key has ASR model access. "
            "Singapore region: set DASHSCOPE_REALTIME_URL=wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime"
        )
        raise ValueError(f"ASR {reason}. {hint}") from e
    except Exception as e:
        logger.exception("ASR error: %s", e)
        raise
    finally:
        time.sleep(0.2)
        conversation.close()

    result = " ".join(final_transcript).strip()
    if not result and callback.last_partial:
        result = callback.last_partial.strip()
    return result


def transcribe_wav_bytes(wav_bytes: bytes, **kwargs) -> str:
    """
    Transcribe audio bytes (WAV, WebM/Opus, etc.). Converts to PCM 16kHz if needed.

    Browser MediaRecorder typically outputs WebM/Opus (not always WAV). Uses
    from_file() so pydub can auto-detect format.

    Args:
        wav_bytes: Audio file bytes (WAV, WebM, etc. from mic recorder).
        **kwargs: Passed to transcribe_audio_stream (language, on_partial, on_final, etc.).

    Returns:
        Final transcript string.
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        raise ImportError("pydub is required for audio conversion. pip install pydub")

    audio = AudioSegment.from_file(io.BytesIO(wav_bytes))
    if ASR_DEBUG:
        _debug(
            "ASR input audio: bytes=%s duration=%.2fs frame_rate=%s channels=%s sample_width=%s dBFS=%.2f rms=%s",
            len(wav_bytes),
            getattr(audio, "duration_seconds", 0.0),
            audio.frame_rate,
            audio.channels,
            audio.sample_width,
            audio.dBFS,
            audio.rms,
        )
    if audio.frame_rate != 16000 or audio.channels != 1 or audio.sample_width != 2:
        # DashScope expects linear PCM; force 16kHz mono 16-bit LE.
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    if ASR_DEBUG:
        _debug(
            "ASR normalized audio: duration=%.2fs frame_rate=%s channels=%s sample_width=%s dBFS=%.2f rms=%s",
            getattr(audio, "duration_seconds", 0.0),
            audio.frame_rate,
            audio.channels,
            audio.sample_width,
            audio.dBFS,
            audio.rms,
        )
        if getattr(audio, "duration_seconds", 0.0) < 1.0:
            _debug("ASR warning: short audio duration (%.2fs), consider speaking longer.", audio.duration_seconds)
        if audio.dBFS < -35:
            _debug("ASR warning: low input volume (dBFS=%.2f), consider increasing mic gain.", audio.dBFS)
    pcm = audio.raw_data
    return transcribe_audio_stream(
        pcm,
        sample_rate=16000,
        sample_width_bytes=audio.sample_width,
        **kwargs,
    )
