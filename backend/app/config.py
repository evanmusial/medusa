from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Medusa"
    environment: str = "development"
    bind_host: str = "0.0.0.0"
    public_port: int = 3737
    public_host: str = Field(default="medusa.home.musial.io", validation_alias="MEDUSA_PUBLIC_HOST")
    haproxy_stats_url: str = Field(
        default="http://haproxy:8404/stats;csv",
        validation_alias="MEDUSA_HAPROXY_STATS_URL",
    )

    database_url: str = Field(
        default="postgresql+psycopg://medusa:medusa@localhost:5432/medusa",
        validation_alias="DATABASE_URL",
    )

    session_cookie_name: str = "medusa_session"
    session_ttl_hours: int = 24 * 14
    admin_email: str = Field(default="admin@medusa.local", validation_alias="MEDUSA_ADMIN_EMAIL")
    admin_password: str = Field(default="medusa", validation_alias="MEDUSA_PASSWORD")
    allow_default_password: bool = Field(default=True, validation_alias="MEDUSA_ALLOW_DEFAULT_PASSWORD")
    local_auto_login: bool = Field(default=False, validation_alias="MEDUSA_LOCAL_AUTO_LOGIN")
    database_backup_storage: str = Field(default="local", validation_alias="MEDUSA_DATABASE_BACKUP_STORAGE")

    data_dir: Path = Field(default=Path("./data"), validation_alias="MEDUSA_DATA_DIR")
    local_storage_dir: Path = Field(default=Path("./data/originals"), validation_alias="MEDUSA_LOCAL_STORAGE_DIR")
    build_version: str | None = Field(default=None, validation_alias="MEDUSA_BUILD_VERSION")
    build_date: str | None = Field(default=None, validation_alias="MEDUSA_BUILD_DATE")
    build_hash: str | None = Field(default=None, validation_alias="MEDUSA_BUILD_HASH")
    git_sha: str | None = Field(default=None, validation_alias="MEDUSA_GIT_SHA")
    release_status_path: Path | None = Field(default=None, validation_alias="MEDUSA_RELEASE_STATUS_PATH")
    release_request_path: Path | None = Field(default=None, validation_alias="MEDUSA_RELEASE_REQUEST_PATH")
    cache_backend: str = Field(default="valkey", validation_alias="MEDUSA_CACHE_BACKEND")
    cache_url: str = Field(default="valkey://valkey:6379/0", validation_alias="MEDUSA_CACHE_URL")
    cache_ttl_seconds: int = Field(default=3600, validation_alias="MEDUSA_CACHE_TTL_SECONDS")
    cache_max_payload_bytes: int = Field(default=2_097_152, validation_alias="MEDUSA_CACHE_MAX_PAYLOAD_BYTES")
    valkey_maxmemory: str = Field(default="8gb", validation_alias="MEDUSA_VALKEY_MAXMEMORY")
    metrics_internal_token: str | None = Field(default=None, validation_alias="MEDUSA_METRICS_INTERNAL_TOKEN")
    metrics_internal_snapshot_url: str = Field(
        default="http://backend:8000/api/internal/metrics/snapshot",
        validation_alias="MEDUSA_METRICS_INTERNAL_SNAPSHOT_URL",
    )
    metrics_bind_host: str = Field(default="0.0.0.0", validation_alias="MEDUSA_METRICS_BIND_HOST")
    metrics_port: int = Field(default=43737, validation_alias="MEDUSA_METRICS_PORT")
    metrics_require_auth: bool = Field(default=True, validation_alias="MEDUSA_METRICS_REQUIRE_AUTH")
    metrics_bearer_token: str | None = Field(default=None, validation_alias="MEDUSA_METRICS_BEARER_TOKEN")
    metrics_bearer_token_file: str | None = Field(
        default="/app/data/secrets/prometheus-token",
        validation_alias="MEDUSA_METRICS_BEARER_TOKEN_FILE",
    )
    metrics_heavy_ttl_seconds: int = Field(default=900, validation_alias="MEDUSA_METRICS_HEAVY_TTL_SECONDS")
    metrics_docker_socket_path: str | None = Field(default=None, validation_alias="MEDUSA_METRICS_DOCKER_SOCKET_PATH")

    gcs_bucket: str | None = Field(default=None, validation_alias="GCS_BUCKET")
    gcs_prefix: str = Field(default="medusa", validation_alias="GCS_PREFIX")
    google_cloud_project: str | None = Field(default=None, validation_alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str = Field(default="global", validation_alias="GOOGLE_CLOUD_LOCATION")
    google_application_credentials: str | None = Field(
        default=None,
        validation_alias="GOOGLE_APPLICATION_CREDENTIALS",
    )

    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.5", validation_alias="OPENAI_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias="OPENAI_EMBEDDING_MODEL",
    )
    openai_pricing_tier: str = Field(default="standard", validation_alias="MEDUSA_OPENAI_PRICING_TIER")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    google_genai_use_vertexai: bool = Field(default=False, validation_alias="GOOGLE_GENAI_USE_VERTEXAI")
    openai_send_pdf_file: bool = Field(default=True, validation_alias="MEDUSA_OPENAI_SEND_PDF")
    openai_pdf_file_max_mb: int = Field(default=24, validation_alias="MEDUSA_OPENAI_PDF_FILE_MAX_MB")
    openai_normalize_page_text: bool = Field(default=True, validation_alias="MEDUSA_OPENAI_NORMALIZE_PAGE_TEXT")
    openai_page_normalization_mode: str = Field(default="auto", validation_alias="MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE")
    openai_page_normalization_auto_max_pages: int = Field(
        default=4,
        validation_alias="MEDUSA_OPENAI_PAGE_NORMALIZATION_AUTO_MAX_PAGES",
    )
    openai_text_normalization_page_max_chars: int = Field(
        default=14_000,
        validation_alias="MEDUSA_OPENAI_TEXT_NORMALIZATION_PAGE_MAX_CHARS",
    )
    openai_request_timeout_seconds: float = Field(default=180.0, validation_alias="MEDUSA_OPENAI_REQUEST_TIMEOUT_SECONDS")
    inquest_inline_timeout_seconds: float = Field(default=45.0, validation_alias="MEDUSA_INQUEST_INLINE_TIMEOUT_SECONDS")
    openai_combine_document_intelligence: bool = Field(
        default=False,
        validation_alias="MEDUSA_OPENAI_COMBINE_DOCUMENT_INTELLIGENCE",
    )
    openai_prompt_cache_retention: str | None = Field(
        default="24h",
        validation_alias="MEDUSA_OPENAI_PROMPT_CACHE_RETENTION",
    )
    openai_apa_reasoning_effort: str | None = Field(
        default="high",
        validation_alias="MEDUSA_OPENAI_APA_REASONING_EFFORT",
    )
    openai_bibliography_reasoning_effort: str | None = Field(
        default="off",
        validation_alias="MEDUSA_OPENAI_BIBLIOGRAPHY_REASONING_EFFORT",
    )
    openai_page_normalization_timeout_seconds: float = Field(
        default=90.0,
        validation_alias="MEDUSA_OPENAI_PAGE_NORMALIZATION_TIMEOUT_SECONDS",
    )
    openai_embedding_timeout_seconds: float = Field(default=60.0, validation_alias="MEDUSA_OPENAI_EMBEDDING_TIMEOUT_SECONDS")
    second_pass_processing_enabled: bool = Field(default=True, validation_alias="MEDUSA_SECOND_PASS_PROCESSING_ENABLED")
    raw_text_extraction_timeout_seconds: float = Field(
        default=900.0,
        validation_alias="MEDUSA_RAW_TEXT_EXTRACTION_TIMEOUT_SECONDS",
    )

    recommendations_enable_openalex: bool = Field(default=True, validation_alias="MEDUSA_RECOMMENDATIONS_ENABLE_OPENALEX")
    recommendations_enable_semantic_scholar: bool = Field(
        default=True,
        validation_alias="MEDUSA_RECOMMENDATIONS_ENABLE_SEMANTIC_SCHOLAR",
    )
    recommendations_enable_crossref: bool = Field(default=True, validation_alias="MEDUSA_RECOMMENDATIONS_ENABLE_CROSSREF")
    recommendations_enable_unpaywall: bool = Field(
        default=True,
        validation_alias="MEDUSA_RECOMMENDATIONS_ENABLE_UNPAYWALL",
    )
    recommendations_enable_arxiv: bool = Field(default=True, validation_alias="MEDUSA_RECOMMENDATIONS_ENABLE_ARXIV")
    recommendations_max_results_per_source: int = Field(default=40, validation_alias="MEDUSA_RECOMMENDATIONS_MAX_PER_SOURCE")
    recommendations_request_timeout_seconds: float = Field(
        default=16.0,
        validation_alias="MEDUSA_RECOMMENDATIONS_REQUEST_TIMEOUT_SECONDS",
    )
    recommendation_download_timeout_seconds: float = Field(
        default=60.0,
        validation_alias="MEDUSA_RECOMMENDATION_DOWNLOAD_TIMEOUT_SECONDS",
    )
    recommendation_download_max_mb: int = Field(default=80, validation_alias="MEDUSA_RECOMMENDATION_DOWNLOAD_MAX_MB")
    openalex_mailto: str | None = Field(default=None, validation_alias="MEDUSA_OPENALEX_MAILTO")
    unpaywall_email: str | None = Field(default=None, validation_alias="MEDUSA_UNPAYWALL_EMAIL")
    recommendations_arxiv_title_lookups: int = Field(
        default=8,
        validation_alias="MEDUSA_RECOMMENDATIONS_ARXIV_TITLE_LOOKUPS",
    )
    semantic_scholar_api_key: str | None = Field(default=None, validation_alias="SEMANTIC_SCHOLAR_API_KEY")
    citation_title_web_search: bool = Field(default=True, validation_alias="MEDUSA_CITATION_TITLE_WEB_SEARCH")
    citation_title_web_search_timeout_seconds: float = Field(
        default=8.0,
        validation_alias="MEDUSA_CITATION_TITLE_WEB_SEARCH_TIMEOUT_SECONDS",
    )

    enable_google_vision: bool = Field(default=True, validation_alias="MEDUSA_ENABLE_GOOGLE_VISION")
    low_text_page_threshold: int = 120
    worker_poll_seconds: float = 2.0
    worker_import_concurrency: int = Field(default=4, validation_alias="MEDUSA_IMPORT_WORKER_CONCURRENCY")
    worker_stale_job_seconds: int = Field(default=900, validation_alias="MEDUSA_WORKER_STALE_JOB_SECONDS")
    document_cache_size_mb: int = Field(default=1024, validation_alias="MEDUSA_DOCUMENT_CACHE_SIZE_MB")
    slipstream_enabled: bool = Field(default=False, validation_alias="MEDUSA_SLIPSTREAM_ENABLED")
    slipstream_public_base_url: str | None = Field(default=None, validation_alias="MEDUSA_SLIPSTREAM_PUBLIC_BASE_URL")
    slipstream_lease_ttl_seconds: int = Field(default=180, validation_alias="MEDUSA_SLIPSTREAM_LEASE_TTL_SECONDS")
    slipstream_heartbeat_seconds: int = Field(default=30, validation_alias="MEDUSA_SLIPSTREAM_HEARTBEAT_SECONDS")
    slipstream_max_result_mb: int = Field(default=512, validation_alias="MEDUSA_SLIPSTREAM_MAX_RESULT_MB")
    slipstream_require_tls: bool = Field(default=True, validation_alias="MEDUSA_SLIPSTREAM_REQUIRE_TLS")
    slipstream_signature_window_seconds: int = Field(default=300, validation_alias="MEDUSA_SLIPSTREAM_SIGNATURE_WINDOW_SECONDS")

    cors_origins: list[str] = [
        "http://localhost:3737",
        "http://127.0.0.1:3737",
    ]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.local_storage_dir.mkdir(parents=True, exist_ok=True)
    return settings
