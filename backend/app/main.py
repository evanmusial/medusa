from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any, Iterable
from urllib.parse import quote

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import get_settings
from app.database import engine, get_db, init_db, is_postgres, session_scope
from app.models import (
    Annotation,
    AttributeDefinition,
    BackupRun,
    CitationCandidate,
    ConcordanceJob,
    ConcordanceRun,
    Document,
    DocumentAccessorySummary,
    DocumentCapability,
    DocumentCompositionRecord,
    DocumentAttributeValue,
    DocumentPage,
    DocumentRecommendation,
    DocumentTagAssessment,
    DocumentVersion,
    DoiStash,
    Domain,
    Figure,
    ImportBatch,
    ImportJob,
    Note,
    OpenAIUsageRecord,
    ProcessingEvent,
    PortfolioAssessmentFinding,
    PortfolioAssessmentRun,
    PortfolioItem,
    PortfolioMaterial,
    PortfolioSuggestion,
    PortfolioVersion,
    PortfolioVersionEdge,
    Project,
    ProjectBibliography,
    ProjectItem,
    ReconInquiry,
    ReconRun,
    SavedSearch,
    SlipstreamClient,
    SlipstreamLease,
    Tag,
    TagRelationship,
    TextChunk,
    User,
    document_domains,
    document_tags,
    utc_now,
)
from app.schemas import (
    AccessorySummaryCreate,
    AccessorySummaryOut,
    AccessorySummaryPatch,
    AccountUpdateRequest,
    AnnotationCreate,
    AnnotationOut,
    AnnotationPatch,
    AppPreferencesOut,
    AppPreferencesPatch,
    AttributeDefinitionCreate,
    AttributeDefinitionOut,
    BackupArtifactOut,
    BackupEstimateOut,
    BackupRunOut,
    BibliographyOut,
    CacheHydrateOut,
    CacheRefreshOut,
    CacheStatusOut,
    CitationCandidatePatch,
    CitationCandidateOut,
    ConcordanceCapabilityOut,
    ConcordanceRunEstimateOut,
    ConcordanceJobOut,
    ConcordanceRunCreate,
    ConcordanceRunOut,
    ContainerFootprintStatusOut,
    ContainerRestartOut,
    DashboardOut,
    DatabaseMaintenanceResultOut,
    DatabaseMaintenanceStatusOut,
    DocumentDetail,
    DuplicateDocumentOut,
    DuplicateDismissCreate,
    DuplicateDismissOut,
    DuplicatePairOut,
    DuplicateResolveCreate,
    DuplicateResolveOut,
    DuplicateScanOut,
    DocumentCompositionOut,
    DocumentCacheStatusOut,
    DocumentPatch,
    DocumentPagePatch,
    DocumentRecommendationDownloadCreate,
    DocumentRecommendationDownloadOut,
    DocumentRecommendationOut,
    DocumentRecommendationRefreshOut,
    DocumentTextScrub,
    DocumentTrashOut,
    DocumentTrashRequest,
    DocumentVersionOut,
    DocumentVisualPageScanApplyCreate,
    DocumentVisualPageScanCreate,
    DocumentVisualPageScanReviewOut,
    DoiStashCreate,
    DoiStashImportOut,
    DoiStashOut,
    DocumentListOut,
    DocumentListRow,
    DocumentSummary,
    FigurePatch,
    GcsBucketLifecycleOut,
    DomainCreate,
    DomainDeleteOut,
    DomainOut,
    DomainPatch,
    DomainReorder,
    IngestionHistoryOut,
    ImportBatchOut,
    ImportDuplicateCheckOut,
    ImportDuplicateDocumentOut,
    ImportDuplicateFileOut,
    ImportJobOut,
    ImportQueueActionOut,
    HAProxyStatsStatusOut,
    LibraryFunStatsOut,
    LoginRequest,
    NoteCreate,
    NoteOut,
    NotePatch,
    ModelPricingStatusOut,
    OpenAIUsageOut,
    ProcessingEventOut,
    PortfolioAssessmentCreate,
    PortfolioAssessmentRunOut,
    PortfolioItemCreate,
    PortfolioItemOut,
    PortfolioItemPatch,
    PortfolioSuggestionOut,
    PortfolioSuggestionRefreshOut,
    ProjectCreate,
    ProjectDetail,
    ProjectItemCreate,
    ProjectItemOut,
    ProjectItemPatch,
    ProjectOut,
    ReleaseStatusOut,
    ReconEstimateOut,
    ReconInquiryCreate,
    ReconInquiryOut,
    ReconInquiryPatch,
    ReconRunCreate,
    ReconRunOut,
    RestoreDatabaseCreate,
    RuntimeLocationOut,
    SavedSearchCreate,
    SavedSearchOut,
    SavedSearchPatch,
    SlipstreamCheckInCreate,
    SlipstreamClaimCreate,
    SlipstreamClaimOut,
    SlipstreamClientOut,
    SlipstreamEnrollmentCreate,
    SlipstreamEnrollmentOut,
    SlipstreamEventCreate,
    SlipstreamFailCreate,
    SlipstreamHeartbeatCreate,
    SlipstreamLeaseOut,
    SlipstreamRegisterCreate,
    SlipstreamResultCreate,
    SlipstreamStatusOut,
    TagCreate,
    TagAssignmentPruneCreate,
    TagGovernancePatch,
    TagMerge,
    TagOperationOut,
    TagOrphanPruneCreate,
    TagOrphanPruneOut,
    TagOptimizationApproveAllCreate,
    TagOptimizationApproveAllOut,
    TagOptimizationCreate,
    TagOptimizationOut,
    TagPruneOut,
    TagRelationshipCreate,
    TagRelationshipOut,
    TagOptimizationSuggestionOut,
    TagOut,
    TagRename,
    TwoFactorDisableRequest,
    TwoFactorEnableOut,
    TwoFactorEnableRequest,
    TwoFactorSetupOut,
    TwoFactorSetupRequest,
    UserOut,
)
from app.security import (
    create_session,
    ensure_admin_user,
    generate_recovery_codes,
    generate_totp_secret,
    hash_password,
    hash_recovery_codes,
    revoke_other_sessions,
    revoke_session,
    touch_session,
    totp_setup_uri,
    user_for_token,
    verify_password,
    verify_totp_code,
    verify_two_factor_code,
)
from app.services.accessory_summaries import AccessorySummaryProcessor, create_accessory_summary
from app.services.analysis_models import (
    MODEL_APA_CITATION,
    MODEL_KEYWORDS_TOPICS,
    MODEL_METADATA,
    MODEL_PAGE_TEXT_NORMALIZATION,
    MODEL_PORTFOLIO_ASSESSMENT,
    MODEL_RAW_TEXT_EXTRACTION,
    MODEL_RECON_INQUIRY,
    MODEL_SUMMARY,
    MODEL_TEXT_CHUNK_ENCODING,
)
from app.services.backups import (
    create_database_backup_run,
    create_restore_run,
    current_database_size_bytes,
    estimate_backup_size,
    launch_database_backup,
    launch_database_restore,
    list_backup_artifacts,
    list_backup_runs,
    list_gcs_backup_artifacts,
    restore_source_from_artifact_uri,
    save_restore_upload,
)
from app.services.cache import (
    CACHE_ALL_REVISION_FAMILIES,
    bump_cache_revisions,
    cache_status_payload,
    get_cached_payload,
    get_cache_backend,
    install_cache_revision_hooks,
    set_cached_payload,
)
from app.services.concordance import create_concordance_run, current_capabilities, estimate_concordance_run
from app.services.composition import active_import_cost_usd, document_composition_summary, record_import_cost_estimate, record_manual_edit
from app.services.citations import format_apa_citation, format_apa_in_text_citation, format_bibtex, format_ris, to_csl_json
from app.services.container_footprint import container_footprint_status, request_container_restart
from app.services.document_cache import (
    current_document_cache_usage,
    document_cache_root,
    ensure_document_pdf_bytes,
    metadata_cache_path,
    register_document_cache,
)
from app.services.document_visibility import (
    LIBRARY_VISIBLE_DOCUMENT_STATUSES,
    document_is_library_visible,
    filter_library_visible_documents,
    library_visible_document_filter,
)
from app.services.duplicates import (
    DUPLICATE_FALSE_POSITIVES_KEY,
    DuplicateMatch,
    active_duplicate_matches_for_profile,
    document_duplicate_profile,
    duplicate_false_positive_document_ids,
    duplicate_document_version_stats,
    duplicate_match_reasons,
    duplicate_match_score,
    duplicate_matches_by_document,
    duplicate_pair_dismissed,
    import_duplicate_profile,
    match_basis,
)
from app.services.exports import build_metadata_export, build_storage_manifest
from app.services.haproxy_stats import haproxy_stats_status
from app.services.gcs_lifecycle import gcs_bucket_lifecycle_status
from app.services.history import changed_snapshot_fields, document_correction_snapshot, document_page_snapshot, record_document_version
from app.services.import_sources import ImportSourceError, estimate_pdf_page_count, prepare_import_source
from app.services.maintenance import (
    mark_database_maintenance_active,
    mark_database_maintenance_finished,
    maintenance_readiness,
)
from app.services.ai import get_ai_service
from app.services.figures import apply_document_figures_page_candidates, preview_document_figures_page_from_storage
from app.services.processing import (
    apply_document_citations,
    document_metadata,
    log_event,
    refresh_import_batch_progress,
)
from app.services.preferences import (
    get_analysis_model,
    get_analysis_models,
    get_app_preferences,
    get_download_naming_template,
    get_valkey_maxmemory,
    import_processing_snapshot,
    import_processing_cloud_page_cap,
    render_download_filename,
    store_google_service_account,
    update_app_preferences,
)
from app.services.recon import (
    cancel_recon_run,
    create_recon_inquiry,
    document_recon_text,
    estimate_recon_run,
    retrieve_recon_evidence,
    run_recon_inquiry,
    update_recon_inquiry,
)
from app.services.openai_usage import (
    OpenAIUsageContext,
    estimated_cost_usd_for_model_tokens,
    estimated_cost_usd_for_record,
    openai_usage_summary,
    refresh_model_pricing,
)
from app.services.performance import (
    begin_request_performance_stats,
    current_request_performance_stats,
    install_sqlalchemy_performance_timing,
    record_route_performance,
    reset_request_performance_stats,
    route_performance_summary,
)
from app.services.recommendations import (
    document_has_recommendation_inputs,
    doi_url,
    list_document_recommendations,
    normalize_doi,
    queue_doi_stash_open_pdf_import,
    queue_recommendation_imports,
    refresh_document_recommendations,
    resolve_doi_metadata_candidate,
)
from app.services.release_status import (
    release_status,
    request_maintenance_run,
    request_release_check,
    request_release_upgrade,
)
from app.services.runtime_location import detect_server_ipv4, runtime_location_payload
from app.services.search import document_search_condition_and_rank, rebuild_document_search_text
from app.services.slipstream import (
    SlipstreamAuthError,
    SlipstreamError,
    artifact_for_lease,
    cancel_lease,
    claim_next_job_lease,
    client_out,
    complete_lease_from_result,
    create_enrollment,
    enrollment_out,
    fail_lease,
    heartbeat_lease,
    record_client_event,
    register_client,
    revoke_client,
    slipstream_status,
    validate_lease_access,
    verify_signature,
)
from app.services.verifier import normalized_title_similarity
from app.services.tag_governance import (
    hybrid_tag_similarity,
    normalize_governance_status,
    normalize_relationship_type,
    pruning_review_suggestions,
    relationship_review_suggestions,
    status_review_suggestions,
    tag_health_summary,
)
from app.services.storage import get_storage_service
from app.services.tags import (
    get_or_create_tag as get_or_create_canonical_tag,
    normalize_tag_name as normalize_canonical_tag_name,
    remember_tag_merge_aliases,
    resolve_tag_alias,
)


settings = get_settings()
app = FastAPI(title="Medusa Research Library", version="0.1.0")
SERVER_IPV4: str | None = None
PERFORMANCE_LOG_MIN_MS = 250.0
performance_logger = logging.getLogger("medusa.performance")
install_sqlalchemy_performance_timing(engine)
install_cache_revision_hooks()

DUPLICATE_IMPORT_STRATEGIES = {"skip", "overwrite", "import_anyway"}
STAGED_IMPORT_STATUS = "staged"
IMPORT_JOB_QUEUE_STATUSES = ("staged", "queued", "running", "failed", "restored_paused")
IMPORT_JOB_CLEARABLE_STATUSES = ("staged", "queued", "running", "failed", "restored_paused")
IMPORT_CACHE_TERMINAL_JOB_STATUSES = ("cleared", "complete")
IMPORT_DUPLICATE_DOCUMENT_STATUSES = (
    "ready",
    "complete",
    "completed",
    "restored",
    "staged",
    "queued",
    "running",
    "failed",
    "restored_paused",
)
DEFAULT_IMPORT_ESTIMATE_USD_PER_PAGE = 0.04
PDF_PREVIEW_RENDER_SCALE = 2.5
CACHE_HYDRATE_LIST_PAGE_SIZE = 50
CACHE_HYDRATE_MAX_DOCUMENTS = 10000
RECENT_AI_FAILURE_NOTICE_LIMIT = 8
RECENT_AI_FAILURE_NOTICE_MAX_AGE = timedelta(minutes=30)
IMPORT_ESTIMATE_CALIBRATION_MIN = 0.25
IMPORT_ESTIMATE_CALIBRATION_MAX = 4.0
IMPORT_ESTIMATE_INPUT_TOKENS_PER_PAGE = 650
WORD_RE = re.compile(r"\b[\w]+(?:[’'\-][\w]+)*\b", re.UNICODE)
REFERENCE_ENTRY_RE = re.compile(r"^\s*(?:\[\d+\]|\d+[\).]|[A-Z][\w'’\-]+,\s+[A-Z])")
DATABASE_MAINTENANCE_LABELS = {
    "backfill_document_md5": "Backfill Document Hashes",
    "compact_database": "Compact Database",
    "optimize_database": "Optimize Database",
}
DATABASE_MAINTENANCE_DETAILS = {
    "backfill_document_md5": "Hydrating originals into the document cache and writing missing MD5 hashes.",
    "compact_database": "Compacting database with PostgreSQL VACUUM FULL and ANALYZE.",
    "optimize_database": "Refreshing PostgreSQL planner statistics with ANALYZE.",
}
DATABASE_MAINTENANCE_LOCK = threading.Lock()
DATABASE_MAINTENANCE_STATE: dict[str, Any] = {
    "active_operation": None,
    "active_operation_started_at": None,
    "active_operation_status_detail": None,
    "last_operation": None,
    "last_operation_status": None,
    "last_operation_completed_at": None,
    "last_operation_status_detail": None,
    "last_operation_error": None,
    "last_operation_database_size_before_bytes": None,
    "last_operation_database_size_after_bytes": None,
}
IMPORT_ESTIMATE_TASK_TOKEN_PROFILES: dict[str, dict[str, int]] = {
    MODEL_METADATA: {"input_per_page": 2000, "output_base": 900},
    MODEL_SUMMARY: {"input_per_page": 950, "output_base": 1000},
    MODEL_APA_CITATION: {"input_per_page": 500, "output_base": 650},
    MODEL_KEYWORDS_TOPICS: {"input_per_page": 1100, "output_base": 400},
    MODEL_PAGE_TEXT_NORMALIZATION: {"input_per_page": 1200, "output_per_page": 900},
    MODEL_TEXT_CHUNK_ENCODING: {"input_per_page": 950, "output_base": 0},
}
IMPORT_ESTIMATE_LOCAL_MODELS = {"", "local", "none", "marker", "pymupdf", "docling"}
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def record_request_performance(request: Request, call_next):
    token = begin_request_performance_stats()
    started_at = perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        elapsed_ms = (perf_counter() - started_at) * 1000
        stats = current_request_performance_stats()
        reset_request_performance_stats(token)
        if response is not None and request.url.path.startswith("/api/"):
            response.headers["X-Medusa-Request-Duration-Ms"] = f"{elapsed_ms:.1f}"
            response.headers["X-Medusa-Sql-Count"] = str(stats.sql_count if stats else 0)
            response.headers["X-Medusa-Sql-Duration-Ms"] = f"{stats.sql_ms:.1f}" if stats else "0.0"
            record_route_performance(request.url.path, elapsed_ms, response.status_code, PERFORMANCE_LOG_MIN_MS)
        if request.url.path.startswith("/api/") and elapsed_ms >= PERFORMANCE_LOG_MIN_MS:
            performance_logger.info(
                "slow_api_request method=%s path=%s status=%s duration_ms=%.1f sql_count=%s sql_ms=%.1f",
                request.method,
                request.url.path,
                getattr(response, "status_code", "error"),
                elapsed_ms,
                stats.sql_count if stats else 0,
                stats.sql_ms if stats else 0.0,
            )


@app.on_event("startup")
def on_startup() -> None:
    global SERVER_IPV4
    SERVER_IPV4 = detect_server_ipv4()
    init_db()
    with session_scope() as db:
        ensure_admin_user(db)
        apply_valkey_maxmemory_preference(db)


@app.get("/api/runtime-location", response_model=RuntimeLocationOut)
def runtime_location(browser_host: str | None = Query(default=None, max_length=255)) -> dict[str, str | None]:
    return runtime_location_payload(browser_host, SERVER_IPV4)


def _metrics_snapshot_token(request: Request) -> str:
    auth_header = (request.headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return (request.headers.get("x-medusa-metrics-token") or "").strip()


def _require_metrics_snapshot_access(request: Request) -> None:
    expected = (settings.metrics_internal_token or "").strip()
    if not expected:
        raise HTTPException(status_code=404, detail="Metrics snapshot endpoint is disabled")
    provided = _metrics_snapshot_token(request)
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Metrics snapshot access denied")


@app.get("/api/internal/metrics/snapshot")
def internal_metrics_snapshot(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    _require_metrics_snapshot_access(request)
    return jsonable_encoder(
        {
            "checked_at": utc_now(),
            "cache": cache_status_payload(db, request_metrics=route_performance_summary(limit=24)),
            "container": container_footprint_status(),
            "database_maintenance": database_maintenance_status_out(db),
            "release": release_status(db=db),
        }
    )


def parse_json_form(value: str | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON form field: {exc}") from exc


def current_user(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    user = user_for_token(db, token)
    if user:
        return user
    if settings.local_auto_login:
        user = ensure_admin_user(db)
        if user.is_active:
            session_token = create_session(db, user, user_agent=request.headers.get("user-agent"))
            set_session_cookie(response, session_token)
            return user
    raise HTTPException(status_code=401, detail="Authentication required")


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.session_ttl_hours * 3600,
    )


def _request_uses_tls(request: Request) -> bool:
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
    if forwarded_proto == "https" or request.url.scheme == "https":
        return True
    client_host = request.client.host if request.client else ""
    return client_host in {"127.0.0.1", "::1", "localhost", "testclient"}


async def current_slipstream_client(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> SlipstreamClient:
    if settings.slipstream_require_tls and not _request_uses_tls(request):
        raise HTTPException(status_code=403, detail="Slipstream requires HTTPS.")
    client_id = request.headers.get("x-slipstream-client-id")
    timestamp = request.headers.get("x-slipstream-timestamp")
    nonce = request.headers.get("x-slipstream-nonce")
    request_body_hash = request.headers.get("x-slipstream-body-sha256")
    signature = request.headers.get("x-slipstream-signature")
    if not all([client_id, timestamp, nonce, request_body_hash, signature]):
        raise HTTPException(status_code=401, detail="Slipstream signature headers are required.")
    client = db.get(SlipstreamClient, client_id)
    if not client:
        raise HTTPException(status_code=401, detail="Slipstream client not found.")
    body = await request.body()
    try:
        verify_signature(
            client,
            method=request.method,
            path=request.url.path,
            timestamp=str(timestamp),
            nonce=str(nonce),
            request_body_hash=str(request_body_hash),
            signature=str(signature),
            body=body,
        )
    except SlipstreamAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return client


def slipstream_lease_token(request: Request) -> str | None:
    return request.headers.get("x-slipstream-lease-token")


def http_error_for_slipstream(exc: Exception) -> HTTPException:
    if isinstance(exc, SlipstreamAuthError):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, SlipstreamError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def apply_valkey_maxmemory_preference(db: Session) -> None:
    maxmemory = get_valkey_maxmemory(db)
    get_cache_backend().configure_maxmemory(maxmemory)


def set_cache_response_headers(response: Response | None, family: str, status: str) -> None:
    if response is None:
        return
    response.headers["X-Medusa-Cache"] = status
    response.headers["X-Medusa-Cache-Family"] = family


def cache_or_load(
    db: Session,
    response: Response | None,
    *,
    family: str,
    revision_families: list[str] | tuple[str, ...] | set[str],
    key_parts: dict[str, Any],
    loader,
):
    status, payload, key, _ = get_cached_payload(
        db,
        family=family,
        revision_families=revision_families,
        key_parts=key_parts,
    )
    if payload is not None:
        set_cache_response_headers(response, family, status)
        return payload
    result = loader()
    write_status = set_cached_payload(key, family, result)
    set_cache_response_headers(response, family, status if status != "miss" or write_status != "error" else "miss")
    return result


def warm_cache_payload(
    db: Session,
    *,
    family: str,
    revision_families: list[str] | tuple[str, ...] | set[str],
    key_parts: dict[str, Any],
    loader,
) -> bool:
    return warm_cache_payload_status(
        db,
        family=family,
        revision_families=revision_families,
        key_parts=key_parts,
        loader=loader,
    ) == "write"


def warm_cache_payload_status(
    db: Session,
    *,
    family: str,
    revision_families: list[str] | tuple[str, ...] | set[str],
    key_parts: dict[str, Any],
    loader,
) -> str:
    status, _ = warm_cache_payload_result(
        db,
        family=family,
        revision_families=revision_families,
        key_parts=key_parts,
        loader=loader,
    )
    return status


def warm_cache_payload_result(
    db: Session,
    *,
    family: str,
    revision_families: list[str] | tuple[str, ...] | set[str],
    key_parts: dict[str, Any],
    loader,
) -> tuple[str, Any]:
    _, _, key, _ = get_cached_payload(
        db,
        family=family,
        revision_families=revision_families,
        key_parts=key_parts,
    )
    result = loader()
    return set_cached_payload(key, family, result), result


def domain_out(
    domain: Domain,
    db: Session | None = None,
    subtree_document_count: int | None = None,
    document_count: int | None = None,
    tag_count_map: dict[str, int] | None = None,
) -> DomainOut:
    document_count = (
        document_count
        if document_count is not None
        else domain_document_count(db, domain.id)
        if db is not None
        else len([document for document in domain.documents if document_is_library_visible(document)])
    )
    tag_counts = tag_count_map or {}
    return DomainOut(
        id=domain.id,
        parent_id=domain.parent_id,
        name=domain.name,
        description=domain.description,
        color=domain.color,
        sort_order=domain.sort_order,
        document_count=document_count,
        subtree_document_count=subtree_document_count
        if subtree_document_count is not None
        else (domain_subtree_document_count(db, domain.id) if db else document_count),
        tags=[tag_out(tag, db, document_count=tag_counts.get(tag.id)) for tag in sorted(domain.tags, key=lambda item: item.name.lower())] if db else [],
    )


def tag_document_count(db: Session, tag_id: str) -> int:
    return (
        db.query(func.count(Document.id))
        .select_from(Document)
        .join(Document.tags)
        .filter(Tag.id == tag_id, library_visible_document_filter())
        .scalar()
        or 0
    )


def tag_document_counts(db: Session, tag_ids: list[str]) -> dict[str, int]:
    unique_ids = unique_tag_ids(tag_ids)
    if not unique_ids:
        return {}
    rows = (
        db.query(document_tags.c.tag_id, func.count(Document.id))
        .select_from(document_tags)
        .join(Document, Document.id == document_tags.c.document_id)
        .filter(document_tags.c.tag_id.in_(unique_ids), library_visible_document_filter())
        .group_by(document_tags.c.tag_id)
        .all()
    )
    return {str(tag_id): int(count or 0) for tag_id, count in rows}


def tag_document_link_count(db: Session, tag_id: str) -> int:
    return int(db.execute(select(func.count()).select_from(document_tags).where(document_tags.c.tag_id == tag_id)).scalar() or 0)


def tag_out(tag: Tag, db: Session, document_count: int | None = None) -> TagOut:
    return TagOut(
        id=tag.id,
        name=tag.name,
        kind=tag.kind,
        color=tag.color,
        status=tag.status,
        definition=tag.definition,
        use_guidance=tag.use_guidance,
        avoid_guidance=tag.avoid_guidance,
        document_count=tag_document_count(db, tag.id) if document_count is None else document_count,
    )


def tag_relationship_out(relationship: TagRelationship, db: Session) -> TagRelationshipOut:
    return TagRelationshipOut(
        id=relationship.id,
        source_tag=tag_out(relationship.source_tag, db),
        target_tag=tag_out(relationship.target_tag, db),
        relationship_type=relationship.relationship_type,
        status=relationship.status,
        rationale=relationship.rationale,
        confidence=float(relationship.confidence) if relationship.confidence is not None else None,
    )


def project_out(project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,
        due_at=project.due_at,
        item_count=len(project.items),
    )


def project_detail_out(project: Project) -> ProjectDetail:
    items = [
        item
        for item in sorted(project.items, key=lambda value: (value.used_in_output, value.status, value.created_at, value.id))
        if document_is_library_visible(item.document)
    ]
    base = project_out(project).model_dump()
    base["item_count"] = len(items)
    return ProjectDetail(**base, items=items)


def unique_preserve_order(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def project_summaries_for_documents(db: Session, document_ids: list[str]) -> dict[str, list[ProjectOut]]:
    unique_document_ids = unique_preserve_order(document_ids)
    if not unique_document_ids:
        return {}
    items = (
        db.query(ProjectItem)
        .options(joinedload(ProjectItem.project))
        .join(Project, Project.id == ProjectItem.project_id)
        .filter(ProjectItem.document_id.in_(unique_document_ids), Project.deleted_at.is_(None))
        .all()
    )
    project_ids = unique_preserve_order([item.project_id for item in items])
    item_counts = (
        {
            project_id: int(count)
            for project_id, count in db.query(ProjectItem.project_id, func.count(ProjectItem.id))
            .filter(ProjectItem.project_id.in_(project_ids))
            .group_by(ProjectItem.project_id)
            .all()
        }
        if project_ids
        else {}
    )
    summaries: dict[str, list[ProjectOut]] = {document_id: [] for document_id in unique_document_ids}
    seen_pairs: set[tuple[str, str]] = set()
    for item in sorted(items, key=lambda value: ((value.project.name or "").lower(), value.project.id)):
        project = item.project
        pair = (item.document_id, project.id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        summaries.setdefault(item.document_id, []).append(
            ProjectOut(
                id=project.id,
                name=project.name,
                description=project.description,
                status=project.status,
                due_at=project.due_at,
                item_count=item_counts.get(project.id, 0),
            )
        )
    return summaries


def apply_document_filters(
    query,
    db: Session,
    *,
    q: str | None = None,
    domain_id: str | None = None,
    tag_id: str | None = None,
    read_status: str | None = None,
    priority: str | None = None,
    citation_status: str | None = None,
):
    search_rank = None
    if q:
        condition, search_rank = document_search_condition_and_rank(db, q)
        if condition is not None:
            query = query.filter(condition)
    if domain_id:
        query = query.filter(Document.domains.any(Domain.id == domain_id))
    if tag_id:
        query = query.filter(Document.tags.any(Tag.id == tag_id))
    if read_status:
        query = query.filter(Document.read_status == read_status)
    if priority:
        query = query.filter(Document.priority == priority)
    if citation_status:
        query = query.filter(Document.citation_status == citation_status)
    return query, search_rank


def document_title_order_columns(db: Session):
    title_key = func.lower(Document.title)
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        title_key = title_key.collate("C")
    return title_key, Document.title, Document.id


def normalize_document_title_spacing(value: str | None) -> str:
    return " ".join((value or "").split())


def duplicate_reason_labels(matches: list[DuplicateMatch]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for match in matches:
        for reason in match.match_reasons:
            label = reason.replace("_", " ")
            if label not in seen:
                seen.add(label)
                labels.append(label)
    return labels


def duplicate_matches_for_documents(db: Session, documents: list[Document]) -> dict[str, list[DuplicateMatch]]:
    if not documents:
        return {}
    visible_documents = filter_library_visible_documents(db.query(Document)).all()
    target_ids = {document.id for document in documents}
    visible_ids = {document.id for document in visible_documents}
    if target_ids == visible_ids:
        return duplicate_matches_by_document(db, documents=visible_documents)
    profiles = {document.id: document_duplicate_profile(document) for document in visible_documents}
    matches: dict[str, list[DuplicateMatch]] = {document.id: [] for document in documents}
    for document in documents:
        left_profile = profiles.get(document.id) or document_duplicate_profile(document)
        for candidate in visible_documents:
            if candidate.id == document.id or duplicate_pair_dismissed(document, candidate):
                continue
            reasons = duplicate_match_reasons(left_profile, profiles[candidate.id])
            score = duplicate_match_score(reasons)
            if score < 60:
                continue
            matches[document.id].append(DuplicateMatch(document=candidate, match_reasons=reasons, match_score=score))
    for document_matches in matches.values():
        document_matches.sort(key=lambda item: (-item.match_score, item.document.created_at, item.document.id))
    return matches


def duplicate_summary_by_document(db: Session, documents: list[Document] | None = None) -> dict[str, dict[str, Any]]:
    matches = duplicate_matches_for_documents(db, documents) if documents is not None else duplicate_matches_by_document(db)
    return {
        document_id: {
            "duplicate_count": len(document_matches),
            "duplicate_document_ids": [match.document.id for match in document_matches],
            "duplicate_reasons": duplicate_reason_labels(document_matches),
        }
        for document_id, document_matches in matches.items()
    }


def persist_duplicate_match_summaries(
    db: Session,
    documents: list[Document],
    matches: dict[str, list[DuplicateMatch]],
):
    checked_at = utc_now()
    for document in documents:
        document_matches = matches.get(document.id, [])
        document.duplicate_count = len(document_matches)
        document.duplicate_reasons = duplicate_reason_labels(document_matches)
        document.duplicate_checked_at = checked_at
        db.add(document)


def refresh_duplicate_match_summaries(db: Session) -> dict[str, list[DuplicateMatch]]:
    documents = filter_library_visible_documents(db.query(Document)).all()
    matches = duplicate_matches_by_document(db, documents=documents)
    persist_duplicate_match_summaries(db, documents, matches)
    return matches


def persisted_duplicate_summary_by_document(documents: list[Document]) -> dict[str, dict[str, Any]]:
    return {
        document.id: {
            "duplicate_count": int(document.duplicate_count or 0),
            "duplicate_reasons": list(document.duplicate_reasons or []),
        }
        for document in documents
    }


def duplicate_document_out(document: Document, match: DuplicateMatch | None = None) -> ImportDuplicateDocumentOut:
    return ImportDuplicateDocumentOut(
        id=document.id,
        title=document.title,
        original_filename=document.original_filename,
        created_at=document.created_at,
        processing_status=document.processing_status,
        match_reasons=match.match_reasons if match else [],
        match_basis=match.match_basis if match else None,
        match_score=match.match_score if match else 0,
    )


def prepared_import_duplicate_profile(prepared) -> Any:
    return import_duplicate_profile(
        title=prepared.title,
        original_filename=prepared.stored_filename,
        source_checksum_sha256=prepared.source_checksum_sha256,
        stored_checksum_sha256=prepared.stored_checksum_sha256,
        source_checksum_md5=prepared.source_checksum_md5,
        stored_checksum_md5=prepared.stored_checksum_md5,
        page_count=prepared.stored_page_count,
    )


def same_drop_duplicate_reasons(left: Any, right: Any) -> list[str]:
    reasons = duplicate_match_reasons(left, right)
    return reasons if {"sha256", "md5", "doi"}.intersection(reasons) else []


NO_DOI_METADATA_KEY = "no_doi"
BIBLIOGRAPHY_VERIFICATION_METADATA_KEY = "bibliography_verification"
DOCUMENT_FIELD_VERIFICATION_CONFIG = {
    "doi": {"attribute": "doi", "metadata_key": "doi_verification", "label": "DOI"},
    "apa_citation": {
        "attribute": "apa_citation",
        "metadata_key": "apa_citation_verification",
        "label": "APA reference list",
    },
    "apa_in_text_citation": {
        "attribute": "apa_in_text_citation",
        "metadata_key": "apa_in_text_citation_verification",
        "label": "APA in-text citation",
    },
    "bibliography": {
        "attribute": "bibliography",
        "metadata_key": BIBLIOGRAPHY_VERIFICATION_METADATA_KEY,
        "label": "Bibliography",
    },
}


def no_doi_flag_from_evidence(evidence: dict[str, Any] | None, doi: str | None = None) -> bool:
    if doi:
        return False
    marker = (evidence or {}).get(NO_DOI_METADATA_KEY)
    if isinstance(marker, dict):
        return marker.get("status") == "confirmed" or marker.get("confirmed") is True
    return marker is True


def document_no_doi(document: Document) -> bool:
    return no_doi_flag_from_evidence(document.metadata_evidence, document.doi)


def document_has_author_identity(document: Document) -> bool:
    return any(" ".join(str(author.get(key) or "").strip() for key in ["given", "family"]).strip() for author in (document.authors or []))


def document_matches_health_status(document: Document, health_status: str) -> bool:
    if health_status == "doi_gap":
        return not document.doi and not document_no_doi(document)
    if health_status == "identity_gap":
        return not document_has_author_identity(document) or not document.publication_year
    return False


def apply_document_health_filter(query, health_status: str | None):
    health_status = (health_status or "").strip()
    if not health_status:
        return query
    if health_status == "citation_review":
        return query.filter(Document.citation_status != "verified")
    if health_status == "missing_summary":
        return query.filter(or_(Document.rich_summary.is_(None), func.trim(Document.rich_summary) == ""))
    if health_status == "unfiled_domains":
        return query.filter(~Document.domains.any())
    if health_status == "untagged":
        return query.filter(~Document.tags.any())
    if health_status == "no_project_use":
        return query.filter(~Document.id.in_(select(ProjectItem.document_id)))
    if health_status in {"doi_gap", "identity_gap"}:
        document_ids = [document.id for document in query.all() if document_matches_health_status(document, health_status)]
        return query.filter(Document.id.in_(document_ids))
    return query


def document_summary_out(
    document: Document,
    duplicate_count: int = 0,
    projects: list[ProjectOut] | None = None,
    duplicate_reasons: list[str] | None = None,
) -> DocumentSummary:
    return DocumentSummary.model_validate(document).model_copy(
        update={
            "duplicate_count": duplicate_count,
            "duplicate_reasons": duplicate_reasons or [],
            "projects": projects or [],
            "no_doi": document_no_doi(document),
        }
    )


def document_list_row_out(document: Document, projects: list[ProjectOut] | None = None) -> DocumentListRow:
    return DocumentListRow.model_validate(document).model_copy(
        update={
            "duplicate_count": int(document.duplicate_count or 0),
            "duplicate_reasons": list(document.duplicate_reasons or []),
            "projects": projects or [],
            "no_doi": document_no_doi(document),
        }
    )


def parse_evidence_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def document_bibliography_generated_at(document: Document, db: Session) -> datetime | None:
    if not document.bibliography:
        return None
    evidence = document.metadata_evidence or {}
    bibliography_evidence = evidence.get("bibliography_extraction")
    if isinstance(bibliography_evidence, dict):
        generated_at = parse_evidence_datetime(bibliography_evidence.get("generated_at"))
        if generated_at:
            return generated_at
    capability = (
        db.query(DocumentCapability)
        .filter(
            DocumentCapability.document_id == document.id,
            DocumentCapability.capability_key == "bibliography_extraction",
            DocumentCapability.status == "complete",
        )
        .one_or_none()
    )
    return parse_evidence_datetime(capability.completed_at) if capability else None


def document_field_verification(document: Document, field: str) -> dict[str, Any] | None:
    config = DOCUMENT_FIELD_VERIFICATION_CONFIG.get(field)
    if not config:
        return None
    value = getattr(document, str(config["attribute"]), None)
    if not (str(value or "").strip()):
        return None
    evidence = document.metadata_evidence or {}
    verification = evidence.get(str(config["metadata_key"]))
    if not isinstance(verification, dict) or verification.get("status") != "verified":
        return None
    verified_at = parse_evidence_datetime(verification.get("verified_at"))
    if not verified_at:
        return None
    return {
        "verified_at": verified_at,
        "verified_by": str(verification.get("verified_by") or "").strip() or None,
    }


def document_field_is_verified(document: Document, field: str) -> bool:
    return document_field_verification(document, field) is not None


def clear_document_field_verifications(document: Document, fields: Iterable[str]) -> bool:
    evidence = dict(document.metadata_evidence or {})
    changed = False
    for field in fields:
        config = DOCUMENT_FIELD_VERIFICATION_CONFIG.get(field)
        if not config:
            continue
        if evidence.pop(str(config["metadata_key"]), None) is not None:
            changed = True
    if changed:
        document.metadata_evidence = evidence
    return changed


def verified_document_fields(document: Document, fields: Iterable[str]) -> list[str]:
    return [field for field in fields if document_field_is_verified(document, field)]


def verified_document_field_labels(fields: Iterable[str]) -> list[str]:
    return [
        str(DOCUMENT_FIELD_VERIFICATION_CONFIG[field]["label"])
        for field in fields
        if field in DOCUMENT_FIELD_VERIFICATION_CONFIG
    ]


def document_bibliography_verification(document: Document) -> dict[str, Any] | None:
    return document_field_verification(document, "bibliography")


def document_bibliography_is_verified(document: Document) -> bool:
    return document_field_is_verified(document, "bibliography")


def clear_document_bibliography_verification(document: Document) -> bool:
    return clear_document_field_verifications(document, ["bibliography"])


def compact_document_version_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in (
        "changed_fields",
        "operation",
        "scrub_count",
        "restored_version_number",
        "candidate_id",
        "kept_document_id",
        "duplicate_document_id",
    ):
        if key in snapshot:
            compact[key] = snapshot[key]

    target_document = restorable_document_snapshot(snapshot)
    target_pages = restorable_page_snapshots(snapshot)
    preview_lines: list[str] = []
    if target_document:
        title = target_document.get("title")
        if isinstance(title, str) and title.strip():
            preview_lines.append(title.strip())
        year = target_document.get("publication_year")
        if isinstance(year, int | str):
            preview_lines.append(f"Year {year}")
        tags = target_document.get("tags")
        if isinstance(tags, list) and tags:
            preview_lines.append(f"{len(tags)} tags")
        attributes = target_document.get("attributes")
        if isinstance(attributes, dict) and attributes:
            preview_lines.append(f"{len(attributes)} attributes")
    if len(target_pages) == 1 and isinstance(target_pages[0].get("page_number"), int):
        preview_lines.append(f"Page {target_pages[0]['page_number']}")
    elif len(target_pages) > 1:
        preview_lines.append(f"{len(target_pages)} pages")
    scrub_count = snapshot.get("scrub_count")
    if isinstance(scrub_count, int):
        preview_lines.append(f"{scrub_count} scrubbed")
    compact["restorable"] = bool(target_document or target_pages)
    if preview_lines:
        compact["preview_lines"] = preview_lines
    return compact


def document_version_out(version: DocumentVersion) -> DocumentVersionOut:
    return DocumentVersionOut.model_validate(version).model_copy(
        update={"metadata_snapshot": compact_document_version_snapshot(version.metadata_snapshot)}
    )


def document_detail_out(document: Document, db: Session) -> DocumentDetail:
    duplicate_summary = persisted_duplicate_summary_by_document([document]).get(document.id, {})
    projects = project_summaries_for_documents(db, [document.id]).get(document.id, [])
    doi_verification = document_field_verification(document, "doi")
    apa_citation_verification = document_field_verification(document, "apa_citation")
    apa_in_text_citation_verification = document_field_verification(document, "apa_in_text_citation")
    bibliography_verification = document_bibliography_verification(document)
    return DocumentDetail.model_validate(document).model_copy(
        update={
            "duplicate_count": duplicate_summary.get("duplicate_count", 0),
            "duplicate_reasons": duplicate_summary.get("duplicate_reasons", []),
            "duplicate_document_ids": [],
            "projects": projects,
            "no_doi": document_no_doi(document),
            "bibliography_generated_at": document_bibliography_generated_at(document, db),
            "doi_verified_at": doi_verification["verified_at"] if doi_verification else None,
            "doi_verified_by": doi_verification["verified_by"] if doi_verification else None,
            "apa_citation_verified_at": apa_citation_verification["verified_at"] if apa_citation_verification else None,
            "apa_citation_verified_by": apa_citation_verification["verified_by"] if apa_citation_verification else None,
            "apa_in_text_citation_verified_at": (
                apa_in_text_citation_verification["verified_at"] if apa_in_text_citation_verification else None
            ),
            "apa_in_text_citation_verified_by": (
                apa_in_text_citation_verification["verified_by"] if apa_in_text_citation_verification else None
            ),
            "bibliography_verified_at": bibliography_verification["verified_at"] if bibliography_verification else None,
            "bibliography_verified_by": bibliography_verification["verified_by"] if bibliography_verification else None,
            "versions": [document_version_out(version) for version in document.versions],
        }
    )


def duplicate_document_review_out(document: Document, version_stats: dict[str, Any] | None = None) -> DuplicateDocumentOut:
    stats = version_stats or {}
    return DuplicateDocumentOut(
        id=document.id,
        title=document.title,
        authors=document.authors or [],
        publication_year=document.publication_year,
        journal=document.journal,
        doi=document.doi,
        original_filename=document.original_filename,
        checksum_sha256=document.checksum_sha256,
        checksum_md5=document.checksum_md5,
        page_count=document.page_count,
        processing_status=document.processing_status,
        citation_status=document.citation_status,
        created_at=document.created_at,
        updated_at=document.updated_at,
        version_count=int(stats.get("version_count") or 0),
        latest_version_at=stats.get("latest_version_at"),
    )


def duplicate_pair_out(left: Document, right: Document, match: DuplicateMatch, stats: dict[str, dict[str, Any]]) -> DuplicatePairOut:
    ordered = sorted([left, right], key=lambda document: (document.title.lower(), document.created_at, document.id))
    return DuplicatePairOut(
        id=f"{ordered[0].id}:{ordered[1].id}",
        left=duplicate_document_review_out(ordered[0], stats.get(ordered[0].id)),
        right=duplicate_document_review_out(ordered[1], stats.get(ordered[1].id)),
        match_reasons=match.match_reasons,
        match_basis=match.match_basis,
        match_score=match.match_score,
    )


def append_duplicate_false_positive_evidence(
    document: Document,
    *,
    other_document: Document,
    dismissed_at,
    match_reasons: list[str],
    match_score: int,
    match_basis_text: str,
) -> None:
    evidence = dict(document.metadata_evidence or {})
    existing_records = evidence.get(DUPLICATE_FALSE_POSITIVES_KEY)
    records = [record for record in existing_records if isinstance(record, dict) and record.get("document_id") != other_document.id] if isinstance(existing_records, list) else []
    records.append(
        {
            "document_id": other_document.id,
            "document_title": other_document.title,
            "dismissed_at": dismissed_at.isoformat(),
            "match_reasons": match_reasons,
            "match_basis": match_basis_text,
            "match_score": match_score,
        }
    )
    evidence[DUPLICATE_FALSE_POSITIVES_KEY] = records
    document.metadata_evidence = evidence


def normalize_tag_name(name: str) -> str:
    return normalize_canonical_tag_name(name)


def normalize_domain_name(name: str) -> str:
    return " ".join(name.strip().split())


def normalize_domain_color(color: str | None) -> str | None:
    if color is None:
        return None
    normalized = color.strip().lower()
    if not normalized:
        return None
    if len(normalized) == 7 and normalized.startswith("#") and all(char in "0123456789abcdef" for char in normalized[1:]):
        return normalized
    raise HTTPException(status_code=400, detail="Domain color must be a #RRGGBB hex value")


def domain_document_count(db: Session | None, domain_id: str) -> int:
    if db is None:
        return 0
    return (
        db.query(Document)
        .filter(library_visible_document_filter(), Document.domains.any(Domain.id == domain_id))
        .count()
    )


def domain_document_counts(db: Session, domain_ids: list[str]) -> dict[str, int]:
    unique_ids = list(dict.fromkeys(domain_id for domain_id in domain_ids if domain_id))
    if not unique_ids:
        return {}
    rows = (
        db.query(document_domains.c.domain_id, func.count(Document.id))
        .select_from(document_domains)
        .join(Document, Document.id == document_domains.c.document_id)
        .filter(document_domains.c.domain_id.in_(unique_ids), library_visible_document_filter())
        .group_by(document_domains.c.domain_id)
        .all()
    )
    return {str(domain_id): int(count or 0) for domain_id, count in rows}


def domain_subtree_document_counts(db: Session, domains: list[Domain]) -> dict[str, int]:
    domain_ids = {domain.id for domain in domains}
    if not domain_ids:
        return {}
    children_by_parent: dict[str | None, list[str]] = {}
    for domain in domains:
        children_by_parent.setdefault(domain.parent_id, []).append(domain.id)

    subtree_ids_by_domain: dict[str, set[str]] = {}
    visiting: set[str] = set()

    def collect(domain_id: str) -> set[str]:
        if domain_id in subtree_ids_by_domain:
            return subtree_ids_by_domain[domain_id]
        if domain_id in visiting:
            return {domain_id}
        visiting.add(domain_id)
        ids = {domain_id}
        for child_id in children_by_parent.get(domain_id, []):
            ids.update(collect(child_id))
        visiting.remove(domain_id)
        subtree_ids_by_domain[domain_id] = ids
        return ids

    for domain_id in domain_ids:
        collect(domain_id)

    rows = (
        db.query(document_domains.c.domain_id, document_domains.c.document_id)
        .join(Document, Document.id == document_domains.c.document_id)
        .filter(library_visible_document_filter(), document_domains.c.domain_id.in_(domain_ids))
        .all()
    )
    document_ids_by_domain: dict[str, set[str]] = {}
    for domain_id, document_id in rows:
        document_ids_by_domain.setdefault(domain_id, set()).add(document_id)

    counts: dict[str, int] = {}
    for domain_id in domain_ids:
        subtree_document_ids: set[str] = set()
        for subtree_domain_id in subtree_ids_by_domain.get(domain_id, {domain_id}):
            subtree_document_ids.update(document_ids_by_domain.get(subtree_domain_id, set()))
        counts[domain_id] = len(subtree_document_ids)
    return counts


def domain_subtree_document_count(db: Session, domain_id: str) -> int:
    domains = db.query(Domain).filter(Domain.deleted_at.is_(None)).all()
    return domain_subtree_document_counts(db, domains).get(domain_id, 0)


def get_active_domain(db: Session, domain_id: str) -> Domain:
    domain = db.get(Domain, domain_id)
    if not domain or domain.deleted_at:
        raise HTTPException(status_code=404, detail="Domain not found")
    return domain


def active_domain_name_exists(db: Session, *, name: str, parent_id: str | None, exclude_id: str | None = None) -> bool:
    normalized_name = name.lower()
    query = db.query(Domain).filter(Domain.deleted_at.is_(None))
    if parent_id:
        query = query.filter(Domain.parent_id == parent_id)
    else:
        query = query.filter(Domain.parent_id.is_(None))
    if exclude_id:
        query = query.filter(Domain.id != exclude_id)
    return any((domain.name or "").lower() == normalized_name for domain in query.all())


def validate_domain_parent(db: Session, *, domain_id: str | None, parent_id: str | None) -> str | None:
    if not parent_id:
        return None
    if domain_id and parent_id == domain_id:
        raise HTTPException(status_code=400, detail="A domain cannot be its own parent")
    parent = get_active_domain(db, parent_id)
    seen: set[str] = set()
    current: Domain | None = parent
    while current:
        if current.id in seen:
            raise HTTPException(status_code=400, detail="Domain parent chain contains a cycle")
        if domain_id and current.id == domain_id:
            raise HTTPException(status_code=400, detail="A domain cannot be moved under one of its children")
        seen.add(current.id)
        current = db.get(Domain, current.parent_id) if current.parent_id else None
        if current and current.deleted_at:
            current = None
    return parent_id


def tags_for_ids(db: Session, tag_ids: list[str]) -> list[Tag]:
    unique_ids = unique_tag_ids([tag_id for tag_id in tag_ids if tag_id])
    if not unique_ids:
        return []
    tags = db.query(Tag).filter(Tag.id.in_(unique_ids)).order_by(func.lower(Tag.name), Tag.name).all()
    if len(tags) != len(unique_ids):
        raise HTTPException(status_code=404, detail="One or more tags were not found")
    by_id = {tag.id: tag for tag in tags}
    return [by_id[tag_id] for tag_id in unique_ids if tag_id in by_id]


def active_documents_for_domain_ids(db: Session, domain_ids: list[str]) -> list[Document]:
    if not domain_ids:
        return []
    return (
        db.query(Document)
        .filter(library_visible_document_filter(), Document.domains.any(Domain.id.in_(domain_ids)))
        .options(selectinload(Document.tags), selectinload(Document.domains), selectinload(Document.attributes))
        .order_by(*document_title_order_columns(db))
        .all()
    )


def record_domain_operation_history(
    db: Session,
    *,
    documents: list[Document],
    before_by_id: dict[str, dict[str, Any]],
    change_note: str,
    operation: str,
    extra: dict[str, Any],
    force_domain_change: bool = False,
) -> int:
    updated_documents = 0
    for document in documents:
        before = before_by_id.get(document.id) or document_correction_snapshot(document)
        after = document_correction_snapshot(document)
        changed_fields = set(changed_snapshot_fields(before, after))
        if not force_domain_change and "domains" not in changed_fields:
            continue
        document.search_text = rebuild_document_search_text(document)
        changed_fields.add("domains")
        record_document_version(
            db,
            document=document,
            change_note=change_note,
            changed_fields=changed_fields,
            before=before,
            after=after,
            extra={"operation": operation, **extra},
        )
        record_manual_edit(db, document=document, message=change_note, metadata={"operation": operation, **extra})
        updated_documents += 1
    return updated_documents


def get_or_create_tag_by_name(db: Session, name: str) -> Tag | None:
    return get_or_create_canonical_tag(db, name)


def active_documents_for_tag_ids(db: Session, tag_ids: list[str]) -> list[Document]:
    if not tag_ids:
        return []
    return (
        db.query(Document)
        .filter(library_visible_document_filter(), Document.tags.any(Tag.id.in_(tag_ids)))
        .options(selectinload(Document.tags), selectinload(Document.domains), selectinload(Document.attributes))
        .order_by(*document_title_order_columns(db))
        .all()
    )


def unique_tag_ids(tag_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_ids: list[str] = []
    for tag_id in tag_ids:
        if tag_id in seen:
            continue
        seen.add(tag_id)
        unique_ids.append(tag_id)
    return unique_ids


TAG_CLEANUP_PREFIX_STOPWORDS = {"a", "an", "and", "by", "for", "in", "of", "on", "the", "to", "with"}
TAG_OPTIMIZATION_PRIMARY_MERGE_LIMIT = 60
TAG_OPTIMIZATION_SINGLETON_MERGE_LIMIT = 120
TAG_OPTIMIZATION_ORPHAN_MERGE_LIMIT = 100
TAG_OPTIMIZATION_ORPHAN_PRUNE_LIMIT = 200
TAG_OPTIMIZATION_RELATIONSHIP_LIMIT = 120
TAG_OPTIMIZATION_STATUS_LIMIT = 200
TAG_OPTIMIZATION_ASSIGNMENT_PRUNE_LIMIT = 200
TAG_OPTIMIZATION_AI_INVENTORY_LIMIT = 300
TAG_OPTIMIZATION_MODEL_SCOPE_LIMIT = 300


def cleanup_tag_tokens(name: str) -> list[str]:
    normalized = normalize_tag_name(name)
    token_text = "".join(character if character.isalnum() else " " for character in normalized)
    return [token for token in token_text.split() if token]


def cleanup_tag_singular_token(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("is", "ss", "us")):
        return token[:-1]
    return token


def cleanup_tag_variant_key(name: str) -> str:
    return " ".join(cleanup_tag_singular_token(token) for token in cleanup_tag_tokens(name))


def cleanup_prefix_target(source_name: str, candidate_name: str) -> bool:
    source_tokens = cleanup_tag_tokens(source_name)
    candidate_tokens = cleanup_tag_tokens(candidate_name)
    if len(candidate_tokens) < 2 or len(source_tokens) <= len(candidate_tokens):
        return False
    return source_tokens[: len(candidate_tokens)] == candidate_tokens


def useful_cleanup_prefix(tokens: list[str]) -> bool:
    return len(tokens) >= 2 and any(token not in TAG_CLEANUP_PREFIX_STOPWORDS for token in tokens)


def tag_optimization_model_inventory(inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(inventory) <= TAG_OPTIMIZATION_AI_INVENTORY_LIMIT:
        return inventory

    def item_count(item: dict[str, Any]) -> int:
        try:
            return int(item.get("document_count") or 0)
        except (TypeError, ValueError):
            return 0

    by_name = {normalize_tag_name(str(item.get("name") or "")): item for item in inventory}
    variant_groups: dict[str, list[dict[str, Any]]] = {}
    prefix_groups: dict[str, list[dict[str, Any]]] = {}
    target_ids: set[str] = set()
    for item in inventory:
        item_id = str(item.get("id") or "")
        name = str(item.get("name") or "")
        tokens = cleanup_tag_tokens(name)
        variant_key = cleanup_tag_variant_key(name)
        if variant_key:
            variant_groups.setdefault(variant_key, []).append(item)
        if len(tokens) >= 2:
            prefix_groups.setdefault(" ".join(tokens[:2]), []).append(item)
        if item_count(item) <= 1:
            for prefix_length in range(2, min(5, len(tokens))):
                target = by_name.get(" ".join(tokens[:prefix_length]))
                if target:
                    target_ids.add(str(target.get("id") or ""))
            if item_id:
                target_ids.add(item_id)

    variant_group_sizes = {
        str(item.get("id") or ""): len(group)
        for group in variant_groups.values()
        if len(group) > 1
        for item in group
    }
    prefix_group_sizes = {
        str(item.get("id") or ""): len(group)
        for group in prefix_groups.values()
        if len(group) > 1
        for item in group
    }
    scored: list[tuple[int, int, str, dict[str, Any]]] = []
    for item in inventory:
        item_id = str(item.get("id") or "")
        name = str(item.get("name") or "")
        tokens = cleanup_tag_tokens(name)
        count = item_count(item)
        score = 0
        if count == 0:
            score += 115
        elif count == 1:
            score += 105
        elif count <= 3:
            score += 35
        if item_id in target_ids:
            score += 80
        if item_id in variant_group_sizes:
            score += min(90, 45 + variant_group_sizes[item_id] * 8)
        if item_id in prefix_group_sizes:
            score += min(70, 24 + prefix_group_sizes[item_id] * 4)
        if len(tokens) >= 3:
            score += min(35, (len(tokens) - 2) * 8)
        scored.append((score, count, name, item))

    selected = [item for score, _, _, item in sorted(scored, key=lambda row: (-row[0], row[1], row[2]))[:TAG_OPTIMIZATION_AI_INVENTORY_LIMIT]]
    return sorted(selected, key=lambda item: str(item.get("name") or "").lower())


def orphan_merge_candidate(
    source: Tag,
    candidates: list[Tag],
    document_counts_by_id: dict[str, int],
) -> tuple[Tag, float, str] | None:
    source_variant = cleanup_tag_variant_key(source.name)
    matches: list[tuple[float, Tag, str]] = []
    for target in candidates:
        if target.id == source.id or target.status not in {"canonical", "candidate"}:
            continue
        if document_counts_by_id.get(target.id, 0) <= 0:
            continue
        target_variant = cleanup_tag_variant_key(target.name)
        confidence = 0.0
        rationale = ""
        if source_variant and source_variant == target_variant:
            confidence = 0.92
            rationale = f'This orphaned tag is a spelling, plural, or formatting variant of the used tag "{target.name}".'
        elif cleanup_prefix_target(source.name, target.name):
            confidence = 0.82
            rationale = f'This orphaned tag appears to be covered by the used broader tag "{target.name}".'
        else:
            similarity = hybrid_tag_similarity(source.name, target.name)
            if similarity >= 0.76:
                confidence = min(0.9, similarity)
                rationale = f'This orphaned tag is semantically close to the used tag "{target.name}".'
        if confidence:
            matches.append((confidence, target, rationale))
    if not matches:
        return None
    confidence, target, rationale = sorted(
        matches,
        key=lambda item: (
            item[0],
            item[1].status == "canonical",
            document_counts_by_id.get(item[1].id, 0),
            -len(cleanup_tag_tokens(item[1].name)),
            item[1].name,
        ),
        reverse=True,
    )[0]
    return target, confidence, rationale


def record_tag_operation_history(
    db: Session,
    *,
    documents: list[Document],
    before_by_id: dict[str, dict[str, Any]],
    change_note: str,
    operation: str,
    extra: dict[str, Any],
) -> int:
    updated_documents = 0
    for document in documents:
        before = before_by_id.get(document.id) or document_correction_snapshot(document)
        after = document_correction_snapshot(document)
        changed_fields = set(changed_snapshot_fields(before, after))
        if "tags" not in changed_fields:
            continue
        document.search_text = rebuild_document_search_text(document)
        changed_fields.add("tags")
        record_document_version(
            db,
            document=document,
            change_note=change_note,
            changed_fields=changed_fields,
            before=before,
            after=after,
            extra={"operation": operation, **extra},
        )
        record_manual_edit(db, document=document, message=change_note, metadata={"operation": operation, **extra})
        updated_documents += 1
    return updated_documents


def get_or_create_attribute_definition(db: Session, key: str) -> AttributeDefinition | None:
    name = " ".join(key.strip().split())
    if not name:
        return None
    definition = db.get(AttributeDefinition, name)
    if not definition:
        definition = db.query(AttributeDefinition).filter(AttributeDefinition.name == name).one_or_none()
    if definition:
        return definition
    definition = AttributeDefinition(name=name, value_type="markdown")
    db.add(definition)
    db.flush()
    return definition


def normalize_attribute_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"value": value}


RESTORABLE_DOCUMENT_FIELDS = (
    "title",
    "subtitle",
    "authors",
    "universities",
    "publication_year",
    "publisher",
    "journal",
    "doi",
    "source_url",
    "abstract",
    "rich_summary",
    "bibliography",
    "apa_citation",
    "apa_citation_model",
    "apa_citation_source",
    "apa_in_text_citation",
    "apa_in_text_citation_model",
    "apa_in_text_citation_source",
    "citation_status",
    "metadata_confidence",
    "metadata_evidence",
    "read_status",
    "priority",
)
RESTORABLE_PAGE_FIELDS = ("text", "normalized_text", "text_source", "low_text", "image_uri")


def sanitize_snapshot_string(value: Any) -> Any:
    return value.replace("\x00", "") if isinstance(value, str) else value


def restorable_document_snapshot(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    after = snapshot.get("after")
    if isinstance(after, dict):
        return after
    if any(field in snapshot for field in (*RESTORABLE_DOCUMENT_FIELDS, "tags", "domains", "attributes")):
        return snapshot
    return None


def restorable_page_snapshots(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    page_after = snapshot.get("page_after")
    if isinstance(page_after, dict):
        pages.append(page_after)
    page_entries = snapshot.get("pages")
    if isinstance(page_entries, list):
        for entry in page_entries:
            if not isinstance(entry, dict):
                continue
            after = entry.get("after")
            if isinstance(after, dict):
                pages.append(after)
            elif any(field in entry for field in RESTORABLE_PAGE_FIELDS):
                pages.append(entry)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for page in pages:
        key = (page.get("id"), page.get("page_number"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(page)
    return deduped


def apply_document_snapshot(db: Session, document: Document, snapshot: dict[str, Any]) -> set[str]:
    changed_fields: set[str] = set()
    for field in RESTORABLE_DOCUMENT_FIELDS:
        if field not in snapshot:
            continue
        value = sanitize_snapshot_string(snapshot[field])
        if getattr(document, field) != value:
            setattr(document, field, value)
            changed_fields.add(field)

    if "tags" in snapshot:
        tag_names = [name for name in snapshot.get("tags") or [] if isinstance(name, str)]
        tags = []
        for name in tag_names:
            tag = get_or_create_tag_by_name(db, name)
            if tag and tag not in tags:
                tags.append(tag)
        if sorted(tag.name for tag in document.tags) != sorted(tag.name for tag in tags):
            document.tags = tags
            changed_fields.add("tags")

    if "domains" in snapshot:
        domain_ids = [domain_id for domain_id in snapshot.get("domains") or [] if isinstance(domain_id, str)]
        domains = db.query(Domain).filter(Domain.id.in_(domain_ids)).all() if domain_ids else []
        if sorted(domain.id for domain in document.domains) != sorted(domain.id for domain in domains):
            document.domains = domains
            changed_fields.add("domains")

    if "attributes" in snapshot and isinstance(snapshot["attributes"], dict):
        target_attributes = {
            key: normalize_attribute_value(value)
            for key, value in snapshot["attributes"].items()
            if isinstance(key, str) and key.strip() and value not in (None, "")
        }
        current_attributes = {value.definition.name: value.value for value in document.attributes if value.definition}
        if current_attributes != target_attributes:
            document.attributes.clear()
            db.flush()
            for key, value in target_attributes.items():
                definition = get_or_create_attribute_definition(db, key)
                if not definition:
                    continue
                document.attributes.append(
                    DocumentAttributeValue(
                        document_id=document.id,
                        attribute_definition_id=definition.id,
                        value=value,
                    )
                )
            changed_fields.add("attributes")

    return changed_fields


def document_page_for_snapshot(db: Session, document: Document, snapshot: dict[str, Any]) -> DocumentPage | None:
    page_id = snapshot.get("id")
    if isinstance(page_id, str):
        page = (
            db.query(DocumentPage)
            .filter(DocumentPage.id == page_id, DocumentPage.document_id == document.id)
            .one_or_none()
        )
        if page:
            return page
    page_number = snapshot.get("page_number")
    if isinstance(page_number, int):
        return (
            db.query(DocumentPage)
            .filter(DocumentPage.document_id == document.id, DocumentPage.page_number == page_number)
            .one_or_none()
        )
    return None


def apply_document_page_snapshot(page: DocumentPage, snapshot: dict[str, Any]) -> set[str]:
    changed_fields: set[str] = set()
    for field in RESTORABLE_PAGE_FIELDS:
        if field not in snapshot:
            continue
        value = sanitize_snapshot_string(snapshot[field])
        if getattr(page, field) != value:
            setattr(page, field, value)
            changed_fields.add(f"page_{page.page_number}_{field}")
    return changed_fields


def json_download(payload: dict[str, Any], filename_prefix: str) -> FastAPIResponse:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{filename_prefix}-{stamp}.json"
    content = json.dumps(jsonable_encoder(payload), indent=2, sort_keys=True)
    return FastAPIResponse(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def content_disposition_header(disposition: str, filename: str) -> str:
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii")
    ascii_fallback = "".join(
        char if 32 <= ord(char) < 127 and char not in {'"', "\\", ";"} else "_"
        for char in ascii_fallback
    )
    ascii_fallback = ascii_fallback or "download.pdf"
    return f'{disposition}; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quote(filename, safe="")}'


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.get("/api/slipstream/status", response_model=SlipstreamStatusOut)
def slipstream_admin_status(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    payload = slipstream_status(db)
    db.commit()
    return payload


@app.post("/api/slipstream/enrollments", response_model=SlipstreamEnrollmentOut)
def create_slipstream_enrollment(
    payload: SlipstreamEnrollmentCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    enrollment, token = create_enrollment(db, label=payload.label, ttl_minutes=payload.ttl_minutes)
    db.commit()
    db.refresh(enrollment)
    return enrollment_out(enrollment, token=token)


@app.get("/api/slipstream/clients", response_model=list[SlipstreamClientOut])
def list_slipstream_clients(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, Any]]:
    return [client_out(client) for client in db.query(SlipstreamClient).order_by(SlipstreamClient.created_at.asc()).all()]


@app.post("/api/slipstream/clients/{client_id}/disable", response_model=SlipstreamClientOut)
def disable_slipstream_client(
    client_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    client = db.get(SlipstreamClient, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Slipstream client not found")
    revoke_client(db, client, disable_only=True)
    db.commit()
    db.refresh(client)
    return client_out(client)


@app.post("/api/slipstream/clients/{client_id}/revoke", response_model=SlipstreamClientOut)
def revoke_slipstream_client(
    client_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    client = db.get(SlipstreamClient, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Slipstream client not found")
    revoke_client(db, client)
    db.commit()
    db.refresh(client)
    return client_out(client)


@app.post("/api/slipstream/leases/{lease_id}/cancel", response_model=SlipstreamLeaseOut)
def cancel_slipstream_lease(
    lease_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    lease = db.get(SlipstreamLease, lease_id)
    if not lease:
        raise HTTPException(status_code=404, detail="Slipstream lease not found")
    result = cancel_lease(db, lease)
    db.commit()
    return result


@app.post("/api/slipstream/register", response_model=SlipstreamClientOut)
def register_slipstream_client(
    payload: SlipstreamRegisterCreate,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        client = register_client(
            db,
            enrollment_token=payload.enrollment_token,
            name=payload.name,
            public_key=payload.public_key,
            version=payload.version,
            capabilities=payload.capabilities or None,
            capacity=payload.capacity,
            metadata=payload.metadata,
        )
    except Exception as exc:
        raise http_error_for_slipstream(exc) from exc
    db.commit()
    db.refresh(client)
    return client_out(client)


@app.post("/api/slipstream/check-in", response_model=SlipstreamClientOut)
def check_in_slipstream_client(
    payload: SlipstreamCheckInCreate,
    client: Annotated[SlipstreamClient, Depends(current_slipstream_client)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    client.last_check_in_at = utc_now()
    if payload.version is not None:
        client.version = payload.version
    if payload.capabilities is not None:
        client.capabilities = payload.capabilities
    if payload.capacity is not None:
        client.capacity = max(1, payload.capacity)
    if payload.metadata:
        metadata = dict(client.client_metadata or {})
        metadata.update(payload.metadata)
        client.client_metadata = metadata
    db.commit()
    db.refresh(client)
    return client_out(client)


@app.post("/api/slipstream/leases/claim", response_model=SlipstreamClaimOut)
def claim_slipstream_lease(
    payload: SlipstreamClaimCreate,
    client: Annotated[SlipstreamClient, Depends(current_slipstream_client)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        claim = claim_next_job_lease(db, client=client, worker_kind="slipstream", job_types=payload.job_types or None)
    except Exception as exc:
        raise http_error_for_slipstream(exc) from exc
    db.commit()
    return claim or {"lease": None, "lease_token": None, "work": None}


@app.post("/api/slipstream/leases/{lease_id}/heartbeat", response_model=SlipstreamLeaseOut)
def heartbeat_slipstream_lease(
    lease_id: str,
    payload: SlipstreamHeartbeatCreate,
    request: Request,
    client: Annotated[SlipstreamClient, Depends(current_slipstream_client)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        lease = validate_lease_access(db, lease_id=lease_id, client=client, lease_token=slipstream_lease_token(request))
        result = heartbeat_lease(db, lease, detail=payload.detail)
    except Exception as exc:
        raise http_error_for_slipstream(exc) from exc
    db.commit()
    return result


@app.get("/api/slipstream/leases/{lease_id}/artifact")
def slipstream_lease_artifact(
    lease_id: str,
    request: Request,
    client: Annotated[SlipstreamClient, Depends(current_slipstream_client)],
    db: Annotated[Session, Depends(get_db)],
) -> FastAPIResponse:
    try:
        lease = validate_lease_access(db, lease_id=lease_id, client=client, lease_token=slipstream_lease_token(request))
        data, filename = artifact_for_lease(db, lease)
        heartbeat_lease(db, lease, detail="artifact downloaded")
    except Exception as exc:
        raise http_error_for_slipstream(exc) from exc
    db.commit()
    return FastAPIResponse(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition_header("attachment", filename)},
    )


@app.post("/api/slipstream/leases/{lease_id}/events", response_model=SlipstreamLeaseOut)
def slipstream_lease_event(
    lease_id: str,
    payload: SlipstreamEventCreate,
    request: Request,
    client: Annotated[SlipstreamClient, Depends(current_slipstream_client)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        lease = validate_lease_access(db, lease_id=lease_id, client=client, lease_token=slipstream_lease_token(request))
        record_client_event(db, lease, event_type=payload.event_type, message=payload.message, level=payload.level, payload=payload.payload)
    except Exception as exc:
        raise http_error_for_slipstream(exc) from exc
    db.commit()
    db.refresh(lease)
    return {
        "id": lease.id,
        "client_id": lease.client_id,
        "client_name": lease.client.name if lease.client else None,
        "worker_kind": lease.worker_kind,
        "job_type": lease.job_type,
        "job_id": lease.job_id,
        "status": lease.status,
        "claimed_at": lease.claimed_at,
        "heartbeat_at": lease.heartbeat_at,
        "expires_at": lease.expires_at,
        "completed_at": lease.completed_at,
        "canceled_at": lease.canceled_at,
        "last_error": lease.last_error,
    }


@app.post("/api/slipstream/leases/{lease_id}/results", response_model=SlipstreamLeaseOut)
async def slipstream_lease_result(
    lease_id: str,
    payload: SlipstreamResultCreate,
    request: Request,
    client: Annotated[SlipstreamClient, Depends(current_slipstream_client)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    body = await request.body()
    max_bytes = max(1, settings.slipstream_max_result_mb) * 1024 * 1024
    if len(body) > max_bytes:
        raise HTTPException(status_code=413, detail="Slipstream result payload is too large.")
    try:
        lease = validate_lease_access(db, lease_id=lease_id, client=client, lease_token=slipstream_lease_token(request), require_active=False)
        result = complete_lease_from_result(db, lease, manifest=payload.model_dump())
    except Exception as exc:
        raise http_error_for_slipstream(exc) from exc
    db.commit()
    return result


@app.post("/api/slipstream/leases/{lease_id}/fail", response_model=SlipstreamLeaseOut)
def slipstream_lease_fail(
    lease_id: str,
    payload: SlipstreamFailCreate,
    request: Request,
    client: Annotated[SlipstreamClient, Depends(current_slipstream_client)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        lease = validate_lease_access(db, lease_id=lease_id, client=client, lease_token=slipstream_lease_token(request))
        result = fail_lease(db, lease, error=payload.error, payload=payload.payload)
    except Exception as exc:
        raise http_error_for_slipstream(exc) from exc
    db.commit()
    return result


@app.post("/api/auth/login", response_model=UserOut)
def login(payload: LoginRequest, request: Request, response: Response, db: Annotated[Session, Depends(get_db)]) -> User:
    login_email = payload.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == login_email).one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.two_factor_enabled and not verify_two_factor_code(user, payload.otp_code):
        raise HTTPException(status_code=401, detail="Invalid email, password, or two-factor code")
    token = create_session(db, user, user_agent=request.headers.get("user-agent"))
    set_session_cookie(response, token)
    return user


@app.post("/api/auth/logout")
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> dict[str, str]:
    if token:
        revoke_session(db, token)
    response.delete_cookie(settings.session_cookie_name)
    return {"status": "ok"}


@app.get("/api/me", response_model=UserOut)
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user


@app.post("/api/activity/heartbeat")
def activity_heartbeat(
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> dict[str, Any]:
    session = touch_session(db, token)
    if not session:
        raise HTTPException(status_code=401, detail="Authentication required")
    db.commit()
    return {"status": "ok", "last_seen_at": session.last_seen_at}


@app.post("/api/me/two-factor/setup", response_model=TwoFactorSetupOut)
def setup_two_factor(
    payload: TwoFactorSetupRequest,
    user: Annotated[User, Depends(current_user)],
) -> TwoFactorSetupOut:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    if user.two_factor_enabled:
        raise HTTPException(status_code=409, detail="Two-factor authentication is already enabled")
    secret = generate_totp_secret()
    return TwoFactorSetupOut(secret=secret, otpauth_uri=totp_setup_uri(secret, user.email))


@app.post("/api/me/two-factor/enable", response_model=TwoFactorEnableOut)
def enable_two_factor(
    payload: TwoFactorEnableRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> dict[str, Any]:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    if user.two_factor_enabled:
        raise HTTPException(status_code=409, detail="Two-factor authentication is already enabled")
    matched_step = verify_totp_code(payload.secret, payload.otp_code)
    if matched_step is None:
        raise HTTPException(status_code=400, detail="Enter a valid authenticator code")
    recovery_codes = generate_recovery_codes()
    user.two_factor_enabled = True
    user.two_factor_secret = payload.secret
    user.two_factor_confirmed_at = utc_now()
    user.two_factor_last_used_step = matched_step
    user.two_factor_recovery_hashes = hash_recovery_codes(recovery_codes)
    revoke_other_sessions(db, user, token)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user": user, "recovery_codes": recovery_codes}


@app.post("/api/me/two-factor/disable", response_model=UserOut)
def disable_two_factor(
    payload: TwoFactorDisableRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    if user.two_factor_enabled and not verify_two_factor_code(user, payload.otp_code):
        raise HTTPException(status_code=403, detail="Two-factor code is incorrect")
    user.two_factor_enabled = False
    user.two_factor_secret = None
    user.two_factor_confirmed_at = None
    user.two_factor_last_used_step = None
    user.two_factor_recovery_hashes = []
    revoke_other_sessions(db, user, token)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/api/release/status", response_model=ReleaseStatusOut)
def read_release_status(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    client_version: str | None = Query(default=None, max_length=120),
) -> ReleaseStatusOut:
    return release_status(client_version=client_version, db=db)


@app.post("/api/release/upgrade", response_model=ReleaseStatusOut)
def start_release_upgrade(
    user: Annotated[User, Depends(current_user)],
    client_version: str | None = Query(default=None, max_length=120),
) -> ReleaseStatusOut:
    try:
        return request_release_upgrade(client_version=client_version, requested_by=user.email)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/release/check", response_model=ReleaseStatusOut)
def start_release_check(
    user: Annotated[User, Depends(current_user)],
    client_version: str | None = Query(default=None, max_length=120),
) -> ReleaseStatusOut:
    return request_release_check(client_version=client_version, requested_by=user.email)


@app.post("/api/release/maintenance", response_model=ReleaseStatusOut)
def start_maintenance_run(
    user: Annotated[User, Depends(current_user)],
    client_version: str | None = Query(default=None, max_length=120),
) -> ReleaseStatusOut:
    return request_maintenance_run(client_version=client_version, requested_by=user.email)


@app.patch("/api/me", response_model=UserOut)
def update_me(
    payload: AccountUpdateRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="Current password is incorrect")

    next_email = payload.email.strip().lower() if payload.email is not None else user.email
    if not next_email or "@" not in next_email or len(next_email) > 320:
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if next_email != user.email:
        existing = (
            db.query(User)
            .filter(func.lower(User.email) == next_email.lower())
            .filter(User.id != user.id)
            .one_or_none()
        )
        if existing:
            raise HTTPException(status_code=409, detail="Email is already in use")
        user.email = next_email

    password_change_requested = payload.new_password is not None or payload.new_password_confirmation is not None
    if password_change_requested:
        next_password = payload.new_password or ""
        if next_password != (payload.new_password_confirmation or ""):
            raise HTTPException(status_code=400, detail="New passwords do not match")
        if len(next_password) < 8:
            raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
        user.password_hash = hash_password(next_password)
        revoke_other_sessions(db, user, token)

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def count_words_in_text(value: str | None) -> int:
    return len(WORD_RE.findall(value or ""))


def bibliography_reference_count(value: str | None) -> int:
    normalized = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return 0
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n+", normalized) if part.strip()]
    if len(paragraphs) > 1:
        return len(paragraphs)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if not lines:
        return 0
    if len(lines) == 1:
        return 1
    marked_lines = sum(1 for line in lines if REFERENCE_ENTRY_RE.match(line))
    if marked_lines:
        return max(1, marked_lines)
    return len(lines)


def author_identity(author: Any) -> str | None:
    if isinstance(author, dict):
        parts = [
            str(author.get("given") or "").strip(),
            str(author.get("family") or "").strip(),
        ]
        value = " ".join(part for part in parts if part)
    else:
        value = str(author or "").strip()
    normalized = " ".join(value.split()).lower()
    return normalized or None


def library_fun_stats_out(db: Session) -> LibraryFunStatsOut:
    document_counts = (
        filter_library_visible_documents(
            db.query(
                func.count(Document.id),
                func.coalesce(func.sum(Document.page_count), 0),
                func.coalesce(
                    func.sum(case((func.nullif(func.trim(Document.doi), "").isnot(None), 1), else_=0)),
                    0,
                ),
                func.coalesce(func.sum(case((Document.citation_status == "verified", 1), else_=0)), 0),
            )
        )
        .one()
    )
    page_record_count = (
        db.query(func.count(DocumentPage.id))
        .join(Document, DocumentPage.document_id == Document.id)
        .filter(library_visible_document_filter())
        .scalar()
        or 0
    )
    figure_count = (
        db.query(func.count(Figure.id))
        .join(Document, Figure.document_id == Document.id)
        .filter(library_visible_document_filter())
        .scalar()
        or 0
    )
    chunk_counts = (
        db.query(func.count(TextChunk.id), func.coalesce(func.sum(TextChunk.token_count), 0))
        .join(Document, TextChunk.document_id == Document.id)
        .filter(library_visible_document_filter())
        .one()
    )
    annotation_count = (
        db.query(func.count(Annotation.id))
        .join(Document, Annotation.document_id == Document.id)
        .filter(library_visible_document_filter(), Annotation.deleted_at.is_(None))
        .scalar()
        or 0
    )
    project_resource_count = (
        db.query(func.count(ProjectItem.id))
        .join(Document, ProjectItem.document_id == Document.id)
        .join(Project, ProjectItem.project_id == Project.id)
        .filter(library_visible_document_filter(), Project.deleted_at.is_(None))
        .scalar()
        or 0
    )
    used_project_resource_count = (
        db.query(func.count(ProjectItem.id))
        .join(Document, ProjectItem.document_id == Document.id)
        .join(Project, ProjectItem.project_id == Project.id)
        .filter(library_visible_document_filter(), Project.deleted_at.is_(None), ProjectItem.used_in_output.is_(True))
        .scalar()
        or 0
    )

    parsed_word_count = 0
    parsed_character_count = 0
    for normalized_text, raw_text in (
        db.query(DocumentPage.normalized_text, DocumentPage.text)
        .join(Document, DocumentPage.document_id == Document.id)
        .filter(library_visible_document_filter())
        .yield_per(500)
    ):
        text_value = normalized_text or raw_text or ""
        parsed_character_count += len(text_value)
        parsed_word_count += count_words_in_text(text_value)

    indexed_word_count = 0
    indexed_character_count = 0
    bibliography_document_count = 0
    bibliography_references = 0
    unique_authors: set[str] = set()
    for authors, bibliography, search_text in filter_library_visible_documents(
        db.query(Document.authors, Document.bibliography, Document.search_text)
    ).yield_per(200):
        indexed_character_count += len(search_text or "")
        indexed_word_count += count_words_in_text(search_text)
        reference_count = bibliography_reference_count(bibliography)
        if reference_count:
            bibliography_document_count += 1
            bibliography_references += reference_count
        if isinstance(authors, list):
            for author in authors:
                identity = author_identity(author)
                if identity:
                    unique_authors.add(identity)

    return LibraryFunStatsOut(
        checked_at=utc_now(),
        document_count=int(document_counts[0] or 0),
        page_count=int(document_counts[1] or 0),
        page_record_count=int(page_record_count),
        figure_count=int(figure_count),
        bibliography_reference_count=int(bibliography_references),
        bibliography_document_count=int(bibliography_document_count),
        parsed_word_count=int(parsed_word_count),
        indexed_word_count=int(indexed_word_count),
        parsed_character_count=int(parsed_character_count),
        indexed_character_count=int(indexed_character_count),
        text_chunk_count=int(chunk_counts[0] or 0),
        text_chunk_token_count=int(chunk_counts[1] or 0),
        doi_count=int(document_counts[2] or 0),
        verified_citation_count=int(document_counts[3] or 0),
        unique_author_count=len(unique_authors),
        annotation_count=int(annotation_count),
        note_count=db.query(Note).filter(Note.deleted_at.is_(None)).count(),
        project_resource_count=int(project_resource_count),
        used_project_resource_count=int(used_project_resource_count),
        domain_count=db.query(Domain).filter(Domain.deleted_at.is_(None)).count(),
        tag_count=db.query(Tag).count(),
    )


def recent_failed_ai_call_notices(db: Session) -> list[dict[str, Any]]:
    fresh_after = utc_now() - RECENT_AI_FAILURE_NOTICE_MAX_AGE
    records = (
        db.query(OpenAIUsageRecord)
        .filter(OpenAIUsageRecord.status == "failed", OpenAIUsageRecord.created_at >= fresh_after)
        .order_by(OpenAIUsageRecord.created_at.desc(), OpenAIUsageRecord.id.desc())
        .limit(RECENT_AI_FAILURE_NOTICE_LIMIT)
        .all()
    )
    if not records:
        return []
    document_ids = sorted({record.document_id for record in records if record.document_id})
    document_titles = {
        document.id: document.title or document.original_filename
        for document in db.query(Document).filter(Document.id.in_(document_ids)).all()
    } if document_ids else {}
    notices: list[dict[str, Any]] = []
    for record in records:
        cost = estimated_cost_usd_for_record(record, db)
        notices.append(
            {
                "id": record.id,
                "created_at": record.created_at,
                "document_id": record.document_id,
                "document_title": document_titles.get(record.document_id or ""),
                "source": record.source,
                "task_key": record.task_key,
                "operation": record.operation,
                "provider": record.provider,
                "model": record.model,
                "endpoint": record.endpoint,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "total_tokens": record.total_tokens,
                "error_message": record.error_message,
                "estimated_cost_usd": None if cost is None else round(cost, 6),
            }
        )
    return notices


def dashboard_out(db: Session) -> DashboardOut:
    import_queued_jobs = db.query(ImportJob).filter(ImportJob.status == "queued").count()
    import_running_jobs = db.query(ImportJob).filter(ImportJob.status == "running").count()
    queue_import_jobs = db.query(ImportJob).filter(ImportJob.status.in_(IMPORT_JOB_QUEUE_STATUSES)).count()
    active_import_jobs = import_queued_jobs + import_running_jobs
    active_concordance_jobs = db.query(ConcordanceJob).filter(ConcordanceJob.status.in_(["queued", "running"])).count()
    active_accessory_summary_jobs = (
        db.query(DocumentAccessorySummary).filter(DocumentAccessorySummary.status.in_(["queued", "running"])).count()
    )
    failed_import_jobs = db.query(ImportJob).filter(ImportJob.status == "failed").count()
    failed_concordance_jobs = db.query(ConcordanceJob).filter(ConcordanceJob.status == "failed").count()
    failed_accessory_summary_jobs = db.query(DocumentAccessorySummary).filter(DocumentAccessorySummary.status == "failed").count()
    active_batch_ids = [
        row[0]
        for row in db.query(ImportJob.batch_id).filter(ImportJob.status.in_(["queued", "running"])).distinct().all()
    ]
    active_import_job_ids = [
        row[0]
        for row in db.query(ImportJob.id).filter(ImportJob.status.in_(["queued", "running"])).all()
    ]
    active_batches = db.query(ImportBatch).filter(ImportBatch.id.in_(active_batch_ids)).all() if active_batch_ids else []
    import_progress_total = sum(batch.total_files for batch in active_batches)
    import_progress_completed = sum(batch.completed_files for batch in active_batches)
    import_progress_failed = sum(batch.failed_files for batch in active_batches)
    active_import_job = (
        db.query(ImportJob)
        .filter(ImportJob.status == "running")
        .order_by(ImportJob.locked_at.asc(), ImportJob.created_at.asc())
        .first()
    )
    active_started_at = None
    if active_import_job:
        active_started_at = active_import_job.locked_at or active_import_job.updated_at
    active_elapsed_seconds = int((utc_now() - active_started_at).total_seconds()) if active_started_at else None
    document_counts = (
        filter_library_visible_documents(db.query(
            func.count(Document.id),
            func.coalesce(func.sum(case((Document.read_status == "unread", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Document.citation_status == "needs_review", 1), else_=0)), 0),
        ))
        .one()
    )
    return DashboardOut(
        documents=int(document_counts[0] or 0),
        unread=int(document_counts[1] or 0),
        needs_review=int(document_counts[2] or 0),
        domains=db.query(Domain).filter(Domain.deleted_at.is_(None)).count(),
        tags=db.query(Tag).count(),
        notes=db.query(Note).filter(Note.deleted_at.is_(None)).count(),
        review_items=db.query(CitationCandidate).filter(CitationCandidate.status == "needs_review").count(),
        stashes=doi_stash_query(db).count(),
        queued_jobs=active_import_jobs + active_concordance_jobs + active_accessory_summary_jobs,
        queue_import_jobs=queue_import_jobs,
        active_import_jobs=active_import_jobs,
        import_queued_jobs=import_queued_jobs,
        import_running_jobs=import_running_jobs,
        import_progress_total=import_progress_total,
        import_progress_completed=import_progress_completed,
        import_progress_failed=import_progress_failed,
        import_active_step=active_import_job.current_step if active_import_job else None,
        import_active_elapsed_seconds=active_elapsed_seconds,
        import_active_cost_usd=active_import_cost_usd(db, active_import_job_ids),
        active_concordance_jobs=active_concordance_jobs,
        active_accessory_summary_jobs=active_accessory_summary_jobs,
        failed_jobs=failed_import_jobs + failed_concordance_jobs + failed_accessory_summary_jobs,
        failed_import_jobs=failed_import_jobs,
        failed_concordance_jobs=failed_concordance_jobs,
        failed_accessory_summary_jobs=failed_accessory_summary_jobs,
        recent_failed_ai_calls=recent_failed_ai_call_notices(db),
        projects=db.query(Project).filter(Project.deleted_at.is_(None)).count(),
    )


@app.get("/api/dashboard", response_model=DashboardOut)
def dashboard(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    response: Response = None,
) -> DashboardOut:
    return cache_or_load(
        db,
        response,
        family="dashboard",
        revision_families={"dashboard", "jobs", "library", "organization"},
        key_parts={"endpoint": "dashboard"},
        loader=lambda: dashboard_out(db),
    )


@app.get("/api/status/library-fun", response_model=LibraryFunStatsOut)
def library_fun_stats(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    response: Response = None,
) -> LibraryFunStatsOut:
    return cache_or_load(
        db,
        response,
        family="status:library_fun",
        revision_families={"status", "library", "organization"},
        key_parts={"endpoint": "library_fun_stats"},
        loader=lambda: library_fun_stats_out(db),
    )


@app.get("/api/cache/status", response_model=CacheStatusOut)
def cache_status(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    return cache_status_payload(db, request_metrics=route_performance_summary())


@app.post("/api/cache/refresh", response_model=CacheRefreshOut)
def refresh_cache(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    before = cache_status_payload(db, request_metrics=route_performance_summary())
    refreshed_at = utc_now()
    bump_cache_revisions(db, CACHE_ALL_REVISION_FAMILIES, reason="manual_refresh")
    db.commit()
    get_cache_backend().remember_refresh(refreshed_at)

    warmed_keys = 0
    warmers = [
        {
            "family": "dashboard",
            "revision_families": {"dashboard", "jobs", "library", "organization"},
            "key_parts": {"endpoint": "dashboard"},
            "loader": lambda: dashboard_out(db),
        },
        {
            "family": "status:library_fun",
            "revision_families": {"status", "library", "organization"},
            "key_parts": {"endpoint": "library_fun_stats"},
            "loader": lambda: library_fun_stats_out(db),
        },
        {
            "family": "organization",
            "revision_families": {"organization", "library"},
            "key_parts": {"endpoint": "domains"},
            "loader": lambda: domain_list_out(db),
        },
        {
            "family": "organization",
            "revision_families": {"organization", "library"},
            "key_parts": {"endpoint": "tags"},
            "loader": lambda: tag_list_out(db),
        },
        {
            "family": "organization",
            "revision_families": {"organization", "library"},
            "key_parts": {"endpoint": "projects"},
            "loader": lambda: project_list_out(db),
        },
        {
            "family": "documents:list",
            "revision_families": {"library", "organization"},
            "key_parts": {
                "q": "",
                "domain_id": "",
                "tag_id": "",
                "read_status": "",
                "priority": "",
                "citation_status": "",
                "duplicate_status": "",
                "health_status": "",
                "all": False,
                "offset": 0,
                "limit": 50,
            },
            "loader": lambda: document_list_rows_out(db, offset=0, limit=50),
        },
    ]
    for warmer in warmers:
        try:
            if warm_cache_payload(db, **warmer):
                warmed_keys += 1
        except Exception:
            logging.getLogger("medusa.cache").debug("Cache warm failed for %s", warmer["family"], exc_info=True)

    after = cache_status_payload(db, request_metrics=route_performance_summary())
    return {
        "status": "complete",
        "message": f"Cache revisions refreshed. Warmed {warmed_keys} derived payloads.",
        "refreshed_at": refreshed_at,
        "refreshed_families": list(CACHE_ALL_REVISION_FAMILIES),
        "warmed_keys": warmed_keys,
        "before": before,
        "after": after,
    }


@app.post("/api/cache/hydrate", response_model=CacheHydrateOut)
def hydrate_cache(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_document_details: bool = True,
    include_saved_searches: bool = True,
    max_documents: Annotated[int, Query(ge=1, le=CACHE_HYDRATE_MAX_DOCUMENTS)] = CACHE_HYDRATE_MAX_DOCUMENTS,
    page_size: Annotated[int, Query(ge=10)] = CACHE_HYDRATE_LIST_PAGE_SIZE,
) -> dict[str, Any]:
    logger = logging.getLogger("medusa.cache")
    before = cache_status_payload(db, request_metrics=route_performance_summary())
    hydrated_at = utc_now()
    counters = {
        "hydrated_keys": 0,
        "base_keys": 0,
        "document_detail_keys": 0,
        "list_page_keys": 0,
        "saved_search_keys": 0,
        "organization_keys": 0,
        "skipped_payloads": 0,
        "errored_payloads": 0,
    }

    if not before.get("enabled") or not before.get("reachable"):
        after = cache_status_payload(db, request_metrics=route_performance_summary())
        return {
            "status": "skipped",
            "message": before.get("message") or "Cache hydration skipped because the cache backend is unavailable.",
            "hydrated_at": hydrated_at,
            "document_count": 0,
            **counters,
            "before": before,
            "after": after,
        }

    def record_write_status(status: str, bucket: str) -> None:
        if status == "write":
            counters["hydrated_keys"] += 1
            counters[bucket] += 1
        elif status == "bypass":
            counters["skipped_payloads"] += 1
        elif status == "error":
            counters["errored_payloads"] += 1

    def hydrate_payload(
        *,
        family: str,
        revision_families: set[str],
        key_parts: dict[str, Any],
        loader,
        bucket: str,
    ) -> Any | None:
        try:
            status, result = warm_cache_payload_result(
                db,
                family=family,
                revision_families=revision_families,
                key_parts=key_parts,
                loader=loader,
            )
            record_write_status(status, bucket)
            return result
        except Exception:
            counters["errored_payloads"] += 1
            logger.debug("Cache hydration failed for %s %s", family, key_parts, exc_info=True)
            return None

    def filter_value(filters: dict[str, Any] | None, key: str) -> str:
        if not filters:
            return ""
        value = filters.get(key)
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        return ""

    def hydrate_document_list_pages(
        *,
        q: str = "",
        filters: dict[str, Any] | None = None,
        saved_search: bool = False,
    ) -> None:
        offset = 0
        while True:
            domain_id = filter_value(filters, "domain_id")
            tag_id = filter_value(filters, "tag_id")
            read_status = filter_value(filters, "read_status")
            priority = filter_value(filters, "priority")
            citation_status = filter_value(filters, "citation_status")
            duplicate_status = filter_value(filters, "duplicate_status")
            health_status = filter_value(filters, "health_status")
            key_parts = {
                "q": q or "",
                "domain_id": domain_id,
                "tag_id": tag_id,
                "read_status": read_status,
                "priority": priority,
                "citation_status": citation_status,
                "duplicate_status": duplicate_status,
                "health_status": health_status,
                "all": False,
                "offset": offset,
                "limit": page_size,
            }

            def load_page(offset: int = offset) -> DocumentListOut:
                return document_list_rows_out(
                    db,
                    q=q,
                    domain_id=domain_id,
                    tag_id=tag_id,
                    read_status=read_status,
                    priority=priority,
                    citation_status=citation_status,
                    duplicate_status=duplicate_status,
                    health_status=health_status,
                    all_results=False,
                    offset=offset,
                    limit=page_size,
                )

            result = hydrate_payload(
                family="documents:list",
                revision_families={"library", "organization"},
                key_parts=key_parts,
                loader=load_page,
                bucket="saved_search_keys" if saved_search else "list_page_keys",
            )
            if not result or not getattr(result, "has_more", False):
                break
            offset += page_size

    for warmer in [
        {
            "family": "dashboard",
            "revision_families": {"dashboard", "jobs", "library", "organization"},
            "key_parts": {"endpoint": "dashboard"},
            "loader": lambda: dashboard_out(db),
            "bucket": "base_keys",
        },
        {
            "family": "status:library_fun",
            "revision_families": {"status", "library", "organization"},
            "key_parts": {"endpoint": "library_fun_stats"},
            "loader": lambda: library_fun_stats_out(db),
            "bucket": "base_keys",
        },
        {
            "family": "organization",
            "revision_families": {"organization", "library"},
            "key_parts": {"endpoint": "domains"},
            "loader": lambda: domain_list_out(db),
            "bucket": "organization_keys",
        },
        {
            "family": "organization",
            "revision_families": {"organization", "library"},
            "key_parts": {"endpoint": "tags"},
            "loader": lambda: tag_list_out(db),
            "bucket": "organization_keys",
        },
        {
            "family": "organization",
            "revision_families": {"organization", "library"},
            "key_parts": {"endpoint": "projects"},
            "loader": lambda: project_list_out(db),
            "bucket": "organization_keys",
        },
    ]:
        hydrate_payload(**warmer)

    hydrate_document_list_pages()
    if include_saved_searches:
        saved_searches = db.query(SavedSearch).filter(SavedSearch.deleted_at.is_(None)).order_by(SavedSearch.sort_order, SavedSearch.name).all()
        for saved_search in saved_searches:
            hydrate_document_list_pages(q=saved_search.query or "", filters=saved_search.filters or {}, saved_search=True)

    documents = []
    if include_document_details:
        documents = (
            filter_library_visible_documents(db.query(Document))
            .options(selectinload(Document.tags), selectinload(Document.domains), selectinload(Document.versions))
            .order_by(*document_title_order_columns(db))
            .limit(max_documents)
            .all()
        )
        for document in documents:
            hydrate_payload(
                family="documents:detail",
                revision_families={"document_detail", "organization"},
                key_parts={
                    "document_id": document.id,
                    "updated_at": document.updated_at.isoformat() if document.updated_at else "",
                    "deleted_at": document.deleted_at.isoformat() if document.deleted_at else "",
                    "processing_status": document.processing_status,
                },
                loader=lambda document=document: document_detail_out(document, db),
                bucket="document_detail_keys",
            )

    get_cache_backend().remember_hydration(hydrated_at)
    after = cache_status_payload(db, request_metrics=route_performance_summary())
    return {
        "status": "complete",
        "message": (
            f"Hydrated {counters['hydrated_keys']} cache payloads from PostgreSQL"
            f" for {len(documents)} document details."
        ),
        "hydrated_at": hydrated_at,
        "document_count": len(documents),
        **counters,
        "before": before,
        "after": after,
    }


@app.get("/api/preferences", response_model=AppPreferencesOut)
def read_preferences(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    return get_app_preferences(db)


@app.patch("/api/preferences", response_model=AppPreferencesOut)
def patch_preferences(
    payload: AppPreferencesPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        preferences = update_app_preferences(
            db,
            import_worker_concurrency=payload.import_worker_concurrency,
            accent_color_day=payload.accent_color_day,
            accent_color_night=payload.accent_color_night,
            document_cache_size_mb=payload.document_cache_size_mb,
            valkey_maxmemory=payload.valkey_maxmemory,
            library_alternating_rows=payload.library_alternating_rows,
            library_page_size=payload.library_page_size,
            library_density=payload.library_density,
            detail_sticky_fields=payload.detail_sticky_fields,
            download_naming_template=payload.download_naming_template,
            citation_convention=payload.citation_convention,
            gcs_bucket=payload.gcs_bucket,
            analysis_models=payload.analysis_models,
            import_processing_presets=payload.import_processing_presets,
            default_import_processing_preset_id=payload.default_import_processing_preset_id,
            second_pass_processing_enabled=payload.second_pass_processing_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    apply_valkey_maxmemory_preference(db)
    return preferences


@app.get("/api/preferences/gcs-lifecycle", response_model=GcsBucketLifecycleOut)
def read_gcs_bucket_lifecycle(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    return gcs_bucket_lifecycle_status(db)


@app.get("/api/document-cache/status", response_model=DocumentCacheStatusOut)
def document_cache_status(_: Annotated[User, Depends(current_user)]) -> dict[str, int]:
    return current_document_cache_usage()


@app.get("/api/utilities/database/status", response_model=DatabaseMaintenanceStatusOut)
def database_maintenance_status(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DatabaseMaintenanceStatusOut:
    return database_maintenance_status_out(db)


@app.post("/api/utilities/database/compact", response_model=DatabaseMaintenanceResultOut)
def compact_database(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DatabaseMaintenanceResultOut:
    try:
        return run_database_sql_maintenance(
            db,
            operation="compact_database",
            postgres_sql="VACUUM (FULL, ANALYZE)",
            sqlite_sql="VACUUM",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/utilities/database/optimize", response_model=DatabaseMaintenanceResultOut)
def optimize_database(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DatabaseMaintenanceResultOut:
    try:
        return run_database_sql_maintenance(
            db,
            operation="optimize_database",
            postgres_sql="ANALYZE",
            sqlite_sql="ANALYZE",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/utilities/import-cache/clear", response_model=DatabaseMaintenanceResultOut)
def clear_import_cache(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DatabaseMaintenanceResultOut:
    return clear_hidden_import_cache(db)


@app.post("/api/utilities/document-hashes/backfill", response_model=DatabaseMaintenanceResultOut)
def backfill_document_hashes(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DatabaseMaintenanceResultOut:
    try:
        return run_document_md5_backfill(db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/utilities/container/status", response_model=ContainerFootprintStatusOut)
def container_status(_: Annotated[User, Depends(current_user)]) -> ContainerFootprintStatusOut:
    return container_footprint_status()


@app.post("/api/utilities/container/restart", response_model=ContainerRestartOut)
def restart_container(_: Annotated[User, Depends(current_user)]) -> ContainerRestartOut:
    try:
        return request_container_restart()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/utilities/haproxy/status", response_model=HAProxyStatsStatusOut)
def haproxy_status(_: Annotated[User, Depends(current_user)]) -> HAProxyStatsStatusOut:
    return haproxy_stats_status()


@app.post("/api/preferences/google-service-account", response_model=AppPreferencesOut)
async def upload_google_service_account(
    file: Annotated[UploadFile, File()],
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Upload a service account JSON file.")
    if len(content) > 512 * 1024:
        raise HTTPException(status_code=400, detail="Service account JSON is unexpectedly large.")
    try:
        preferences = store_google_service_account(db, content, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return preferences


@app.post("/api/model-pricing/refresh", response_model=ModelPricingStatusOut)
def refresh_models_and_pricing(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    status = refresh_model_pricing(db)
    db.commit()
    return status


@app.get("/api/openai/usage", response_model=OpenAIUsageOut)
def read_openai_usage(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    period: str = Query("all_time", pattern="^(last_day|last_month|last_3_months|all_time)$"),
) -> dict[str, Any]:
    return openai_usage_summary(db, period=period)


def domain_list_out(db: Session) -> list[DomainOut]:
    domains = (
        db.query(Domain)
        .filter(Domain.deleted_at.is_(None))
        .options(selectinload(Domain.tags))
        .order_by(func.lower(Domain.name), Domain.name, Domain.sort_order)
        .all()
    )
    subtree_counts = domain_subtree_document_counts(db, domains)
    direct_counts = domain_document_counts(db, [domain.id for domain in domains])
    domain_tag_ids = list({tag.id for domain in domains for tag in domain.tags})
    tag_counts = tag_document_counts(db, domain_tag_ids)
    return [
        domain_out(
            domain,
            db,
            subtree_document_count=subtree_counts.get(domain.id, 0),
            document_count=direct_counts.get(domain.id, 0),
            tag_count_map=tag_counts,
        )
        for domain in domains
    ]


@app.get("/api/domains", response_model=list[DomainOut])
def list_domains(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    response: Response = None,
) -> list[DomainOut]:
    return cache_or_load(
        db,
        response,
        family="organization",
        revision_families={"organization", "library"},
        key_parts={"endpoint": "domains"},
        loader=lambda: domain_list_out(db),
    )


@app.post("/api/domains", response_model=DomainOut)
def create_domain(
    payload: DomainCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DomainOut:
    name = normalize_domain_name(payload.name)
    if not name:
        raise HTTPException(status_code=400, detail="Domain name is required")
    parent_id = validate_domain_parent(db, domain_id=None, parent_id=payload.parent_id)
    if active_domain_name_exists(db, name=name, parent_id=parent_id):
        raise HTTPException(status_code=409, detail="A domain with that name already exists at this level")
    next_order = (
        db.query(func.max(Domain.sort_order))
        .filter(Domain.deleted_at.is_(None), Domain.parent_id == parent_id if parent_id else Domain.parent_id.is_(None))
        .scalar()
        or 0
    ) + 1
    domain = Domain(
        name=name,
        parent_id=parent_id,
        description=(payload.description or "").strip() or None,
        color=normalize_domain_color(payload.color),
        sort_order=next_order,
        tags=tags_for_ids(db, payload.tag_ids),
    )
    db.add(domain)
    db.commit()
    db.refresh(domain)
    return domain_out(domain, db)


@app.patch("/api/domains/{domain_id}", response_model=DomainOut)
def update_domain(
    domain_id: str,
    payload: DomainPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DomainOut:
    domain = get_active_domain(db, domain_id)
    old_name = domain.name
    old_parent_id = domain.parent_id
    documents = active_documents_for_domain_ids(db, [domain.id])
    before_by_id = {document.id: document_correction_snapshot(document) for document in documents}

    if "name" in payload.model_fields_set:
        name = normalize_domain_name(payload.name or "")
        if not name:
            raise HTTPException(status_code=400, detail="Domain name is required")
        if name != domain.name and active_domain_name_exists(db, name=name, parent_id=domain.parent_id, exclude_id=domain.id):
            raise HTTPException(status_code=409, detail="A domain with that name already exists at this level")
        domain.name = name

    if "parent_id" in payload.model_fields_set:
        parent_id = validate_domain_parent(db, domain_id=domain.id, parent_id=payload.parent_id)
        if active_domain_name_exists(db, name=domain.name, parent_id=parent_id, exclude_id=domain.id):
            raise HTTPException(status_code=409, detail="A domain with that name already exists at the destination level")
        domain.parent_id = parent_id

    if "description" in payload.model_fields_set:
        domain.description = (payload.description or "").strip() or None

    if "color" in payload.model_fields_set:
        domain.color = normalize_domain_color(payload.color)

    if "sort_order" in payload.model_fields_set and payload.sort_order is not None:
        domain.sort_order = payload.sort_order

    if "tag_ids" in payload.model_fields_set:
        domain.tags = tags_for_ids(db, payload.tag_ids or [])

    db.flush()
    if domain.name != old_name:
        record_domain_operation_history(
            db,
            documents=documents,
            before_by_id=before_by_id,
            change_note=f'Renamed domain "{old_name}" to "{domain.name}"',
            operation="domain_rename",
            extra={"domain_id": domain.id, "old_name": old_name, "new_name": domain.name},
            force_domain_change=True,
        )
    elif domain.parent_id != old_parent_id:
        for document in documents:
            document.search_text = rebuild_document_search_text(document)

    db.commit()
    db.refresh(domain)
    return domain_out(domain, db)


@app.post("/api/domains/reorder", response_model=list[DomainOut])
def reorder_domains(
    payload: DomainReorder,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DomainOut]:
    requested_ids = [item.id for item in payload.domains]
    if len(requested_ids) != len(set(requested_ids)):
        raise HTTPException(status_code=400, detail="Domain reorder payload contains duplicate ids")
    domains = db.query(Domain).filter(Domain.id.in_(requested_ids), Domain.deleted_at.is_(None)).all()
    if len(domains) != len(requested_ids):
        raise HTTPException(status_code=404, detail="One or more domains were not found")
    domain_by_id = {domain.id: domain for domain in domains}
    proposed_parents = {item.id: item.parent_id for item in payload.domains}

    for item in payload.domains:
        domain = domain_by_id[item.id]
        parent_id = item.parent_id
        if parent_id and parent_id not in domain_by_id:
            validate_domain_parent(db, domain_id=domain.id, parent_id=parent_id)
        elif parent_id == domain.id:
            raise HTTPException(status_code=400, detail="A domain cannot be its own parent")

        seen: set[str] = set()
        current_parent_id = parent_id
        while current_parent_id:
            if current_parent_id == domain.id or current_parent_id in seen:
                raise HTTPException(status_code=400, detail="Domain reorder would create a parent cycle")
            seen.add(current_parent_id)
            current_parent = domain_by_id.get(current_parent_id) or get_active_domain(db, current_parent_id)
            current_parent_id = proposed_parents.get(current_parent.id, current_parent.parent_id)

    for item in payload.domains:
        domain = domain_by_id[item.id]
        if active_domain_name_exists(db, name=domain.name, parent_id=item.parent_id, exclude_id=domain.id):
            raise HTTPException(status_code=409, detail=f'A domain named "{domain.name}" already exists at the destination level')
        domain.parent_id = item.parent_id
        domain.sort_order = item.sort_order

    db.commit()
    domains = (
        db.query(Domain)
        .filter(Domain.deleted_at.is_(None))
        .options(selectinload(Domain.tags))
        .order_by(func.lower(Domain.name), Domain.name, Domain.sort_order)
        .all()
    )
    subtree_counts = domain_subtree_document_counts(db, domains)
    direct_counts = domain_document_counts(db, [domain.id for domain in domains])
    domain_tag_ids = list({tag.id for domain in domains for tag in domain.tags})
    tag_counts = tag_document_counts(db, domain_tag_ids)
    return [
        domain_out(
            domain,
            db,
            subtree_document_count=subtree_counts.get(domain.id, 0),
            document_count=direct_counts.get(domain.id, 0),
            tag_count_map=tag_counts,
        )
        for domain in domains
    ]


@app.delete("/api/domains/{domain_id}", response_model=DomainDeleteOut)
def delete_domain(
    domain_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DomainDeleteOut:
    domain = get_active_domain(db, domain_id)
    documents = active_documents_for_domain_ids(db, [domain.id])
    before_by_id = {document.id: document_correction_snapshot(document) for document in documents}

    for document in documents:
        document.domains = [item for item in document.domains if item.id != domain.id]

    children = db.query(Domain).filter(Domain.deleted_at.is_(None), Domain.parent_id == domain.id).order_by(func.lower(Domain.name), Domain.name, Domain.sort_order).all()
    for child in children:
        target_parent_id = domain.parent_id
        if active_domain_name_exists(db, name=child.name, parent_id=target_parent_id, exclude_id=child.id):
            target_parent_id = None
        child.parent_id = target_parent_id

    db.query(Note).filter(Note.domain_id == domain.id).update({Note.domain_id: None}, synchronize_session=False)
    deleted_at = utc_now()
    domain.deleted_at = deleted_at
    domain.parent_id = None
    domain.sort_order = 0

    db.flush()
    updated_documents = record_domain_operation_history(
        db,
        documents=documents,
        before_by_id=before_by_id,
        change_note=f'Deleted domain "{domain.name}"',
        operation="domain_delete",
        extra={"domain_id": domain.id, "name": domain.name},
    )
    db.commit()
    return DomainDeleteOut(deleted_id=domain.id, updated_documents=updated_documents)


def tag_list_out(db: Session) -> list[TagOut]:
    tags = db.query(Tag).order_by(Tag.name).all()
    counts = tag_document_counts(db, [tag.id for tag in tags])
    return [tag_out(tag, db, document_count=counts.get(tag.id, 0)) for tag in tags]


@app.get("/api/tags", response_model=list[TagOut])
def list_tags(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    response: Response = None,
) -> list[TagOut]:
    return cache_or_load(
        db,
        response,
        family="organization",
        revision_families={"organization", "library"},
        key_parts={"endpoint": "tags"},
        loader=lambda: tag_list_out(db),
    )


@app.post("/api/tags", response_model=TagOut)
def create_tag(
    payload: TagCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TagOut:
    tag = get_or_create_tag_by_name(db, payload.name)
    if not tag:
        raise HTTPException(status_code=400, detail="Tag name is required")
    if payload.color and not tag.color:
        tag.color = payload.color
    db.commit()
    db.refresh(tag)
    return tag_out(tag, db)


@app.patch("/api/tags/{tag_id}", response_model=TagOperationOut)
def rename_tag(
    tag_id: str,
    payload: TagRename,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TagOperationOut:
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    normalized = normalize_tag_name(payload.name)
    if not normalized:
        raise HTTPException(status_code=400, detail="Tag name is required")
    if normalized == tag.name:
        return TagOperationOut(tag=tag_out(tag, db), updated_documents=0, removed_tag_ids=[])
    existing = db.query(Tag).filter(Tag.id != tag.id, Tag.name == normalized).one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A tag with that name already exists. Use Merge to combine tags.")

    old_name = tag.name
    documents = active_documents_for_tag_ids(db, [tag.id])
    before_by_id = {document.id: document_correction_snapshot(document) for document in documents}
    tag.name = normalized
    db.flush()
    updated_documents = record_tag_operation_history(
        db,
        documents=documents,
        before_by_id=before_by_id,
        change_note=f'Renamed tag "{old_name}" to "{normalized}"',
        operation="tag_rename",
        extra={"tag_id": tag.id, "old_name": old_name, "new_name": normalized},
    )
    db.commit()
    db.refresh(tag)
    return TagOperationOut(tag=tag_out(tag, db), updated_documents=updated_documents, removed_tag_ids=[])


@app.patch("/api/tags/{tag_id}/governance", response_model=TagOut)
def update_tag_governance(
    tag_id: str,
    payload: TagGovernancePatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TagOut:
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if payload.status is not None:
        tag.status = normalize_governance_status(payload.status)
    if payload.definition is not None:
        tag.definition = payload.definition.strip() or None
    if payload.use_guidance is not None:
        tag.use_guidance = payload.use_guidance.strip() or None
    if payload.avoid_guidance is not None:
        tag.avoid_guidance = payload.avoid_guidance.strip() or None
    metadata = dict(tag.governance_metadata or {})
    metadata["last_manual_governance_update"] = utc_now().isoformat()
    tag.governance_metadata = metadata
    db.commit()
    db.refresh(tag)
    return tag_out(tag, db)


@app.post("/api/tags/merge", response_model=TagOperationOut)
def merge_tags(
    payload: TagMerge,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TagOperationOut:
    source_ids = unique_tag_ids(payload.source_tag_ids)
    if not source_ids:
        raise HTTPException(status_code=400, detail="Select at least one tag to merge")
    source_rows = db.query(Tag).filter(Tag.id.in_(source_ids)).all()
    if len(source_rows) != len(source_ids):
        raise HTTPException(status_code=404, detail="One or more tags were not found")
    source_by_id = {tag.id: tag for tag in source_rows}
    source_tags = [source_by_id[tag_id] for tag_id in source_ids]
    source_names = {tag.id: tag.name for tag in source_tags}

    target_tag: Tag | None = None
    target_name = normalize_tag_name(payload.target_name or "")
    target_name_matched_alias = False
    if payload.target_tag_id:
        target_tag = source_by_id.get(payload.target_tag_id) or db.get(Tag, payload.target_tag_id)
        if not target_tag:
            raise HTTPException(status_code=404, detail="Kept tag was not found")
    elif target_name:
        target_tag = db.query(Tag).filter(Tag.name == target_name).one_or_none()
        if target_tag is None:
            target_tag = resolve_tag_alias(db, target_name)
            target_name_matched_alias = target_tag is not None
        if target_tag is None:
            target_tag = source_tags[0]
    else:
        raise HTTPException(status_code=400, detail="Choose a tag to keep or enter a new tag name")

    if target_tag.id in source_by_id and len(source_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least two tags to merge, or choose an existing tag outside the source set")

    documents = active_documents_for_tag_ids(db, source_ids)
    before_by_id = {document.id: document_correction_snapshot(document) for document in documents}

    if target_name and not target_name_matched_alias and target_tag.name != target_name:
        collision = db.query(Tag).filter(Tag.id != target_tag.id, Tag.name == target_name).one_or_none()
        if collision:
            target_tag = collision
        else:
            target_tag.name = target_name

    removed_tag_ids = [tag.id for tag in source_tags if tag.id != target_tag.id]
    alias_names = remember_tag_merge_aliases(
        db,
        source_tag_ids=source_ids,
        source_tag_names=source_names,
        target_tag=target_tag,
        metadata={
            "operation": "tag_merge",
            "source_tag_ids": source_ids,
            "source_tag_names": source_names,
            "target_tag_id": target_tag.id,
            "target_tag_name": target_tag.name,
            "removed_tag_ids": removed_tag_ids,
        },
    )

    for document in documents:
        next_tags = [tag for tag in document.tags if tag.id not in source_ids or tag.id == target_tag.id]
        if all(tag.id != target_tag.id for tag in next_tags):
            next_tags.append(target_tag)
        document.tags = list({tag.id: tag for tag in next_tags}.values())

    for tag in source_tags:
        if tag.id == target_tag.id:
            continue
        db.delete(tag)

    db.flush()
    updated_documents = record_tag_operation_history(
        db,
        documents=documents,
        before_by_id=before_by_id,
        change_note=f'Merged {len(source_tags)} tags into "{target_tag.name}"',
        operation="tag_merge",
        extra={
            "source_tag_ids": source_ids,
            "source_tag_names": source_names,
            "target_tag_id": target_tag.id,
            "target_tag_name": target_tag.name,
            "removed_tag_ids": removed_tag_ids,
            "alias_names": alias_names,
        },
    )
    db.commit()
    db.refresh(target_tag)
    return TagOperationOut(tag=tag_out(target_tag, db), updated_documents=updated_documents, removed_tag_ids=removed_tag_ids)


@app.post("/api/tags/relationships", response_model=TagRelationshipOut)
def create_tag_relationship(
    payload: TagRelationshipCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TagRelationshipOut:
    if payload.source_tag_id == payload.target_tag_id:
        raise HTTPException(status_code=400, detail="A tag relationship needs two different tags")
    source_tag = db.get(Tag, payload.source_tag_id)
    target_tag = db.get(Tag, payload.target_tag_id)
    if not source_tag or not target_tag:
        raise HTTPException(status_code=404, detail="One or more tags were not found")
    try:
        relationship_type = normalize_relationship_type(payload.relationship_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    relationship = (
        db.query(TagRelationship)
        .filter(
            TagRelationship.source_tag_id == source_tag.id,
            TagRelationship.target_tag_id == target_tag.id,
            TagRelationship.relationship_type == relationship_type,
        )
        .one_or_none()
    )
    if not relationship:
        relationship = TagRelationship(
            source_tag=source_tag,
            target_tag=target_tag,
            relationship_type=relationship_type,
            status="approved",
            relationship_metadata={},
        )
        db.add(relationship)
    relationship.status = "approved"
    relationship.rationale = (payload.rationale or "").strip() or None
    relationship.confidence = payload.confidence
    relationship.relationship_metadata = {
        **(relationship.relationship_metadata or {}),
        "approved_from": "optimize",
    }
    db.commit()
    db.refresh(relationship)
    return tag_relationship_out(relationship, db)


@app.post("/api/tags/assignments/prune", response_model=TagPruneOut)
def prune_tag_assignment(
    payload: TagAssignmentPruneCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TagPruneOut:
    document = (
        db.query(Document)
        .filter(Document.id == payload.document_id, library_visible_document_filter())
        .options(selectinload(Document.tags), selectinload(Document.domains), selectinload(Document.attributes))
        .one_or_none()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    tag = db.get(Tag, payload.tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if all(existing.id != tag.id for existing in document.tags):
        return TagPruneOut(document_id=document.id, tag_id=tag.id, updated_documents=0)
    before = document_correction_snapshot(document)
    document.tags = [existing for existing in document.tags if existing.id != tag.id]
    document.search_text = rebuild_document_search_text(document)
    rationale = (payload.rationale or "").strip() or "Pruned weak tag assignment from Optimize"
    assessments = (
        db.query(DocumentTagAssessment)
        .filter(DocumentTagAssessment.document_id == document.id, DocumentTagAssessment.tag_id == tag.id)
        .all()
    )
    for assessment in assessments:
        assessment.status = "pruned"
    after = document_correction_snapshot(document)
    record_document_version(
        db,
        document=document,
        change_note=f'Pruned tag "{tag.name}"',
        changed_fields={"tags"},
        before=before,
        after=after,
        extra={"operation": "tag_assignment_prune", "tag_id": tag.id, "tag_name": tag.name, "rationale": rationale},
    )
    record_manual_edit(
        db,
        document=document,
        message=f'Pruned tag "{tag.name}"',
        metadata={"operation": "tag_assignment_prune", "tag_id": tag.id, "tag_name": tag.name, "rationale": rationale},
    )
    db.commit()
    return TagPruneOut(document_id=document.id, tag_id=tag.id, updated_documents=1)


@app.post("/api/tags/orphans/prune", response_model=TagOrphanPruneOut)
def prune_orphan_tag(
    payload: TagOrphanPruneCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TagOrphanPruneOut:
    tag = db.get(Tag, payload.tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag_document_link_count(db, tag.id) > 0:
        raise HTTPException(status_code=400, detail="Only tags with no document links can be pruned entirely")
    tag_id = tag.id
    tag_name = tag.name
    assessments = db.query(DocumentTagAssessment).filter(DocumentTagAssessment.tag_id == tag.id).all()
    for assessment in assessments:
        assessment.tag_id = None
        assessment.status = "orphan_tag_pruned"
        assessment.assessment_metadata = {
            **(assessment.assessment_metadata or {}),
            "orphan_pruned_tag_id": tag_id,
            "orphan_pruned_tag_name": tag_name,
            "orphan_pruned_rationale": (payload.rationale or "").strip() or None,
        }
    db.delete(tag)
    db.commit()
    return TagOrphanPruneOut(tag_id=tag_id, tag_name=tag_name, removed_tag_ids=[tag_id])


@app.post("/api/tags/optimize/approve-all", response_model=TagOptimizationApproveAllOut)
def approve_all_tag_optimizations(
    payload: TagOptimizationApproveAllCreate,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TagOptimizationApproveAllOut:
    skipped: list[dict[str, str]] = []
    removed_tag_ids: list[str] = []
    updated_documents = 0
    merges_applied = 0
    relationships_applied = 0
    statuses_applied = 0
    prunes_applied = 0
    orphans_pruned = 0

    def skip(kind: str, item_id: str | None, reason: Any) -> None:
        skipped.append({"kind": kind, "id": item_id or "", "reason": str(reason or "Skipped stale suggestion")})

    for item in payload.merge_suggestions:
        try:
            result = merge_tags(
                TagMerge(source_tag_ids=item.source_tag_ids, target_tag_id=item.target_tag_id, target_name=item.target_name),
                user,
                db,
            )
        except HTTPException as exc:
            db.rollback()
            skip("merge", item.id, exc.detail)
            continue
        merges_applied += 1
        updated_documents += result.updated_documents
        removed_tag_ids.extend(result.removed_tag_ids)

    for item in payload.orphan_prune_suggestions:
        try:
            result = prune_orphan_tag(TagOrphanPruneCreate(tag_id=item.tag_id, rationale=item.rationale), user, db)
        except HTTPException as exc:
            db.rollback()
            skip("orphan_prune", item.id, exc.detail)
            continue
        orphans_pruned += 1
        removed_tag_ids.extend(result.removed_tag_ids)

    for item in payload.relationship_suggestions:
        try:
            create_tag_relationship(
                TagRelationshipCreate(
                    source_tag_id=item.source_tag_id,
                    target_tag_id=item.target_tag_id,
                    relationship_type=item.relationship_type,
                    rationale=item.rationale,
                    confidence=item.confidence,
                ),
                user,
                db,
            )
        except HTTPException as exc:
            db.rollback()
            skip("relationship", item.id, exc.detail)
            continue
        relationships_applied += 1

    for item in payload.status_suggestions:
        try:
            update_tag_governance(item.tag_id, TagGovernancePatch(status=item.suggested_status), user, db)
        except HTTPException as exc:
            db.rollback()
            skip("status", item.id, exc.detail)
            continue
        statuses_applied += 1

    for item in payload.pruning_suggestions:
        try:
            result = prune_tag_assignment(
                TagAssignmentPruneCreate(document_id=item.document_id, tag_id=item.tag_id, rationale=item.rationale),
                user,
                db,
            )
        except HTTPException as exc:
            db.rollback()
            skip("prune", item.id, exc.detail)
            continue
        if result.updated_documents <= 0:
            skip("prune", item.id, "The tag assignment was already absent.")
            continue
        prunes_applied += 1
        updated_documents += result.updated_documents

    return TagOptimizationApproveAllOut(
        merges_applied=merges_applied,
        relationships_applied=relationships_applied,
        statuses_applied=statuses_applied,
        prunes_applied=prunes_applied,
        orphans_pruned=orphans_pruned,
        updated_documents=updated_documents,
        removed_tag_ids=unique_tag_ids(removed_tag_ids),
        skipped=skipped,
    )


@app.post("/api/tags/optimize", response_model=TagOptimizationOut)
def optimize_tags(
    payload: TagOptimizationCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TagOptimizationOut:
    requested_ids = unique_tag_ids(payload.tag_ids or [])
    query = db.query(Tag)
    if requested_ids:
        query = query.filter(Tag.id.in_(requested_ids))
    tag_rows = query.order_by(Tag.name).all()
    if requested_ids and len(tag_rows) != len(requested_ids):
        raise HTTPException(status_code=404, detail="One or more tags were not found")
    if len(tag_rows) < 2:
        raise HTTPException(status_code=400, detail="At least two tags are required for optimization")

    document_counts_by_id = tag_document_counts(db, [tag.id for tag in tag_rows])
    inventory = [
        {
            "id": tag.id,
            "name": tag.name,
            "document_count": document_counts_by_id.get(tag.id, 0),
        }
        for tag in tag_rows
    ]
    model_inventory = tag_optimization_model_inventory(inventory)
    tag_creation_model = get_analysis_model(db, MODEL_KEYWORDS_TOPICS)
    ai_planner_error: str | None = None
    ai_planner_skipped = len(tag_rows) > TAG_OPTIMIZATION_MODEL_SCOPE_LIMIT
    if ai_planner_skipped:
        result = {"suggestions": [], "singleton_suggestions": []}
    else:
        try:
            result = get_ai_service().generate_tag_optimization_suggestions(
                model_inventory,
                model=tag_creation_model,
                primary_limit=TAG_OPTIMIZATION_PRIMARY_MERGE_LIMIT,
                singleton_limit=TAG_OPTIMIZATION_SINGLETON_MERGE_LIMIT,
                usage_context=OpenAIUsageContext(source="tags", capability_key="tag_optimization"),
            )
        except Exception as exc:
            ai_planner_error = str(exc)
            result = {"suggestions": [], "singleton_suggestions": []}

    tag_by_id = {tag.id: tag for tag in tag_rows}
    considered_tag_by_name = {tag.name: tag for tag in tag_rows}
    all_tag_rows = db.query(Tag).order_by(Tag.name).all()
    all_tag_by_name = {tag.name: tag for tag in all_tag_rows}
    all_document_counts_by_id = tag_document_counts(db, [tag.id for tag in all_tag_rows])
    suggestions: list[TagOptimizationSuggestionOut] = []
    singleton_suggestions: list[TagOptimizationSuggestionOut] = []
    orphan_merge_suggestions: list[TagOptimizationSuggestionOut] = []
    orphan_prune_suggestions: list[dict[str, Any]] = []
    orphan_action_tag_ids: set[str] = set()
    seen: set[tuple[str, tuple[str, ...]]] = set()

    def append_suggestion(
        item: dict[str, Any],
        destination: list[TagOptimizationSuggestionOut],
        *,
        fallback_rationale: str,
        id_prefix: str = "merge",
        require_singleton: bool = False,
        limit: int = TAG_OPTIMIZATION_PRIMARY_MERGE_LIMIT,
    ) -> bool:
        if not isinstance(item, dict):
            return False
        target_name = normalize_tag_name(str(item.get("target_name") or ""))
        if not target_name:
            return False
        source_ids = unique_tag_ids([str(tag_id) for tag_id in item.get("source_tag_ids") or [] if str(tag_id) in tag_by_id])
        target_in_scope = considered_tag_by_name.get(target_name)
        if target_in_scope and target_in_scope.id not in source_ids:
            source_ids.append(target_in_scope.id)
        if len(source_ids) < 2:
            return False
        if require_singleton and not any(document_counts_by_id.get(tag_id) == 1 for tag_id in source_ids):
            return False
        source_tags = sorted((tag_by_id[tag_id] for tag_id in source_ids), key=lambda tag: tag.name.lower())
        source_ids = [tag.id for tag in source_tags]
        key = (target_name, tuple(source_ids))
        if key in seen:
            return False
        seen.add(key)
        try:
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0
        confidence = min(1.0, max(0.0, confidence))
        affected_documents = len(active_documents_for_tag_ids(db, source_ids))
        target_tag = all_tag_by_name.get(target_name)
        destination.append(
            TagOptimizationSuggestionOut(
                id=f"{id_prefix}:{target_name}:{','.join(sorted(source_ids))}",
                target_name=target_name,
                target_tag_id=target_tag.id if target_tag else None,
                source_tag_ids=source_ids,
                source_tags=[tag_out(tag, db) for tag in source_tags],
                affected_documents=affected_documents,
                rationale=str(item.get("rationale") or fallback_rationale),
                confidence=confidence,
            )
        )
        return len(destination) >= limit

    def append_orphan_merge_suggestion(source: Tag, target: Tag, confidence: float, rationale: str) -> bool:
        source_tags = [source]
        source_ids = [source.id]
        key = (target.name, tuple(source_ids))
        if key in seen:
            return False
        seen.add(key)
        orphan_action_tag_ids.add(source.id)
        orphan_merge_suggestions.append(
            TagOptimizationSuggestionOut(
                id=f"orphan-merge:{target.name}:{source.id}",
                target_name=target.name,
                target_tag_id=target.id,
                source_tag_ids=source_ids,
                source_tags=[tag_out(tag, db) for tag in source_tags],
                affected_documents=0,
                rationale=rationale,
                confidence=confidence,
            )
        )
        return len(orphan_merge_suggestions) >= TAG_OPTIMIZATION_ORPHAN_MERGE_LIMIT

    raw_suggestions = result.get("suggestions") if isinstance(result, dict) else None
    suggestion_items = raw_suggestions if isinstance(raw_suggestions, list) else []
    for item in suggestion_items:
        if append_suggestion(
            item,
            suggestions,
            fallback_rationale="These tags appear to overlap and may be clearer as one tag.",
            id_prefix="merge",
            limit=TAG_OPTIMIZATION_PRIMARY_MERGE_LIMIT,
        ):
            break

    raw_singleton_suggestions = result.get("singleton_suggestions") if isinstance(result, dict) else None
    singleton_items = raw_singleton_suggestions if isinstance(raw_singleton_suggestions, list) else []
    for item in singleton_items:
        if append_suggestion(
            item,
            singleton_suggestions,
            fallback_rationale="These low-count tags look close enough to review as a cleanup merge.",
            id_prefix="singleton",
            require_singleton=True,
            limit=TAG_OPTIMIZATION_SINGLETON_MERGE_LIMIT,
        ):
            break

    singleton_rows = [tag for tag in tag_rows if document_counts_by_id.get(tag.id) == 1]
    variant_groups: dict[str, list[Tag]] = {}
    for tag in tag_rows:
        key = cleanup_tag_variant_key(tag.name)
        if key:
            variant_groups.setdefault(key, []).append(tag)
    for group in variant_groups.values():
        if len(singleton_suggestions) >= TAG_OPTIMIZATION_SINGLETON_MERGE_LIMIT:
            break
        if len(group) < 2 or not any(document_counts_by_id.get(tag.id) == 1 for tag in group):
            continue
        target = sorted(
            group,
            key=lambda tag: (
                len(cleanup_tag_tokens(tag.name)),
                1 if document_counts_by_id.get(tag.id) == 1 else 0,
                tag.name,
            ),
        )[0]
        append_suggestion(
            {
                "target_name": target.name,
                "source_tag_ids": [tag.id for tag in group],
                "rationale": "Single-document tags with matching singular/plural or formatting forms may be the same reusable tag.",
                "confidence": 0.78,
            },
            singleton_suggestions,
            fallback_rationale="These low-count tags look close enough to review as a cleanup merge.",
            id_prefix="singleton",
            require_singleton=True,
            limit=TAG_OPTIMIZATION_SINGLETON_MERGE_LIMIT,
        )

    prefix_groups: dict[str, set[str]] = {}
    for singleton in singleton_rows:
        candidates = [candidate for candidate in tag_rows if candidate.id != singleton.id and cleanup_prefix_target(singleton.name, candidate.name)]
        if not candidates:
            continue
        target = sorted(candidates, key=lambda tag: (-len(cleanup_tag_tokens(tag.name)), tag.name))[0]
        prefix_groups.setdefault(target.name, {target.id}).add(singleton.id)
    for target_name, source_ids in sorted(prefix_groups.items()):
        if len(singleton_suggestions) >= TAG_OPTIMIZATION_SINGLETON_MERGE_LIMIT:
            break
        append_suggestion(
            {
                "target_name": target_name,
                "source_tag_ids": sorted(source_ids),
                "rationale": "Single-document tags share an existing broader prefix tag and may not need separate labels.",
                "confidence": 0.7,
            },
            singleton_suggestions,
            fallback_rationale="These low-count tags look close enough to review as a cleanup merge.",
            id_prefix="singleton",
            require_singleton=True,
            limit=TAG_OPTIMIZATION_SINGLETON_MERGE_LIMIT,
        )

    shared_prefix_groups: dict[str, list[Tag]] = {}
    for singleton in singleton_rows:
        tokens = cleanup_tag_tokens(singleton.name)
        prefix_tokens = tokens[:2]
        if len(tokens) < 3 or not useful_cleanup_prefix(prefix_tokens):
            continue
        prefix_name = " ".join(prefix_tokens)
        if prefix_name in considered_tag_by_name:
            continue
        shared_prefix_groups.setdefault(prefix_name, []).append(singleton)
    for prefix_name, group in sorted(shared_prefix_groups.items()):
        if len(singleton_suggestions) >= TAG_OPTIMIZATION_SINGLETON_MERGE_LIMIT:
            break
        if len(group) < 2:
            continue
        append_suggestion(
            {
                "target_name": prefix_name,
                "source_tag_ids": [tag.id for tag in group],
                "rationale": "Several single-document tags share the same prefix; a shorter primitive tag may cover them better.",
                "confidence": 0.62,
            },
            singleton_suggestions,
            fallback_rationale="These low-count tags look close enough to review as a cleanup merge.",
            id_prefix="singleton",
            require_singleton=True,
            limit=TAG_OPTIMIZATION_SINGLETON_MERGE_LIMIT,
        )

    true_orphan_rows = [tag for tag in tag_rows if document_counts_by_id.get(tag.id, 0) == 0 and tag_document_link_count(db, tag.id) == 0]
    used_target_rows = [tag for tag in all_tag_rows if all_document_counts_by_id.get(tag.id, 0) > 0]
    for orphan in sorted(true_orphan_rows, key=lambda tag: tag.name):
        if len(orphan_merge_suggestions) >= TAG_OPTIMIZATION_ORPHAN_MERGE_LIMIT:
            break
        match = orphan_merge_candidate(orphan, used_target_rows, all_document_counts_by_id)
        if match:
            target, confidence, rationale = match
            append_orphan_merge_suggestion(orphan, target, confidence, rationale)
    for orphan in sorted(true_orphan_rows, key=lambda tag: tag.name):
        if orphan.id in orphan_action_tag_ids:
            continue
        orphan_action_tag_ids.add(orphan.id)
        orphan_prune_suggestions.append(
            {
                "id": f"orphan-prune:{orphan.id}",
                "tag": orphan,
                "rationale": "This tag has no document links and no strong used-tag merge target; prune it entirely instead of keeping taxonomy clutter.",
                "confidence": 0.88,
            }
        )
        if len(orphan_prune_suggestions) >= TAG_OPTIMIZATION_ORPHAN_PRUNE_LIMIT:
            break

    relationship_suggestions = [
        {
            "id": item["id"],
            "source_tag": tag_out(item["source_tag"], db),
            "target_tag": tag_out(item["target_tag"], db),
            "relationship_type": item["relationship_type"],
            "rationale": item["rationale"],
            "confidence": float(item["confidence"]),
        }
        for item in relationship_review_suggestions(db, tag_rows, limit=TAG_OPTIMIZATION_RELATIONSHIP_LIMIT)
    ]
    status_suggestions = [
        {
            "id": item["id"],
            "tag": tag_out(item["tag"], db),
            "suggested_status": item["suggested_status"],
            "rationale": item["rationale"],
            "confidence": float(item["confidence"]),
        }
        for item in status_review_suggestions(db, tag_rows, limit=TAG_OPTIMIZATION_STATUS_LIMIT)
        if item["tag"].id not in orphan_action_tag_ids
    ]
    pruning_suggestions = [
        {
            "id": item["id"],
            "document_id": item["document_id"],
            "document_title": item["document_title"],
            "tag": tag_out(item["tag"], db),
            "rationale": item["rationale"],
            "confidence": float(item["confidence"]),
            "relevance_score": float(item["relevance_score"]),
            "library_fit_score": float(item["library_fit_score"]),
            "novelty_score": float(item["novelty_score"]),
            "overall_score": float(item["overall_score"]),
        }
        for item in pruning_review_suggestions(db, tag_rows, limit=TAG_OPTIMIZATION_ASSIGNMENT_PRUNE_LIMIT)
    ]

    health_summary = tag_health_summary(db, tag_rows)
    if ai_planner_error:
        health_summary["ai_planner_failed"] = 1
    if ai_planner_skipped:
        health_summary["ai_planner_skipped"] = 1

    return TagOptimizationOut(
        model=tag_creation_model,
        considered_tags=len(tag_rows),
        suggestions=suggestions,
        singleton_suggestions=singleton_suggestions,
        orphan_merge_suggestions=orphan_merge_suggestions,
        relationship_suggestions=relationship_suggestions,
        status_suggestions=status_suggestions,
        pruning_suggestions=pruning_suggestions,
        orphan_prune_suggestions=[
            {
                "id": item["id"],
                "tag": tag_out(item["tag"], db),
                "rationale": item["rationale"],
                "confidence": float(item["confidence"]),
            }
            for item in orphan_prune_suggestions
        ],
        health_summary=health_summary,
    )


@app.get("/api/saved-searches", response_model=list[SavedSearchOut])
def list_saved_searches(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[SavedSearch]:
    return db.query(SavedSearch).filter(SavedSearch.deleted_at.is_(None)).order_by(SavedSearch.sort_order, SavedSearch.name).all()


@app.post("/api/saved-searches", response_model=SavedSearchOut)
def create_saved_search(
    payload: SavedSearchCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SavedSearch:
    saved_search = SavedSearch(name=payload.name.strip(), query=(payload.query or "").strip() or None, filters=payload.filters)
    if not saved_search.name:
        raise HTTPException(status_code=400, detail="Saved search name is required")
    db.add(saved_search)
    db.commit()
    db.refresh(saved_search)
    return saved_search


@app.patch("/api/saved-searches/{saved_search_id}", response_model=SavedSearchOut)
def patch_saved_search(
    saved_search_id: str,
    payload: SavedSearchPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SavedSearch:
    saved_search = db.get(SavedSearch, saved_search_id)
    if not saved_search or saved_search.deleted_at:
        raise HTTPException(status_code=404, detail="Saved search not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key == "name" and value is not None:
            value = value.strip()
            if not value:
                raise HTTPException(status_code=400, detail="Saved search name is required")
        if key == "query" and value is not None:
            value = value.strip() or None
        setattr(saved_search, key, value)
    db.commit()
    db.refresh(saved_search)
    return saved_search


@app.delete("/api/saved-searches/{saved_search_id}")
def delete_saved_search(
    saved_search_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    saved_search = db.get(SavedSearch, saved_search_id)
    if not saved_search or saved_search.deleted_at:
        raise HTTPException(status_code=404, detail="Saved search not found")
    saved_search.deleted_at = utc_now()
    db.commit()
    return {"status": "deleted"}


def recon_inquiry_or_404(db: Session, inquiry_id: str) -> ReconInquiry:
    inquiry = (
        db.query(ReconInquiry)
        .options(
            selectinload(ReconInquiry.runs).selectinload(ReconRun.evidence),
            selectinload(ReconInquiry.runs).selectinload(ReconRun.answers),
        )
        .filter(ReconInquiry.id == inquiry_id, ReconInquiry.deleted_at.is_(None))
        .one_or_none()
    )
    if not inquiry:
        raise HTTPException(status_code=404, detail="Recon inquiry not found")
    return inquiry


def recon_run_or_404(db: Session, run_id: str) -> ReconRun:
    run = (
        db.query(ReconRun)
        .options(selectinload(ReconRun.evidence), selectinload(ReconRun.answers), joinedload(ReconRun.inquiry))
        .filter(ReconRun.id == run_id)
        .one_or_none()
    )
    if not run or not run.inquiry or run.inquiry.deleted_at:
        raise HTTPException(status_code=404, detail="Recon run not found")
    return run


@app.get("/api/recon/inquiries", response_model=list[ReconInquiryOut])
def list_recon_inquiries(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ReconInquiry]:
    return (
        db.query(ReconInquiry)
        .options(
            selectinload(ReconInquiry.runs).selectinload(ReconRun.evidence),
            selectinload(ReconInquiry.runs).selectinload(ReconRun.answers),
        )
        .filter(ReconInquiry.deleted_at.is_(None))
        .order_by(ReconInquiry.updated_at.desc(), ReconInquiry.title)
        .all()
    )


@app.post("/api/recon/inquiries", response_model=ReconInquiryOut)
def create_recon_inquiry_route(
    payload: ReconInquiryCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ReconInquiry:
    try:
        inquiry = create_recon_inquiry(
            db,
            title=payload.title,
            question=payload.question,
            instructions=payload.instructions,
            scope_type=payload.scope_type,
            scope=payload.scope,
            default_mode=payload.default_mode,
            model=payload.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return recon_inquiry_or_404(db, inquiry.id)


@app.patch("/api/recon/inquiries/{inquiry_id}", response_model=ReconInquiryOut)
def patch_recon_inquiry_route(
    inquiry_id: str,
    payload: ReconInquiryPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ReconInquiry:
    inquiry = recon_inquiry_or_404(db, inquiry_id)
    try:
        update_recon_inquiry(db, inquiry, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return recon_inquiry_or_404(db, inquiry_id)


@app.post("/api/recon/inquiries/{inquiry_id}/estimate", response_model=ReconEstimateOut)
def estimate_recon_inquiry_route(
    inquiry_id: str,
    payload: ReconRunCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    inquiry = recon_inquiry_or_404(db, inquiry_id)
    return estimate_recon_run(
        db,
        question=inquiry.question,
        scope_type=inquiry.scope_type,
        scope=inquiry.scope,
        mode=payload.mode or inquiry.default_mode,
    )


@app.post("/api/recon/inquiries/{inquiry_id}/runs", response_model=ReconRunOut)
def start_recon_run_route(
    inquiry_id: str,
    payload: ReconRunCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ReconRun:
    inquiry = recon_inquiry_or_404(db, inquiry_id)
    return run_recon_inquiry(db, inquiry, mode=payload.mode, model=payload.model)


@app.get("/api/recon/runs/{run_id}", response_model=ReconRunOut)
def get_recon_run_route(
    run_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ReconRun:
    return recon_run_or_404(db, run_id)


@app.post("/api/recon/runs/{run_id}/cancel", response_model=ReconRunOut)
def cancel_recon_run_route(
    run_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ReconRun:
    run = recon_run_or_404(db, run_id)
    return cancel_recon_run(db, run)


@app.get("/api/attributes", response_model=list[AttributeDefinitionOut])
def list_attributes(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[AttributeDefinition]:
    return db.query(AttributeDefinition).filter(AttributeDefinition.deleted_at.is_(None)).order_by(AttributeDefinition.name).all()


@app.post("/api/attributes", response_model=AttributeDefinitionOut)
def create_attribute(
    payload: AttributeDefinitionCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AttributeDefinition:
    definition = AttributeDefinition(**payload.model_dump())
    db.add(definition)
    db.commit()
    db.refresh(definition)
    return definition


def project_list_out(db: Session) -> list[ProjectOut]:
    projects = db.query(Project).filter(Project.deleted_at.is_(None)).order_by(Project.created_at.desc()).all()
    return [project_out(project) for project in projects]


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    response: Response = None,
) -> list[ProjectOut]:
    return cache_or_load(
        db,
        response,
        family="organization",
        revision_families={"organization", "library"},
        key_parts={"endpoint": "projects"},
        loader=lambda: project_list_out(db),
    )


@app.post("/api/projects", response_model=ProjectOut)
def create_project(
    payload: ProjectCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectOut:
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project_out(project)


@app.get("/api/projects/{project_id}", response_model=ProjectDetail)
def get_project(
    project_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectDetail:
    project = db.get(Project, project_id)
    if not project or project.deleted_at:
        raise HTTPException(status_code=404, detail="Project not found")
    return project_detail_out(project)


@app.post("/api/projects/{project_id}/items", response_model=ProjectDetail)
def add_project_items(
    project_id: str,
    payload: ProjectItemCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectDetail:
    project = db.get(Project, project_id)
    if not project or project.deleted_at:
        raise HTTPException(status_code=404, detail="Project not found")
    document_ids = list(dict.fromkeys(payload.document_ids))
    if not document_ids:
        raise HTTPException(status_code=400, detail="document_ids is required")
    documents = filter_library_visible_documents(db.query(Document)).filter(Document.id.in_(document_ids)).all()
    existing_ids = {item.document_id for item in project.items}
    for document in documents:
        if document.id in existing_ids:
            continue
        db.add(
            ProjectItem(
                project_id=project.id,
                document_id=document.id,
                status=payload.status,
                priority=payload.priority,
                used_in_output=payload.used_in_output,
                note=payload.note,
            )
        )
    db.commit()
    db.refresh(project)
    db.expire(project, ["items"])
    return project_detail_out(project)


@app.patch("/api/projects/{project_id}/items/{item_id}", response_model=ProjectItemOut)
def patch_project_item(
    project_id: str,
    item_id: str,
    payload: ProjectItemPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectItem:
    item = db.query(ProjectItem).filter(ProjectItem.project_id == project_id, ProjectItem.id == item_id).one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Project item not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@app.delete("/api/projects/{project_id}/items/{item_id}")
def delete_project_item(
    project_id: str,
    item_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    item = db.query(ProjectItem).filter(ProjectItem.project_id == project_id, ProjectItem.id == item_id).one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Project item not found")
    db.delete(item)
    db.commit()
    return {"status": "deleted"}


@app.get("/api/documents", response_model=list[DocumentSummary])
def list_documents(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    domain_id: str | None = None,
    tag_id: str | None = None,
    read_status: str | None = None,
    priority: str | None = None,
    citation_status: str | None = None,
    duplicate_status: str | None = None,
    health_status: str | None = None,
    include_duplicate_summary: bool = True,
    include_projects: bool = True,
    limit: Annotated[int | None, Query(ge=1, le=5000)] = None,
) -> list[DocumentSummary]:
    query = filter_library_visible_documents(db.query(Document)).options(selectinload(Document.tags), selectinload(Document.domains))
    query, search_rank = apply_document_filters(
        query,
        db,
        q=q,
        domain_id=domain_id,
        tag_id=tag_id,
        read_status=read_status,
        priority=priority,
        citation_status=citation_status,
    )
    if duplicate_status:
        if duplicate_status == "duplicates":
            query = query.filter(Document.duplicate_count > 0)
        elif duplicate_status == "unique":
            query = query.filter(Document.duplicate_count == 0)
    query = apply_document_health_filter(query, health_status)
    order_columns = [search_rank.desc()] if search_rank is not None else []
    order_columns.extend(document_title_order_columns(db))
    query = query.order_by(None).order_by(*order_columns)
    if limit is not None:
        query = query.limit(limit)
    documents = query.all()
    duplicate_summary = persisted_duplicate_summary_by_document(documents) if include_duplicate_summary else {}
    project_map = project_summaries_for_documents(db, [document.id for document in documents]) if include_projects else {}
    return [
        document_summary_out(
            document,
            duplicate_summary.get(document.id, {}).get("duplicate_count", 0),
            project_map.get(document.id, []),
            duplicate_summary.get(document.id, {}).get("duplicate_reasons", []),
        )
        for document in documents
    ]


def document_list_rows_out(
    db: Session,
    q: str | None = None,
    domain_id: str | None = None,
    tag_id: str | None = None,
    read_status: str | None = None,
    priority: str | None = None,
    citation_status: str | None = None,
    duplicate_status: str | None = None,
    health_status: str | None = None,
    all_results: Annotated[bool, Query(alias="all")] = False,
    focus_document_id: str | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1)] = 50,
) -> DocumentListOut:
    query = filter_library_visible_documents(db.query(Document)).options(selectinload(Document.tags), selectinload(Document.domains))
    query, search_rank = apply_document_filters(
        query,
        db,
        q=q,
        domain_id=domain_id,
        tag_id=tag_id,
        read_status=read_status,
        priority=priority,
        citation_status=citation_status,
    )
    if duplicate_status == "duplicates":
        query = query.filter(Document.duplicate_count > 0)
    elif duplicate_status == "unique":
        query = query.filter(Document.duplicate_count == 0)
    query = apply_document_health_filter(query, health_status)

    total_count = int(query.order_by(None).count())
    total_page_count = int(query.order_by(None).with_entities(func.coalesce(func.sum(Document.page_count), 0)).scalar() or 0)
    latest_updated = query.order_by(None).with_entities(func.max(Document.updated_at)).scalar()
    order_columns = [search_rank.desc()] if search_rank is not None else []
    order_columns.extend(document_title_order_columns(db))
    focus_index: int | None = None
    if focus_document_id:
        ordered_ids = [row[0] for row in query.order_by(None).order_by(*order_columns).with_entities(Document.id).all()]
        try:
            focus_index = ordered_ids.index(focus_document_id)
        except ValueError:
            focus_index = None
        if focus_index is not None and not all_results and not (offset <= focus_index < offset + limit):
            offset = (focus_index // limit) * limit
    if all_results:
        offset = 0
        documents = query.order_by(None).order_by(*order_columns).all()
        limit = len(documents)
    else:
        documents = query.order_by(None).order_by(*order_columns).offset(offset).limit(limit).all()
    project_map = project_summaries_for_documents(db, [document.id for document in documents])
    revision_parts = [str(total_count), str(total_page_count), latest_updated.isoformat() if latest_updated else "none"]
    return DocumentListOut(
        items=[document_list_row_out(document, project_map.get(document.id, [])) for document in documents],
        total_count=total_count,
        total_page_count=total_page_count,
        offset=offset,
        limit=limit,
        has_more=False if all_results else offset + len(documents) < total_count,
        revision=":".join(revision_parts),
        focus_document_id=focus_document_id,
        focus_index=focus_index,
    )


@app.get("/api/documents/list", response_model=DocumentListOut)
def list_document_rows(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    response: Response = None,
    q: str | None = None,
    domain_id: str | None = None,
    tag_id: str | None = None,
    read_status: str | None = None,
    priority: str | None = None,
    citation_status: str | None = None,
    duplicate_status: str | None = None,
    health_status: str | None = None,
    all_results: Annotated[bool, Query(alias="all")] = False,
    focus_document_id: str | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1)] = 50,
) -> DocumentListOut:
    key_parts = {
        "q": q or "",
        "domain_id": domain_id or "",
        "tag_id": tag_id or "",
        "read_status": read_status or "",
        "priority": priority or "",
        "citation_status": citation_status or "",
        "duplicate_status": duplicate_status or "",
        "health_status": health_status or "",
        "all": bool(all_results),
        "focus_document_id": focus_document_id or "",
        "offset": int(offset),
        "limit": int(limit),
    }
    return cache_or_load(
        db,
        response,
        family="documents:list",
        revision_families={"library", "organization"},
        key_parts=key_parts,
        loader=lambda: document_list_rows_out(
            db,
            q=q,
            domain_id=domain_id,
            tag_id=tag_id,
            read_status=read_status,
            priority=priority,
            citation_status=citation_status,
            duplicate_status=duplicate_status,
            health_status=health_status,
            all_results=all_results,
            focus_document_id=focus_document_id,
            offset=offset,
            limit=limit,
        ),
    )


@app.get("/api/documents/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    response: Response = None,
) -> DocumentDetail:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    key_parts = {
        "document_id": document.id,
        "updated_at": document.updated_at.isoformat() if document.updated_at else "",
        "deleted_at": document.deleted_at.isoformat() if document.deleted_at else "",
        "processing_status": document.processing_status,
    }
    return cache_or_load(
        db,
        response,
        family="documents:detail",
        revision_families={"document_detail", "organization"},
        key_parts=key_parts,
        loader=lambda: document_detail_out(document, db),
    )


@app.get("/api/documents/duplicates/scan", response_model=DuplicateScanOut)
def scan_document_duplicates(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DuplicateScanOut:
    documents = filter_library_visible_documents(db.query(Document)).order_by(*document_title_order_columns(db)).all()
    matches = duplicate_matches_by_document(db, documents=documents)
    persist_duplicate_match_summaries(db, documents, matches)
    db.commit()
    stats = duplicate_document_version_stats(db, [document.id for document in documents])
    by_id = {document.id: document for document in documents}
    pairs: list[DuplicatePairOut] = []
    seen: set[tuple[str, str]] = set()
    for document in documents:
        for match in matches.get(document.id, []):
            pair_key = tuple(sorted([document.id, match.document.id]))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            pairs.append(duplicate_pair_out(document, by_id[match.document.id], match, stats))
    pairs.sort(key=lambda pair: (-pair.match_score, pair.left.title.lower(), pair.right.title.lower(), pair.id))
    return DuplicateScanOut(pairs=pairs, pair_count=len(pairs), document_count=len({item for pair in pairs for item in [pair.left.id, pair.right.id]}))


@app.post("/api/documents/duplicates/resolve", response_model=DuplicateResolveOut)
def resolve_document_duplicate(
    payload: DuplicateResolveCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DuplicateResolveOut:
    if payload.keep_document_id == payload.duplicate_document_id:
        raise HTTPException(status_code=400, detail="Choose two different documents")
    keep_document = db.get(Document, payload.keep_document_id)
    duplicate_document = db.get(Document, payload.duplicate_document_id)
    if not document_is_library_visible(keep_document) or not document_is_library_visible(duplicate_document):
        raise HTTPException(status_code=404, detail="Duplicate pair not found")
    reasons = duplicate_match_reasons(document_duplicate_profile(keep_document), document_duplicate_profile(duplicate_document))
    if duplicate_match_score(reasons) <= 0:
        raise HTTPException(status_code=400, detail="Documents no longer match as duplicates")
    resolved_at = utc_now()
    basis = match_basis(reasons)
    keep_before = document_correction_snapshot(keep_document)
    duplicate_before = document_correction_snapshot(duplicate_document)
    keep_evidence = dict(keep_document.metadata_evidence or {})
    kept_resolutions = list(keep_evidence.get("duplicate_resolutions") or [])
    kept_resolutions.append(
        {
            "status": "kept",
            "duplicate_document_id": duplicate_document.id,
            "match_reasons": reasons,
            "match_basis": basis,
            "resolved_at": resolved_at.isoformat(),
        }
    )
    keep_evidence["duplicate_resolutions"] = kept_resolutions
    keep_document.metadata_evidence = keep_evidence
    duplicate_evidence = dict(duplicate_document.metadata_evidence or {})
    duplicate_evidence["duplicate_resolution"] = {
        "status": "resolved_duplicate",
        "kept_document_id": keep_document.id,
        "match_reasons": reasons,
        "match_basis": basis,
        "resolved_at": resolved_at.isoformat(),
    }
    duplicate_document.metadata_evidence = duplicate_evidence
    duplicate_document.deleted_at = resolved_at
    db.flush()
    record_document_version(
        db,
        document=keep_document,
        change_note="Duplicate resolution kept",
        changed_fields={"metadata_evidence"},
        before=keep_before,
        after=document_correction_snapshot(keep_document),
        extra={"operation": "duplicate_resolution", "duplicate_document_id": duplicate_document.id, "match_reasons": reasons},
    )
    record_document_version(
        db,
        document=duplicate_document,
        change_note="Duplicate resolution removed",
        changed_fields={"metadata_evidence", "deleted_at"},
        before=duplicate_before,
        after=document_correction_snapshot(duplicate_document),
        extra={
            "operation": "duplicate_resolution",
            "kept_document_id": keep_document.id,
            "match_reasons": reasons,
            "deleted_at": resolved_at.isoformat(),
        },
    )
    record_manual_edit(
        db,
        document=keep_document,
        message="Duplicate resolution kept",
        metadata={"duplicate_document_id": duplicate_document.id, "match_reasons": reasons, "match_basis": basis},
    )
    record_manual_edit(
        db,
        document=duplicate_document,
        message="Duplicate resolution removed",
        metadata={"kept_document_id": keep_document.id, "match_reasons": reasons, "match_basis": basis},
    )
    refresh_duplicate_match_summaries(db)
    db.commit()
    return DuplicateResolveOut(keep_document_id=keep_document.id, duplicate_document_id=duplicate_document.id)


@app.post("/api/documents/duplicates/dismiss", response_model=DuplicateDismissOut)
def dismiss_document_duplicate(
    payload: DuplicateDismissCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DuplicateDismissOut:
    if payload.left_document_id == payload.right_document_id:
        raise HTTPException(status_code=400, detail="Choose two different documents")
    left_document = db.get(Document, payload.left_document_id)
    right_document = db.get(Document, payload.right_document_id)
    if not document_is_library_visible(left_document) or not document_is_library_visible(right_document):
        raise HTTPException(status_code=404, detail="Duplicate pair not found")
    if (
        right_document.id in duplicate_false_positive_document_ids(left_document)
        and left_document.id in duplicate_false_positive_document_ids(right_document)
    ):
        return DuplicateDismissOut(left_document_id=left_document.id, right_document_id=right_document.id)

    reasons = duplicate_match_reasons(document_duplicate_profile(left_document), document_duplicate_profile(right_document))
    score = duplicate_match_score(reasons)
    basis = match_basis(reasons) if reasons else "manual review"
    dismissed_at = utc_now()
    left_before = document_correction_snapshot(left_document)
    right_before = document_correction_snapshot(right_document)
    append_duplicate_false_positive_evidence(
        left_document,
        other_document=right_document,
        dismissed_at=dismissed_at,
        match_reasons=reasons,
        match_score=score,
        match_basis_text=basis,
    )
    append_duplicate_false_positive_evidence(
        right_document,
        other_document=left_document,
        dismissed_at=dismissed_at,
        match_reasons=reasons,
        match_score=score,
        match_basis_text=basis,
    )
    db.flush()
    record_document_version(
        db,
        document=left_document,
        change_note="Duplicate match dismissed",
        changed_fields={"metadata_evidence"},
        before=left_before,
        after=document_correction_snapshot(left_document),
        extra={"operation": "duplicate_false_positive", "other_document_id": right_document.id, "match_reasons": reasons},
    )
    record_document_version(
        db,
        document=right_document,
        change_note="Duplicate match dismissed",
        changed_fields={"metadata_evidence"},
        before=right_before,
        after=document_correction_snapshot(right_document),
        extra={"operation": "duplicate_false_positive", "other_document_id": left_document.id, "match_reasons": reasons},
    )
    record_manual_edit(
        db,
        document=left_document,
        message="Duplicate match marked different",
        metadata={"other_document_id": right_document.id, "match_reasons": reasons, "match_basis": basis},
    )
    record_manual_edit(
        db,
        document=right_document,
        message="Duplicate match marked different",
        metadata={"other_document_id": left_document.id, "match_reasons": reasons, "match_basis": basis},
    )
    refresh_duplicate_match_summaries(db)
    db.commit()
    return DuplicateDismissOut(left_document_id=left_document.id, right_document_id=right_document.id)


@app.get("/api/documents/{document_id}/composition", response_model=DocumentCompositionOut)
def get_document_composition(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    return document_composition_summary(db, document)


@app.post("/api/documents/{document_id}/citation-refresh", response_model=ConcordanceRunOut)
def refresh_document_citation(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    confirm_verified: bool = False,
) -> ConcordanceRun:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    verified_fields = verified_document_fields(document, ["doi", "apa_citation", "apa_in_text_citation"])
    if verified_fields:
        if not confirm_verified:
            raise HTTPException(status_code=409, detail="Confirm refreshing manually verified DOI or APA citation data before starting")
        before = document_correction_snapshot(document)
        if clear_document_field_verifications(document, verified_fields):
            db.flush()
            record_document_version(
                db,
                document=document,
                change_note="Cleared DOI/APA verification for refresh",
                changed_fields={"metadata_evidence"},
                before=before,
                after=document_correction_snapshot(document),
                extra={"operation": "citation_refresh_unverify", "fields": verified_fields},
            )
            record_manual_edit(
                db,
                document=document,
                message="Cleared DOI/APA verification for refresh",
                metadata={"operation": "citation_refresh_unverify", "fields": verified_fields},
            )
    run = create_concordance_run(
        db,
        scope_type="documents",
        scope_data={"document_ids": [document.id]},
        capability_keys=["citation_refresh"],
        force=True,
        label=f"Citation check: {document.title}",
    )
    db.commit()
    db.refresh(run)
    return run


def mark_document_field_verified(db: Session, document: Document, field: str, user: User) -> DocumentDetail:
    config = DOCUMENT_FIELD_VERIFICATION_CONFIG.get(field)
    if not config:
        raise HTTPException(status_code=404, detail="Verification field not found")
    value = getattr(document, str(config["attribute"]), None)
    if not (str(value or "").strip()):
        raise HTTPException(status_code=400, detail=f"{config['label']} is required before it can be marked verified")

    before = document_correction_snapshot(document)
    verified_at = utc_now()
    evidence = dict(document.metadata_evidence or {})
    evidence[str(config["metadata_key"])] = {
        "status": "verified",
        "verified_at": verified_at.isoformat(),
        "verified_by": user.email,
        "verified_by_user_id": user.id,
    }
    document.metadata_evidence = evidence
    db.flush()
    record_document_version(
        db,
        document=document,
        change_note=f"Verified {config['label']}",
        changed_fields={"metadata_evidence"},
        before=before,
        after=document_correction_snapshot(document),
        extra={"operation": "document_field_verification", "field": field, "verified_at": verified_at.isoformat()},
    )
    record_manual_edit(
        db,
        document=document,
        message=f"Verified {config['label']}",
        metadata={"operation": "document_field_verification", "field": field, "verified_at": verified_at.isoformat()},
    )
    db.commit()
    db.refresh(document)
    return document_detail_out(document, db)


@app.post("/api/documents/{document_id}/field-verifications/{field}", response_model=DocumentDetail)
def verify_document_field(
    document_id: str,
    field: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    return mark_document_field_verified(db, document, field, user)


@app.post("/api/documents/{document_id}/bibliography-verification", response_model=DocumentDetail)
def verify_document_bibliography(
    document_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    return mark_document_field_verified(db, document, "bibliography", user)


@app.post("/api/documents/{document_id}/bibliography-refresh", response_model=ConcordanceRunOut)
def refresh_document_bibliography(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    confirm_verified: bool = False,
) -> ConcordanceRun:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    if document_bibliography_is_verified(document):
        if not confirm_verified:
            raise HTTPException(status_code=409, detail="Confirm refreshing the manually verified bibliography before starting")
        before = document_correction_snapshot(document)
        if clear_document_bibliography_verification(document):
            db.flush()
            record_document_version(
                db,
                document=document,
                change_note="Cleared bibliography verification for refresh",
                changed_fields={"metadata_evidence"},
                before=before,
                after=document_correction_snapshot(document),
                extra={"operation": "bibliography_refresh_unverify"},
            )
            record_manual_edit(
                db,
                document=document,
                message="Cleared bibliography verification for refresh",
                metadata={"operation": "bibliography_refresh_unverify"},
            )
    run = create_concordance_run(
        db,
        scope_type="documents",
        scope_data={"document_ids": [document.id]},
        capability_keys=["bibliography_extraction"],
        force=True,
        label=f"Bibliography refresh: {document.title}",
    )
    db.commit()
    db.refresh(run)
    return run


@app.post("/api/documents/{document_id}/accessory-summaries", response_model=AccessorySummaryOut)
def queue_document_accessory_summary(
    document_id: str,
    payload: AccessorySummaryCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentAccessorySummary:
    return _create_document_accessory_summary(document_id, payload, db, inline=False)


@app.post("/api/documents/{document_id}/inquests", response_model=AccessorySummaryOut)
def create_document_inquest(
    document_id: str,
    payload: AccessorySummaryCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentAccessorySummary:
    return _create_document_accessory_summary(document_id, payload, db, inline=True)


def _create_document_accessory_summary(
    document_id: str,
    payload: AccessorySummaryCreate,
    db: Session,
    *,
    inline: bool,
) -> DocumentAccessorySummary:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        summary = create_accessory_summary(
            db,
            document,
            prompt=payload.prompt,
            model=payload.model,
            title=payload.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(summary)
    if inline:
        AccessorySummaryProcessor().process_summary(
            db,
            summary,
            timeout_seconds=settings.inquest_inline_timeout_seconds,
            defer_timeouts=True,
        )
        db.refresh(summary)
    return summary


@app.patch("/api/accessory-summaries/{summary_id}", response_model=AccessorySummaryOut)
def patch_accessory_summary(
    summary_id: str,
    payload: AccessorySummaryPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentAccessorySummary:
    summary = db.get(DocumentAccessorySummary, summary_id)
    if not summary or not document_is_library_visible(summary.document):
        raise HTTPException(status_code=404, detail="Accessory summary not found")
    if payload.title is not None:
        title = " ".join(payload.title.strip().split())
        summary.title = title[:240] or None
    if document_is_library_visible(summary.document):
        summary.document.search_text = rebuild_document_search_text(summary.document)
    db.commit()
    db.refresh(summary)
    return summary


@app.get("/api/documents/{document_id}/recommendations", response_model=list[DocumentRecommendationOut])
def get_document_recommendations(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    hide_existing: bool = False,
    view: str | None = Query(default=None, pattern="^(discover|known|all)$"),
    family: str | None = Query(
        default=None,
        pattern="^(diverse|closest|newer|foundational|methods|contrasting|open_pdf|reference_material)$",
    ),
) -> list[DocumentRecommendation]:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    rows = list_document_recommendations(db, document, hide_existing=hide_existing, view=view, family=family)
    db.commit()
    return rows


@app.post("/api/documents/{document_id}/recommendations/refresh", response_model=DocumentRecommendationRefreshOut)
def refresh_recommendations(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentRecommendationRefreshOut:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    if document.processing_status != "ready":
        raise HTTPException(status_code=409, detail="Recommendations are available after processing is complete")
    if not document_has_recommendation_inputs(document):
        raise HTTPException(status_code=400, detail="A title, DOI, extracted bibliography, summary, tag, or domain is required to refresh related-paper recommendations")
    rows = refresh_document_recommendations(db, document)
    db.commit()
    return DocumentRecommendationRefreshOut(
        document_id=document.id,
        recommendation_count=len(rows),
        recommendations=[DocumentRecommendationOut.model_validate(row) for row in rows],
    )


@app.post("/api/documents/{document_id}/recommendations/download", response_model=DocumentRecommendationDownloadOut)
def download_recommendations(
    document_id: str,
    payload: DocumentRecommendationDownloadCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentRecommendationDownloadOut:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    if payload.mode == "new":
        recommendations = [
            row
            for row in list_document_recommendations(db, document, view="discover", family="open_pdf")
            if row.has_pdf
        ]
    else:
        ids = payload.recommendation_ids or []
        if not ids:
            raise HTTPException(status_code=400, detail="recommendation_ids is required for selected downloads")
        recommendations = (
            db.query(DocumentRecommendation)
            .filter(DocumentRecommendation.source_document_id == document.id, DocumentRecommendation.id.in_(ids))
            .order_by(DocumentRecommendation.title)
            .all()
        )
    if not recommendations:
        raise HTTPException(status_code=400, detail="No recommendations matched the download request")
    result = queue_recommendation_imports(db, document, recommendations, skip_existing=payload.skip_existing)
    db.commit()
    return DocumentRecommendationDownloadOut(**result)


PORTFOLIO_VERSION_DOCUMENT_KIND = "portfolio_version"
PORTFOLIO_MATERIAL_DOCUMENT_KIND = "portfolio_material"
PORTFOLIO_SUGGESTION_STOPWORDS = {
    "about",
    "after",
    "also",
    "analysis",
    "because",
    "before",
    "between",
    "could",
    "draft",
    "from",
    "have",
    "into",
    "more",
    "other",
    "paper",
    "portfolio",
    "research",
    "should",
    "study",
    "their",
    "there",
    "these",
    "this",
    "through",
    "version",
    "were",
    "when",
    "where",
    "which",
    "with",
    "would",
}


def portfolio_source_storage_key(checksum: str, document_id: str, filename: str) -> str:
    return f"portfolio/sources/{checksum[:2]}/{checksum}/{document_id}/{filename}"


def sync_portfolio_processing_status(item: PortfolioItem) -> None:
    for version in item.versions:
        if version.document and version.processing_status != version.document.processing_status:
            version.processing_status = version.document.processing_status
    if item.current_version and item.current_version.document:
        item.current_version.processing_status = item.current_version.document.processing_status


def portfolio_item_query(db: Session):
    return (
        db.query(PortfolioItem)
        .options(
            selectinload(PortfolioItem.current_version).joinedload(PortfolioVersion.document),
            selectinload(PortfolioItem.current_version).selectinload(PortfolioVersion.parent_edges),
            selectinload(PortfolioItem.versions).joinedload(PortfolioVersion.document),
            selectinload(PortfolioItem.versions).selectinload(PortfolioVersion.parent_edges),
            selectinload(PortfolioItem.materials).joinedload(PortfolioMaterial.document),
            selectinload(PortfolioItem.suggestions).joinedload(PortfolioSuggestion.library_document),
            selectinload(PortfolioItem.assessment_runs).selectinload(PortfolioAssessmentRun.findings),
        )
        .filter(PortfolioItem.deleted_at.is_(None))
    )


def portfolio_item_or_404(db: Session, portfolio_item_id: str) -> PortfolioItem:
    item = portfolio_item_query(db).filter(PortfolioItem.id == portfolio_item_id).one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Portfolio item not found")
    sync_portfolio_processing_status(item)
    return item


def portfolio_version_or_404(db: Session, version_id: str) -> PortfolioVersion:
    version = (
        db.query(PortfolioVersion)
        .join(PortfolioItem, PortfolioItem.id == PortfolioVersion.portfolio_item_id)
        .options(joinedload(PortfolioVersion.document), selectinload(PortfolioVersion.parent_edges))
        .filter(PortfolioVersion.id == version_id, PortfolioItem.deleted_at.is_(None))
        .one_or_none()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Portfolio version not found")
    if version.document:
        version.processing_status = version.document.processing_status
    return version


def portfolio_material_or_404(db: Session, material_id: str) -> PortfolioMaterial:
    material = (
        db.query(PortfolioMaterial)
        .join(PortfolioItem, PortfolioItem.id == PortfolioMaterial.portfolio_item_id)
        .options(joinedload(PortfolioMaterial.document))
        .filter(PortfolioMaterial.id == material_id, PortfolioMaterial.deleted_at.is_(None), PortfolioItem.deleted_at.is_(None))
        .one_or_none()
    )
    if not material:
        raise HTTPException(status_code=404, detail="Portfolio material not found")
    return material


def next_portfolio_version_number(db: Session, portfolio_item_id: str) -> int:
    current = (
        db.query(func.max(PortfolioVersion.version_number))
        .filter(PortfolioVersion.portfolio_item_id == portfolio_item_id)
        .scalar()
    )
    return int(current or 0) + 1


def portfolio_upload_batch_label(item: PortfolioItem, role: str) -> str:
    return f"Portfolio: {item.title} ({role})"[:240]


def create_portfolio_processing_document(
    db: Session,
    *,
    item: PortfolioItem,
    data: bytes,
    filename: str | None,
    content_type: str | None,
    document_kind: str,
    role: str,
) -> tuple[Any, Document, ImportJob, str]:
    try:
        prepared = prepare_import_source(data, filename, content_type)
    except ImportSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    preset_snapshot = import_processing_snapshot(db, None)
    batch = ImportBatch(
        label=portfolio_upload_batch_label(item, role),
        total_files=1,
        shared_defaults={
            "origin": "portfolio",
            "portfolio_item_id": item.id,
            "portfolio_role": role,
            "document_kind": document_kind,
            "priority": "normal",
            "read_status": "unread",
            "processing_preset_id": preset_snapshot["id"],
            "processing_preset_name": preset_snapshot["name"],
            "processing_preset_mode": preset_snapshot["mode"],
            "processing_preset_snapshot": preset_snapshot,
        },
    )
    db.add(batch)
    db.flush()

    document = Document(
        title=prepared.title,
        document_kind=document_kind,
        original_filename=prepared.stored_filename,
        content_type=prepared.stored_content_type,
        checksum_sha256=prepared.source_checksum_sha256,
        checksum_md5=prepared.stored_checksum_md5,
        page_count=prepared.stored_page_count or 0,
        processing_status="queued",
        priority="normal",
        read_status="unread",
    )
    db.add(document)
    db.flush()

    storage = get_storage_service()
    stored_key = import_storage_key(prepared.source_checksum_sha256, document.id, prepared.stored_filename)
    stored = storage.put_bytes(stored_key, prepared.stored_data, prepared.stored_content_type)
    source_storage_uri = stored.uri
    source_storage_status = stored.backend
    if prepared.source_kind != "pdf":
        source_key = portfolio_source_storage_key(prepared.source_checksum_sha256, document.id, prepared.source_filename)
        source_stored = storage.put_bytes(source_key, data, prepared.source_content_type)
        source_storage_uri = source_stored.uri
        source_storage_status = source_stored.backend

    cache_dir = document_cache_root()
    cache_path = import_cache_path(cache_dir, document.id)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(prepared.stored_data)

    document.gcs_uri = stored.uri
    document.storage_status = stored.backend
    document.metadata_evidence = {
        "file_size_bytes": len(prepared.stored_data),
        "local_cache_path": str(cache_path),
        "document_cache_path": str(cache_path),
        "source_import": prepared.metadata,
        "source_file": {
            "filename": prepared.source_filename,
            "content_type": prepared.source_content_type,
            "checksum_sha256": prepared.source_checksum_sha256,
            "checksum_md5": prepared.source_checksum_md5,
            "size_bytes": prepared.source_size_bytes,
            "storage_uri": source_storage_uri,
            "storage_status": source_storage_status,
        },
        "hashes": {
            "source_sha256": prepared.source_checksum_sha256,
            "source_md5": prepared.source_checksum_md5,
            "stored_sha256": prepared.stored_checksum_sha256,
            "stored_md5": prepared.stored_checksum_md5,
        },
        "portfolio": {
            "item_id": item.id,
            "role": role,
            "document_kind": document_kind,
        },
        "import_defaults": batch.shared_defaults,
        "import_processing_preset": preset_snapshot,
    }
    register_document_cache(document, cache_path, source="portfolio")

    job = ImportJob(batch_id=batch.id, document_id=document.id, status="queued", current_step="stored")
    db.add(job)
    db.flush()
    model_preferences = get_analysis_models(db)
    estimate_rates = import_cost_exemplar_rates(db)
    cost_estimate = estimate_import_job_cost(job, model_preferences=model_preferences, rates=estimate_rates, db=db)
    estimated_cost_usd = float(cost_estimate.get("estimated_cost_usd") or 0.0)
    estimate_page_count = cost_estimate.get("estimated_page_count")
    if not isinstance(estimate_page_count, int):
        estimate_page_count = document_estimated_page_count(document)
    upload_estimate = {
        "estimated_cost_usd": estimated_cost_usd,
        "estimated_page_count": estimate_page_count,
        "basis": cost_estimate.get("basis") or "none",
        "uncalibrated_cost_usd": cost_estimate.get("uncalibrated_cost_usd"),
        "minimum_cloud_call_cost_usd": cost_estimate.get("minimum_cloud_call_cost_usd"),
        "step_estimates": cost_estimate.get("steps", []),
        "calibration_factor": estimate_rates.get("estimate_calibration_factor"),
        "calibration_sample_count": estimate_rates.get("estimate_calibration_sample_count"),
        "model_preferences": model_preferences,
        "processing_preset": {
            "id": preset_snapshot["id"],
            "name": preset_snapshot["name"],
            "mode": preset_snapshot["mode"],
        },
        "estimated_at": utc_now().isoformat(),
    }
    document.metadata_evidence = {**(document.metadata_evidence or {}), "upload_cost_estimate": upload_estimate}
    record_import_cost_estimate(
        db,
        document=document,
        job=job,
        estimated_cost_usd=estimated_cost_usd,
        estimate_basis=str(upload_estimate["basis"]),
        estimated_page_count=estimate_page_count,
        model_preferences=model_preferences,
        metadata={
            "origin": "portfolio",
            "portfolio_item_id": item.id,
            "portfolio_role": role,
            "processing_preset": upload_estimate["processing_preset"],
            "step_estimates": upload_estimate["step_estimates"],
            "calibration_factor": upload_estimate["calibration_factor"],
            "calibration_sample_count": upload_estimate["calibration_sample_count"],
        },
    )
    log_event(
        db,
        job=job,
        document=document,
        event_type="portfolio_upload_queued",
        message="Portfolio upload was queued for processing.",
        payload={"portfolio_item_id": item.id, "role": role, "source_kind": prepared.source_kind},
    )
    refresh_import_batch_progress(db, batch)
    return prepared, document, job, source_storage_uri


def portfolio_document_response(
    document: Document,
    *,
    filename: str,
    content_type: str,
    download: bool,
    uri: str | None = None,
) -> FastAPIResponse:
    storage_uri = uri or document.gcs_uri
    if not storage_uri:
        raise HTTPException(status_code=404, detail="Portfolio file is unavailable")
    try:
        data = get_storage_service().get_bytes(storage_uri)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Portfolio file is unavailable") from exc
    return FastAPIResponse(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": content_disposition_header("attachment" if download else "inline", filename.replace('"', ""))},
    )


def portfolio_suggestion_terms(document: Document) -> list[str]:
    text = " ".join(part for part in [document.title, document.abstract, document.rich_summary, document.search_text] if part)
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{3,}", text.lower())
    terms: list[str] = []
    seen: set[str] = set()
    for word in words:
        clean = word.strip("-")
        if clean in seen or clean in PORTFOLIO_SUGGESTION_STOPWORDS:
            continue
        seen.add(clean)
        terms.append(clean)
        if len(terms) >= 16:
            break
    return terms


def portfolio_overlap_score(terms: list[str], document: Document) -> float:
    if not terms:
        return 0.0
    haystack = f"{document.title} {document.abstract or ''} {document.rich_summary or ''} {document.search_text or ''}".lower()
    matched = sum(1 for term in terms if term in haystack)
    return round(matched / max(1, len(terms)), 3)


@app.get("/api/portfolio", response_model=list[PortfolioItemOut])
def list_portfolio_items(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[PortfolioItem]:
    items = portfolio_item_query(db).order_by(PortfolioItem.updated_at.desc(), PortfolioItem.title).all()
    for item in items:
        sync_portfolio_processing_status(item)
    return items


@app.post("/api/portfolio", response_model=PortfolioItemOut)
def create_portfolio_item(
    payload: PortfolioItemCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PortfolioItem:
    title = " ".join(payload.title.strip().split())
    if not title:
        raise HTTPException(status_code=400, detail="Portfolio title is required")
    item = PortfolioItem(
        title=title,
        description=payload.description,
        project_ids=payload.project_ids,
        domain_ids=payload.domain_ids,
        tag_ids=payload.tag_ids,
    )
    db.add(item)
    db.commit()
    return portfolio_item_or_404(db, item.id)


@app.get("/api/portfolio/{portfolio_item_id}", response_model=PortfolioItemOut)
def get_portfolio_item(
    portfolio_item_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PortfolioItem:
    return portfolio_item_or_404(db, portfolio_item_id)


@app.patch("/api/portfolio/{portfolio_item_id}", response_model=PortfolioItemOut)
def update_portfolio_item(
    portfolio_item_id: str,
    payload: PortfolioItemPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PortfolioItem:
    item = portfolio_item_or_404(db, portfolio_item_id)
    if payload.title is not None:
        title = " ".join(payload.title.strip().split())
        if not title:
            raise HTTPException(status_code=400, detail="Portfolio title is required")
        item.title = title
    if payload.description is not None:
        item.description = payload.description
    if payload.status is not None:
        item.status = " ".join(payload.status.strip().split())[:40] or "active"
    if payload.current_version_id is not None:
        version = (
            db.query(PortfolioVersion)
            .filter(PortfolioVersion.id == payload.current_version_id, PortfolioVersion.portfolio_item_id == item.id)
            .one_or_none()
        )
        if not version:
            raise HTTPException(status_code=400, detail="Current version must belong to this Portfolio item")
        item.current_version_id = version.id
    if payload.project_ids is not None:
        item.project_ids = payload.project_ids
    if payload.domain_ids is not None:
        item.domain_ids = payload.domain_ids
    if payload.tag_ids is not None:
        item.tag_ids = payload.tag_ids
    db.commit()
    return portfolio_item_or_404(db, portfolio_item_id)


@app.post("/api/portfolio/{portfolio_item_id}/versions", response_model=PortfolioItemOut)
async def upload_portfolio_version(
    portfolio_item_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    label: Annotated[str | None, Form()] = None,
    upload_note: Annotated[str | None, Form()] = None,
    parent_version_id: Annotated[str | None, Form()] = None,
) -> PortfolioItem:
    item = portfolio_item_or_404(db, portfolio_item_id)
    parent = None
    parent_version_id = parent_version_id or item.current_version_id
    if parent_version_id:
        parent = (
            db.query(PortfolioVersion)
            .filter(PortfolioVersion.id == parent_version_id, PortfolioVersion.portfolio_item_id == item.id)
            .one_or_none()
        )
        if not parent:
            raise HTTPException(status_code=400, detail="Parent version must belong to this Portfolio item")
    data = await file.read()
    prepared, document, job, source_storage_uri = create_portfolio_processing_document(
        db,
        item=item,
        data=data,
        filename=file.filename,
        content_type=file.content_type,
        document_kind=PORTFOLIO_VERSION_DOCUMENT_KIND,
        role="version",
    )
    version = PortfolioVersion(
        portfolio_item_id=item.id,
        document_id=document.id,
        version_number=next_portfolio_version_number(db, item.id),
        label=" ".join(label.strip().split()) if label else None,
        upload_note=upload_note,
        source_filename=prepared.source_filename,
        source_content_type=prepared.source_content_type,
        source_checksum_sha256=prepared.source_checksum_sha256,
        source_checksum_md5=prepared.source_checksum_md5,
        source_storage_uri=source_storage_uri,
        source_size_bytes=prepared.source_size_bytes,
        processing_status=document.processing_status,
        version_metadata={
            "source_import": prepared.metadata,
            "import_job_id": job.id,
            "import_batch_id": job.batch_id,
        },
    )
    db.add(version)
    db.flush()
    if parent:
        db.add(
            PortfolioVersionEdge(
                parent_version_id=parent.id,
                child_version_id=version.id,
                relation_type="supersedes",
                edge_metadata={"created_by": "portfolio_upload"},
            )
        )
    item.current_version_id = version.id
    db.commit()
    return portfolio_item_or_404(db, portfolio_item_id)


@app.post("/api/portfolio/{portfolio_item_id}/materials", response_model=PortfolioItemOut)
async def upload_portfolio_material(
    portfolio_item_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    role: Annotated[str, Form()] = "reference",
    label: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    version_id: Annotated[str | None, Form()] = None,
    required_for_assessment: Annotated[bool, Form()] = False,
) -> PortfolioItem:
    item = portfolio_item_or_404(db, portfolio_item_id)
    version = None
    if version_id:
        version = (
            db.query(PortfolioVersion)
            .filter(PortfolioVersion.id == version_id, PortfolioVersion.portfolio_item_id == item.id)
            .one_or_none()
        )
        if not version:
            raise HTTPException(status_code=400, detail="Material version scope must belong to this Portfolio item")
    clean_role = re.sub(r"[^a-z0-9_-]+", "_", role.strip().lower()).strip("_")[:80] or "reference"
    data = await file.read()
    prepared, document, job, source_storage_uri = create_portfolio_processing_document(
        db,
        item=item,
        data=data,
        filename=file.filename,
        content_type=file.content_type,
        document_kind=PORTFOLIO_MATERIAL_DOCUMENT_KIND,
        role=f"material:{clean_role}",
    )
    material = PortfolioMaterial(
        portfolio_item_id=item.id,
        version_id=version.id if version else None,
        document_id=document.id,
        role=clean_role,
        label=(" ".join(label.strip().split()) if label else None) or Path(prepared.source_filename).stem[:240],
        required_for_assessment=required_for_assessment,
        notes=notes,
        material_metadata={
            "source_import": prepared.metadata,
            "source_filename": prepared.source_filename,
            "source_content_type": prepared.source_content_type,
            "source_checksum_sha256": prepared.source_checksum_sha256,
            "source_storage_uri": source_storage_uri,
            "source_size_bytes": prepared.source_size_bytes,
            "import_job_id": job.id,
            "import_batch_id": job.batch_id,
        },
    )
    db.add(material)
    db.commit()
    return portfolio_item_or_404(db, portfolio_item_id)


@app.get("/api/portfolio/versions/{version_id}/preview")
def portfolio_version_preview(
    version_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    download: Annotated[bool, Query()] = False,
) -> FastAPIResponse:
    version = portfolio_version_or_404(db, version_id)
    return portfolio_document_response(
        version.document,
        filename=version.document.original_filename,
        content_type=version.document.content_type or "application/pdf",
        download=download,
    )


@app.get("/api/portfolio/versions/{version_id}/source")
def portfolio_version_source(
    version_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    download: Annotated[bool, Query()] = True,
) -> FastAPIResponse:
    version = portfolio_version_or_404(db, version_id)
    return portfolio_document_response(
        version.document,
        filename=version.source_filename,
        content_type=version.source_content_type or "application/octet-stream",
        download=download,
        uri=version.source_storage_uri,
    )


@app.get("/api/portfolio/materials/{material_id}/preview")
def portfolio_material_preview(
    material_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    download: Annotated[bool, Query()] = False,
) -> FastAPIResponse:
    material = portfolio_material_or_404(db, material_id)
    return portfolio_document_response(
        material.document,
        filename=material.document.original_filename,
        content_type=material.document.content_type or "application/pdf",
        download=download,
    )


@app.get("/api/portfolio/materials/{material_id}/source")
def portfolio_material_source(
    material_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    download: Annotated[bool, Query()] = True,
) -> FastAPIResponse:
    material = portfolio_material_or_404(db, material_id)
    metadata = material.material_metadata or {}
    source_uri = metadata.get("source_storage_uri") if isinstance(metadata.get("source_storage_uri"), str) else None
    filename = str(metadata.get("source_filename") or material.document.original_filename)
    content_type = str(metadata.get("source_content_type") or material.document.content_type or "application/octet-stream")
    return portfolio_document_response(material.document, filename=filename, content_type=content_type, download=download, uri=source_uri)


@app.post("/api/portfolio/{portfolio_item_id}/suggestions/refresh", response_model=PortfolioSuggestionRefreshOut)
def refresh_portfolio_suggestions(
    portfolio_item_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PortfolioSuggestionRefreshOut:
    item = portfolio_item_or_404(db, portfolio_item_id)
    version = item.current_version
    if not version or not version.document:
        raise HTTPException(status_code=409, detail="Upload a Portfolio version before refreshing resources")
    document = version.document
    recon_question = (
        f"Find authoritative Library sources that can support or enrich this Portfolio paper: {document.title}.\n\n"
        f"{document_recon_text(document, max_chars=20_000)}"
    )
    recon_candidates, _ = retrieve_recon_evidence(
        db,
        question=recon_question,
        scope_type="library",
        scope={},
        mode="source_finder",
        exclude_document_ids={document.id},
    )
    seen_document_ids: set[str] = set()
    candidates = []
    for evidence in recon_candidates:
        if evidence.document.id in seen_document_ids:
            continue
        seen_document_ids.add(evidence.document.id)
        candidates.append(evidence)
        if len(candidates) >= 8:
            break

    db.query(PortfolioSuggestion).filter(
        PortfolioSuggestion.portfolio_item_id == item.id,
        PortfolioSuggestion.version_id == version.id,
        PortfolioSuggestion.source_type == "library",
    ).delete(synchronize_session=False)
    suggestions: list[PortfolioSuggestion] = []
    for index, evidence in enumerate(candidates, start=1):
        document_candidate = evidence.document
        suggestion = PortfolioSuggestion(
            portfolio_item_id=item.id,
            version_id=version.id,
            library_document_id=document_candidate.id,
            source_type="library",
            title=document_candidate.title,
            relation_family="closest",
            score=evidence.score,
            status="candidate",
            evidence={
                "basis": "recon_retrieval",
                "label": f"R{index}",
                "snippet": evidence.snippet,
                "page_start": evidence.page_start,
                "page_end": evidence.page_end,
                "evidence_kind": evidence.evidence_kind,
                "score_basis": (evidence.metadata or {}).get("score_basis"),
                "source_document_processing_status": document.processing_status,
            },
        )
        db.add(suggestion)
        suggestions.append(suggestion)
    db.commit()
    rows = (
        db.query(PortfolioSuggestion)
        .options(joinedload(PortfolioSuggestion.library_document))
        .filter(
            PortfolioSuggestion.portfolio_item_id == item.id,
            PortfolioSuggestion.version_id == version.id,
            PortfolioSuggestion.source_type == "library",
        )
        .order_by(PortfolioSuggestion.score.desc().nullslast(), PortfolioSuggestion.created_at.desc())
        .all()
    )
    return PortfolioSuggestionRefreshOut(
        portfolio_item_id=item.id,
        suggestion_count=len(rows),
        suggestions=[PortfolioSuggestionOut.model_validate(row) for row in rows],
    )


@app.post("/api/portfolio/{portfolio_item_id}/assessments", response_model=PortfolioAssessmentRunOut)
def create_portfolio_assessment(
    portfolio_item_id: str,
    payload: PortfolioAssessmentCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PortfolioAssessmentRun:
    item = portfolio_item_or_404(db, portfolio_item_id)
    version = None
    if payload.version_id:
        version = (
            db.query(PortfolioVersion)
            .options(joinedload(PortfolioVersion.document))
            .filter(PortfolioVersion.id == payload.version_id, PortfolioVersion.portfolio_item_id == item.id)
            .one_or_none()
        )
        if not version:
            raise HTTPException(status_code=400, detail="Assessment version must belong to this Portfolio item")
    else:
        version = item.current_version
    if not version or not version.document:
        raise HTTPException(status_code=409, detail="Upload a Portfolio version before running assessment")

    model_ids = [model for model in (payload.model_ids or []) if model.strip()]
    if not model_ids:
        model_ids = [get_analysis_model(db, MODEL_PORTFOLIO_ASSESSMENT)]
    run = PortfolioAssessmentRun(
        portfolio_item_id=item.id,
        version_id=version.id,
        mode=payload.mode or "quality_review",
        model_ids=model_ids,
        status="complete",
        completed_at=utc_now(),
    )
    db.add(run)
    db.flush()

    materials = [material for material in item.materials if not material.deleted_at and (material.version_id in (None, version.id))]
    material_roles = {material.role.lower() for material in materials}
    findings: list[PortfolioAssessmentFinding] = []

    def add_finding(category: str, severity: str, title: str, body: str, evidence: dict[str, Any] | None = None) -> None:
        finding = PortfolioAssessmentFinding(
            assessment_run_id=run.id,
            category=category,
            severity=severity,
            title=title,
            body=body,
            evidence=evidence or {},
        )
        db.add(finding)
        findings.append(finding)

    document = version.document
    if document.processing_status != "ready":
        add_finding(
            "processing",
            "warning",
            "Version is still processing",
            "Assessment can run a baseline pass now, but quality and completeness checks improve after extraction, summary, and search indexing finish.",
            {"processing_status": document.processing_status},
        )
    if not materials:
        add_finding(
            "materials",
            "warning",
            "No supporting materials attached",
            "Attach a rubric, assignment prompt, reference, or feedback document before relying on model-based quality assessment.",
        )
    if not ({"rubric", "assignment", "prompt"} & material_roles):
        add_finding(
            "rubric",
            "info",
            "No rubric or assignment prompt found",
            "Assessments can compare against references, but a rubric or prompt gives the models a sharper target for focus, quality, and completeness.",
            {"material_roles": sorted(material_roles)},
        )
    if not item.suggestions:
        add_finding(
            "resources",
            "info",
            "Resource suggestions have not been refreshed",
            "Run Find Resources to compare this version with Library material and collect additional context before a deep assessment.",
        )
    recon_question = (
        f"Find Library evidence that can support, challenge, or enrich this Portfolio version: {item.title}.\n\n"
        f"{document_recon_text(document, max_chars=18_000)}"
    )
    recon_evidence, _ = retrieve_recon_evidence(db, question=recon_question, scope_type="library", scope={}, mode="source_finder")
    library_evidence_items = [
        {
            "label": f"L{index}",
            "document_id": evidence.document.id,
            "title": evidence.document.title,
            "citation": evidence.document.apa_citation or evidence.document.title,
            "page_start": evidence.page_start,
            "page_end": evidence.page_end,
            "snippet": evidence.snippet,
            "score": evidence.score,
        }
        for index, evidence in enumerate(recon_evidence[:8], start=1)
    ]
    if library_evidence_items:
        add_finding(
            "resources",
            "info",
            "Library support evidence found",
            "Recon found Library sources that can support or contextualize this Portfolio version. Review Find Resources for the ranked source list.",
            {"library_evidence": library_evidence_items[:5]},
        )
    text_for_count = document.search_text or document.abstract or document.rich_summary or document.title
    word_count = len(re.findall(r"\b[\w'-]+\b", text_for_count or ""))
    if document.processing_status == "ready" and word_count < 250:
        add_finding(
            "completeness",
            "warning",
            "Extracted text is short",
            "The current extracted text is short enough that completeness and focus checks may be underpowered.",
            {"word_count": word_count},
        )
    if not findings:
        add_finding(
            "baseline",
            "info",
            "Ready for model comparison",
            "The version has extracted text and at least one supporting material. Run a multi-model assessment when deeper scoring prompts are enabled.",
            {"word_count": word_count},
        )
    model_assessment_result: dict[str, Any] | None = None
    material_items = [
        {
            "label": f"M{index}",
            "role": material.role,
            "title": material.label or (material.document.title if material.document else None),
            "required_for_assessment": material.required_for_assessment,
            "notes": material.notes,
            "text": document_recon_text(material.document, max_chars=12_000) if material.document else "",
        }
        for index, material in enumerate(materials[:8], start=1)
    ]
    try:
        model_assessment_result = get_ai_service().generate_portfolio_assessment(
            item.title,
            document_recon_text(document, max_chars=60_000),
            material_items,
            library_evidence_items,
            model=model_ids[0],
            usage_context=OpenAIUsageContext(document_id=document.id, source="portfolio", capability_key=MODEL_PORTFOLIO_ASSESSMENT),
        )
        for finding_payload in model_assessment_result.get("findings") or []:
            raw_severity = str(finding_payload.get("severity") or "info").lower()
            severity = raw_severity if raw_severity in {"info", "warning", "critical"} else "info"
            add_finding(
                str(finding_payload.get("category") or "model_review")[:80],
                severity,
                str(finding_payload.get("title") or "Model assessment finding")[:300],
                str(finding_payload.get("body") or ""),
                {
                    "source": "model",
                    "model": model_ids[0],
                    "evidence_labels": finding_payload.get("evidence_labels") or [],
                },
            )
    except Exception as exc:
        model_assessment_result = {"fallback_reason": str(exc)}

    run.summary = (
        str(model_assessment_result.get("summary"))
        if model_assessment_result and model_assessment_result.get("summary")
        else f"Portfolio assessment completed with {len(findings)} finding{'s' if len(findings) != 1 else ''}."
    )
    run.assessment_metadata = {
        "local_baseline": True,
        "model_ids": model_ids,
        "material_snapshot": [
            {
                "id": material.id,
                "role": material.role,
                "label": material.label,
                "version_id": material.version_id,
                "required_for_assessment": material.required_for_assessment,
            }
            for material in materials
        ],
        "suggestion_count": len(item.suggestions),
        "library_evidence_count": len(library_evidence_items),
        "library_evidence": library_evidence_items,
        "model_assessment": model_assessment_result or {},
        "word_count": word_count,
    }
    db.commit()
    return (
        db.query(PortfolioAssessmentRun)
        .options(selectinload(PortfolioAssessmentRun.findings))
        .filter(PortfolioAssessmentRun.id == run.id)
        .one()
    )


def sync_doi_stash_import_status(stash: DoiStash) -> bool:
    if not stash.import_job:
        return False
    previous_status = stash.status
    if stash.import_job.status == "complete":
        stash.status = "imported"
        stash.imported_document_id = stash.imported_document_id or stash.import_job.document_id
        stash.imported_at = stash.imported_at or stash.import_job.updated_at or utc_now()
    elif stash.import_job.status == "failed":
        stash.status = "import_failed"
    elif stash.import_job.status in {"queued", "running", "restored_paused"}:
        stash.status = "import_queued"
    return stash.status != previous_status


DOI_STASH_TITLE_MATCH_THRESHOLD = 0.94
DOI_STASH_BIBLIOGRAPHIC_METADATA_KEY = "bibliographic"
DOI_STASH_BIBLIOGRAPHIC_LOOKUP_KEY = "bibliographic_lookup"
DOI_STASH_LIST_LOOKUP_LIMIT = 3


def _clean_stash_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def _clean_stash_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _clean_stash_authors(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    authors: list[dict[str, Any]] = []
    for author in value:
        if not isinstance(author, dict):
            continue
        cleaned = {
            "given": _clean_stash_text(author.get("given")) or "",
            "family": _clean_stash_text(author.get("family")) or "",
            "affiliation": _clean_stash_text(author.get("affiliation")),
            "email": _clean_stash_text(author.get("email")),
        }
        if cleaned["given"] or cleaned["family"]:
            authors.append(cleaned)
    return authors


def _doi_stash_title_is_placeholder(title: str | None, doi: str | None) -> bool:
    normalized_doi = normalize_doi(doi)
    if not title or not normalized_doi:
        return not bool(title)
    return normalized_title_similarity(title, normalized_doi) >= 0.98


def _doi_stash_bibliographic_metadata(stash: DoiStash) -> dict[str, Any]:
    metadata = stash.stash_metadata if isinstance(stash.stash_metadata, dict) else {}
    bibliographic = metadata.get(DOI_STASH_BIBLIOGRAPHIC_METADATA_KEY)
    return bibliographic if isinstance(bibliographic, dict) else {}


def _doi_stash_recommendation_snapshot(recommendation: DocumentRecommendation | None) -> dict[str, Any]:
    if not recommendation:
        return {}
    return {
        "title": _clean_stash_text(recommendation.title),
        "authors": _clean_stash_authors(recommendation.authors),
        "publication_year": recommendation.publication_year,
        "journal": _clean_stash_text(recommendation.journal),
        "description": _clean_stash_text(recommendation.description),
        "source_url": _clean_stash_text(recommendation.source_url),
        "provider": _clean_stash_text(recommendation.source_provider),
        "source": "recommendation",
        "captured_at": utc_now().isoformat(),
    }


def _doi_stash_candidate_snapshot(candidate: Any | None) -> dict[str, Any]:
    if not candidate:
        return {}
    return {
        "title": _clean_stash_text(getattr(candidate, "title", None)),
        "authors": _clean_stash_authors(getattr(candidate, "authors", None)),
        "publication_year": _clean_stash_int(getattr(candidate, "publication_year", None)),
        "journal": _clean_stash_text(getattr(candidate, "journal", None)),
        "description": _clean_stash_text(getattr(candidate, "description", None)),
        "source_url": _clean_stash_text(getattr(candidate, "source_url", None)),
        "pdf_url": _clean_stash_text(getattr(candidate, "pdf_url", None)),
        "provider": _clean_stash_text(getattr(candidate, "provider", None)),
        "relation": _clean_stash_text(getattr(candidate, "relation", None)),
        "source": "public_doi_metadata",
        "captured_at": utc_now().isoformat(),
    }


def _apply_doi_stash_bibliographic_snapshot(stash: DoiStash, snapshot: dict[str, Any]) -> bool:
    cleaned = {
        "title": _clean_stash_text(snapshot.get("title")),
        "authors": _clean_stash_authors(snapshot.get("authors")),
        "publication_year": _clean_stash_int(snapshot.get("publication_year")),
        "journal": _clean_stash_text(snapshot.get("journal")),
        "description": _clean_stash_text(snapshot.get("description")),
        "page_count": _clean_stash_int(snapshot.get("page_count")),
        "source_url": _clean_stash_text(snapshot.get("source_url")),
        "pdf_url": _clean_stash_text(snapshot.get("pdf_url")),
        "provider": _clean_stash_text(snapshot.get("provider")),
        "relation": _clean_stash_text(snapshot.get("relation")),
        "source": _clean_stash_text(snapshot.get("source")),
        "captured_at": _clean_stash_text(snapshot.get("captured_at")) or utc_now().isoformat(),
    }
    compact = {key: value for key, value in cleaned.items() if value not in (None, "", [])}
    if not compact:
        return False

    metadata = dict(stash.stash_metadata or {})
    previous = metadata.get(DOI_STASH_BIBLIOGRAPHIC_METADATA_KEY)
    merged = dict(previous) if isinstance(previous, dict) else {}
    changed = False
    for key, value in compact.items():
        if key not in merged or merged.get(key) in (None, "", []):
            merged[key] = value
            changed = True
    if changed:
        metadata[DOI_STASH_BIBLIOGRAPHIC_METADATA_KEY] = merged
        stash.stash_metadata = metadata
    if merged.get("title") and _doi_stash_title_is_placeholder(stash.title, stash.doi):
        stash.title = str(merged["title"])[:800]
        changed = True
    if merged.get("source_url") and not stash.source_url:
        stash.source_url = str(merged["source_url"])
        changed = True
    if merged.get("provider") and not stash.source_provider:
        stash.source_provider = str(merged["provider"])[:160]
        changed = True
    return changed


def enrich_doi_stash_from_public_metadata(stash: DoiStash) -> bool:
    metadata = dict(stash.stash_metadata or {})
    lookup = metadata.get(DOI_STASH_BIBLIOGRAPHIC_LOOKUP_KEY)
    if isinstance(lookup, dict) and lookup.get("status") in {"complete", "unavailable", "failed"}:
        return False
    try:
        candidate = resolve_doi_metadata_candidate(
            stash.doi,
            title=stash.title,
            source_url=stash.source_url,
            source_provider=stash.source_provider,
        )
    except Exception as exc:
        metadata[DOI_STASH_BIBLIOGRAPHIC_LOOKUP_KEY] = {
            "status": "failed",
            "message": str(exc),
            "attempted_at": utc_now().isoformat(),
        }
        stash.stash_metadata = metadata
        return True

    snapshot = _doi_stash_candidate_snapshot(candidate)
    has_identity_metadata = bool(
        (snapshot.get("title") and not _doi_stash_title_is_placeholder(str(snapshot.get("title")), stash.doi))
        or snapshot.get("authors")
        or snapshot.get("publication_year")
        or snapshot.get("journal")
        or snapshot.get("description")
    )
    if has_identity_metadata:
        _apply_doi_stash_bibliographic_snapshot(stash, snapshot)
    metadata = dict(stash.stash_metadata or {})
    metadata[DOI_STASH_BIBLIOGRAPHIC_LOOKUP_KEY] = {
        "status": "complete" if has_identity_metadata else "unavailable",
        "provider": snapshot.get("provider"),
        "attempted_at": utc_now().isoformat(),
    }
    stash.stash_metadata = metadata
    return True


def doi_stash_needs_public_metadata_lookup(stash: DoiStash) -> bool:
    if stash.imported_document or stash.recommendation:
        return False
    if _doi_stash_bibliographic_metadata(stash):
        return False
    metadata = stash.stash_metadata if isinstance(stash.stash_metadata, dict) else {}
    lookup = metadata.get(DOI_STASH_BIBLIOGRAPHIC_LOOKUP_KEY)
    return not (isinstance(lookup, dict) and lookup.get("status") in {"complete", "unavailable", "failed"})


def doi_stash_document_info(stash: DoiStash) -> dict[str, Any]:
    bibliographic = _doi_stash_bibliographic_metadata(stash)
    recommendation = stash.recommendation
    imported_document = stash.imported_document
    title = stash.title
    authors: list[dict[str, Any]] = []
    publication_year: int | None = None
    journal: str | None = None
    description: str | None = None
    page_count: int | None = None
    metadata_source: str | None = None

    if imported_document:
        title = imported_document.title or title
        authors = _clean_stash_authors(imported_document.authors)
        publication_year = imported_document.publication_year
        journal = _clean_stash_text(imported_document.journal)
        description = _clean_stash_text(imported_document.abstract or imported_document.rich_summary)
        page_count = imported_document.page_count if imported_document.page_count > 0 else None
        metadata_source = "library"
    if recommendation and not imported_document:
        if _doi_stash_title_is_placeholder(title, stash.doi):
            title = recommendation.title or title
        authors = authors or _clean_stash_authors(recommendation.authors)
        publication_year = publication_year or recommendation.publication_year
        journal = journal or _clean_stash_text(recommendation.journal)
        description = description or _clean_stash_text(recommendation.description)
        metadata_source = metadata_source or _clean_stash_text(recommendation.source_provider) or "recommendation"

    title = title if not _doi_stash_title_is_placeholder(title, stash.doi) else _clean_stash_text(bibliographic.get("title")) or title
    authors = authors or _clean_stash_authors(bibliographic.get("authors"))
    publication_year = publication_year or _clean_stash_int(bibliographic.get("publication_year"))
    journal = journal or _clean_stash_text(bibliographic.get("journal"))
    description = description or _clean_stash_text(bibliographic.get("description"))
    page_count = page_count or _clean_stash_int(bibliographic.get("page_count"))
    metadata_source = metadata_source or _clean_stash_text(bibliographic.get("provider")) or _clean_stash_text(stash.source_provider)

    return {
        "title": title,
        "authors": authors,
        "publication_year": publication_year,
        "journal": journal,
        "description": description,
        "page_count": page_count,
        "metadata_source": metadata_source,
        "source_url": stash.source_url
        or _clean_stash_text(bibliographic.get("source_url"))
        or (recommendation.source_url if recommendation else None),
        "source_provider": stash.source_provider or _clean_stash_text(bibliographic.get("provider")),
    }


def _doi_stash_match_basis(stash: DoiStash, document: Document | None) -> str | None:
    if not document:
        return None
    reasons: list[str] = []
    stash_doi = normalize_doi(stash.doi)
    document_doi = normalize_doi(document.doi)
    if stash_doi and document_doi and stash_doi == document_doi:
        reasons.append("doi")
    if stash.title and normalized_title_similarity(stash.title, document.title) >= DOI_STASH_TITLE_MATCH_THRESHOLD:
        reasons.append("title")
    if "doi" in reasons and "title" in reasons:
        return "doi_title"
    return reasons[0] if reasons else None


def _doi_stash_metadata_match_basis(stash: DoiStash) -> str | None:
    metadata = stash.stash_metadata or {}
    matched_import = metadata.get("matched_import") if isinstance(metadata, dict) else None
    if not isinstance(matched_import, dict):
        return None
    reasons = matched_import.get("match_reasons")
    if not isinstance(reasons, list):
        source = matched_import.get("source")
        if source == "library_doi_title_match":
            return "doi_title"
        if source == "library_title_match":
            return "title"
        if source == "library_doi_match":
            return "doi"
        return None
    normalized_reasons = {str(reason) for reason in reasons}
    if {"doi", "title"}.issubset(normalized_reasons):
        return "doi_title"
    if "doi" in normalized_reasons:
        return "doi"
    if "title" in normalized_reasons:
        return "title"
    return None


def doi_stash_library_match_basis(stash: DoiStash) -> str | None:
    return _doi_stash_metadata_match_basis(stash) or _doi_stash_match_basis(stash, stash.imported_document)


def _best_doi_stash_title_match(documents: list[Document], stash: DoiStash) -> tuple[Document | None, float]:
    if not stash.title:
        return None, 0.0
    best: tuple[float, Document | None] = (0.0, None)
    for document in documents:
        score = normalized_title_similarity(document.title, stash.title)
        if score > best[0]:
            best = (score, document)
    return (best[1], best[0]) if best[0] >= DOI_STASH_TITLE_MATCH_THRESHOLD else (None, best[0])


def sync_doi_stash_library_matches(db: Session, stashes: list[DoiStash]) -> bool:
    matchable_by_doi: dict[str, DoiStash] = {}
    matchable_by_title: list[DoiStash] = []
    for stash in stashes:
        if stash.status == "import_queued":
            continue
        normalized = normalize_doi(stash.doi)
        if stash.status == "imported" and stash.imported_document_id:
            continue
        if normalized:
            matchable_by_doi.setdefault(normalized, stash)
        if stash.title:
            matchable_by_title.append(stash)
    if not matchable_by_doi and not matchable_by_title:
        return False

    changed = False
    documents = (
        filter_library_visible_documents(db.query(Document))
        .order_by(Document.updated_at.desc(), Document.created_at.desc(), Document.id)
        .all()
    )
    documents_by_doi = {normalize_doi(document.doi): document for document in documents if normalize_doi(document.doi)}
    matched_stash_ids: set[str] = set()
    match_candidates: list[tuple[DoiStash, Document, str, float | None]] = []
    for doi, stash in matchable_by_doi.items():
        document = documents_by_doi.get(doi)
        if not document:
            continue
        basis = _doi_stash_match_basis(stash, document) or "doi"
        match_candidates.append((stash, document, basis, None))
        matched_stash_ids.add(stash.id)
    for stash in matchable_by_title:
        if stash.id in matched_stash_ids:
            continue
        document, score = _best_doi_stash_title_match(documents, stash)
        if not document:
            continue
        match_candidates.append((stash, document, "title", score))
        matched_stash_ids.add(stash.id)

    for stash, document, basis, title_score in match_candidates:
        stash.imported_document_id = document.id
        stash.status = "imported"
        stash.imported_at = stash.imported_at or document.updated_at or document.created_at or utc_now()
        match_reasons = ["doi", "title"] if basis == "doi_title" else [basis]
        metadata = dict(stash.stash_metadata or {})
        metadata["matched_import"] = {
            "document_id": document.id,
            "document_title": document.title,
            "doi": normalize_doi(document.doi),
            "match_reasons": match_reasons,
            "title_similarity": title_score,
            "matched_at": utc_now().isoformat(),
            "source": f"library_{basis}_match",
        }
        stash.stash_metadata = metadata
        changed = True
    return changed


def doi_stash_query(db: Session):
    return (
        db.query(DoiStash)
        .options(joinedload(DoiStash.imported_document), joinedload(DoiStash.import_job), joinedload(DoiStash.recommendation))
        .filter(DoiStash.deleted_at.is_(None))
    )


def doi_stash_out(stash: DoiStash) -> DoiStashOut:
    document_info = doi_stash_document_info(stash)
    return DoiStashOut(
        id=stash.id,
        doi=stash.doi,
        title=document_info["title"],
        authors=document_info["authors"],
        publication_year=document_info["publication_year"],
        journal=document_info["journal"],
        description=document_info["description"],
        page_count=document_info["page_count"],
        metadata_source=document_info["metadata_source"],
        source_url=document_info["source_url"],
        source_provider=document_info["source_provider"],
        source_document_id=stash.source_document_id,
        recommendation_id=stash.recommendation_id,
        imported_document_id=stash.imported_document_id,
        imported_document_title=stash.imported_document.title if stash.imported_document else None,
        library_match_basis=doi_stash_library_match_basis(stash),
        import_job_id=stash.import_job_id,
        import_job_status=stash.import_job.status if stash.import_job else None,
        status=stash.status,
        uploaded_filename=stash.uploaded_filename,
        imported_at=stash.imported_at,
        stash_metadata=stash.stash_metadata or {},
        created_at=stash.created_at,
        updated_at=stash.updated_at,
    )


@app.get("/api/doi-stashes", response_model=list[DoiStashOut])
def list_doi_stashes(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DoiStashOut]:
    stashes = doi_stash_query(db).order_by(DoiStash.created_at.desc()).all()
    changed = False
    lookup_budget = DOI_STASH_LIST_LOOKUP_LIMIT
    for stash in stashes:
        changed = sync_doi_stash_import_status(stash) or changed
        if lookup_budget > 0 and doi_stash_needs_public_metadata_lookup(stash):
            changed = enrich_doi_stash_from_public_metadata(stash) or changed
            lookup_budget -= 1
    changed = sync_doi_stash_library_matches(db, stashes) or changed
    if changed:
        db.commit()
    return [doi_stash_out(stash) for stash in stashes]


@app.post("/api/doi-stashes", response_model=DoiStashOut)
def create_doi_stash(
    payload: DoiStashCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DoiStashOut:
    doi = normalize_doi(payload.doi)
    if not doi:
        raise HTTPException(status_code=400, detail="A valid DOI is required")
    recommendation = db.get(DocumentRecommendation, payload.recommendation_id) if payload.recommendation_id else None
    if payload.recommendation_id and not recommendation:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    title = payload.title or (recommendation.title if recommendation else None)
    source_url = payload.source_url or (recommendation.source_url if recommendation else None) or doi_url(doi)
    source_provider = payload.source_provider or (recommendation.source_provider if recommendation else None)
    source_document_id = payload.source_document_id or (recommendation.source_document_id if recommendation else None)
    stash = db.query(DoiStash).filter(DoiStash.doi == doi).one_or_none()
    if stash:
        stash.deleted_at = None
        stash.title = title or stash.title
        stash.source_url = source_url or stash.source_url
        stash.source_provider = source_provider or stash.source_provider
        stash.source_document_id = source_document_id or stash.source_document_id
        stash.recommendation_id = (payload.recommendation_id if recommendation else None) or stash.recommendation_id
        if stash.status == "removed":
            stash.status = "active"
        if recommendation:
            _apply_doi_stash_bibliographic_snapshot(stash, _doi_stash_recommendation_snapshot(recommendation))
    else:
        stash = DoiStash(
            doi=doi,
            title=title,
            source_url=source_url,
            source_provider=source_provider,
            source_document_id=source_document_id,
            recommendation_id=payload.recommendation_id if recommendation else None,
            status="active",
            stash_metadata={"created_from": "recommendation" if payload.recommendation_id else "manual"},
        )
        db.add(stash)
        if recommendation:
            _apply_doi_stash_bibliographic_snapshot(stash, _doi_stash_recommendation_snapshot(recommendation))
    if not recommendation:
        enrich_doi_stash_from_public_metadata(stash)
    db.commit()
    db.refresh(stash)
    return doi_stash_out(stash)


@app.delete("/api/doi-stashes/{stash_id}")
def delete_doi_stash(
    stash_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    stash = db.get(DoiStash, stash_id)
    if not stash or stash.deleted_at:
        raise HTTPException(status_code=404, detail="DOI stash not found")
    stash.deleted_at = utc_now()
    stash.status = "removed"
    db.commit()
    return {"status": "ok"}


@app.post("/api/doi-stashes/{stash_id}/import", response_model=DoiStashImportOut)
def import_doi_stash_pdf(
    stash_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DoiStashImportOut:
    stash = doi_stash_query(db).filter(DoiStash.id == stash_id).one_or_none()
    if not stash:
        raise HTTPException(status_code=404, detail="DOI stash not found")
    sync_doi_stash_import_status(stash)
    if stash.status == "import_queued":
        raise HTTPException(status_code=409, detail="This DOI stash already has an import queued or running")
    result = queue_doi_stash_open_pdf_import(db, stash)
    db.commit()
    db.refresh(stash)
    return DoiStashImportOut(stash=doi_stash_out(stash), **result)


@app.post("/api/doi-stashes/{stash_id}/upload", response_model=DoiStashOut)
async def upload_doi_stash_pdf(
    stash_id: str,
    file: Annotated[UploadFile, File()],
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DoiStashOut:
    stash = doi_stash_query(db).filter(DoiStash.id == stash_id).one_or_none()
    if not stash:
        raise HTTPException(status_code=404, detail="DOI stash not found")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Upload a PDF file.")
    filename = file.filename or f"{stash.doi.replace('/', '_')}.pdf"
    looks_like_pdf = data.lstrip().startswith(b"%PDF") or (file.content_type == "application/pdf") or filename.lower().endswith(".pdf")
    if not looks_like_pdf:
        raise HTTPException(status_code=400, detail="Upload a PDF file.")

    checksum = hashlib.sha256(data).hexdigest()
    checksum_md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    title = stash.title or Path(filename).stem.replace("_", " ").replace("-", " ")
    duplicate_profile = import_duplicate_profile(
        title=title,
        original_filename=filename,
        source_checksum_sha256=checksum,
        stored_checksum_sha256=checksum,
        source_checksum_md5=checksum_md5,
        stored_checksum_md5=checksum_md5,
        doi=stash.doi,
    )
    batch = ImportBatch(
        label=f"Stash: {stash.doi}",
        total_files=1,
        shared_defaults={
            "source": "doi_stash",
            "doi_stash_id": stash.id,
            "doi": stash.doi,
        },
    )
    db.add(batch)
    db.flush()

    existing_matches = active_duplicate_matches_for_profile(db, duplicate_profile, statuses=IMPORT_DUPLICATE_DOCUMENT_STATUSES)
    if existing_matches:
        job = create_skipped_duplicate_job(
            db,
            batch=batch,
            document=existing_matches[0].document,
            filename=filename,
            checksum=checksum,
            reason=f"matched_existing_document:{existing_matches[0].match_basis}",
        )
        stash.imported_document_id = existing_matches[0].document.id
        stash.import_job_id = job.id
        stash.status = "imported"
        stash.uploaded_filename = filename
        stash.imported_at = utc_now()
        refresh_import_batch_progress(db, batch)
        db.commit()
        db.refresh(stash)
        return doi_stash_out(stash)

    document = Document(
        title=title,
        original_filename=filename,
        content_type=file.content_type or "application/pdf",
        checksum_sha256=checksum,
        checksum_md5=checksum_md5,
        doi=stash.doi,
        source_url=stash.source_url or doi_url(stash.doi),
        priority="normal",
        read_status="unread",
    )
    db.add(document)
    db.flush()

    storage = get_storage_service()
    cache_dir = document_cache_root()
    key = import_storage_key(checksum, document.id, filename)
    stored = storage.put_bytes(key, data, file.content_type or "application/pdf")
    cache_path = import_cache_path(cache_dir, document.id)
    cache_path.write_bytes(data)
    document.gcs_uri = stored.uri
    document.storage_status = stored.backend
    document.processing_status = "queued"
    document.metadata_evidence = {
        "file_size_bytes": len(data),
        "local_cache_path": str(cache_path),
        "document_cache_path": str(cache_path),
        "hashes": {"source_sha256": checksum, "source_md5": checksum_md5, "stored_sha256": checksum, "stored_md5": checksum_md5},
        "doi_stash": {
            "id": stash.id,
            "doi": stash.doi,
            "title": stash.title,
            "source_url": stash.source_url,
            "source_provider": stash.source_provider,
            "recommendation_id": stash.recommendation_id,
            "source_document_id": stash.source_document_id,
        },
    }
    register_document_cache(document, cache_path, source="doi_stash")

    job = ImportJob(batch_id=batch.id, document_id=document.id, status="queued", current_step="stored")
    db.add(job)
    db.flush()
    stash.imported_document_id = document.id
    stash.import_job_id = job.id
    stash.status = "import_queued"
    stash.uploaded_filename = filename
    refresh_import_batch_progress(db, batch)
    db.commit()
    db.refresh(stash)
    return doi_stash_out(stash)


@app.get("/api/documents/{document_id}/original")
def document_original(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    download: Annotated[bool, Query()] = False,
) -> FastAPIResponse:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    if not document.gcs_uri:
        raise HTTPException(status_code=404, detail="Original document is unavailable")
    try:
        data = get_storage_service().get_bytes(document.gcs_uri)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Original document is unavailable") from exc
    filename = (
        render_download_filename(document, get_download_naming_template(db))
        if download
        else document.original_filename.replace('"', "")
    )
    return FastAPIResponse(
        content=data,
        media_type=document.content_type or "application/pdf",
        headers={"Content-Disposition": content_disposition_header("attachment" if download else "inline", filename)},
    )


@app.get("/api/documents/{document_id}/pages/{page_number}/image")
def document_page_image(
    document_id: str,
    page_number: int,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FastAPIResponse:
    if page_number < 1:
        raise HTTPException(status_code=400, detail="Page number must be at least 1")
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    if document.page_count and page_number > document.page_count:
        raise HTTPException(status_code=404, detail="Page image not found")
    if not document.gcs_uri:
        raise HTTPException(status_code=404, detail="Original document is unavailable")
    try:
        import fitz

        data = ensure_document_pdf_bytes(db, document, source="page_preview")
        if data is None:
            raise HTTPException(status_code=404, detail="Original document is unavailable")
        db.commit()
        with fitz.open(stream=data, filetype="pdf") as pdf:
            if page_number > pdf.page_count:
                raise HTTPException(status_code=404, detail="Page image not found")
            page = pdf.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(PDF_PREVIEW_RENDER_SCALE, PDF_PREVIEW_RENDER_SCALE), alpha=False)
            png = pixmap.tobytes("png")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Could not render page image: {exc}") from exc
    return FastAPIResponse(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.get("/api/documents/{document_id}/annotations", response_model=list[AnnotationOut])
def list_annotations(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[Annotation]:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    return (
        db.query(Annotation)
        .filter(Annotation.document_id == document_id, Annotation.deleted_at.is_(None))
        .order_by(Annotation.page_number, Annotation.created_at.desc())
        .all()
    )


@app.post("/api/documents/{document_id}/annotations", response_model=AnnotationOut)
def create_annotation(
    document_id: str,
    payload: AnnotationCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Annotation:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    annotation = Annotation(**payload.model_dump())
    document.annotations.append(annotation)
    db.flush()
    document.search_text = rebuild_document_search_text(document)
    db.commit()
    db.refresh(annotation)
    return annotation


@app.patch("/api/annotations/{annotation_id}", response_model=AnnotationOut)
def patch_annotation(
    annotation_id: str,
    payload: AnnotationPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Annotation:
    annotation = db.get(Annotation, annotation_id)
    if not annotation or annotation.deleted_at:
        raise HTTPException(status_code=404, detail="Annotation not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(annotation, key, value)
    document = db.get(Document, annotation.document_id)
    if document_is_library_visible(document):
        document.search_text = rebuild_document_search_text(document)
    db.commit()
    db.refresh(annotation)
    return annotation


@app.delete("/api/annotations/{annotation_id}")
def delete_annotation(
    annotation_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    annotation = db.get(Annotation, annotation_id)
    if not annotation or annotation.deleted_at:
        raise HTTPException(status_code=404, detail="Annotation not found")
    annotation.deleted_at = utc_now()
    document = db.get(Document, annotation.document_id)
    if document_is_library_visible(document):
        document.search_text = rebuild_document_search_text(document)
    db.commit()
    return {"status": "deleted"}


def _clean_figure_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


@app.get("/api/figures/{figure_id}/asset")
def figure_asset(
    figure_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FastAPIResponse:
    figure = db.get(Figure, figure_id)
    if not figure or not figure.asset_uri:
        raise HTTPException(status_code=404, detail="Figure asset not found")
    try:
        data = get_storage_service().get_bytes(figure.asset_uri, timeout=5, retry=None)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Figure asset is unavailable") from exc
    content_type = mimetypes.guess_type(figure.asset_uri)[0] or "application/octet-stream"
    return FastAPIResponse(content=data, media_type=content_type)


@app.patch("/api/figures/{figure_id}", response_model=DocumentDetail)
def patch_figure(
    figure_id: str,
    payload: FigurePatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    figure = db.get(Figure, figure_id)
    document = db.get(Document, figure.document_id) if figure else None
    if not figure or not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Figure not found")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return document_detail_out(document, db)

    before = document_correction_snapshot(document)
    changed = False
    for field in ("figure_label", "caption", "gist"):
        if field not in updates:
            continue
        next_value = _clean_figure_text(updates[field])
        if getattr(figure, field) != next_value:
            setattr(figure, field, next_value)
            changed = True

    if not changed:
        return document_detail_out(document, db)

    document.search_text = rebuild_document_search_text(document)
    log_event(
        db,
        job=None,
        document=document,
        event_type="figure_update",
        message=f"Updated extracted figure {figure.figure_label or figure.id}.",
        payload={
            "figure_id": figure.id,
            "page_number": figure.page_number,
            "figure_label": figure.figure_label,
            "caption": figure.caption,
            "gist": figure.gist,
        },
    )
    db.flush()
    record_document_version(
        db,
        document=document,
        change_note=f"Updated extracted figure {figure.figure_label or figure.id}",
        changed_fields={"figures", "search_text"},
        before=before,
        after=document_correction_snapshot(document),
        extra={"figure_update": {"figure_id": figure.id}},
    )
    record_manual_edit(
        db,
        document=document,
        message=f"Updated extracted figure {figure.figure_label or figure.id}",
        metadata={"operation": "figure_update", "figure_id": figure.id, "page_number": figure.page_number},
    )
    db.commit()
    db.refresh(document)
    return document_detail_out(document, db)


@app.delete("/api/figures/{figure_id}", response_model=DocumentDetail)
def delete_figure(
    figure_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    figure = db.get(Figure, figure_id)
    document = db.get(Document, figure.document_id) if figure else None
    if not figure or not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Figure not found")

    before = document_correction_snapshot(document)
    deleted_figure = {
        "id": figure.id,
        "page_number": figure.page_number,
        "figure_label": figure.figure_label,
        "caption": figure.caption,
        "gist": figure.gist,
        "asset_uri": figure.asset_uri,
        "geometry": figure.geometry,
    }
    asset_uri = figure.asset_uri
    label = figure.figure_label or f"Page {figure.page_number or '?'} figure"
    if figure in document.figures:
        document.figures.remove(figure)
    db.delete(figure)
    db.flush()
    document.search_text = rebuild_document_search_text(document)
    log_event(
        db,
        job=None,
        document=document,
        event_type="figure_delete",
        message=f"Deleted extracted figure {label}.",
        payload={"figure": deleted_figure},
    )
    db.flush()
    record_document_version(
        db,
        document=document,
        change_note=f"Deleted extracted figure {label}",
        changed_fields={"figures", "search_text"},
        before=before,
        after=document_correction_snapshot(document),
        extra={"figure_delete": {"figure": deleted_figure}},
    )
    record_manual_edit(
        db,
        document=document,
        message=f"Deleted extracted figure {label}",
        metadata={"operation": "figure_delete", "figure": deleted_figure},
    )
    db.commit()
    if asset_uri:
        try:
            get_storage_service().delete_uri(asset_uri)
        except Exception:
            pass
    db.refresh(document)
    return document_detail_out(document, db)


@app.post("/api/documents/{document_id}/figures/page-scan", response_model=DocumentVisualPageScanReviewOut)
def scan_document_page_visuals(
    document_id: str,
    payload: DocumentVisualPageScanCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")

    max_page = document.page_count or max((page.page_number for page in document.pages), default=0)
    if max_page and payload.page_number > max_page:
        raise HTTPException(status_code=400, detail=f"Page {payload.page_number} is outside this document's {max_page} pages.")

    try:
        result = preview_document_figures_page_from_storage(db, document, payload.page_number)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Could not scan page {payload.page_number} for visuals: {exc}") from exc

    return {"document_id": document.id, **result}


@app.post("/api/documents/{document_id}/figures/page-scan/apply", response_model=DocumentDetail)
def apply_document_page_visual_scan(
    document_id: str,
    payload: DocumentVisualPageScanApplyCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")

    max_page = document.page_count or max((page.page_number for page in document.pages), default=0)
    if max_page and payload.page_number > max_page:
        raise HTTPException(status_code=400, detail=f"Page {payload.page_number} is outside this document's {max_page} pages.")

    candidates = [candidate.model_dump() for candidate in payload.candidates if candidate.page_number == payload.page_number]
    if not candidates:
        raise HTTPException(status_code=400, detail="Select at least one visual candidate to keep.")

    before = document_correction_snapshot(document)
    try:
        result = apply_document_figures_page_candidates(db, document, payload.page_number, candidates)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Could not keep page {payload.page_number} visual candidates: {exc}") from exc

    evidence = dict(document.metadata_evidence or {})
    visual_scans = list(evidence.get("visual_page_scans") or [])
    visual_scans.append(
        {
            "page_number": payload.page_number,
            "figures": result.get("figures", 0),
            "replaced_figures": result.get("replaced_figures", 0),
            "preserved_existing": result.get("preserved_existing", False),
            "warnings": result.get("audit_warnings", []),
            "scanned_at": utc_now().isoformat(),
            "source": "reader_page_scan",
            "review_status": "kept",
        }
    )
    evidence["visual_page_scans"] = visual_scans[-25:]
    document.metadata_evidence = evidence
    document.search_text = rebuild_document_search_text(document)
    log_event(
        db,
        job=None,
        document=document,
        event_type="visual_page_scan",
        message=f"Scanned page {payload.page_number} for figures, tables, graphs, photos, and other visual assets.",
        payload=result,
    )
    db.flush()
    record_document_version(
        db,
        document=document,
        change_note=f"Scanned page {payload.page_number} for visuals",
        changed_fields={"figures", "metadata_evidence", "search_text"},
        before=before,
        after=document_correction_snapshot(document),
        extra={"visual_page_scan": result},
    )
    record_manual_edit(
        db,
        document=document,
        message=f"Scanned page {payload.page_number} for visuals",
        metadata={
            "operation": "visual_page_scan",
            "page_number": payload.page_number,
            "figures": result.get("figures", 0),
            "replaced_figures": result.get("replaced_figures", 0),
            "preserved_existing": result.get("preserved_existing", False),
        },
    )
    db.commit()
    db.refresh(document)
    return document_detail_out(document, db)


@app.patch("/api/documents/{document_id}", response_model=DocumentDetail)
def patch_document(
    document_id: str,
    payload: DocumentPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")

    data = payload.model_dump(exclude_unset=True)
    tag_ids = data.pop("tag_ids", None)
    tag_names = data.pop("tag_names", None)
    domain_ids = data.pop("domain_ids", None)
    project_ids = data.pop("project_ids", None)
    attribute_values = data.pop("attribute_values", None)
    no_doi = data.pop("no_doi", None)
    confirm_verified_doi_edit = bool(data.pop("confirm_verified_doi_edit", False))
    confirm_verified_apa_citation_edit = bool(data.pop("confirm_verified_apa_citation_edit", False))
    confirm_verified_apa_in_text_citation_edit = bool(data.pop("confirm_verified_apa_in_text_citation_edit", False))
    confirm_verified_bibliography_edit = bool(data.pop("confirm_verified_bibliography_edit", False))
    requested_field_changes = {key for key, value in data.items() if getattr(document, key) != value}
    citation_fields = {"title", "authors", "publication_year", "journal", "publisher", "doi", "source_url"}
    no_doi_clears_doi = no_doi is True and bool(document.doi)
    doi_change_requested = "doi" in requested_field_changes or no_doi_clears_doi
    citation_metadata_change_requested = bool(requested_field_changes & citation_fields) or no_doi_clears_doi
    apa_citation_change_requested = "apa_citation" in requested_field_changes or (
        citation_metadata_change_requested and "apa_citation" not in data
    )
    apa_in_text_citation_change_requested = "apa_in_text_citation" in requested_field_changes or (
        citation_metadata_change_requested and "apa_in_text_citation" not in data
    )
    bibliography_change_requested = "bibliography" in requested_field_changes
    if doi_change_requested and document_field_is_verified(document, "doi") and not confirm_verified_doi_edit:
        raise HTTPException(status_code=409, detail="Confirm editing the manually verified DOI before saving changes")
    if apa_citation_change_requested and document_field_is_verified(document, "apa_citation") and not confirm_verified_apa_citation_edit:
        raise HTTPException(status_code=409, detail="Confirm editing the manually verified APA reference list before saving changes")
    if (
        apa_in_text_citation_change_requested
        and document_field_is_verified(document, "apa_in_text_citation")
        and not confirm_verified_apa_in_text_citation_edit
    ):
        raise HTTPException(status_code=409, detail="Confirm editing the manually verified APA in-text citation before saving changes")
    if bibliography_change_requested and document_bibliography_is_verified(document) and not confirm_verified_bibliography_edit:
        raise HTTPException(status_code=409, detail="Confirm editing the manually verified bibliography before saving changes")
    before = document_correction_snapshot(document)
    changed_fields: set[str] = set()
    for key, value in data.items():
        if getattr(document, key) != value:
            setattr(document, key, value)
            changed_fields.add(key)
    if "doi" in data and document.doi:
        evidence = dict(document.metadata_evidence or {})
        if evidence.pop(NO_DOI_METADATA_KEY, None) is not None:
            document.metadata_evidence = evidence
            changed_fields.add("metadata_evidence")
    if no_doi is not None:
        evidence = dict(document.metadata_evidence or {})
        if no_doi:
            if document.doi:
                document.doi = None
                changed_fields.add("doi")
            if not no_doi_flag_from_evidence(evidence, document.doi):
                evidence[NO_DOI_METADATA_KEY] = {
                    "status": "confirmed",
                    "source": "manual",
                    "updated_at": utc_now().isoformat(),
                }
                document.metadata_evidence = evidence
                changed_fields.add("metadata_evidence")
        elif evidence.pop(NO_DOI_METADATA_KEY, None) is not None:
            document.metadata_evidence = evidence
            changed_fields.add("metadata_evidence")
    if "apa_citation" in changed_fields:
        document.apa_citation_source = "user"
        document.apa_citation_model = None
        changed_fields.update({"apa_citation_source", "apa_citation_model"})
    if "apa_in_text_citation" in changed_fields:
        document.apa_in_text_citation_source = "user"
        document.apa_in_text_citation_model = None
        changed_fields.update({"apa_in_text_citation_source", "apa_in_text_citation_model"})
    if tag_ids is not None:
        document.tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
        changed_fields.add("tags")
    if tag_names is not None:
        tags = []
        for name in tag_names:
            tag = get_or_create_tag_by_name(db, name)
            if tag and tag not in tags:
                tags.append(tag)
        document.tags = tags
        changed_fields.add("tags")
    if domain_ids is not None:
        document.domains = db.query(Domain).filter(Domain.id.in_(domain_ids)).all() if domain_ids else []
        changed_fields.add("domains")
    if project_ids is not None:
        requested_project_ids = unique_preserve_order([str(project_id) for project_id in project_ids])
        current_items = (
            db.query(ProjectItem)
            .join(Project, Project.id == ProjectItem.project_id)
            .filter(ProjectItem.document_id == document.id, Project.deleted_at.is_(None))
            .all()
        )
        if set(requested_project_ids) != {item.project_id for item in current_items}:
            requested_project_id_set = set(requested_project_ids)
            for item in current_items:
                if item.project_id not in requested_project_id_set:
                    db.delete(item)
            projects = (
                db.query(Project).filter(Project.id.in_(requested_project_ids), Project.deleted_at.is_(None)).all()
                if requested_project_ids
                else []
            )
            apply_project_defaults(db, document, projects, document.priority)
            changed_fields.add("projects")
    if attribute_values is not None:
        for key, value in attribute_values.items():
            definition = get_or_create_attribute_definition(db, key)
            if not definition:
                continue
            current = (
                db.query(DocumentAttributeValue)
                .filter(
                    DocumentAttributeValue.document_id == document.id,
                    DocumentAttributeValue.attribute_definition_id == definition.id,
                )
                .one_or_none()
            )
            if value in (None, ""):
                if current:
                    db.delete(current)
                    changed_fields.add("attributes")
                continue
            normalized_value = normalize_attribute_value(value)
            if current:
                if current.value != normalized_value:
                    current.value = normalized_value
                    changed_fields.add("attributes")
            else:
                db.add(
                    DocumentAttributeValue(
                        document_id=document.id,
                        attribute_definition_id=definition.id,
                        value=normalized_value,
                    )
                )
                changed_fields.add("attributes")

    if changed_fields & citation_fields:
        citation_metadata = document_metadata(document)
        citation_model = get_analysis_model(db, MODEL_APA_CITATION)
        if "apa_citation" not in data and "apa_in_text_citation" not in data:
            apply_document_citations(document, citation_metadata, model=citation_model, source="metadata")
            changed_fields.update(
                {
                    "apa_citation",
                    "apa_citation_model",
                    "apa_citation_source",
                    "apa_in_text_citation",
                    "apa_in_text_citation_model",
                    "apa_in_text_citation_source",
                }
            )
        elif "apa_citation" not in data:
            document.apa_citation = format_apa_citation(citation_metadata)
            document.apa_citation_model = citation_model
            document.apa_citation_source = "metadata"
            changed_fields.update({"apa_citation", "apa_citation_model", "apa_citation_source"})
        elif "apa_in_text_citation" not in data:
            document.apa_in_text_citation = format_apa_in_text_citation(citation_metadata)
            document.apa_in_text_citation_model = citation_model
            document.apa_in_text_citation_source = "metadata"
            changed_fields.update({"apa_in_text_citation", "apa_in_text_citation_model", "apa_in_text_citation_source"})
    verification_fields_to_clear = []
    if "doi" in changed_fields:
        verification_fields_to_clear.append("doi")
    if "apa_citation" in changed_fields:
        verification_fields_to_clear.append("apa_citation")
    if "apa_in_text_citation" in changed_fields:
        verification_fields_to_clear.append("apa_in_text_citation")
    if "bibliography" in changed_fields:
        verification_fields_to_clear.append("bibliography")
    if verification_fields_to_clear and clear_document_field_verifications(document, verification_fields_to_clear):
        changed_fields.add("metadata_evidence")
    if changed_fields:
        document.search_text = rebuild_document_search_text(document)
        db.flush()
        after = document_correction_snapshot(document)
        record_document_version(
            db,
            document=document,
            change_note="Manual correction",
            changed_fields=changed_fields,
            before=before,
            after=after,
        )
        record_manual_edit(
            db,
            document=document,
            message="Manual correction",
            metadata={"changed_fields": sorted(changed_fields)},
        )
    db.commit()
    db.refresh(document)
    return document_detail_out(document, db)


@app.patch("/api/documents/{document_id}/pages/{page_id}", response_model=DocumentDetail)
def patch_document_page(
    document_id: str,
    page_id: str,
    payload: DocumentPagePatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    page = (
        db.query(DocumentPage)
        .filter(DocumentPage.id == page_id, DocumentPage.document_id == document.id)
        .one_or_none()
    )
    if not page:
        raise HTTPException(status_code=404, detail="Document page not found")

    next_text = payload.normalized_text.replace("\x00", "")
    before = document_correction_snapshot(document)
    page_before = document_page_snapshot(page)
    if page.normalized_text != next_text or page.text_source != "manual":
        page.normalized_text = next_text
        page.text_source = "manual"
        document.search_text = rebuild_document_search_text(document)
        db.flush()
        page_after = document_page_snapshot(page)
        record_document_version(
            db,
            document=document,
            change_note=f"Edited extracted text page {page.page_number}",
            changed_fields={"pages", f"page_{page.page_number}_normalized_text"},
            before=before,
            after=document_correction_snapshot(document),
            extra={
                "page_id": page.id,
                "page_number": page.page_number,
                "page_before": page_before,
                "page_after": page_after,
            },
        )
        record_manual_edit(
            db,
            document=document,
            message=f"Edited extracted text page {page.page_number}",
            metadata={"page_id": page.id, "page_number": page.page_number},
        )
    db.commit()
    db.refresh(document)
    return document_detail_out(document, db)


@app.post("/api/documents/{document_id}/pages/scrub", response_model=DocumentDetail)
def scrub_document_text(
    document_id: str,
    payload: DocumentTextScrub,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    needle = payload.text.replace("\x00", "")
    if not needle.strip():
        raise HTTPException(status_code=400, detail="Scrub text cannot be blank")

    before = document_correction_snapshot(document)
    changed_fields: set[str] = set()
    scrubbed_pages: list[dict[str, Any]] = []
    scrub_count = 0
    pages = sorted(document.pages, key=lambda page: page.page_number)
    for page in pages:
        current_text = page.normalized_text if page.normalized_text is not None else page.text or ""
        page_count = current_text.count(needle)
        if page_count == 0:
            continue
        page_before = document_page_snapshot(page)
        page.normalized_text = current_text.replace(needle, "")
        page.text_source = "manual"
        scrub_count += page_count
        changed_fields.update({"pages", f"page_{page.page_number}_normalized_text", f"page_{page.page_number}_text_source"})
        scrubbed_pages.append(
            {
                "count": page_count,
                "before": page_before,
                "after": document_page_snapshot(page),
            }
        )

    if scrub_count:
        document.search_text = rebuild_document_search_text(document)
        changed_fields.add("search_text")
        db.flush()
        record_document_version(
            db,
            document=document,
            change_note=f"Scrubbed extracted text ({scrub_count} matches)",
            changed_fields=changed_fields,
            before=before,
            after=document_correction_snapshot(document),
            extra={
                "scrub_text": needle,
                "scrub_count": scrub_count,
                "pages": scrubbed_pages,
            },
        )
        record_manual_edit(
            db,
            document=document,
            message="Scrubbed extracted text",
            metadata={"scrub_count": scrub_count, "page_count": len(scrubbed_pages)},
        )
    db.commit()
    db.refresh(document)
    return document_detail_out(document, db)


@app.post("/api/documents/{document_id}/versions/{version_id}/restore", response_model=DocumentDetail)
def restore_document_version(
    document_id: str,
    version_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    version = db.get(DocumentVersion, version_id)
    if not version or version.document_id != document.id:
        raise HTTPException(status_code=404, detail="Document version not found")

    snapshot = version.metadata_snapshot or {}
    target_document = restorable_document_snapshot(snapshot)
    target_pages = restorable_page_snapshots(snapshot)
    if not target_document and not target_pages:
        raise HTTPException(status_code=400, detail="Document version does not contain a restorable snapshot")

    before = document_correction_snapshot(document)
    changed_fields: set[str] = set()
    if target_document:
        changed_fields.update(apply_document_snapshot(db, document, target_document))

    restored_pages: list[dict[str, Any]] = []
    for target_page in target_pages:
        page = document_page_for_snapshot(db, document, target_page)
        if not page:
            continue
        page_before = document_page_snapshot(page)
        page_changed_fields = apply_document_page_snapshot(page, target_page)
        if not page_changed_fields:
            continue
        changed_fields.update({"pages", *page_changed_fields})
        restored_pages.append({"before": page_before, "after": document_page_snapshot(page)})

    after = document_correction_snapshot(document)
    changed_fields.update(changed_snapshot_fields(before, after))
    if changed_fields:
        document.search_text = rebuild_document_search_text(document)
        changed_fields.add("search_text")
        db.flush()
        after = document_correction_snapshot(document)

    record_document_version(
        db,
        document=document,
        change_note=f"Restored v{version.version_number} as current",
        changed_fields=changed_fields or {"restore"},
        before=before,
        after=after,
        extra={
            "restored_version_id": version.id,
            "restored_version_number": version.version_number,
            "restored_pages": restored_pages,
        },
    )
    record_manual_edit(
        db,
        document=document,
        message=f"Restored v{version.version_number} as current",
        metadata={"restored_version_id": version.id, "restored_version_number": version.version_number},
    )
    db.commit()
    db.refresh(document)
    return document_detail_out(document, db)


def trash_documents_by_id(db: Session, document_ids: list[str], *, source: str) -> DocumentTrashOut:
    unique_ids = list(dict.fromkeys(document_ids))
    if not unique_ids:
        return DocumentTrashOut(trashed=0, document_ids=[])
    documents = (
        filter_library_visible_documents(
            db.query(Document).options(
                selectinload(Document.tags),
                selectinload(Document.domains),
                selectinload(Document.attributes).selectinload(DocumentAttributeValue.definition),
                selectinload(Document.figures),
            )
        )
        .filter(Document.id.in_(unique_ids))
        .all()
    )
    by_id = {document.id: document for document in documents}
    ordered_documents = [by_id[document_id] for document_id in unique_ids if document_id in by_id]
    trashed_at = utc_now()
    trashed_ids: list[str] = []
    for document in ordered_documents:
        before = document_correction_snapshot(document)
        evidence = dict(document.metadata_evidence or {})
        trash_events = list(evidence.get("trash_events") or [])
        trash_events.append({"source": source, "trashed_at": trashed_at.isoformat()})
        evidence["trash_events"] = trash_events
        document.metadata_evidence = evidence
        document.deleted_at = trashed_at
        db.flush()
        record_document_version(
            db,
            document=document,
            change_note="Moved to Trash",
            changed_fields={"deleted_at", "metadata_evidence"},
            before=before,
            after=document_correction_snapshot(document),
            extra={"operation": "document_trash", "source": source, "deleted_at": trashed_at.isoformat()},
        )
        record_manual_edit(
            db,
            document=document,
            message="Moved to Trash",
            metadata={"operation": "document_trash", "source": source, "deleted_at": trashed_at.isoformat()},
        )
        trashed_ids.append(document.id)
    db.commit()
    return DocumentTrashOut(trashed=len(trashed_ids), document_ids=trashed_ids)


@app.delete("/api/documents/{document_id}")
def delete_document(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str | int | list[str]]:
    result = trash_documents_by_id(db, [document_id], source="detail")
    if result.trashed <= 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "trashed", "trashed": result.trashed, "document_ids": result.document_ids}


@app.post("/api/documents/trash", response_model=DocumentTrashOut)
def trash_documents(
    payload: DocumentTrashRequest,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentTrashOut:
    result = trash_documents_by_id(db, payload.document_ids, source="library_selection")
    if result.trashed <= 0:
        raise HTTPException(status_code=404, detail="No selected Library documents were found")
    return result


@app.post("/api/documents/bulk")
def bulk_update_documents(
    payload: dict[str, Any],
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    ids = payload.get("document_ids") or []
    updates = payload.get("updates") or {}
    if not ids:
        raise HTTPException(status_code=400, detail="document_ids is required")
    documents = filter_library_visible_documents(db.query(Document)).filter(Document.id.in_(ids)).all()
    for document in documents:
        for key in ["read_status", "priority", "citation_status"]:
            if key in updates:
                setattr(document, key, updates[key])
        if "tag_ids" in updates:
            tags = db.query(Tag).filter(Tag.id.in_(updates["tag_ids"])).all()
            document.tags = list({tag.id: tag for tag in [*document.tags, *tags]}.values())
        if "tag_names" in updates:
            tags = [tag for name in updates["tag_names"] if (tag := get_or_create_tag_by_name(db, str(name)))]
            document.tags = list({tag.id: tag for tag in [*document.tags, *tags]}.values())
        if "domain_ids" in updates:
            domains = db.query(Domain).filter(Domain.id.in_(updates["domain_ids"])).all()
            document.domains = list({domain.id: domain for domain in [*document.domains, *domains]}.values())
        if "project_ids" in updates:
            projects = db.query(Project).filter(Project.id.in_(updates["project_ids"]), Project.deleted_at.is_(None)).all()
            apply_project_defaults(db, document, projects, document.priority)
    db.commit()
    return {"updated": len(documents)}


@app.post("/api/documents/title-cleanup")
def cleanup_document_titles(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    documents = (
        filter_library_visible_documents(db.query(Document))
        .options(selectinload(Document.tags), selectinload(Document.domains), selectinload(Document.attributes))
        .all()
    )
    updated = 0
    for document in documents:
        normalized_title = normalize_document_title_spacing(document.title)
        if not normalized_title or normalized_title == document.title:
            continue
        before = document_correction_snapshot(document)
        old_title = document.title
        document.title = normalized_title
        document.search_text = rebuild_document_search_text(document)
        db.flush()
        record_document_version(
            db,
            document=document,
            change_note="Title cleanup",
            changed_fields={"title", "search_text"},
            before=before,
            after=document_correction_snapshot(document),
            extra={"old_title": old_title, "new_title": normalized_title},
        )
        record_manual_edit(
            db,
            document=document,
            message="Title cleanup",
            metadata={"old_title": old_title, "new_title": normalized_title},
        )
        updated += 1
    db.commit()
    return {"updated": updated}


def validate_duplicate_strategy(strategy: str) -> str:
    if strategy not in DUPLICATE_IMPORT_STRATEGIES:
        raise HTTPException(status_code=400, detail="Unsupported duplicate import strategy")
    return strategy


def import_storage_key(checksum: str, document_id: str, filename: str) -> str:
    return f"documents/{checksum[:2]}/{checksum}/{document_id}/{filename}"


def import_cache_path(cache_dir: Path, document_id: str) -> Path:
    return cache_dir / f"{document_id}.pdf"


def apply_project_defaults(db: Session, document: Document, projects: list[Project], priority: str) -> None:
    for project in projects:
        existing = (
            db.query(ProjectItem)
            .filter(ProjectItem.project_id == project.id, ProjectItem.document_id == document.id)
            .one_or_none()
        )
        if not existing:
            db.add(ProjectItem(project_id=project.id, document_id=document.id, priority=priority))


def apply_attribute_defaults(db: Session, document: Document, attributes: dict[str, Any], *, replace: bool = False) -> None:
    if replace:
        document.attributes.clear()
        db.flush()
    for name, value in attributes.items():
        definition = db.query(AttributeDefinition).filter(AttributeDefinition.name == name).one_or_none()
        if not definition:
            definition = AttributeDefinition(name=name, value_type="markdown")
            db.add(definition)
            db.flush()
        existing = (
            db.query(DocumentAttributeValue)
            .filter(
                DocumentAttributeValue.document_id == document.id,
                DocumentAttributeValue.attribute_definition_id == definition.id,
            )
            .one_or_none()
        )
        normalized_value = normalize_attribute_value(value)
        if existing:
            existing.value = normalized_value
        else:
            db.add(
                DocumentAttributeValue(
                    document_id=document.id,
                    attribute_definition_id=definition.id,
                    value=normalized_value,
                )
            )


def reset_document_for_overwrite(db: Session, document: Document) -> None:
    before = document_correction_snapshot(document)
    db.query(DocumentCompositionRecord).filter(DocumentCompositionRecord.document_id == document.id).delete(synchronize_session=False)
    document.subtitle = None
    document.authors = []
    document.universities = []
    document.publication_year = None
    document.publisher = None
    document.journal = None
    document.doi = None
    document.source_url = None
    document.abstract = None
    document.rich_summary = None
    document.bibliography = None
    document.apa_citation = None
    document.apa_citation_model = None
    document.apa_citation_source = None
    document.apa_in_text_citation = None
    document.apa_in_text_citation_model = None
    document.apa_in_text_citation_source = None
    document.citation_status = "needs_review"
    document.metadata_confidence = None
    document.search_text = None
    document.page_count = 0
    document.pages.clear()
    document.chunks.clear()
    document.figures.clear()
    document.capabilities.clear()
    db.query(CitationCandidate).filter(CitationCandidate.document_id == document.id, CitationCandidate.status == "needs_review").delete(
        synchronize_session=False
    )
    db.flush()
    record_document_version(
        db,
        document=document,
        change_note="Import overwrite",
        changed_fields={
            "subtitle",
            "authors",
            "universities",
            "publication_year",
            "publisher",
            "journal",
            "doi",
            "source_url",
            "abstract",
            "rich_summary",
            "bibliography",
            "apa_citation",
            "apa_in_text_citation",
            "citation_status",
            "metadata_confidence",
            "search_text",
            "page_count",
            "pages",
            "chunks",
            "figures",
            "capabilities",
            "citation_candidates",
        },
        before=before,
        after=document_correction_snapshot(document),
    )


def create_skipped_duplicate_job(
    db: Session,
    *,
    batch: ImportBatch,
    document: Document | None,
    filename: str,
    checksum: str,
    reason: str,
) -> ImportJob:
    job = ImportJob(
        batch_id=batch.id,
        document_id=document.id if document else None,
        status="complete",
        current_step="duplicate_skipped",
    )
    db.add(job)
    db.flush()
    db.add(
        ProcessingEvent(
            import_job_id=job.id,
            document_id=document.id if document else None,
            level="warning",
            event_type="duplicate_skipped",
            message="Duplicate upload skipped by import policy.",
            payload={"filename": filename, "checksum_sha256": checksum, "reason": reason},
        )
    )
    return job


async def inspect_import_duplicates(files: list[UploadFile], db: Session) -> ImportDuplicateCheckOut:
    seen_profiles: list[Any] = []
    rows: list[ImportDuplicateFileOut] = []
    duplicate_count = 0
    for upload in files:
        data = await upload.read()
        try:
            prepared = prepare_import_source(data, upload.filename, upload.content_type)
        except ImportSourceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        profile = prepared_import_duplicate_profile(prepared)
        matches = active_duplicate_matches_for_profile(db, profile, statuses=IMPORT_DUPLICATE_DOCUMENT_STATUSES)
        duplicate_in_upload = any(same_drop_duplicate_reasons(profile, seen_profile) for seen_profile in seen_profiles)
        seen_profiles.append(profile)
        duplicate_reasons = duplicate_reason_labels(matches)
        if matches or duplicate_in_upload:
            duplicate_count += 1
        rows.append(
            ImportDuplicateFileOut(
                filename=prepared.source_filename,
                checksum_sha256=prepared.source_checksum_sha256,
                checksum_md5=prepared.stored_checksum_md5,
                file_size_bytes=prepared.source_size_bytes,
                source_kind=prepared.source_kind,
                stored_filename=prepared.stored_filename,
                detected_title=prepared.title,
                existing_documents=[duplicate_document_out(match.document, match) for match in matches],
                duplicate_in_upload=duplicate_in_upload,
                duplicate_reasons=duplicate_reasons,
            )
        )
    return ImportDuplicateCheckOut(files=rows, duplicate_file_count=duplicate_count)


@app.post("/api/imports/duplicates", response_model=ImportDuplicateCheckOut)
async def check_import_duplicates(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    files: Annotated[list[UploadFile], File()],
) -> ImportDuplicateCheckOut:
    return await inspect_import_duplicates(files, db)


@app.post("/api/imports/batches", response_model=ImportBatchOut)
async def create_import_batch(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    files: Annotated[list[UploadFile], File()],
    label: Annotated[str | None, Form()] = None,
    domain_ids: Annotated[str | None, Form()] = None,
    tag_ids: Annotated[str | None, Form()] = None,
    project_ids: Annotated[str | None, Form()] = None,
    priority: Annotated[str, Form()] = "normal",
    read_status: Annotated[str, Form()] = "unread",
    attributes: Annotated[str | None, Form()] = None,
    duplicate_strategy: Annotated[str, Form()] = "skip",
    processing_preset_id: Annotated[str | None, Form()] = None,
) -> ImportBatch:
    duplicate_strategy = validate_duplicate_strategy(duplicate_strategy)
    parsed_domain_ids = parse_json_form(domain_ids, [])
    parsed_tag_ids = parse_json_form(tag_ids, [])
    parsed_project_ids = parse_json_form(project_ids, [])
    parsed_attributes = parse_json_form(attributes, {})
    preset_snapshot = import_processing_snapshot(db, processing_preset_id)
    prepared_files = []
    for upload in files:
        data = await upload.read()
        try:
            prepared_files.append(prepare_import_source(data, upload.filename, upload.content_type))
        except ImportSourceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    batch = ImportBatch(
        label=label,
        total_files=len(prepared_files),
        shared_defaults={
            "domain_ids": parsed_domain_ids,
            "tag_ids": parsed_tag_ids,
            "project_ids": parsed_project_ids,
            "priority": priority,
            "read_status": read_status,
            "attributes": parsed_attributes,
            "processing_preset_id": preset_snapshot["id"],
            "processing_preset_name": preset_snapshot["name"],
            "processing_preset_mode": preset_snapshot["mode"],
            "processing_preset_snapshot": preset_snapshot,
        },
    )
    db.add(batch)
    db.flush()

    domains = db.query(Domain).filter(Domain.id.in_(parsed_domain_ids)).all() if parsed_domain_ids else []
    tags = db.query(Tag).filter(Tag.id.in_(parsed_tag_ids)).all() if parsed_tag_ids else []
    projects = db.query(Project).filter(Project.id.in_(parsed_project_ids)).all() if parsed_project_ids else []
    storage = get_storage_service()
    cache_dir = document_cache_root()
    model_preferences = get_analysis_models(db)
    estimate_rates = import_cost_exemplar_rates(db)

    batch_documents: list[tuple[Any, Document]] = []
    for prepared in prepared_files:
        checksum = prepared.source_checksum_sha256
        filename = prepared.source_filename
        stored_filename = prepared.stored_filename
        profile = prepared_import_duplicate_profile(prepared)
        existing_matches = active_duplicate_matches_for_profile(db, profile, statuses=IMPORT_DUPLICATE_DOCUMENT_STATUSES)
        batch_match = next(
            (
                (existing_profile, existing_document, duplicate_match_reasons(profile, existing_profile))
                for existing_profile, existing_document in batch_documents
                if same_drop_duplicate_reasons(profile, existing_profile)
            ),
            None,
        )
        if batch_match and duplicate_strategy != "import_anyway":
            _, already_handled_document, batch_reasons = batch_match
            create_skipped_duplicate_job(
                db,
                batch=batch,
                document=already_handled_document,
                filename=filename,
                checksum=checksum,
                reason=f"duplicate_in_current_batch:{match_basis(batch_reasons)}",
            )
            continue

        if existing_matches and duplicate_strategy == "skip":
            create_skipped_duplicate_job(
                db,
                batch=batch,
                document=existing_matches[0].document,
                filename=filename,
                checksum=checksum,
                reason=f"matched_existing_document:{existing_matches[0].match_basis}",
            )
            continue

        duplicate_source_ids = [match.document.id for match in existing_matches]
        duplicate_source_reasons = {match.document.id: match.match_reasons for match in existing_matches}
        if existing_matches and duplicate_strategy == "overwrite":
            document = existing_matches[0].document
            reset_document_for_overwrite(db, document)
        else:
            document = Document(
                title=prepared.title,
                original_filename=stored_filename,
                content_type=prepared.stored_content_type,
                checksum_sha256=checksum,
                checksum_md5=prepared.stored_checksum_md5,
                priority=priority,
                read_status=read_status,
            )
            db.add(document)
            db.flush()

        key = import_storage_key(checksum, document.id, stored_filename)
        stored = storage.put_bytes(key, prepared.stored_data, prepared.stored_content_type)
        cache_path = import_cache_path(cache_dir, document.id)
        cache_path.write_bytes(prepared.stored_data)
        document.title = prepared.title
        document.original_filename = stored_filename
        document.content_type = prepared.stored_content_type
        document.checksum_sha256 = checksum
        document.checksum_md5 = prepared.stored_checksum_md5
        document.gcs_uri = stored.uri
        document.storage_status = stored.backend
        document.processing_status = STAGED_IMPORT_STATUS
        document.priority = priority
        document.read_status = read_status
        estimated_page_count = prepared.stored_page_count or 0
        document.page_count = estimated_page_count
        document.metadata_evidence = {
            "file_size_bytes": len(prepared.stored_data),
            "local_cache_path": str(cache_path),
            "document_cache_path": str(cache_path),
            "source_import": prepared.metadata,
            "hashes": {
                "source_sha256": prepared.source_checksum_sha256,
                "source_md5": prepared.source_checksum_md5,
                "stored_sha256": prepared.stored_checksum_sha256,
                "stored_md5": prepared.stored_checksum_md5,
            },
            "upload_cost_estimate": {
                "estimated_page_count": estimated_page_count or None,
                "basis": "pending_preset_step_cost_model",
            },
            "import_defaults": batch.shared_defaults,
            "import_processing_preset": preset_snapshot,
            "duplicate_import": {
                "strategy": duplicate_strategy,
                "matched_document_ids": duplicate_source_ids,
                "matched_document_reasons": duplicate_source_reasons,
            },
        }
        register_document_cache(document, cache_path, source="upload")
        document.domains = domains.copy()
        document.tags = tags.copy()
        apply_project_defaults(db, document, projects, priority)
        apply_attribute_defaults(db, document, parsed_attributes, replace=duplicate_strategy == "overwrite")

        job = ImportJob(batch_id=batch.id, document_id=document.id, status=STAGED_IMPORT_STATUS, current_step=STAGED_IMPORT_STATUS)
        db.add(job)
        db.flush()
        cost_estimate = estimate_import_job_cost(
            job,
            model_preferences=model_preferences,
            rates=estimate_rates,
            db=db,
        )
        estimated_cost_usd = float(cost_estimate.get("estimated_cost_usd") or 0.0)
        estimate_basis = str(cost_estimate.get("basis") or "none")
        estimate_page_count = cost_estimate.get("estimated_page_count")
        if not isinstance(estimate_page_count, int):
            estimate_page_count = document_estimated_page_count(document)
        upload_estimate = {
            "estimated_cost_usd": estimated_cost_usd,
            "estimated_page_count": estimate_page_count,
            "basis": estimate_basis,
            "uncalibrated_cost_usd": cost_estimate.get("uncalibrated_cost_usd"),
            "minimum_cloud_call_cost_usd": cost_estimate.get("minimum_cloud_call_cost_usd"),
            "step_estimates": cost_estimate.get("steps", []),
            "calibration_factor": estimate_rates.get("estimate_calibration_factor"),
            "calibration_sample_count": estimate_rates.get("estimate_calibration_sample_count"),
            "model_preferences": model_preferences,
            "processing_preset": {
                "id": preset_snapshot["id"],
                "name": preset_snapshot["name"],
                "mode": preset_snapshot["mode"],
            },
            "estimated_at": utc_now().isoformat(),
        }
        document.metadata_evidence = {**(document.metadata_evidence or {}), "upload_cost_estimate": upload_estimate}
        record_import_cost_estimate(
            db,
            document=document,
            job=job,
            estimated_cost_usd=estimated_cost_usd,
            estimate_basis=estimate_basis,
            estimated_page_count=estimate_page_count,
            model_preferences=model_preferences,
            metadata={
                "calibration_factor": estimate_rates.get("estimate_calibration_factor"),
                "calibration_sample_count": estimate_rates.get("estimate_calibration_sample_count"),
                "uncalibrated_cost_usd": cost_estimate.get("uncalibrated_cost_usd"),
                "minimum_cloud_call_cost_usd": cost_estimate.get("minimum_cloud_call_cost_usd"),
                "step_estimates": cost_estimate.get("steps", []),
                "processing_preset": {
                    "id": preset_snapshot["id"],
                    "name": preset_snapshot["name"],
                    "mode": preset_snapshot["mode"],
                },
            },
        )
        batch_documents.append((profile, document))

    refresh_import_batch_progress(db, batch)
    db.commit()
    db.refresh(batch)
    return batch


@app.get("/api/imports/batches", response_model=list[ImportBatchOut])
def list_import_batches(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[ImportBatch]:
    return db.query(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(50).all()


def import_job_file_size(document: Document | None) -> int | None:
    if not document:
        return None
    metadata_evidence = document.metadata_evidence or {}
    stored_size = metadata_evidence.get("file_size_bytes")
    if isinstance(stored_size, int):
        return stored_size
    candidate_paths = [metadata_evidence.get("local_cache_path")]
    if document.gcs_uri and not document.gcs_uri.startswith("gs://"):
        candidate_paths.append(document.gcs_uri)
    for raw_path in candidate_paths:
        if not isinstance(raw_path, str) or not raw_path:
            continue
        path = Path(raw_path)
        if path.exists() and path.is_file():
            return path.stat().st_size
    return None


def import_job_costs_usd(db: Session, import_job_ids: list[str]) -> dict[str, float]:
    if not import_job_ids:
        return {}
    costs: dict[str, float] = {job_id: 0.0 for job_id in import_job_ids}
    usage_rows = db.query(OpenAIUsageRecord).filter(OpenAIUsageRecord.import_job_id.in_(import_job_ids)).all()
    for usage in usage_rows:
        if usage.import_job_id:
            costs[usage.import_job_id] = costs.get(usage.import_job_id, 0.0) + (estimated_cost_usd_for_record(usage, db) or 0.0)
    return {job_id: round(cost, 6) for job_id, cost in costs.items()}


IMPORT_JOB_STATUS_PRIORITY = {
    "running": 0,
    "failed": 1,
    "restored_paused": 2,
    "queued": 3,
    "staged": 4,
    "complete": 5,
    "duplicate_skipped": 6,
    "cleared": 7,
}


def document_estimated_page_count(document: Document | None) -> int | None:
    if not document:
        return None
    if document.page_count and document.page_count > 0:
        return document.page_count
    evidence = document.metadata_evidence or {}
    estimate = evidence.get("upload_cost_estimate")
    if isinstance(estimate, dict):
        value = estimate.get("estimated_page_count")
        if isinstance(value, int) and value > 0:
            return value
    source_import = evidence.get("source_import")
    if isinstance(source_import, dict):
        value = source_import.get("estimated_page_count") or source_import.get("extracted_page_count")
        if isinstance(value, int) and value > 0:
            return value
        pages = source_import.get("extracted_pages")
        if isinstance(pages, list) and pages:
            return len(pages)
    return None


def document_persisted_cost_estimate(document: Document | None) -> tuple[float, str, int | None] | None:
    if not document:
        return None
    estimate = (document.metadata_evidence or {}).get("upload_cost_estimate")
    if not isinstance(estimate, dict):
        return None
    amount = estimate.get("estimated_cost_usd")
    try:
        estimated_cost = float(amount)
    except (TypeError, ValueError):
        return None
    if estimated_cost <= 0:
        return None
    page_count = estimate.get("estimated_page_count")
    if not isinstance(page_count, int) or page_count <= 0:
        page_count = document_estimated_page_count(document)
    basis = str(estimate.get("basis") or "persisted_estimate")
    return round(estimated_cost, 6), basis, page_count


def document_import_processing_preset(document: Document | None, batch: ImportBatch | None = None) -> dict[str, Any] | None:
    if document:
        evidence = document.metadata_evidence or {}
        preset = evidence.get("import_processing_preset")
        if isinstance(preset, dict):
            return preset
    shared_defaults = batch.shared_defaults if batch else None
    if isinstance(shared_defaults, dict):
        preset = shared_defaults.get("processing_preset_snapshot")
        if isinstance(preset, dict):
            return preset
        preset_id = shared_defaults.get("processing_preset_id")
        preset_name = shared_defaults.get("processing_preset_name")
        preset_mode = shared_defaults.get("processing_preset_mode")
        if preset_id or preset_name:
            return {"id": preset_id or "balanced", "name": preset_name or str(preset_id), "mode": preset_mode or "balanced"}
    return None


ACTIVE_IMPORT_HISTORY_STATUSES = {"staged", "queued", "running", "restored_paused"}


def ingestion_history_timestamp(value: datetime | None) -> datetime | None:
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def ingestion_history_sort_time(value: datetime | None) -> float:
    normalized = ingestion_history_timestamp(value)
    return normalized.timestamp() if normalized else 0.0


def latest_import_estimate_for_job(job: ImportJob) -> float:
    estimate_records = [
        record
        for record in (job.composition_records or [])
        if record.record_kind == "estimate" and record.stage_key == "import_cost_estimate"
    ]
    if estimate_records:
        estimate = max(estimate_records, key=lambda record: record.created_at or datetime.min.replace(tzinfo=timezone.utc))
        try:
            return max(0.0, float(estimate.amount_usd or 0.0))
        except (TypeError, ValueError):
            return 0.0
    persisted = document_persisted_cost_estimate(job.document)
    return persisted[0] if persisted else 0.0


def ingestion_history_row(batch: ImportBatch, *, actual_costs_by_job: dict[str, float]) -> dict[str, Any]:
    jobs = list(batch.jobs or [])
    status_counts: dict[str, int] = {}
    for job in jobs:
        status_counts[job.status] = status_counts.get(job.status, 0) + 1

    started_candidates = [
        ingestion_history_timestamp(event.created_at)
        for job in jobs
        for event in (job.events or [])
        if event.event_type == "manual_import_process_uploads" and event.created_at
    ]
    if not started_candidates:
        started_candidates = [
            ingestion_history_timestamp(event.created_at)
            for job in jobs
            for event in (job.events or [])
            if event.event_type == "started" and event.created_at
        ]
    if not started_candidates:
        started_candidates = [ingestion_history_timestamp(job.locked_at) for job in jobs if job.locked_at]
    started_candidates = [candidate for candidate in started_candidates if candidate]
    started_at = min(started_candidates) if started_candidates else None

    active = any(job.status in ACTIVE_IMPORT_HISTORY_STATUSES for job in jobs)
    completed_at = None
    if jobs and not active:
        terminal_updates = [ingestion_history_timestamp(job.updated_at) for job in jobs if job.updated_at]
        terminal_updates = [candidate for candidate in terminal_updates if candidate]
        completed_at = max(terminal_updates) if terminal_updates else ingestion_history_timestamp(batch.updated_at)

    duration_seconds = None
    if started_at:
        duration_end = completed_at or (utc_now() if active else None)
        if duration_end:
            duration_seconds = max(0, int((duration_end - started_at).total_seconds()))

    running_jobs = [job for job in jobs if job.status == "running"]
    latest_stage_job = (
        max(running_jobs or jobs, key=lambda job: ingestion_history_sort_time(job.updated_at or job.created_at or batch.created_at))
        if jobs
        else None
    )
    total_size = sum(import_job_file_size(job.document) or 0 for job in jobs)
    estimated_cost = round(sum(latest_import_estimate_for_job(job) for job in jobs), 6)
    actual_cost = round(sum(actual_costs_by_job.get(job.id, 0.0) for job in jobs), 6)
    processed_files = status_counts.get("complete", 0) + status_counts.get("failed", 0)
    cost_per_document = round(actual_cost / processed_files, 6) if processed_files > 0 else None
    preset = document_import_processing_preset(None, batch)

    return {
        "batch_id": batch.id,
        "label": batch.label,
        "status": batch.status,
        "active": active,
        "total_files": batch.total_files,
        "completed_files": status_counts.get("complete", batch.completed_files),
        "failed_files": status_counts.get("failed", batch.failed_files),
        "queued_files": status_counts.get("queued", 0),
        "running_files": status_counts.get("running", 0),
        "staged_files": status_counts.get("staged", 0),
        "cleared_files": status_counts.get("cleared", 0),
        "estimated_cost_usd": estimated_cost,
        "actual_cost_usd": actual_cost,
        "cost_variance_usd": round(actual_cost - estimated_cost, 6) if estimated_cost > 0 else None,
        "cost_per_document_usd": cost_per_document,
        "total_size_bytes": total_size,
        "processing_preset_id": str(preset.get("id")) if preset and preset.get("id") is not None else None,
        "processing_preset_name": str(preset.get("name")) if preset and preset.get("name") is not None else None,
        "processing_preset_mode": str(preset.get("mode")) if preset and preset.get("mode") is not None else None,
        "latest_stage": latest_stage_job.current_step if latest_stage_job else None,
        "duration_seconds": duration_seconds,
        "started_at": started_at,
        "completed_at": completed_at,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
    }


@app.get("/api/utilities/ingestion-history", response_model=list[IngestionHistoryOut])
def list_ingestion_history(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    batches = (
        db.query(ImportBatch)
        .options(
            selectinload(ImportBatch.jobs).joinedload(ImportJob.document),
            selectinload(ImportBatch.jobs).selectinload(ImportJob.events),
            selectinload(ImportBatch.jobs).selectinload(ImportJob.composition_records),
        )
        .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())
        .limit(limit)
        .all()
    )
    job_ids = [job.id for batch in batches for job in (batch.jobs or [])]
    actual_costs_by_job = import_job_costs_usd(db, job_ids)
    return [ingestion_history_row(batch, actual_costs_by_job=actual_costs_by_job) for batch in batches]


def import_estimate_calibration(db: Session) -> tuple[float, int]:
    estimate_rows = (
        db.query(DocumentCompositionRecord.document_id, DocumentCompositionRecord.amount_usd, DocumentCompositionRecord.created_at)
        .filter(
            DocumentCompositionRecord.record_kind == "estimate",
            DocumentCompositionRecord.stage_key == "import_cost_estimate",
            DocumentCompositionRecord.amount_usd > 0,
        )
        .order_by(DocumentCompositionRecord.created_at.desc())
        .limit(1000)
        .all()
    )
    latest_estimates: dict[str, float] = {}
    for document_id, amount, _created_at in estimate_rows:
        if document_id in latest_estimates:
            continue
        try:
            estimate_amount = float(amount or 0)
        except (TypeError, ValueError):
            continue
        if estimate_amount > 0:
            latest_estimates[document_id] = estimate_amount
    if not latest_estimates:
        return 1.0, 0

    document_ids = list(latest_estimates)
    complete_document_ids = {
        row[0]
        for row in db.query(ImportJob.document_id)
        .filter(ImportJob.document_id.in_(document_ids), ImportJob.status == "complete")
        .all()
        if row[0]
    }
    if not complete_document_ids:
        return 1.0, 0

    actual_rows = (
        db.query(DocumentCompositionRecord.document_id, func.sum(DocumentCompositionRecord.amount_usd))
        .filter(
            DocumentCompositionRecord.document_id.in_(complete_document_ids),
            DocumentCompositionRecord.record_kind.in_(["llm", "embedding"]),
            DocumentCompositionRecord.amount_usd > 0,
        )
        .group_by(DocumentCompositionRecord.document_id)
        .all()
    )
    actual_by_document: dict[str, float] = {}
    for document_id, amount in actual_rows:
        try:
            actual_amount = float(amount or 0)
        except (TypeError, ValueError):
            continue
        if actual_amount > 0:
            actual_by_document[document_id] = actual_amount

    compared_document_ids = [document_id for document_id in complete_document_ids if document_id in actual_by_document]
    if not compared_document_ids:
        return 1.0, 0
    total_estimated = sum(latest_estimates[document_id] for document_id in compared_document_ids)
    total_actual = sum(actual_by_document[document_id] for document_id in compared_document_ids)
    if total_estimated <= 0 or total_actual <= 0:
        return 1.0, 0
    factor = total_actual / total_estimated
    factor = max(IMPORT_ESTIMATE_CALIBRATION_MIN, min(IMPORT_ESTIMATE_CALIBRATION_MAX, factor))
    return round(factor, 4), len(compared_document_ids)


def import_cost_exemplar_rates(db: Session) -> dict[str, Any]:
    records = (
        db.query(OpenAIUsageRecord, Document.page_count)
        .join(Document, OpenAIUsageRecord.document_id == Document.id)
        .filter(
            OpenAIUsageRecord.source == "import",
            OpenAIUsageRecord.status != "failed",
            Document.page_count > 0,
        )
        .order_by(OpenAIUsageRecord.created_at.desc())
        .limit(4000)
        .all()
    )
    task_model_document_costs: dict[tuple[str, str, str], float] = {}
    task_model_document_pages: dict[tuple[str, str, str], int] = {}
    task_document_costs: dict[tuple[str, str], float] = {}
    task_document_pages: dict[tuple[str, str], int] = {}
    document_costs: dict[str, float] = {}
    document_pages: dict[str, int] = {}

    for record, page_count in records:
        if not record.document_id or not page_count:
            continue
        cost = estimated_cost_usd_for_record(record, db) or 0.0
        if cost <= 0:
            continue
        pages = max(1, int(page_count))
        task_key = record.task_key or record.capability_key or "unknown"
        model = record.model or "unknown"
        task_model_key = (record.document_id, task_key, model)
        task_key_only = (record.document_id, task_key)
        task_model_document_costs[task_model_key] = task_model_document_costs.get(task_model_key, 0.0) + cost
        task_model_document_pages[task_model_key] = pages
        task_document_costs[task_key_only] = task_document_costs.get(task_key_only, 0.0) + cost
        task_document_pages[task_key_only] = pages
        document_costs[record.document_id] = document_costs.get(record.document_id, 0.0) + cost
        document_pages[record.document_id] = pages

    def aggregate_per_page(document_cost_map: dict[Any, float], document_page_map: dict[Any, int], key_index: slice | None = None) -> dict[Any, float]:
        cost_by_key: dict[Any, float] = {}
        page_by_key: dict[Any, int] = {}
        for key, cost in document_cost_map.items():
            aggregate_key = key[key_index] if key_index else "overall"
            if isinstance(aggregate_key, tuple) and len(aggregate_key) == 1:
                aggregate_key = aggregate_key[0]
            cost_by_key[aggregate_key] = cost_by_key.get(aggregate_key, 0.0) + cost
            page_by_key[aggregate_key] = page_by_key.get(aggregate_key, 0) + document_page_map.get(key, 0)
        return {
            key: cost / max(1, page_by_key.get(key, 0))
            for key, cost in cost_by_key.items()
            if page_by_key.get(key, 0) > 0
        }

    task_model_rates = aggregate_per_page(task_model_document_costs, task_model_document_pages, slice(1, 3))
    task_rates = aggregate_per_page(task_document_costs, task_document_pages, slice(1, 2))
    overall_rates = aggregate_per_page(document_costs, document_pages)
    calibration_factor, calibration_sample_count = import_estimate_calibration(db)
    return {
        "task_model_rates": task_model_rates,
        "task_rates": task_rates,
        "overall_rate": overall_rates.get("overall", 0.0),
        "exemplar_count": len(document_costs),
        "estimate_calibration_factor": calibration_factor,
        "estimate_calibration_sample_count": calibration_sample_count,
    }


def apply_import_estimate_calibration(amount: float, basis: str, rates: dict[str, Any]) -> tuple[float, str]:
    factor = float(rates.get("estimate_calibration_factor") or 1.0)
    sample_count = int(rates.get("estimate_calibration_sample_count") or 0)
    if sample_count <= 0 or factor <= 0 or abs(factor - 1.0) < 0.0001:
        return amount, basis
    return round(amount * factor, 6), f"calibrated_{basis}"


def import_estimate_model_is_cloud(model: str | None) -> bool:
    normalized = (model or "").strip().lower()
    if normalized in IMPORT_ESTIMATE_LOCAL_MODELS:
        return False
    return normalized.startswith(("gpt-", "o", "gemini-", "text-embedding-"))


def import_estimate_tokens(task_key: str, page_count: int) -> tuple[int, int]:
    profile = IMPORT_ESTIMATE_TASK_TOKEN_PROFILES.get(
        task_key,
        {"input_per_page": IMPORT_ESTIMATE_INPUT_TOKENS_PER_PAGE, "output_base": 500},
    )
    input_tokens = int(profile.get("input_base", 0)) + int(profile.get("input_per_page", 0)) * page_count
    output_tokens = int(profile.get("output_base", 0)) + int(profile.get("output_per_page", 0)) * page_count
    return max(0, input_tokens), max(0, output_tokens)


def apply_import_estimate_model_floor(
    *,
    step: dict[str, Any],
    task_key: str,
    model: str | None,
    exemplar_cost: float,
    db: Session | None,
) -> None:
    input_tokens, output_tokens = import_estimate_tokens(task_key, 1)
    priced_floor = estimated_cost_usd_for_model_tokens(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        db=db,
    )
    if priced_floor is None or priced_floor <= exemplar_cost:
        step["estimated_cost_usd"] = round(max(0.0, exemplar_cost), 6)
        return
    original_basis = str(step.get("basis") or "exemplar")
    step["estimated_cost_usd"] = round(priced_floor, 6)
    step["basis"] = f"{original_basis}_model_floor"
    step["exemplar_cost_usd"] = round(max(0.0, exemplar_cost), 6)
    step["model_pricing_floor_usd"] = round(priced_floor, 6)
    step["estimated_input_tokens"] = input_tokens
    step["estimated_output_tokens"] = output_tokens


def import_estimate_step_model_floor(step: dict[str, Any], db: Session | None) -> float:
    page_count = step.get("estimated_page_count")
    if not isinstance(page_count, int) or page_count <= 0:
        return 0.0
    model = str(step.get("model") or "")
    if not import_estimate_model_is_cloud(model):
        return 0.0
    task_key = str(step.get("task_key") or "")
    input_tokens, output_tokens = import_estimate_tokens(task_key, 1)
    priced_floor = estimated_cost_usd_for_model_tokens(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        db=db,
    )
    return round(max(0.0, float(priced_floor or 0.0)), 6)


def import_estimate_cloud_call_floor(steps: list[dict[str, Any]], db: Session | None) -> float:
    return round(sum(import_estimate_step_model_floor(step, db) for step in steps), 6)


def import_estimate_step_cost(
    *,
    task_key: str,
    label: str,
    model: str | None,
    page_count: int,
    rates: dict[str, Any],
    db: Session | None,
    status: str = "estimated",
    note: str | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "task_key": task_key,
        "label": label,
        "model": model or "local",
        "estimated_page_count": page_count,
        "estimated_cost_usd": 0.0,
        "basis": "local",
        "status": status,
    }
    if note:
        step["note"] = note
    if page_count <= 0:
        step["basis"] = "not_expected"
        return step
    if not import_estimate_model_is_cloud(model):
        return step

    task_model_rates: dict[tuple[str, str], float] = rates.get("task_model_rates", {})
    task_rates: dict[str, float] = rates.get("task_rates", {})
    exact_rate = task_model_rates.get((task_key, model or ""))
    if exact_rate is not None:
        exemplar_cost = max(0.0, float(exact_rate)) * page_count
        step["basis"] = "task_model_exemplar"
        apply_import_estimate_model_floor(
            step=step,
            task_key=task_key,
            model=model,
            exemplar_cost=exemplar_cost,
            db=db,
        )
        return step
    fallback_rate = task_rates.get(task_key)
    if fallback_rate is not None:
        exemplar_cost = max(0.0, float(fallback_rate)) * page_count
        step["basis"] = "task_exemplar"
        apply_import_estimate_model_floor(
            step=step,
            task_key=task_key,
            model=model,
            exemplar_cost=exemplar_cost,
            db=db,
        )
        return step

    input_tokens, output_tokens = import_estimate_tokens(task_key, page_count)
    priced = estimated_cost_usd_for_model_tokens(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        db=db,
    )
    if priced is not None:
        step["estimated_cost_usd"] = round(priced, 6)
        step["basis"] = "model_pricing"
        step["estimated_input_tokens"] = input_tokens
        step["estimated_output_tokens"] = output_tokens
    else:
        step["basis"] = "unpriced_model"
        step["status"] = "unpriced"
        step["estimated_input_tokens"] = input_tokens
        step["estimated_output_tokens"] = output_tokens
    return step


def import_estimate_processing_steps(
    *,
    preset: dict[str, Any] | None,
    model_preferences: dict[str, str],
    page_count: int,
    rates: dict[str, Any],
    db: Session | None,
) -> list[dict[str, Any]]:
    preset = preset or {}
    cleanup = preset.get("cleanup") if isinstance(preset.get("cleanup"), dict) else {}
    ocr = preset.get("ocr") if isinstance(preset.get("ocr"), dict) else {}
    structured_tables = preset.get("structured_tables") if isinstance(preset.get("structured_tables"), dict) else {}
    bibliography = preset.get("bibliography") if isinstance(preset.get("bibliography"), dict) else {}
    visuals = preset.get("visuals") if isinstance(preset.get("visuals"), dict) else {}
    cost = preset.get("cost") if isinstance(preset.get("cost"), dict) else {}
    second_pass_enabled = bool(preset.get("second_pass_enabled", True))
    steps: list[dict[str, Any]] = [
        {
            "task_key": "raw_text_extraction",
            "label": "Raw text extraction",
            "model": model_preferences.get(MODEL_RAW_TEXT_EXTRACTION, "marker"),
            "estimated_page_count": page_count,
            "estimated_cost_usd": 0.0,
            "basis": "local",
            "status": "local",
            "note": "Marker/PyMuPDF extraction is local in the current pipeline; cloud raw extraction fallbacks are not wired yet.",
        }
    ]

    if second_pass_enabled:
        steps.append(
            {
                "task_key": "document_structure_cleanup",
                "label": "Structure cleanup",
                "model": "local",
                "estimated_page_count": page_count if bool(cleanup.get("enabled", True)) else 0,
                "estimated_cost_usd": 0.0,
                "basis": "local",
                "status": "local" if bool(cleanup.get("enabled", True)) else "disabled_by_preset",
            }
        )
        ocr_enabled = bool(ocr.get("enabled", True))
        steps.append(
            {
                "task_key": "ocr_fallback",
                "label": "OCR fallback",
                "model": str(ocr.get("provider") or "google_vision") if ocr_enabled else "none",
                "estimated_page_count": 0,
                "estimated_cost_usd": 0.0,
                "basis": "pending_provider_integration" if ocr_enabled else "disabled_by_preset",
                "status": "pending_provider_integration" if ocr_enabled else "disabled_by_preset",
                "note": "Low-text OCR is eligibility-audit only until Google Vision execution is wired.",
            }
        )
        cleanup_cloud_enabled = bool(cleanup.get("cloud_escalation", True))
        cleanup_model = str(cleanup.get("model") or model_preferences.get(MODEL_PAGE_TEXT_NORMALIZATION) or "gpt-5.4-mini")
        cleanup_page_count = 0
        if bool(cleanup.get("enabled", True)) and cleanup_cloud_enabled and import_estimate_model_is_cloud(cleanup_model):
            cleanup_page_count = min(page_count, import_processing_cloud_page_cap(preset, page_count))
        steps.append(
            import_estimate_step_cost(
                task_key=MODEL_PAGE_TEXT_NORMALIZATION,
                label="Flagged-page normalization",
                model=cleanup_model if cleanup_page_count else "local",
                page_count=cleanup_page_count,
                rates=rates,
                db=db,
                status="estimated" if cleanup_page_count else "local_or_not_flagged",
                note="Uses the selected preset cleanup model and cap; actual calls only happen for flagged pages.",
            )
        )
        steps.append(
            {
                "task_key": "structured_tables",
                "label": "Structured tables",
                "model": "local",
                "estimated_page_count": page_count if bool(structured_tables.get("enabled", True)) else 0,
                "estimated_cost_usd": 0.0,
                "basis": "evidence_only" if bool(structured_tables.get("enabled", True)) else "disabled_by_preset",
                "status": "evidence_only" if bool(structured_tables.get("enabled", True)) else "disabled_by_preset",
            }
        )
        steps.append(
            {
                "task_key": "visual_asset_extraction",
                "label": "Visual asset extraction",
                "model": "local",
                "estimated_page_count": page_count if bool(visuals.get("enabled", True)) else 0,
                "estimated_cost_usd": 0.0,
                "basis": "local" if bool(visuals.get("enabled", True)) else "disabled_by_preset",
                "status": "local" if bool(visuals.get("enabled", True)) else "disabled_by_preset",
            }
        )
        visual_model = str(visuals.get("model") or "gemini-3.1-flash-lite")
        visual_calls_enabled = (
            bool(visuals.get("context_enabled", True))
            and str(cost.get("visual_model_calls") or "cropped_regions_only") != "none"
            and import_estimate_model_is_cloud(visual_model)
        )
        steps.append(
            {
                "task_key": "visual_asset_context",
                "label": "Visual context",
                "model": visual_model if visual_calls_enabled else "local",
                "estimated_page_count": 0,
                "estimated_cost_usd": 0.0,
                "basis": "pending_cropped_region_model_calls" if visual_calls_enabled else "local",
                "status": "pending_provider_integration" if visual_calls_enabled else "local_or_disabled",
                "note": "Current visual context uses local captions/nearby text; cropped-region visual model calls are not wired yet.",
            }
        )
        steps.append(
            {
                "task_key": "bibliography_extraction",
                "label": "Bibliography extraction",
                "model": "local",
                "estimated_page_count": page_count if bool(bibliography.get("enabled", True)) else 0,
                "estimated_cost_usd": 0.0,
                "basis": "local" if bool(bibliography.get("enabled", True)) else "disabled_by_preset",
                "status": "local" if bool(bibliography.get("enabled", True)) else "disabled_by_preset",
            }
        )

    shared_steps = [
        (MODEL_METADATA, "Metadata extraction", model_preferences.get(MODEL_METADATA)),
        (MODEL_SUMMARY, "Summary", model_preferences.get(MODEL_SUMMARY)),
        (MODEL_APA_CITATION, "APA citation fallback", model_preferences.get(MODEL_APA_CITATION)),
        (MODEL_KEYWORDS_TOPICS, "Tag suggestions", model_preferences.get(MODEL_KEYWORDS_TOPICS)),
        (MODEL_TEXT_CHUNK_ENCODING, "Text chunk encoding", model_preferences.get(MODEL_TEXT_CHUNK_ENCODING)),
    ]
    for task_key, label, model in shared_steps:
        steps.append(
            import_estimate_step_cost(
                task_key=task_key,
                label=label,
                model=model,
                page_count=page_count,
                rates=rates,
                db=db,
            )
        )
    return steps


def estimate_import_job_cost(
    job: ImportJob,
    *,
    model_preferences: dict[str, str],
    rates: dict[str, Any],
    db: Session | None = None,
) -> dict[str, Any]:
    page_count = document_estimated_page_count(job.document)
    if not page_count or page_count <= 0:
        page_count = 1
    preset = document_import_processing_preset(job.document, job.batch)
    steps = import_estimate_processing_steps(
        preset=preset,
        model_preferences=model_preferences,
        page_count=page_count,
        rates=rates,
        db=db,
    )
    priced_steps = [step for step in steps if float(step.get("estimated_cost_usd") or 0) > 0]
    uncalibrated_amount = round(sum(float(step.get("estimated_cost_usd") or 0) for step in priced_steps), 6)
    cloud_call_floor = import_estimate_cloud_call_floor(steps, db)
    if uncalibrated_amount > 0:
        exact_rate_count = sum(1 for step in priced_steps if step.get("basis") == "task_model_exemplar")
        fallback_rate_count = sum(1 for step in priced_steps if step.get("basis") == "task_exemplar")
        priced_count = sum(1 for step in priced_steps if step.get("basis") == "model_pricing")
        if exact_rate_count and not fallback_rate_count and not priced_count:
            basis = "preset_task_model_exemplar"
        elif exact_rate_count or fallback_rate_count or priced_count:
            basis = "preset_steps"
        else:
            basis = "preset_steps"
        amount, basis = apply_import_estimate_calibration(uncalibrated_amount, basis, rates)
        if cloud_call_floor > amount:
            amount = cloud_call_floor
            basis = f"{basis}_model_floor"
        return {
            "estimated_cost_usd": amount,
            "basis": basis,
            "estimated_page_count": page_count,
            "uncalibrated_cost_usd": uncalibrated_amount,
            "minimum_cloud_call_cost_usd": cloud_call_floor,
            "steps": steps,
            "processing_preset": (
                {
                    "id": preset.get("id"),
                    "name": preset.get("name"),
                    "mode": preset.get("mode"),
                    "second_pass_enabled": preset.get("second_pass_enabled", True),
                }
                if preset
                else None
            ),
        }

    overall_rate = float(rates.get("overall_rate") or 0.0)
    if overall_rate > 0:
        amount, basis = apply_import_estimate_calibration(round(overall_rate * page_count, 6), "library_exemplar", rates)
        if cloud_call_floor > amount:
            amount = cloud_call_floor
            basis = f"{basis}_model_floor"
        return {
            "estimated_cost_usd": amount,
            "basis": basis,
            "estimated_page_count": page_count,
            "uncalibrated_cost_usd": round(overall_rate * page_count, 6),
            "minimum_cloud_call_cost_usd": cloud_call_floor,
            "steps": steps,
            "processing_preset": None,
        }
    amount, basis = apply_import_estimate_calibration(round(DEFAULT_IMPORT_ESTIMATE_USD_PER_PAGE * page_count, 6), "default", rates)
    if cloud_call_floor > amount:
        amount = cloud_call_floor
        basis = f"{basis}_model_floor"
    return {
        "estimated_cost_usd": amount,
        "basis": basis,
        "estimated_page_count": page_count,
        "uncalibrated_cost_usd": round(DEFAULT_IMPORT_ESTIMATE_USD_PER_PAGE * page_count, 6),
        "minimum_cloud_call_cost_usd": cloud_call_floor,
        "steps": steps,
        "processing_preset": None,
    }


def estimate_import_job_cost_usd(
    job: ImportJob,
    *,
    model_preferences: dict[str, str],
    rates: dict[str, Any],
    db: Session | None = None,
) -> tuple[float, str, int | None]:
    estimate = estimate_import_job_cost(job, model_preferences=model_preferences, rates=rates, db=db)
    amount = float(estimate.get("estimated_cost_usd") or 0.0)
    basis = str(estimate.get("basis") or "none")
    page_count = estimate.get("estimated_page_count")
    if not isinstance(page_count, int):
        page_count = None
    return amount, basis, page_count


def import_job_sort_key(job: ImportJob) -> tuple[int, float, str]:
    priority = IMPORT_JOB_STATUS_PRIORITY.get(job.status, 7)
    if job.status in {"running", "queued", "staged", "restored_paused"}:
        timestamp = job.created_at or job.updated_at or utc_now()
        return (priority, timestamp.timestamp(), job.id)
    timestamp = job.updated_at or job.created_at or utc_now()
    return (priority, -timestamp.timestamp(), job.id)


def dedupe_import_jobs(*groups: list[ImportJob]) -> list[ImportJob]:
    by_id: dict[str, ImportJob] = {}
    for group in groups:
        for job in group:
            by_id[job.id] = job
    return sorted(by_id.values(), key=import_job_sort_key)


def import_job_step_model(current_step: str, model_preferences: dict[str, str]) -> str | None:
    step = current_step or "stored"
    if step == STAGED_IMPORT_STATUS:
        return None
    if step in {"stored", "extracting"}:
        return model_preferences.get(MODEL_RAW_TEXT_EXTRACTION)
    if step == "normalizing_pages" or step.startswith("normalizing_page_"):
        return model_preferences.get(MODEL_PAGE_TEXT_NORMALIZATION)
    if step in {
        "cleaning_structure",
        "extracting_bibliography",
        "extracted",
        "extracting_figures",
        "figures",
        "cleaning_cache",
        "duplicate_skipped",
    }:
        return "local"
    if step in {"enriching", "enriched"}:
        models = [
            model_preferences.get(MODEL_METADATA),
            model_preferences.get(MODEL_SUMMARY),
            model_preferences.get(MODEL_APA_CITATION),
            model_preferences.get(MODEL_KEYWORDS_TOPICS),
        ]
        unique_models = [model for index, model in enumerate(models) if model and model not in models[:index]]
        return " + ".join(unique_models) if unique_models else None
    if step in {"indexing", "indexed"}:
        return model_preferences.get(MODEL_TEXT_CHUNK_ENCODING)
    return None


def import_job_event_value(job: ImportJob, key: str, event_type: str | None = None) -> str | None:
    events = sorted(job.events or [], key=lambda event: event.created_at, reverse=True)
    for event in events:
        if event_type and event.event_type != event_type:
            continue
        value = (event.payload or {}).get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def import_job_event_message(job: ImportJob, event_type: str | None = None) -> str | None:
    events = sorted(job.events or [], key=lambda event: event.created_at, reverse=True)
    for event in events:
        if event_type and event.event_type != event_type:
            continue
        if event.message and event.message.strip():
            return event.message.strip()
    return None


def active_slipstream_leases_by_job(db: Session, job_type: str, job_ids: list[str]) -> dict[str, SlipstreamLease]:
    if not job_ids:
        return {}
    leases = (
        db.query(SlipstreamLease)
        .options(joinedload(SlipstreamLease.client))
        .filter(
            SlipstreamLease.job_type == job_type,
            SlipstreamLease.job_id.in_(job_ids),
            SlipstreamLease.status == "active",
        )
        .all()
    )
    return {lease.job_id: lease for lease in leases}


def lease_assignment_payload(lease: SlipstreamLease | None) -> dict[str, Any]:
    if not lease:
        return {
            "assigned_worker_kind": None,
            "assigned_client_id": None,
            "assigned_client_name": None,
            "lease_heartbeat_at": None,
            "lease_expires_at": None,
        }
    return {
        "assigned_worker_kind": lease.worker_kind,
        "assigned_client_id": lease.client_id,
        "assigned_client_name": lease.client.name if lease.client else None,
        "lease_heartbeat_at": lease.heartbeat_at,
        "lease_expires_at": lease.expires_at,
    }


def import_job_out(
    job: ImportJob,
    *,
    model_preferences: dict[str, str] | None = None,
    estimated_cost_usd: float = 0.0,
    cost_estimate: tuple[float, str, int | None] | None = None,
    lease: SlipstreamLease | None = None,
) -> dict[str, Any]:
    model_preferences = model_preferences or {}
    projected_cost, estimate_basis, estimate_page_count = cost_estimate or (0.0, "none", document_estimated_page_count(job.document))
    persisted_estimate = document_persisted_cost_estimate(job.document)
    if persisted_estimate and job.status in {STAGED_IMPORT_STATUS, "queued"}:
        projected_cost, estimate_basis, estimate_page_count = persisted_estimate
    actual_cost = round(estimated_cost_usd, 6)
    display_cost = actual_cost
    display_basis = "actual" if actual_cost > 0 else "none"
    if actual_cost <= 0 and job.status in {STAGED_IMPORT_STATUS, "queued"}:
        display_cost = projected_cost
        display_basis = estimate_basis
    event_title = import_job_event_value(job, "title", job.current_step) or import_job_event_value(job, "title")
    event_error = import_job_event_message(job, job.current_step) or import_job_event_message(job)
    processing_preset = document_import_processing_preset(job.document, job.batch)
    last_error = job.last_error
    if job.status == "failed" and not job.document_id and job.current_step == "download_failed":
        last_error = event_error or job.last_error
    return {
        "id": job.id,
        "batch_id": job.batch_id,
        "document_id": job.document_id,
        "document_title": job.document.title if job.document else event_title,
        "original_filename": job.document.original_filename if job.document else None,
        "file_size_bytes": import_job_file_size(job.document),
        "document_page_count": document_estimated_page_count(job.document),
        "status": job.status,
        "current_step": job.current_step,
        "current_model": import_job_step_model(job.current_step, model_preferences),
        "estimated_cost_usd": round(display_cost, 6),
        "estimated_cost_basis": display_basis,
        "estimated_cost_page_count": estimate_page_count,
        "processing_preset_id": processing_preset.get("id") if processing_preset else None,
        "processing_preset_name": processing_preset.get("name") if processing_preset else None,
        "processing_preset_mode": processing_preset.get("mode") if processing_preset else None,
        "attempts": job.attempts,
        "last_error": last_error or (event_error if job.status == "failed" else None),
        "locked_at": job.locked_at,
        **lease_assignment_payload(lease),
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def concordance_job_out(job: ConcordanceJob, *, lease: SlipstreamLease | None = None) -> dict[str, Any]:
    return {
        "id": job.id,
        "run_id": job.run_id,
        "document_id": job.document_id,
        "capability_key": job.capability_key,
        "target_version": job.target_version,
        "status": job.status,
        "attempts": job.attempts,
        "last_error": job.last_error,
        "locked_at": job.locked_at,
        **lease_assignment_payload(lease),
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def staged_import_cache_path(document: Document | None) -> Path | None:
    if not document:
        return None
    evidence = document.metadata_evidence or {}
    for key in ("document_cache_path", "local_cache_path"):
        raw_path = evidence.get(key)
        if isinstance(raw_path, str) and raw_path.strip():
            return Path(raw_path)
    return None


def repair_missing_staged_page_estimates(
    db: Session,
    jobs: list[ImportJob],
    *,
    model_preferences: dict[str, str],
    estimate_rates: dict[str, Any],
) -> None:
    repaired = False
    for job in jobs:
        if job.status not in {STAGED_IMPORT_STATUS, "queued"} or not job.document:
            continue
        document = job.document
        if document.page_count and document.page_count > 0:
            continue
        cache_path = staged_import_cache_path(document)
        if not cache_path or not cache_path.exists():
            continue
        try:
            page_count = estimate_pdf_page_count(cache_path.read_bytes())
        except OSError:
            continue
        if not page_count or page_count <= 0:
            continue

        document.page_count = page_count
        evidence = dict(document.metadata_evidence or {})
        source_import = dict(evidence.get("source_import") or {})
        source_import["estimated_page_count"] = page_count
        evidence["source_import"] = source_import
        cost_estimate = estimate_import_job_cost(
            job,
            model_preferences=model_preferences,
            rates=estimate_rates,
            db=db,
        )
        estimated_cost_usd = float(cost_estimate.get("estimated_cost_usd") or 0.0)
        estimate_basis = str(cost_estimate.get("basis") or "none")
        upload_estimate = dict(evidence.get("upload_cost_estimate") or {})
        upload_estimate.update(
            {
                "estimated_cost_usd": estimated_cost_usd,
                "estimated_page_count": page_count,
                "basis": estimate_basis,
                "uncalibrated_cost_usd": cost_estimate.get("uncalibrated_cost_usd"),
                "minimum_cloud_call_cost_usd": cost_estimate.get("minimum_cloud_call_cost_usd"),
                "step_estimates": cost_estimate.get("steps", []),
                "calibration_factor": estimate_rates.get("estimate_calibration_factor"),
                "calibration_sample_count": estimate_rates.get("estimate_calibration_sample_count"),
                "model_preferences": model_preferences,
                "repaired_page_count_at": utc_now().isoformat(),
            }
        )
        evidence["upload_cost_estimate"] = upload_estimate
        document.metadata_evidence = evidence
        record_import_cost_estimate(
            db,
            document=document,
            job=job,
            estimated_cost_usd=estimated_cost_usd,
            estimate_basis=estimate_basis,
            estimated_page_count=page_count,
            model_preferences=model_preferences,
            metadata={
                "repaired_page_count": True,
                "calibration_factor": estimate_rates.get("estimate_calibration_factor"),
                "calibration_sample_count": estimate_rates.get("estimate_calibration_sample_count"),
                "uncalibrated_cost_usd": cost_estimate.get("uncalibrated_cost_usd"),
                "minimum_cloud_call_cost_usd": cost_estimate.get("minimum_cloud_call_cost_usd"),
                "step_estimates": cost_estimate.get("steps", []),
            },
        )
        repaired = True
    if repaired:
        db.commit()


@app.get("/api/imports/jobs", response_model=list[ImportJobOut])
def list_import_jobs(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[dict[str, Any]]:
    query = db.query(ImportJob).options(joinedload(ImportJob.document), selectinload(ImportJob.events))
    queue_jobs = (
        query.filter(ImportJob.status.in_(IMPORT_JOB_QUEUE_STATUSES))
        .order_by(ImportJob.created_at.asc(), ImportJob.id.asc())
        .all()
    )
    recent_jobs = (
        db.query(ImportJob)
        .options(joinedload(ImportJob.document), selectinload(ImportJob.events))
        .order_by(ImportJob.created_at.desc())
        .limit(100)
        .all()
    )
    jobs = dedupe_import_jobs(queue_jobs, recent_jobs)
    model_preferences = get_analysis_models(db)
    estimate_rates = import_cost_exemplar_rates(db)
    repair_missing_staged_page_estimates(
        db,
        jobs,
        model_preferences=model_preferences,
        estimate_rates=estimate_rates,
    )
    costs = import_job_costs_usd(db, [job.id for job in jobs])
    leases = active_slipstream_leases_by_job(db, "import", [job.id for job in jobs])
    return [
        import_job_out(
            job,
            model_preferences=model_preferences,
            estimated_cost_usd=costs.get(job.id, 0.0),
            cost_estimate=estimate_import_job_cost_usd(job, model_preferences=model_preferences, rates=estimate_rates, db=db),
            lease=leases.get(job.id),
        )
        for job in jobs
    ]


def import_job_previous_state(job: ImportJob) -> dict[str, Any]:
    return {
        "status": job.status,
        "current_step": job.current_step,
        "attempts": job.attempts,
        "locked_at": job.locked_at.isoformat() if job.locked_at else None,
        "last_error": job.last_error,
    }


def requeue_import_job(db: Session, job: ImportJob, *, event_type: str = "manual_import_rescue") -> None:
    previous = import_job_previous_state(job)
    job.status = "queued"
    job.locked_at = None
    job.last_error = None
    if job.document:
        job.document.processing_status = "queued"
    if job.batch:
        refresh_import_batch_progress(db, job.batch)
    db.add(
        ProcessingEvent(
            import_job_id=job.id,
            document_id=job.document_id,
            event_type=event_type,
            message="Import job was manually requeued.",
            payload={"previous": previous},
        )
    )


def stage_import_job_for_processing(db: Session, job: ImportJob) -> None:
    previous = import_job_previous_state(job)
    job.status = "queued"
    job.current_step = "stored"
    job.locked_at = None
    job.last_error = None
    if job.document:
        job.document.processing_status = "queued"
        evidence = dict(job.document.metadata_evidence or {})
        estimate = dict(evidence.get("upload_cost_estimate") or {})
        estimate["queued_at"] = utc_now().isoformat()
        evidence["upload_cost_estimate"] = estimate
        job.document.metadata_evidence = evidence
    if job.batch:
        refresh_import_batch_progress(db, job.batch)
    db.add(
        ProcessingEvent(
            import_job_id=job.id,
            document_id=job.document_id,
            event_type="manual_import_process_uploads",
            message="Staged upload was released for import processing.",
            payload={"previous": previous},
        )
    )


def clear_import_job(
    db: Session,
    job: ImportJob,
    *,
    event_type: str = "manual_import_clear",
    message: str = "Import job was cleared from the queue.",
) -> None:
    previous = import_job_previous_state(job)
    job.status = "cleared"
    job.current_step = "cleared"
    job.locked_at = None
    if job.document and job.document.processing_status != "ready":
        job.document.processing_status = "cleared"
    if job.batch:
        refresh_import_batch_progress(db, job.batch)
    db.add(
        ProcessingEvent(
            import_job_id=job.id,
            document_id=job.document_id,
            event_type=event_type,
            message=message,
            payload={"previous": previous},
        )
    )


def delete_staged_document_cache(document: Document) -> int:
    cache_path = metadata_cache_path(document, require_managed=True)
    if not cache_path:
        return 0
    try:
        cache_path.unlink()
        return 1
    except OSError:
        return 0


def delete_staged_original(document: Document) -> int:
    if not document.gcs_uri:
        return 0
    try:
        return 1 if get_storage_service().delete_uri(document.gcs_uri) else 0
    except Exception:
        return 0


def import_cache_document_ids(db: Session) -> set[str]:
    active_document_ids = {
        row[0]
        for row in db.query(ImportJob.document_id)
        .filter(ImportJob.document_id.isnot(None), ImportJob.status.in_(IMPORT_JOB_QUEUE_STATUSES))
        .all()
        if row[0]
    }
    terminal_document_ids = {
        row[0]
        for row in db.query(ImportJob.document_id)
        .filter(ImportJob.document_id.isnot(None), ImportJob.status.in_(IMPORT_CACHE_TERMINAL_JOB_STATUSES))
        .all()
        if row[0]
    }
    candidate_ids = terminal_document_ids - active_document_ids
    if not candidate_ids:
        return set()
    return {
        row[0]
        for row in db.query(Document.id)
        .filter(
            Document.id.in_(candidate_ids),
            Document.processing_status.notin_(LIBRARY_VISIBLE_DOCUMENT_STATUSES),
        )
        .all()
    }


def terminal_orphan_import_jobs(db: Session) -> list[ImportJob]:
    return (
        db.query(ImportJob)
        .options(joinedload(ImportJob.batch))
        .filter(ImportJob.document_id.is_(None), ImportJob.status.in_(IMPORT_CACHE_TERMINAL_JOB_STATUSES))
        .all()
    )


def database_maintenance_status_out(db: Session) -> DatabaseMaintenanceStatusOut:
    document_ids = import_cache_document_ids(db)
    hidden_project_item_count = (
        db.query(ProjectItem).filter(ProjectItem.document_id.in_(document_ids)).count()
        if document_ids
        else 0
    )
    terminal_import_job_count = (
        db.query(ImportJob).filter(ImportJob.document_id.in_(document_ids)).count()
        if document_ids
        else 0
    )
    orphan_import_job_count = len(terminal_orphan_import_jobs(db))
    document_hash_missing_count = (
        db.query(Document)
        .filter(
            Document.deleted_at.is_(None),
            Document.processing_status.in_(IMPORT_DUPLICATE_DOCUMENT_STATUSES),
            Document.checksum_md5.is_(None),
        )
        .count()
    )
    return DatabaseMaintenanceStatusOut(
        import_cache_count=len(document_ids),
        document_hash_missing_count=document_hash_missing_count,
        hidden_project_item_count=hidden_project_item_count,
        terminal_import_job_count=terminal_import_job_count,
        orphan_import_job_count=orphan_import_job_count,
        database_size_bytes=current_database_size_bytes(db),
        **database_maintenance_state_payload(),
    )


def database_maintenance_state_payload() -> dict[str, Any]:
    with DATABASE_MAINTENANCE_LOCK:
        state = dict(DATABASE_MAINTENANCE_STATE)
    active_operation = state.get("active_operation")
    active_started_at = state.get("active_operation_started_at")
    elapsed = None
    if isinstance(active_started_at, datetime):
        elapsed = max(0.0, (utc_now() - active_started_at).total_seconds())
    return {
        "active_operation": active_operation,
        "active_operation_label": DATABASE_MAINTENANCE_LABELS.get(active_operation) if active_operation else None,
        "active_operation_started_at": active_started_at,
        "active_operation_elapsed_seconds": elapsed,
        "active_operation_status_detail": state.get("active_operation_status_detail"),
        "last_operation": state.get("last_operation"),
        "last_operation_status": state.get("last_operation_status"),
        "last_operation_completed_at": state.get("last_operation_completed_at"),
        "last_operation_status_detail": state.get("last_operation_status_detail"),
        "last_operation_error": state.get("last_operation_error"),
        "last_operation_database_size_before_bytes": state.get("last_operation_database_size_before_bytes"),
        "last_operation_database_size_after_bytes": state.get("last_operation_database_size_after_bytes"),
    }


def _set_database_maintenance_active(operation: str, *, database_size_before: int | None) -> None:
    with DATABASE_MAINTENANCE_LOCK:
        active_operation = DATABASE_MAINTENANCE_STATE.get("active_operation")
        if active_operation:
            label = DATABASE_MAINTENANCE_LABELS.get(active_operation, active_operation.replace("_", " "))
            raise ValueError(f"{label} is already running.")
        DATABASE_MAINTENANCE_STATE.update(
            {
                "active_operation": operation,
                "active_operation_started_at": utc_now(),
                "active_operation_status_detail": DATABASE_MAINTENANCE_DETAILS.get(operation, "Database maintenance is running."),
                "last_operation": None,
                "last_operation_status": None,
                "last_operation_completed_at": None,
                "last_operation_status_detail": None,
                "last_operation_error": None,
                "last_operation_database_size_before_bytes": database_size_before,
                "last_operation_database_size_after_bytes": None,
            }
        )
    mark_database_maintenance_active(
        operation,
        DATABASE_MAINTENANCE_DETAILS.get(operation, "Database maintenance is running."),
    )


def _update_database_maintenance_detail(detail: str) -> None:
    with DATABASE_MAINTENANCE_LOCK:
        if DATABASE_MAINTENANCE_STATE.get("active_operation"):
            DATABASE_MAINTENANCE_STATE["active_operation_status_detail"] = detail


def _finish_database_maintenance(
    operation: str,
    *,
    status: str,
    detail: str,
    database_size_after: int | None = None,
    error: str | None = None,
) -> None:
    with DATABASE_MAINTENANCE_LOCK:
        DATABASE_MAINTENANCE_STATE.update(
            {
                "active_operation": None,
                "active_operation_started_at": None,
                "active_operation_status_detail": None,
                "last_operation": operation,
                "last_operation_status": status,
                "last_operation_completed_at": utc_now(),
                "last_operation_status_detail": detail,
                "last_operation_error": error,
                "last_operation_database_size_after_bytes": database_size_after,
            }
        )
    mark_database_maintenance_finished(operation, status=status, detail=detail, error=error)


def _execute_document_md5_backfill() -> None:
    operation = "backfill_document_md5"
    processed = 0
    updated = 0
    failed = 0
    try:
        with session_scope() as db:
            documents = (
                db.query(Document)
                .filter(
                    Document.deleted_at.is_(None),
                    Document.processing_status.in_(IMPORT_DUPLICATE_DOCUMENT_STATUSES),
                )
                .order_by(Document.created_at.asc(), Document.id.asc())
                .all()
            )
            total = len(documents)
            for document in documents:
                processed += 1
                if document.checksum_md5:
                    if processed % 10 == 0 or processed == total:
                        _update_database_maintenance_detail(f"Hashing documents: {processed}/{total} checked, {updated} updated.")
                    continue
                data = ensure_document_pdf_bytes(db, document, source="md5_backfill")
                if not data:
                    failed += 1
                    _update_database_maintenance_detail(
                        f"Hashing documents: {processed}/{total} checked, {updated} updated, {failed} unavailable."
                    )
                    continue
                checksum_md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
                document.checksum_md5 = checksum_md5
                evidence = dict(document.metadata_evidence or {})
                hashes = dict(evidence.get("hashes") or {})
                hashes["stored_md5"] = checksum_md5
                hashes.setdefault("stored_sha256", document.checksum_sha256)
                hashes["backfilled_at"] = utc_now().isoformat()
                evidence["hashes"] = hashes
                document.metadata_evidence = evidence
                updated += 1
                if processed % 10 == 0 or processed == total:
                    db.commit()
                    _update_database_maintenance_detail(
                        f"Hashing documents: {processed}/{total} checked, {updated} updated, {failed} unavailable."
                    )
            db.commit()
        with session_scope() as db:
            database_size_after = current_database_size_bytes(db)
        _finish_database_maintenance(
            operation,
            status="complete",
            detail=f"Document hash backfill complete: {updated} updated, {failed} unavailable.",
            database_size_after=database_size_after,
        )
    except Exception as exc:
        _finish_database_maintenance(operation, status="failed", detail="Document hash backfill failed.", error=str(exc))


def _execute_database_sql_maintenance(operation: str, *, postgres_sql: str, sqlite_sql: str) -> None:
    sql = postgres_sql if is_postgres() else sqlite_sql
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(sql))
        with session_scope() as db:
            database_size_after = current_database_size_bytes(db)
        _finish_database_maintenance(
            operation,
            status="complete",
            detail=f"{DATABASE_MAINTENANCE_LABELS.get(operation, operation.replace('_', ' ').title())} complete.",
            database_size_after=database_size_after,
        )
    except Exception as exc:
        _finish_database_maintenance(
            operation,
            status="failed",
            detail=f"{DATABASE_MAINTENANCE_LABELS.get(operation, operation.replace('_', ' ').title())} failed.",
            error=str(exc),
        )


def run_database_sql_maintenance(db: Session, *, operation: str, postgres_sql: str, sqlite_sql: str) -> DatabaseMaintenanceResultOut:
    db.commit()
    database_size_before = current_database_size_bytes(db)
    _set_database_maintenance_active(operation, database_size_before=database_size_before)
    thread = threading.Thread(
        target=_execute_database_sql_maintenance,
        kwargs={"operation": operation, "postgres_sql": postgres_sql, "sqlite_sql": sqlite_sql},
        daemon=True,
        name=f"medusa-{operation}",
    )
    thread.start()
    status = database_maintenance_status_out(db)
    return DatabaseMaintenanceResultOut(
        **status.model_dump(),
        operation=operation,
        status="running",
        message=f"{DATABASE_MAINTENANCE_LABELS.get(operation, operation.replace('_', ' ').title())} started.",
        database_size_before_bytes=database_size_before,
        database_size_after_bytes=None,
    )


def run_document_md5_backfill(db: Session) -> DatabaseMaintenanceResultOut:
    db.commit()
    database_size_before = current_database_size_bytes(db)
    _set_database_maintenance_active("backfill_document_md5", database_size_before=database_size_before)
    thread = threading.Thread(
        target=_execute_document_md5_backfill,
        daemon=True,
        name="medusa-backfill-document-md5",
    )
    thread.start()
    status = database_maintenance_status_out(db)
    return DatabaseMaintenanceResultOut(
        **status.model_dump(),
        operation="backfill_document_md5",
        status="running",
        message="Document hash backfill started.",
        database_size_before_bytes=database_size_before,
        database_size_after_bytes=None,
    )


def clear_hidden_import_cache(db: Session) -> DatabaseMaintenanceResultOut:
    status_before = database_maintenance_status_out(db)
    document_ids = import_cache_document_ids(db)
    if not document_ids and status_before.orphan_import_job_count == 0:
        return DatabaseMaintenanceResultOut(
            **status_before.model_dump(),
            operation="clear_import_cache",
            message="No hidden import cache rows to clear.",
        )

    documents = (
        db.query(Document)
        .filter(Document.id.in_(document_ids))
        .all()
        if document_ids
        else []
    )
    import_jobs = (
        db.query(ImportJob)
        .options(joinedload(ImportJob.batch))
        .filter(ImportJob.document_id.in_(document_ids))
        .all()
        if document_ids
        else []
    )
    orphan_jobs = terminal_orphan_import_jobs(db)
    batch_ids = {job.batch_id for job in [*import_jobs, *orphan_jobs] if job.batch_id}

    deleted_cache_files = 0
    deleted_original_objects = 0
    for document in documents:
        deleted_cache_files += delete_staged_document_cache(document)
        deleted_original_objects += delete_staged_original(document)

    removed_project_items = (
        db.query(ProjectItem).filter(ProjectItem.document_id.in_(document_ids)).delete(synchronize_session=False)
        if document_ids
        else 0
    )
    if document_ids:
        for document in documents:
            document.domains.clear()
            document.tags.clear()
        db.query(DocumentTagAssessment).filter(DocumentTagAssessment.document_id.in_(document_ids)).delete(synchronize_session=False)
        db.query(CitationCandidate).filter(CitationCandidate.document_id.in_(document_ids)).delete(synchronize_session=False)
        db.query(ProcessingEvent).filter(ProcessingEvent.document_id.in_(document_ids)).delete(synchronize_session=False)
        db.query(OpenAIUsageRecord).filter(OpenAIUsageRecord.document_id.in_(document_ids)).update(
            {"document_id": None},
            synchronize_session=False,
        )
        db.query(DoiStash).filter(DoiStash.source_document_id.in_(document_ids)).update(
            {"source_document_id": None},
            synchronize_session=False,
        )
        db.query(DoiStash).filter(DoiStash.imported_document_id.in_(document_ids)).update(
            {"imported_document_id": None},
            synchronize_session=False,
        )
        db.query(DocumentRecommendation).filter(DocumentRecommendation.source_document_id.in_(document_ids)).delete(
            synchronize_session=False,
        )
        db.query(DocumentRecommendation).filter(DocumentRecommendation.existing_document_id.in_(document_ids)).update(
            {"existing_document_id": None},
            synchronize_session=False,
        )
        db.query(DocumentRecommendation).filter(DocumentRecommendation.imported_document_id.in_(document_ids)).update(
            {"imported_document_id": None},
            synchronize_session=False,
        )
        db.query(Note).filter(Note.document_id.in_(document_ids)).update({"document_id": None}, synchronize_session=False)

    removed_import_jobs = len(import_jobs)
    removed_orphan_import_jobs = len(orphan_jobs)
    for job in [*import_jobs, *orphan_jobs]:
        db.delete(job)
    for document in documents:
        db.delete(document)

    refresh_or_delete_import_batches(db, batch_ids)
    db.commit()
    status_after = database_maintenance_status_out(db)
    return DatabaseMaintenanceResultOut(
        **status_after.model_dump(),
        operation="clear_import_cache",
        message=f"Cleared {len(documents)} hidden import cache {('item' if len(documents) == 1 else 'items')}.",
        removed_import_documents=len(documents),
        removed_project_items=removed_project_items,
        removed_import_jobs=removed_import_jobs,
        removed_orphan_import_jobs=removed_orphan_import_jobs,
        deleted_cache_files=deleted_cache_files,
        deleted_original_objects=deleted_original_objects,
    )


def staged_document_has_other_import_history(db: Session, job: ImportJob, document: Document) -> bool:
    return (
        db.query(ImportJob)
        .filter(
            ImportJob.document_id == document.id,
            ImportJob.id != job.id,
        )
        .count()
        > 0
    )


def hard_delete_staged_import_job(db: Session, job: ImportJob) -> tuple[int, int, int]:
    document = job.document
    if not document or staged_document_has_other_import_history(db, job, document):
        clear_import_job(
            db,
            job,
            event_type="manual_staged_import_clear",
            message="Staged upload was cleared without deleting a shared document record.",
        )
        return (0, 0, 0)

    deleted_cache_files = delete_staged_document_cache(document)
    deleted_original_objects = delete_staged_original(document)
    document.domains.clear()
    document.tags.clear()
    db.query(ProjectItem).filter(ProjectItem.document_id == document.id).delete(synchronize_session=False)
    db.delete(job)
    db.delete(document)
    return (1, deleted_cache_files, deleted_original_objects)


def refresh_or_delete_import_batches(db: Session, batch_ids: set[str]) -> None:
    db.flush()
    for batch_id in batch_ids:
        batch = db.get(ImportBatch, batch_id)
        if not batch:
            continue
        remaining_jobs = db.query(ImportJob).filter(ImportJob.batch_id == batch.id).count()
        if remaining_jobs == 0:
            db.delete(batch)
            continue
        batch.total_files = remaining_jobs
        refresh_import_batch_progress(db, batch)


@app.post("/api/imports/jobs/process-staged", response_model=ImportQueueActionOut)
def process_staged_import_jobs(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ImportQueueActionOut:
    jobs = (
        db.query(ImportJob)
        .options(joinedload(ImportJob.document), joinedload(ImportJob.batch))
        .filter(ImportJob.status == STAGED_IMPORT_STATUS)
        .order_by(ImportJob.created_at.asc())
        .all()
    )
    for job in jobs:
        stage_import_job_for_processing(db, job)
    db.commit()
    return ImportQueueActionOut(matched_count=len(jobs), updated_count=len(jobs))


@app.post("/api/imports/jobs/clear-staged", response_model=ImportQueueActionOut)
def clear_staged_import_jobs(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ImportQueueActionOut:
    jobs = (
        db.query(ImportJob)
        .options(joinedload(ImportJob.document), joinedload(ImportJob.batch))
        .filter(ImportJob.status == STAGED_IMPORT_STATUS)
        .order_by(ImportJob.created_at.asc())
        .all()
    )
    batch_ids = {job.batch_id for job in jobs if job.batch_id}
    deleted_documents = 0
    deleted_cache_files = 0
    deleted_original_objects = 0
    for job in jobs:
        document_count, cache_count, original_count = hard_delete_staged_import_job(db, job)
        deleted_documents += document_count
        deleted_cache_files += cache_count
        deleted_original_objects += original_count
    refresh_or_delete_import_batches(db, batch_ids)
    db.commit()
    return ImportQueueActionOut(
        matched_count=len(jobs),
        updated_count=len(jobs),
        deleted_documents=deleted_documents,
        deleted_cache_files=deleted_cache_files,
        deleted_original_objects=deleted_original_objects,
    )


@app.post("/api/imports/jobs/retry-failed", response_model=ImportQueueActionOut)
def retry_failed_import_jobs(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ImportQueueActionOut:
    jobs = (
        db.query(ImportJob)
        .options(joinedload(ImportJob.document), joinedload(ImportJob.batch))
        .filter(ImportJob.status == "failed")
        .order_by(ImportJob.created_at.asc())
        .all()
    )
    updated_count = 0
    skipped_unretryable_count = 0
    for job in jobs:
        if not job.document_id:
            skipped_unretryable_count += 1
            continue
        requeue_import_job(db, job, event_type="manual_import_retry_failed")
        updated_count += 1
    db.commit()
    return ImportQueueActionOut(
        matched_count=len(jobs),
        updated_count=updated_count,
        skipped_unretryable_count=skipped_unretryable_count,
    )


@app.post("/api/imports/jobs/clear", response_model=ImportQueueActionOut)
def clear_import_queue(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ImportQueueActionOut:
    jobs = (
        db.query(ImportJob)
        .options(joinedload(ImportJob.document), joinedload(ImportJob.batch))
        .filter(ImportJob.status.in_(IMPORT_JOB_CLEARABLE_STATUSES))
        .order_by(ImportJob.created_at.asc())
        .all()
    )
    updated_count = 0
    skipped_running_count = 0
    for job in jobs:
        if job.status == "running":
            skipped_running_count += 1
            continue
        clear_import_job(db, job)
        updated_count += 1
    db.commit()
    return ImportQueueActionOut(
        matched_count=len(jobs),
        updated_count=updated_count,
        skipped_running_count=skipped_running_count,
    )


@app.post("/api/imports/jobs/clear-failed", response_model=ImportQueueActionOut)
def clear_failed_import_jobs(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ImportQueueActionOut:
    jobs = (
        db.query(ImportJob)
        .options(joinedload(ImportJob.document), joinedload(ImportJob.batch))
        .filter(ImportJob.status == "failed")
        .order_by(ImportJob.created_at.asc())
        .all()
    )
    for job in jobs:
        clear_import_job(db, job)
    db.commit()
    return ImportQueueActionOut(matched_count=len(jobs), updated_count=len(jobs))


@app.post("/api/imports/jobs/{job_id}/cancel", response_model=ImportJobOut)
def cancel_import_job(
    job_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    job = (
        db.query(ImportJob)
        .options(joinedload(ImportJob.document), joinedload(ImportJob.batch), selectinload(ImportJob.events))
        .filter(ImportJob.id == job_id)
        .one_or_none()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Running imports cannot be canceled while the worker lock is active.")
    if job.status not in {STAGED_IMPORT_STATUS, "queued", "failed", "restored_paused"}:
        raise HTTPException(status_code=400, detail="Only staged, queued, failed, or restored imports can be canceled.")

    clear_import_job(db, job, event_type="manual_import_cancel", message="Import job was canceled.")
    db.commit()
    db.refresh(job)
    model_preferences = get_analysis_models(db)
    costs = import_job_costs_usd(db, [job.id])
    return import_job_out(job, model_preferences=model_preferences, estimated_cost_usd=costs.get(job.id, 0.0))


@app.post("/api/imports/jobs/{job_id}/rescue", response_model=ImportJobOut)
def rescue_import_job(
    job_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    job = db.query(ImportJob).options(joinedload(ImportJob.document)).filter(ImportJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    if job.status == "complete":
        raise HTTPException(status_code=400, detail="Completed import jobs do not need rescue.")
    if not job.document_id:
        raise HTTPException(status_code=400, detail="This queue row has no document record to reprocess. Retry from Related instead.")

    marker = job.locked_at or job.updated_at
    stale_cutoff = utc_now() - timedelta(seconds=max(1, settings.worker_stale_job_seconds))
    if job.status == "running" and marker and marker > stale_cutoff:
        raise HTTPException(
            status_code=409,
            detail="This import still has an active worker lock. Restart the app or wait for the stale-lock window before rescuing it.",
        )

    requeue_import_job(db, job)
    db.commit()
    db.refresh(job)
    model_preferences = get_analysis_models(db)
    costs = import_job_costs_usd(db, [job.id])
    return import_job_out(job, model_preferences=model_preferences, estimated_cost_usd=costs.get(job.id, 0.0))


@app.get("/api/exports/metadata")
def export_metadata(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FastAPIResponse:
    return json_download(build_metadata_export(db), "medusa-metadata")


@app.get("/api/exports/storage-manifest")
def export_storage_manifest(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FastAPIResponse:
    return json_download(build_storage_manifest(db), "medusa-storage-manifest")


@app.get("/api/backups/runs", response_model=list[BackupRunOut])
def read_backup_runs(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[BackupRun]:
    return list_backup_runs(db)


@app.get("/api/backups/estimate", response_model=BackupEstimateOut)
def read_backup_estimate(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    return estimate_backup_size(db)


@app.post("/api/backups/database", response_model=BackupRunOut)
def start_database_backup(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> BackupRun:
    try:
        run = create_database_backup_run(db, reason="manual")
        db.commit()
        db.refresh(run)
        launch_database_backup(run.id)
        return run
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/backups/gcs", response_model=list[BackupArtifactOut])
def read_gcs_backups(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, Any]]:
    try:
        return list_gcs_backup_artifacts(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/backups/artifacts", response_model=list[BackupArtifactOut])
def read_backup_artifacts(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, Any]]:
    try:
        return list_backup_artifacts(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/restores/database", response_model=BackupRunOut)
def start_database_restore(
    payload: RestoreDatabaseCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> BackupRun:
    try:
        source = restore_source_from_artifact_uri(db, payload.uri or payload.gcs_uri or "")
        run = create_restore_run(
            db,
            **source,
        )
        db.commit()
        db.refresh(run)
        launch_database_restore(run.id)
        return run
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/restores/database/upload", response_model=BackupRunOut)
async def start_database_restore_from_upload(
    file: Annotated[UploadFile, File()],
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> BackupRun:
    content = await file.read()
    try:
        upload = save_restore_upload(content, file.filename)
        run = create_restore_run(
            db,
            source_kind="upload",
            source_filename=upload["filename"],
            source_local_path=upload["local_path"],
            source_sha256=upload["sha256"],
        )
        run.size_bytes = upload["size_bytes"]
        db.commit()
        db.refresh(run)
        launch_database_restore(run.id)
        return run
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/concordance/capabilities", response_model=list[ConcordanceCapabilityOut])
def list_concordance_capabilities(_: Annotated[User, Depends(current_user)]) -> list[dict[str, Any]]:
    return current_capabilities()


@app.post("/api/concordance/runs/estimate", response_model=ConcordanceRunEstimateOut)
def estimate_concordance_run_endpoint(
    payload: ConcordanceRunCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return estimate_concordance_run(
            db,
            scope_type=payload.scope_type,
            scope_data=payload.scope_data,
            capability_keys=payload.capability_keys,
            force=payload.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/concordance/runs", response_model=ConcordanceRunOut)
def create_concordance_run_endpoint(
    payload: ConcordanceRunCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        run = create_concordance_run(
            db,
            scope_type=payload.scope_type,
            scope_data=payload.scope_data,
            capability_keys=payload.capability_keys,
            force=payload.force,
            label=payload.label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(run)
    return run


@app.get("/api/concordance/runs", response_model=list[ConcordanceRunOut])
def list_concordance_runs(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return db.query(ConcordanceRun).order_by(ConcordanceRun.created_at.desc()).limit(50).all()


@app.get("/api/concordance/jobs", response_model=list[ConcordanceJobOut])
def list_concordance_jobs(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    jobs = db.query(ConcordanceJob).order_by(ConcordanceJob.created_at.desc()).limit(100).all()
    leases = active_slipstream_leases_by_job(db, "concordance", [job.id for job in jobs])
    return [concordance_job_out(job, lease=leases.get(job.id)) for job in jobs]


@app.get("/api/documents/{document_id}/events", response_model=list[ProcessingEventOut])
def document_events(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ProcessingEvent]:
    return db.query(ProcessingEvent).filter(ProcessingEvent.document_id == document_id).order_by(ProcessingEvent.created_at.desc()).all()


@app.get("/api/review-queue", response_model=list[CitationCandidateOut])
def review_queue(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[CitationCandidate]:
    return (
        db.query(CitationCandidate)
        .options(joinedload(CitationCandidate.document))
        .filter(CitationCandidate.status == "needs_review")
        .order_by(CitationCandidate.created_at.desc())
        .all()
    )


@app.patch("/api/review-queue/{candidate_id}", response_model=CitationCandidateOut)
def patch_citation_candidate(
    candidate_id: str,
    payload: CitationCandidatePatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CitationCandidate:
    candidate = db.get(CitationCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Citation candidate not found")
    if payload.status is not None:
        if payload.status not in {"needs_review", "accepted", "rejected"}:
            raise HTTPException(status_code=400, detail="Unsupported citation candidate status")
        candidate.status = payload.status
    if payload.apply_to_document:
        document = db.get(Document, candidate.document_id)
        if not document_is_library_visible(document):
            raise HTTPException(status_code=404, detail="Document not found")
        before = document_correction_snapshot(document)
        changed_fields: set[str] = set()
        metadata = candidate.source_metadata or {}
        for field in ["title", "authors", "publication_year", "journal", "publisher", "doi", "source_url"]:
            value = metadata.get(field)
            if value not in (None, "", []):
                setattr(document, field, value)
                changed_fields.add(field)
        if candidate.citation_text:
            candidate_source = "crossref" if candidate.source == "crossref" else "model"
            apply_document_citations(
                document,
                document_metadata(document),
                reference_list=candidate.citation_text,
                in_text=metadata.get("apa_in_text_citation"),
                model=get_analysis_model(db, MODEL_APA_CITATION),
                source=candidate_source,
            )
            changed_fields.update(
                {
                    "apa_citation",
                    "apa_citation_model",
                    "apa_citation_source",
                    "apa_in_text_citation",
                    "apa_in_text_citation_model",
                    "apa_in_text_citation_source",
                }
            )
        document.citation_status = "verified"
        changed_fields.add("citation_status")
        candidate.status = "accepted"
        document.search_text = rebuild_document_search_text(document)
        db.flush()
        after = document_correction_snapshot(document)
        record_document_version(
            db,
            document=document,
            change_note="Accepted citation candidate",
            changed_fields=changed_fields,
            before=before,
            after=after,
            extra={"candidate_id": candidate.id},
        )
        record_manual_edit(
            db,
            document=document,
            message="Accepted citation candidate",
            metadata={"candidate_id": candidate.id, "changed_fields": sorted(changed_fields)},
        )
    db.commit()
    db.refresh(candidate)
    return candidate


@app.get("/api/projects/{project_id}/bibliography", response_model=BibliographyOut)
def project_bibliography(
    project_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    used_only: bool = False,
) -> BibliographyOut:
    project = db.get(Project, project_id)
    if not project or project.deleted_at:
        raise HTTPException(status_code=404, detail="Project not found")
    documents = [
        item.document
        for item in project.items
        if document_is_library_visible(item.document) and (not used_only or item.used_in_output)
    ]
    metadata = [
        {
            "title": document.title,
            "authors": document.authors,
            "publication_year": document.publication_year,
            "journal": document.journal,
            "publisher": document.publisher,
            "doi": document.doi,
            "source_url": document.source_url,
        }
        for document in documents
    ]
    apa = "\n".join(sorted(document.apa_citation or "" for document in documents if document.apa_citation))
    bibtex = "\n\n".join(format_bibtex(item) for item in metadata)
    ris = "\n\n".join(format_ris(item) for item in metadata)
    csl_json = [to_csl_json(item) for item in metadata]
    body = apa
    bibliography = ProjectBibliography(project_id=project.id, style="apa7", body=body)
    db.add(bibliography)
    db.commit()
    return BibliographyOut(project_id=project.id, apa=apa, bibtex=bibtex, ris=ris, csl_json=csl_json)


@app.get("/api/notes", response_model=list[NoteOut])
def list_notes(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    document_id: str | None = None,
    domain_id: str | None = None,
    project_id: str | None = None,
) -> list[Note]:
    query = db.query(Note).filter(Note.deleted_at.is_(None))
    if document_id:
        query = query.filter(Note.document_id == document_id)
    if domain_id:
        query = query.filter(Note.domain_id == domain_id)
    if project_id:
        query = query.filter(Note.project_id == project_id)
    return query.order_by(Note.created_at.desc()).limit(100).all()


@app.post("/api/notes", response_model=NoteOut)
def create_note(
    payload: NoteCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Note:
    note = Note(**payload.model_dump())
    db.add(note)
    db.flush()
    if note.document_id:
        document = db.get(Document, note.document_id)
        if document_is_library_visible(document):
            document.search_text = rebuild_document_search_text(document)
    db.commit()
    db.refresh(note)
    return note


@app.patch("/api/notes/{note_id}", response_model=NoteOut)
def patch_note(
    note_id: str,
    payload: NotePatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Note:
    note = db.get(Note, note_id)
    if not note or note.deleted_at:
        raise HTTPException(status_code=404, detail="Note not found")
    previous_document_id = note.document_id
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(note, key, value)
    affected_document_ids = {previous_document_id, note.document_id}
    for document_id in affected_document_ids:
        if document_id:
            document = db.get(Document, document_id)
            if document_is_library_visible(document):
                document.search_text = rebuild_document_search_text(document)
    db.commit()
    db.refresh(note)
    return note


@app.delete("/api/notes/{note_id}")
def delete_note(
    note_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    note = db.get(Note, note_id)
    if not note or note.deleted_at:
        raise HTTPException(status_code=404, detail="Note not found")
    note.deleted_at = utc_now()
    if note.document_id:
        document = db.get(Document, note.document_id)
        if document_is_library_visible(document):
            document.search_text = rebuild_document_search_text(document)
    db.commit()
    return {"status": "deleted"}
