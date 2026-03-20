"""
Embedding: convert text chunks to vectors for semantic search.

Structured around a BaseEmbedder ABC for easy extension; currently implements
SentenceTransformerEmbedder and Qwen3Embedding4BEmbedder.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class BaseEmbedder(ABC):
    """
    Abstract base for text embedders. Subclass to add new embedding backends
    (e.g. OpenAI, Cohere, HuggingFace, etc.).
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output embedding dimension."""
        ...

    @abstractmethod
    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """
        Embed a batch of text strings into vectors.

        Args:
            texts: List of text chunks to embed.
            model: Optional model override; semantics depend on implementer.

        Returns:
            List of embedding vectors (each is a list of floats).
        """
        ...

    def embed_single(self, text: str, model: str | None = None) -> list[float]:
        """Embed a single text string."""
        return self.embed([text], model=model)[0]


class SentenceTransformerEmbedder(BaseEmbedder):
    """
    Embedder using sentence-transformers. Good for local, fast semantic search
    without API costs.
    """

    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(self, model: str | None = None) -> None:
        self._model_name = model or self.DEFAULT_MODEL
        self._model: object | None = None

    def _get_model(self) -> object:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    @property
    def dimension(self) -> int:
        # Avoid loading model until first embed; use known dim for common models
        dims: dict[str, int] = {
            "all-MiniLM-L6-v2": 384,
            "all-mpnet-base-v2": 768,
            "paraphrase-multilingual-MiniLM-L12-v2": 384,
        }
        return dims.get(self._model_name, 384)

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        if not texts:
            return []
        # model param reserved for per-call override; use instance model for now
        _ = model
        st = self._get_model()
        vectors = st.encode(texts, convert_to_numpy=True)
        return [v.tolist() for v in vectors]


class Qwen3Embedding4BEmbedder(BaseEmbedder):
    """
    Embedder using Qwen3-Embedding-4B via OpenAI-compatible API.

    Uses DashScope (text-embedding-v4, Qwen3-Embedding series) by default.
    For other providers (e.g. DeepInfra), set QWEN_EMBED_BASE_URL and
    QWEN_EMBED_MODEL=Qwen/Qwen3-Embedding-4B.

    Env:
        DASHSCOPE_API_KEY or QWEN_API_KEY: API key
        QWEN_EMBED_BASE_URL: base URL (default: DashScope compatible-mode)
        QWEN_EMBED_MODEL: model name (default: text-embedding-v4)
        QWEN_EMBED_DIMENSIONS: output dimension (default: 1024)
    """

    DEFAULT_MODEL = "text-embedding-v4"
    DEFAULT_DIMENSION = 1024

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
    ) -> None:
        self._api_key = api_key or os.getenv("QWEN_EMBED_MODEL_API")
        self._base_url = base_url or os.getenv(
            "QWEN_EMBED_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self._model = model or os.getenv("QWEN_EMBED_MODEL", self.DEFAULT_MODEL)
        self._dimension = dimension or int(os.getenv("QWEN_EMBED_DIMENSIONS", str(self.DEFAULT_DIMENSION)))
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            from openai import OpenAI

            from shared.llm_client import build_http_client

            self._client = OpenAI(
                api_key=self._api_key or "",
                base_url=self._base_url,
                http_client=build_http_client(),
            )
        return self._client

    @property
    def dimension(self) -> int:
        return self._dimension

    # DashScope text-embedding API limits batch size to 10 per request
    _BATCH_SIZE = 10

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        if not texts:
            return []
        client = self._get_client()
        m = model or self._model
        results: list[list[float]] = []
        for i in range(0, len(texts), self._BATCH_SIZE):
            batch = texts[i : i + self._BATCH_SIZE]
            kwargs: dict = {
                "model": m,
                "input": batch,
                "encoding_format": "float",
            }
            if "text-embedding-v" in m:
                kwargs["dimensions"] = self._dimension
            resp = client.embeddings.create(**kwargs)
            results.extend([d.embedding for d in resp.data])
        return results


def get_default_embedder() -> BaseEmbedder:
    """
    Return the default embedder instance.

    Set EMBED_PROVIDER env var to choose:
        - "qwen" or "qwen3": Qwen3Embedding4BEmbedder (text-embedding-v4 via DashScope API)
        - "sentence" (default): SentenceTransformerEmbedder
    """
    provider = (os.getenv("EMBED_PROVIDER") or "sentence").strip().lower()
    if provider in ("qwen", "qwen3"):
        return Qwen3Embedding4BEmbedder()
    return SentenceTransformerEmbedder()


_default_embedder = get_default_embedder()


def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """
    Embed a batch of text strings using the default embedder.

    Args:
        texts: List of text chunks to embed.
        model: Optional embedding model name; uses default if not provided.

    Returns:
        List of embedding vectors (each is a list of floats).
    """
    return _default_embedder.embed(texts, model=model)


def embed_single(text: str, model: str | None = None) -> list[float]:
    """
    Embed a single text string using the default embedder.

    Args:
        text: Text to embed.
        model: Optional embedding model name.

    Returns:
        Embedding vector as list of floats.
    """
    return _default_embedder.embed_single(text, model=model)


if __name__ == "__main__":
    # cd backend && python -m retriever.embedding
    embedder = SentenceTransformerEmbedder()
    vecs = embedder.embed(["Hello world", "Semantic search test"])
    assert len(vecs) == 2 and len(vecs[0]) == embedder.dimension
    print("embedding test passed")
