from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from typing import Any

from google import genai
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @abstractmethod
    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class GeminiEmbeddingProvider(EmbeddingProvider):
    def __init__(self, *, api_key: str | None = None, model: str | None = None, timeout_seconds: int | None = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_EMBEDDING_MODEL
        self.timeout_seconds = timeout_seconds or settings.GEMINI_TIMEOUT_SECONDS

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.api_key:
            raise ValueError("Gemini embedding API key is not configured.")

        client = genai.Client(
            api_key=self.api_key,
            http_options={"timeout": self.timeout_seconds * 1000},
        )
        try:
            response = client.models.embed_content(
                model=self.model,
                contents=texts,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=1536,
                ),
            )
        except Exception as exc:  # pragma: no cover - provider may be mocked in tests
            message = str(exc).lower()
            if any(token in message for token in ["rate limit", "quota", "429", "timeout", "temporar", "overloaded", "503"]):
                raise RuntimeError(f"Gemini embeddings rate-limited or timed out: {exc}") from exc
            raise RuntimeError(f"Gemini embedding request failed: {exc}") from exc

        values = getattr(response, "embeddings", None) or []
        if not values:
            raise RuntimeError("Gemini embeddings response was empty.")

        vectors: list[list[float]] = []
        for item in values:
            vector = getattr(item, "values", None)
            if vector is None:
                raise RuntimeError("Gemini embedding response payload was malformed.")
            normalized = [float(value) for value in vector]
            if len(normalized) != 1536:
                raise RuntimeError(
                    f"Gemini embedding dimension mismatch: expected 1536, got {len(normalized)}."
                )
            vectors.append(normalized)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise ValueError("Query text is required.")
        if not self.api_key:
            raise ValueError("Gemini embedding API key is not configured.")

        client = genai.Client(
            api_key=self.api_key,
            http_options={"timeout": self.timeout_seconds * 1000},
        )
        try:
            response = client.models.embed_content(
                model=self.model,
                contents=text.strip(),
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=1536,
                ),
            )
        except Exception as exc:  # pragma: no cover - provider may be mocked in tests
            message = str(exc).lower()
            if any(
                token in message
                for token in [
                    "rate limit",
                    "quota",
                    "429",
                    "timeout",
                    "temporar",
                    "overloaded",
                    "503",
                ]
            ):
                raise RuntimeError(
                    f"Gemini query embedding rate-limited or timed out: {exc}"
                ) from exc
            raise RuntimeError(f"Gemini query embedding request failed: {exc}") from exc

        values = getattr(response, "embeddings", None) or []
        if len(values) != 1:
            raise RuntimeError(
                f"Gemini query embedding response returned {len(values)} vectors; expected 1."
            )
        vector = getattr(values[0], "values", None)
        if vector is None:
            raise RuntimeError("Gemini query embedding response payload was malformed.")
        normalized = [float(value) for value in vector]
        if len(normalized) != 1536:
            raise RuntimeError(
                f"Gemini query embedding dimension mismatch: expected 1536, got {len(normalized)}."
            )
        return normalized

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.api_key:
            raise ValueError("Gemini embedding API key is not configured.")

        client = genai.Client(
            api_key=self.api_key,
            http_options={"timeout": self.timeout_seconds * 1000},
        )
        try:
            response = client.models.embed_content(
                model=self.model,
                contents=[text.strip() for text in texts],
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=1536,
                ),
            )
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Gemini query embedding request failed: {exc}") from exc

        values = getattr(response, "embeddings", None) or []
        if len(values) != len(texts):
            raise RuntimeError(
                f"Gemini query embedding response returned {len(values)} vectors for {len(texts)} texts."
            )

        vectors: list[list[float]] = []
        for item in values:
            vector = getattr(item, "values", None)
            if vector is None:
                raise RuntimeError("Gemini query embedding response payload was malformed.")
            normalized_vector = [float(value) for value in vector]
            if len(normalized_vector) != 1536:
                raise RuntimeError(
                    f"Gemini query embedding dimension mismatch: expected 1536, got {len(normalized_vector)}."
                )
            vectors.append(normalized_vector)
        return vectors


class EmbeddingRepository:
    def __init__(self, db):
        self.db = db

    def get_existing_embedding(self, *, chunk_id: int, embedding_model: str, embedding_version: str):
        from app.models.embedding import Embedding

        return self.db.query(Embedding).filter(
            Embedding.chunk_id == chunk_id,
            Embedding.embedding_model == embedding_model,
            Embedding.embedding_version == embedding_version,
        ).first()

    def upsert_embedding(self, **kwargs):
        from app.models.embedding import Embedding

        existing = self.get_existing_embedding(
            chunk_id=kwargs["chunk_id"],
            embedding_model=kwargs["embedding_model"],
            embedding_version=kwargs["embedding_version"],
        )
        if existing is not None:
            for key, value in kwargs.items():
                setattr(existing, key, value)
            self.db.flush()
            return existing

        instance = Embedding(**kwargs)
        self.db.add(instance)
        self.db.flush()
        return instance

    def search_similar(
        self,
        *,
        query_vector: list[float],
        user_id: int,
        source_types: list[str] | None = None,
        limit: int = 10,
        resume_id: int | None = None,
    ) -> list[dict[str, Any]]:
        from app.models.document_chunk import DocumentChunk
        from app.models.embedding import Embedding

        if limit <= 0:
            raise ValueError("limit must be greater than zero.")
        if len(query_vector) != 1536:
            raise ValueError(
                f"Query vector dimension mismatch: expected 1536, got {len(query_vector)}."
            )

        distance = Embedding.embedding.cosine_distance(query_vector).label("cosine_distance")
        query = (
            self.db.query(Embedding, DocumentChunk, distance)
            .join(DocumentChunk, Embedding.chunk_id == DocumentChunk.id)
            .filter(Embedding.user_id == user_id)
        )
        if resume_id is not None:
            query = query.filter(DocumentChunk.resume_id == resume_id)
        if source_types:
            query = query.filter(Embedding.source_type.in_(source_types))

        rows = query.order_by(distance.asc()).limit(limit).all()

        results: list[dict[str, Any]] = []
        for embedding, chunk, cosine_distance in rows:
            distance_value = float(cosine_distance)
            similarity = max(0.0, min(1.0, 1.0 - distance_value))
            results.append(
                {
                    "embedding_id": embedding.id,
                    "chunk_id": chunk.id,
                    "resume_id": chunk.resume_id,
                    "job_description_id": chunk.job_description_id,
                    "user_id": embedding.user_id,
                    "source_type": embedding.source_type,
                    "source_id": embedding.source_id,
                    "text": chunk.text,
                    "similarity": similarity,
                    "classification": VectorSearchService.classify_similarity(similarity),
                }
            )
        return results

    def list_for_user(self, user_id: int, *, source_type: str | None = None):
        from app.models.embedding import Embedding

        query = self.db.query(Embedding).filter(Embedding.user_id == user_id)
        if source_type:
            query = query.filter(Embedding.source_type == source_type)
        return query.order_by(Embedding.created_at.desc()).all()


