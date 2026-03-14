"""
DashScope Qwen ASR Realtime client — decoupled module for speech-to-text.

Connects to wss://dashscope.aliyuncs.com/api-ws/v1/realtime
and transcribes PCM 16kHz mono audio. Supports server-side VAD.
"""

import base64
import io
import json
import logging
import os
import time

import websocket

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
QWEN_MODEL = os.environ.get("QWEN_ASR_MODEL", "qwen3-asr-flash-realtime")
BASE_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"


def transcribe_audio_stream(
    pcm_bytes: bytes,
    *,
    sample_rate: int = 16000,
    language: str = "en",
    enable_vad: bool = True,
    on_partial: callable = None,
    on_final: callable = None,
) -> str:
    """
    Send PCM audio to DashScope ASR and collect transcription via callbacks.

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

    url = f"{BASE_URL}?model={QWEN_MODEL}"
    headers = [
        f"Authorization: Bearer {API_KEY}",
        "OpenAI-Beta: realtime=v1",
    ]

    final_transcript: list[str] = []
    partial_text: list[str] = []

    def _on_open(ws):
        session = {
            "modalities": ["text"],
            "input_audio_format": "pcm",
            "sample_rate": sample_rate,
            "input_audio_transcription": {"language": language},
            "turn_detection": (
                {
                    "type": "server_vad",
                    "threshold": 0.2,
                    "silence_duration_ms": 800,
                }
                if enable_vad
                else None
            ),
        }
        event = {"event_id": "session_init", "type": "session.update", "session": session}
        ws.send(json.dumps(event))
        logger.info("Session initialized")

    def _on_message(ws, message):
        try:
            data = json.loads(message)
            event_type = data.get("type", "")
            # Partial transcription
            if "conversation.item.input_audio_transcription" in event_type and "text" in event_type:
                item = data.get("item", {})
                transcript = item.get("transcript") or item.get("stash") or ""
                if transcript:
                    partial_text.clear()
                    partial_text.append(transcript)
                    if on_partial:
                        on_partial(transcript)
            # Final transcription
            if "completed" in event_type or "conversation.item.input_audio_transcription.completed" == event_type:
                item = data.get("item", {})
                transcript = item.get("transcript", "")
                if transcript:
                    final_transcript.append(transcript)
                    if on_final:
                        on_final(transcript)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from ASR: %s", message[:200])

    def _on_error(ws, error):
        logger.error("ASR WebSocket error: %s", error)

    def _on_close(ws, code, msg):
        logger.info("ASR WebSocket closed: %s %s", code, msg)

    ws = websocket.WebSocketApp(
        url,
        header=headers,
        on_open=_on_open,
        on_message=_on_message,
        on_error=_on_error,
        on_close=_on_close,
    )

    # Run WebSocket in a thread and send audio from main thread
    import threading

    thread = threading.Thread(target=lambda: ws.run_forever())
    thread.daemon = True
    thread.start()

    # Wait for session init before sending audio
    time.sleep(0.5)

    # Send audio in chunks (3200 bytes ≈ 100ms at 16kHz 16-bit mono)
    chunk_size = 3200
    offset = 0
    while offset < len(pcm_bytes):
        chunk = pcm_bytes[offset : offset + chunk_size]
        if not chunk:
            break
        encoded = base64.b64encode(chunk).decode("utf-8")
        event = {
            "event_id": f"audio_{int(time.time() * 1000)}",
            "type": "input_audio_buffer.append",
            "audio": encoded,
        }
        try:
            ws.send(json.dumps(event))
        except Exception as e:
            logger.error("Failed to send audio chunk: %s", e)
            break
        offset += chunk_size
        time.sleep(0.05)

    if enable_vad:
        try:
            ws.send(json.dumps({"event_id": "commit", "type": "input_audio_buffer.commit"}))
        except Exception:
            pass

    # Wait for processing
    time.sleep(1.0)
    for _ in range(30):
        if final_transcript or not thread.is_alive():
            break
        time.sleep(0.2)

    ws.close()
    thread.join(timeout=2)

    return " ".join(final_transcript).strip() or " ".join(partial_text).strip()


def transcribe_wav_bytes(wav_bytes: bytes, **kwargs) -> str:
    """
    Transcribe WAV audio bytes. Converts to PCM 16kHz if needed.

    Args:
        wav_bytes: WAV file bytes (from mic recorder, etc.).
        **kwargs: Passed to transcribe_audio_stream.

    Returns:
        Final transcript string.
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        raise ImportError("pydub is required for WAV conversion. pip install pydub")

    audio = AudioSegment.from_wav(io.BytesIO(wav_bytes))
    # Resample to 16kHz, convert to mono
    if audio.frame_rate != 16000 or audio.channels != 1:
        audio = audio.set_frame_rate(16000).set_channels(1)
    pcm = audio.raw_data
    return transcribe_audio_stream(pcm, sample_rate=16000, **kwargs)
