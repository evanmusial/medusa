from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_settings


@dataclass(frozen=True)
class StoredObject:
    uri: str
    backend: str


class StorageService:
    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        raise NotImplementedError

    def get_bytes(self, uri: str) -> bytes:
        raise NotImplementedError


class LocalStorageService(StorageService):
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        del content_type
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(uri=str(path.resolve()), backend="local")

    def get_bytes(self, uri: str) -> bytes:
        return Path(uri).read_bytes()


class GcsStorageService(StorageService):
    def __init__(self, bucket_name: str, prefix: str):
        from google.cloud import storage

        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)
        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        object_name = "/".join(part for part in [self.prefix, key] if part)
        blob = self.bucket.blob(object_name)
        blob.upload_from_string(data, content_type=content_type)
        return StoredObject(uri=f"gs://{self.bucket_name}/{object_name}", backend="gcs")

    def get_bytes(self, uri: str) -> bytes:
        parsed = urlparse(uri)
        if parsed.scheme != "gs":
            return Path(uri).read_bytes()
        bucket = self.client.bucket(parsed.netloc)
        blob = bucket.blob(parsed.path.lstrip("/"))
        return blob.download_as_bytes()


def get_storage_service() -> StorageService:
    settings = get_settings()
    if settings.gcs_bucket:
        try:
            return GcsStorageService(settings.gcs_bucket, settings.gcs_prefix)
        except Exception:
            # The app must still boot and import locally if GCS credentials are not ready yet.
            return LocalStorageService(settings.local_storage_dir)
    return LocalStorageService(settings.local_storage_dir)