class EmbeddingService:
    def __init__(self, repository: EmbeddingRepository, provider: EmbeddingProvider, user_id: int | None = None, embedding_model: str | None = None):
        self.repository = repository
        self.provider = provider
        self.user_id = user_id
        self.embedding_model = embedding_model or settings.GEMINI_EMBEDDING_MODEL
        self.embedding_version = settings.GEMINI_EMBEDDING_VERSION

    def _fingerprint(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_record(record: Any) -> dict[str, Any]:
        if record is None:
            return {}
        if isinstance(record, dict):
            return record
        return {
            "id": getattr(record, "id", None),
            "source_type": getattr(record, "source_type", None),
            "source_id": getattr(record, "source_id", None),
            "document_id": getattr(record, "document_id", None),
            "chunk_id": getattr(record, "chunk_id", None),
            "user_id": getattr(record, "user_id", None),
            "text": getattr(record, "text", None),
            "embedding": (
                list(embedding_value)
                if (embedding_value := getattr(record, "embedding", None)) is not None
                else []
            ),
            "embedding_model": getattr(record, "embedding_model", None),
            "embedding_version": getattr(record, "embedding_version", None),
            "content_hash": getattr(record, "content_hash", None),
        }

    def process_chunks(
        self,
        *,
        source_type: str,
        source_id: int,
        chunks,
        document_id: int | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if not chunks:
            return []

        effective_user_id = user_id if user_id is not None else self.user_id
        texts = [chunk.text for chunk in chunks]
        vectors = self.provider.embed_texts(texts)
        if len(vectors) != len(chunks):
            raise RuntimeError(
                f"Embedding provider returned {len(vectors)} vectors for {len(chunks)} chunks."
            )

        output: list[dict[str, Any]] = []
        try:
            for chunk, vector in zip(chunks, vectors, strict=True):
                normalized_vector = [float(value) for value in vector]
                if len(normalized_vector) != 1536:
                    raise RuntimeError(
                        f"Embedding dimension mismatch: expected 1536, got {len(normalized_vector)}."
                    )

                existing = self.repository.get_existing_embedding(
                    chunk_id=chunk.id,
                    embedding_model=self.embedding_model,
                    embedding_version=self.embedding_version,
                )
                if existing is not None and existing.content_hash == chunk.content_hash:
                    output.append(self._normalize_record(existing))
                    continue

                item = self.repository.upsert_embedding(
                    user_id=effective_user_id,
                    source_type=source_type,
                    source_id=source_id,
                    document_id=document_id,
                    chunk_id=chunk.id,
                    text=chunk.text,
                    content_hash=chunk.content_hash,
                    embedding=normalized_vector,
                    embedding_model=self.embedding_model,
                    embedding_version=self.embedding_version,
                )
                output.append(self._normalize_record(item))

            self.repository.db.commit()
            return output
        except Exception:
            self.repository.db.rollback()
            raise


class VectorSearchService:
    def __init__(self, similarity_thresholds: dict[str, float] | None = None):
        self.similarity_thresholds = similarity_thresholds or {
            "strong": 0.85,
            "possible": 0.65,
            "weak": 0.4,
        }

    @staticmethod
    def classify_similarity(score: float) -> str:
        if score >= 0.85:
            return "strong candidate evidence"
        if score >= 0.65:
            return "possible evidence"
        return "weak evidence"

    @staticmethod
    def filter_user_results(results: list[dict[str, Any]], *, user_id: int) -> list[dict[str, Any]]:
        return [item for item in results if item.get("user_id") == user_id]

    def search(
        self,
        *,
        query_vector: list[float],
        candidate_vectors: list[dict[str, Any]],
        user_id: int | None = None,
        resume_id: int | None = None,
    ):
        filtered = candidate_vectors
        if user_id is not None:
            filtered = self.filter_user_results(filtered, user_id=user_id)
        if resume_id is not None:
            filtered = [item for item in filtered if item.get("resume_id") == resume_id]

        scored = []
        for item in filtered:
            candidate = item.get("embedding") or []
            if not candidate:
                continue
            similarity = self._cosine_similarity(query_vector, candidate)
            scored.append({**item, "similarity": similarity, "classification": self.classify_similarity(similarity)})
        return sorted(scored, key=lambda row: row["similarity"], reverse=True)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0

        dot = sum(x * y for x, y in zip(a, b, strict=True))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return max(0.0, min(1.0, dot / (norm_a * norm_b)))
