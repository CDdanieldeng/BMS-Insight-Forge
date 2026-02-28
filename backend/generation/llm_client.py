"""LLM client abstraction for OpenAI and Qwen."""

import os
import time
import uuid

import httpx
from shared.logging_config import setup_logging

logger = setup_logging("generation")

# Lazy imports
_openai_client = None
_qwen_client = None


def _build_http_client() -> httpx.Client:
    """
    Build an HTTP client with configurable TLS verification.
    Useful for corp proxy/certificate environments.
    """
    verify_env = os.getenv("LLM_SSL_VERIFY", "true").strip().lower()
    ca_bundle = (
        os.getenv("LLM_CA_BUNDLE")
        or os.getenv("SSL_CERT_FILE")
        or os.getenv("REQUESTS_CA_BUNDLE")
    )
    timeout = float(os.getenv("LLM_HTTP_TIMEOUT", "120"))

    verify: bool | str = True
    if verify_env in {"0", "false", "no", "off"}:
        verify = False
    elif ca_bundle:
        verify = ca_bundle

    return httpx.Client(timeout=timeout, verify=verify)


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(http_client=_build_http_client())
    return _openai_client


def _get_qwen_client():
    global _qwen_client
    from openai import OpenAI
    if _qwen_client is None:
        _qwen_client = OpenAI(
            api_key=os.getenv("QWEN_API_KEY", ""),
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            http_client=_build_http_client(),
        )
    return _qwen_client


def get_llm_client():
    """Return the configured LLM client based on LLM_PROVIDER env."""
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "qwen":
        return _get_qwen_client()
    return _get_openai_client()


def get_model() -> str:
    """Return the model name for the current provider."""
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "qwen":
        return os.getenv("QWEN_MODEL", "qwen-plus")
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def complete(system_prompt: str, user_prompt: str, max_tokens: int | None = None) -> str:
    """
    Call LLM with system and user prompts, return assistant message content.

    max_tokens caps the output length, which prevents long-running generation
    from exhausting the HTTP timeout. Pass None to use the model default.
    """
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    client = get_llm_client()
    model = get_model()
    request_id = str(uuid.uuid4())[:8]
    start = time.perf_counter()
    logger.info(
        "LLM call start id=%s provider=%s model=%s sys_len=%d user_len=%d max_tokens=%s",
        request_id,
        provider,
        model,
        len(system_prompt or ""),
        len(user_prompt or ""),
        max_tokens,
    )

    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    try:
        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
        total_tokens = getattr(usage, "total_tokens", None) if usage else None
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "LLM call success id=%s elapsed_ms=%d output_len=%d prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            request_id,
            elapsed_ms,
            len(content or ""),
            prompt_tokens if prompt_tokens is not None else "unknown",
            completion_tokens if completion_tokens is not None else "unknown",
            total_tokens if total_tokens is not None else "unknown",
        )
        return content or ""
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            logger.error(
                "TLS certificate verification failed. "
                "Set LLM_CA_BUNDLE/SSL_CERT_FILE to your corporate CA bundle, "
                "or set LLM_SSL_VERIFY=false for local debugging only."
            )
        logger.exception(
            "LLM call failed id=%s provider=%s model=%s elapsed_ms=%d err=%s",
            request_id,
            provider,
            model,
            elapsed_ms,
            e.__class__.__name__,
        )
        raise
