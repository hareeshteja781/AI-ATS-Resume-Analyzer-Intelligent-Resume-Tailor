from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from uuid import uuid4

from app.core.config import settings


class StorageBackend(ABC):
    @abstractmethod
    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_bytes(self, *, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def delete(self, *, key: str) -> None:
        raise NotImplementedError



class LocalStorageBackend(StorageBackend):
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (
            Path(__file__).resolve().parents[2] / ".data" / "storage"
        )

    def _path(self, key: str) -> Path:
        normalized = key.replace("\\", "/").lstrip("/")
        if any(part == ".." for part in normalized.split("/")):
            raise ValueError("Invalid storage key.")
        candidate = (self.root / normalized).resolve()
        root = self.root.resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("Invalid storage key.")
        return candidate

    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
    ) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get_bytes(self, *, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, *, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()


class R2StorageBackend(StorageBackend):
    def __init__(self) -> None:
        import boto3

        self.client = boto3.client(
            "s3",
            endpoint_url=settings.R2_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )



    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
    ) -> str:
        self.client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    def get_bytes(self, *, key: str) -> bytes:
        response = self.client.get_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
        )
        return response["Body"].read()

    def delete(self, *, key: str) -> None:
        self.client.delete_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
        )


def _r2_configured() -> bool:
    return all(
        (
            settings.R2_ENDPOINT_URL,
            settings.R2_ACCESS_KEY_ID,
            settings.R2_SECRET_ACCESS_KEY,
            settings.R2_BUCKET_NAME,
        )
    )


class StorageService:
    def __init__(self, backend: StorageBackend | None = None) -> None:
        if backend is not None:
            self.backend = backend
        elif _r2_configured():
            self.backend = R2StorageBackend()
        elif settings.is_production:
            raise RuntimeError(
                "R2 storage configuration is required in production."
            )
        else:
            self.backend = LocalStorageBackend()

    def build_upload_key(
        self,
        *,
        user_id: int,
        kind: str,
        filename: str,
    ) -> str:
        suffix = Path(filename).suffix.lower()
        return f"users/{user_id}/{kind}/{uuid4().hex}{suffix}"

    def put_upload(
        self,
        *,
        user_id: int,
        kind: str,
        filename: str,
        data: bytes,
        content_type: str,
    ) -> str:
        key = self.build_upload_key(
            user_id=user_id,
            kind=kind,
            filename=filename,
        )
        return self.backend.put_bytes(
            key=key,
            data=data,
            content_type=content_type,
        )

    def get_bytes(self, key: str) -> bytes:
        return self.backend.get_bytes(key=key)

    def delete(self, key: str | None) -> None:
        if not key:
            return
        self.backend.delete(key=key)
