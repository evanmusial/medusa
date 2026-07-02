from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any
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

    def get_bytes(self, uri: str, **kwargs: Any) -> bytes:
        raise NotImplementedError

    def delete_uri(self, uri: str) -> bool:
        raise NotImplementedError


_storage_service_lock = Lock()
_storage_service_cache: tuple[tuple[Any, ...], StorageService] | None = None


def split_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError("GCS URI must start with gs://")
    bucket_name, separator, object_name = uri[len("gs://") :].partition("/")
    if not bucket_name or not separator or not object_name:
        raise ValueError("GCS URI must include a bucket and object name.")
    return bucket_name, object_name


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

    def get_bytes(self, uri: str, **kwargs: Any) -> bytes:
        del kwargs
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

    def get_bytes(self, uri: str, **kwargs: Any) -> bytes:
        if not uri.startswith("gs://"):
            return Path(uri).read_bytes()
        bucket_name, object_name = split_gs_uri(uri)
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        return blob.download_as_bytes(**kwargs)

    def delete_uri(self, uri: str) -> bool:
        if not uri.startswith("gs://"):
            try:
                Path(uri).unlink()
                return True
            except FileNotFoundError:
                return False
        bucket_name, object_name = split_gs_uri(uri)
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        if not blob.exists():
            return False
        blob.delete()
        return True


def _credentials_cache_fingerprint(credentials_path: str | None) -> tuple[Any, ...]:
    if not credentials_path:
        return (None,)
    path = Path(credentials_path).expanduser()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), stat.st_size, stat.st_mtime_ns)


def _storage_cache_key(storage_settings: dict[str, Any]) -> tuple[Any, ...]:
    settings = get_settings()
    gcs_bucket = storage_settings.get("gcs_bucket")
    if gcs_bucket:
        return (
            "gcs",
            gcs_bucket,
            storage_settings.get("gcs_prefix") or settings.gcs_prefix,
            _credentials_cache_fingerprint(storage_settings.get("google_credentials_path")),
        )
    return ("local", str(settings.local_storage_dir))


def get_storage_service() -> StorageService:
    settings = get_settings()
    storage_settings = get_active_storage_settings()
    gcs_bucket = storage_settings.get("gcs_bucket")
    cache_key = _storage_cache_key(storage_settings)
    global _storage_service_cache
    with _storage_service_lock:
        if _storage_service_cache and _storage_service_cache[0] == cache_key:
            return _storage_service_cache[1]
    if gcs_bucket:
        try:
            service = GcsStorageService(
                gcs_bucket,
                storage_settings.get("gcs_prefix") or settings.gcs_prefix,
                storage_settings.get("google_credentials_path"),
            )
            with _storage_service_lock:
                _storage_service_cache = (cache_key, service)
            return service
        except Exception:
            # The app must still boot and import locally if GCS credentials are not ready yet.
            return LocalStorageService(settings.local_storage_dir)
    service = LocalStorageService(settings.local_storage_dir)
    with _storage_service_lock:
        _storage_service_cache = (cache_key, service)
    return service
