from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_settings
from app.services.google_credentials import load_service_account_credentials
from app.services.preferences import get_active_storage_settings


@dataclass(frozen=True)
class StoredObject:
    uri: str
    backend: str


class StorageService:
    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        raise NotImplementedError

    def get_bytes(self, uri: str) -> bytes:
        raise NotImplementedError

    def delete_uri(self, uri: str) -> bool:
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

    def delete_uri(self, uri: str) -> bool:
        parsed = urlparse(uri)
        if parsed.scheme == "gs":
            return False
        path = Path(uri)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False


class GcsStorageService(StorageService):
    def __init__(self, bucket_name: str, prefix: str, credentials_path: str | None = None):
        from google.cloud import storage

        if not credentials_path:
            raise RuntimeError("Google service account credentials are not configured.")
        credentials = load_service_account_credentials(credentials_path)
        project = getattr(credentials, "project_id", None)
        self.client = storage.Client(project=project, credentials=credentials)
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

    def delete_uri(self, uri: str) -> bool:
        parsed = urlparse(uri)
        if parsed.scheme != "gs":
            try:
                Path(uri).unlink()
                return True
            except FileNotFoundError:
                return False
        bucket = self.client.bucket(parsed.netloc)
        blob = bucket.blob(parsed.path.lstrip("/"))
        if not blob.exists():
            return False
        blob.delete()
        return True


def get_storage_service() -> StorageService:
    settings = get_settings()
    storage_settings = get_active_storage_settings()
    gcs_bucket = storage_settings.get("gcs_bucket")
    if gcs_bucket:
        try:
            return GcsStorageService(
                gcs_bucket,
                storage_settings.get("gcs_prefix") or settings.gcs_prefix,
                storage_settings.get("google_credentials_path"),
            )
        except Exception:
            # The app must still boot and import locally if GCS credentials are not ready yet.
            return LocalStorageService(settings.local_storage_dir)
    return LocalStorageService(settings.local_storage_dir)
