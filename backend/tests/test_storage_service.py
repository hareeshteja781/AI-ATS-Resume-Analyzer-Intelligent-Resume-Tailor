from pathlib import Path

import pytest

from app.services.storage_service import (
    LocalStorageBackend,
    StorageService,
)


def test_local_storage_upload_round_trip(tmp_path: Path):
    service = StorageService(backend=LocalStorageBackend(tmp_path))

    key = service.put_upload(
        user_id=7,
        kind="resumes",
        filename="resume.docx",
        data=b"resume-bytes",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert key.startswith("users/7/resumes/")
    assert key.endswith(".docx")
    assert service.get_bytes(key) == b"resume-bytes"

    service.delete(key)
    assert not (tmp_path / key).exists()


def test_local_storage_rejects_path_traversal(tmp_path: Path):
    backend = LocalStorageBackend(tmp_path)

    with pytest.raises(ValueError):
        backend.put_bytes(
            key="../escape.txt",
            data=b"bad",
            content_type="text/plain",
        )



def test_storage_key_uses_unique_object_names(tmp_path: Path):
    service = StorageService(backend=LocalStorageBackend(tmp_path))

    first = service.put_upload(
        user_id=1,
        kind="resumes",
        filename="resume.pdf",
        data=b"one",
        content_type="application/pdf",
    )
    second = service.put_upload(
        user_id=1,
        kind="resumes",
        filename="resume.pdf",
        data=b"two",
        content_type="application/pdf",
    )

    assert first != second
    assert service.get_bytes(first) == b"one"
    assert service.get_bytes(second) == b"two"
