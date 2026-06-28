class FakeBlob:
    def __init__(self, name: str):
        self.name = name
        self.deleted = False

    def download_as_bytes(self, **kwargs):
        self.download_kwargs = kwargs
        return b"stored"

    def exists(self):
        return True

    def delete(self):
        self.deleted = True


class FakeBucket:
    def __init__(self, name: str):
        self.name = name
        self.blobs: list[FakeBlob] = []

    def blob(self, name: str):
        blob = FakeBlob(name)
        self.blobs.append(blob)
        return blob


class FakeClient:
    def __init__(self):
        self.buckets: list[FakeBucket] = []

    def bucket(self, name: str):
        bucket = FakeBucket(name)
        self.buckets.append(bucket)
        return bucket


def load_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.services.storage import GcsStorageService, split_gs_uri

    get_settings.cache_clear()
    return GcsStorageService, split_gs_uri


def make_gcs_service(GcsStorageService):
    service = object.__new__(GcsStorageService)
    service.client = FakeClient()
    service.bucket_name = "bucket"
    service.prefix = "medusa"
    return service


def test_split_gs_uri_preserves_reserved_object_name_characters(monkeypatch, tmp_path):
    _, split_gs_uri = load_storage(monkeypatch, tmp_path)

    bucket, object_name = split_gs_uri("gs://bucket/medusa/documents/Study? Question #1.pdf")

    assert bucket == "bucket"
    assert object_name == "medusa/documents/Study? Question #1.pdf"


def test_gcs_get_bytes_preserves_reserved_object_name_characters(monkeypatch, tmp_path):
    GcsStorageService, _ = load_storage(monkeypatch, tmp_path)
    service = make_gcs_service(GcsStorageService)

    data = service.get_bytes("gs://bucket/medusa/documents/Study? Question #1.pdf", timeout=5, retry=None)

    bucket = service.client.buckets[0]
    blob = bucket.blobs[0]
    assert data == b"stored"
    assert bucket.name == "bucket"
    assert blob.name == "medusa/documents/Study? Question #1.pdf"
    assert blob.download_kwargs == {"timeout": 5, "retry": None}


def test_gcs_delete_uri_preserves_reserved_object_name_characters(monkeypatch, tmp_path):
    GcsStorageService, _ = load_storage(monkeypatch, tmp_path)
    service = make_gcs_service(GcsStorageService)

    deleted = service.delete_uri("gs://bucket/medusa/documents/Study? Question #1.pdf")

    bucket = service.client.buckets[0]
    blob = bucket.blobs[0]
    assert deleted is True
    assert bucket.name == "bucket"
    assert blob.name == "medusa/documents/Study? Question #1.pdf"
    assert blob.deleted is True
