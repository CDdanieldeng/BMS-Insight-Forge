"""
Embedding: convert text chunks to vectors for semantic search.

Structured around a BaseEmbedder ABC for easy extension; currently implements
SentenceTransformerEmbedder.
"""

from __future__ import annotations

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


def get_default_embedder() -> BaseEmbedder:
    """Return the default embedder instance (SentenceTransformer)."""
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
