import hashlib
from types import SimpleNamespace

from app.services.embedding_service import (
    EmbeddingProvider,
    EmbeddingService,
    VectorSearchService,
)


class StubProvider(EmbeddingProvider):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            lowered = text.lower()
            vector = [0.0] * 1536
            if "python" in lowered:
                vector[0] = 1.0
            elif "leadership" in lowered:
                vector[1] = 1.0
            else:
                vector[2] = 1.0
            vectors.append(vector)
        return vectors

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self.embed_texts(texts)


def build_chunk(chunk_id: int, text: str, index: int = 0):
    return SimpleNamespace(
        id=chunk_id,
        index=index,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def build_repository():
    return SimpleNamespace(
        db=SimpleNamespace(commit=lambda: None, rollback=lambda: None),
        get_existing_embedding=lambda **_: None,
        upsert_embedding=lambda **kwargs: kwargs,
    )


def test_embedding_service_processes_persistent_chunks():
    provider = StubProvider()
    repo = build_repository()
    service = EmbeddingService(repository=repo, provider=provider, user_id=42)

    chunks = [
        build_chunk(7, "Python backend engineer", 0),
        build_chunk(8, "Leadership experience", 1),
    ]

    result = service.process_chunks(
        source_type="resume_chunk",
        source_id=7,
        document_id=99,
        chunks=chunks,
    )

    assert len(result) == 2
    assert all(len(item["embedding"]) == 1536 for item in result)
    assert result[0]["chunk_id"] == 7
    assert result[1]["chunk_id"] == 8


def test_embedding_service_is_idempotent_for_same_chunk_and_model():
    calls = {"count": 0}

    class CountingProvider(StubProvider):
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            calls["count"] += 1
            return super().embed_texts(texts)

    text = "Python engineer"
    existing = SimpleNamespace(
        id=1,
        chunk_id=10,
        source_type="resume_chunk",
        source_id=10,
        document_id=10,
        user_id=5,
        text=text,
        embedding=[0.0] * 1536,
        embedding_model="gemini-embedding-001",
        embedding_version="v1",
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    saved = []

    repo = SimpleNamespace(
        db=SimpleNamespace(commit=lambda: None, rollback=lambda: None),
        get_existing_embedding=lambda **_: existing,
        upsert_embedding=lambda **kwargs: saved.append(kwargs) or kwargs,
    )

    service = EmbeddingService(repository=repo, provider=CountingProvider(), user_id=5)
    result = service.process_chunks(
        source_type="resume_chunk",
        source_id=10,
        document_id=10,
        chunks=[build_chunk(10, text)],
    )

    assert calls["count"] == 1
    assert saved == []
    assert result[0]["id"] == 1


def test_vector_search_service_classifies_similarity():
    search = VectorSearchService()

    assert search.classify_similarity(0.92) == "strong candidate evidence"
    assert search.classify_similarity(0.68) == "possible evidence"
    assert search.classify_similarity(0.28) == "weak evidence"


def test_vector_search_service_filters_ownership():
    results = [
        {"source_id": 1, "source_type": "resume_chunk", "user_id": 7, "text": "Python"},
        {"source_id": 2, "source_type": "resume_chunk", "user_id": 8, "text": "Leadership"},
    ]
    filtered = VectorSearchService.filter_user_results(results, user_id=7)
    assert len(filtered) == 1
    assert filtered[0]["user_id"] == 7
