from __future__ import annotations

import hashlib
import json
import mimetypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import get_settings
from app.database import get_db, init_db, session_scope
from app.models import (
    Annotation,
    AttributeDefinition,
    BackupRun,
    CitationCandidate,
    ConcordanceJob,
    ConcordanceRun,
    Document,
    DocumentAccessorySummary,
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
    Project,
    ProjectBibliography,
    ProjectItem,
    SavedSearch,
    Tag,
    TagRelationship,
    User,
    utc_now,
)
from app.schemas import (
    AccessorySummaryCreate,
    AccessorySummaryOut,
    AccessorySummaryPatch,
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
    CitationCandidatePatch,
    CitationCandidateOut,
    ConcordanceCapabilityOut,
    ConcordanceJobOut,
    ConcordanceRunCreate,
    ConcordanceRunOut,
    DashboardOut,
    DocumentDetail,
    DocumentCompositionOut,
    DocumentCacheStatusOut,
    DocumentPatch,
    DocumentPagePatch,
    DocumentRecommendationDownloadCreate,
    DocumentRecommendationDownloadOut,
    DocumentRecommendationOut,
    DocumentRecommendationRefreshOut,
    DocumentTextScrub,
    DoiStashCreate,
    DoiStashOut,
    DocumentSummary,
    DomainCreate,
    DomainDeleteOut,
    DomainOut,
    DomainPatch,
    DomainReorder,
    ImportBatchOut,
    ImportDuplicateCheckOut,
    ImportDuplicateDocumentOut,
    ImportDuplicateFileOut,
    ImportJobOut,
    ImportQueueActionOut,
    LoginRequest,
    NoteCreate,
    NoteOut,
    NotePatch,
    OpenAIUsageOut,
    ProcessingEventOut,
    ProjectCreate,
    ProjectDetail,
    ProjectItemCreate,
    ProjectItemOut,
    ProjectItemPatch,
    ProjectOut,
    RestoreDatabaseCreate,
    RuntimeLocationOut,
    SavedSearchCreate,
    SavedSearchOut,
    SavedSearchPatch,
    TagCreate,
    TagAssignmentPruneCreate,
    TagGovernancePatch,
    TagMerge,
    TagOperationOut,
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
    UserOut,
)
from app.security import create_session, ensure_admin_user, revoke_session, user_for_token, verify_password
from app.services.accessory_summaries import create_accessory_summary
from app.services.analysis_models import (
    DEFAULT_KEYWORDS_TOPICS_MODEL,
    MODEL_APA_CITATION,
    MODEL_KEYWORDS_TOPICS,
    MODEL_METADATA,
    MODEL_PAGE_TEXT_NORMALIZATION,
    MODEL_RAW_TEXT_EXTRACTION,
    MODEL_SUMMARY,
    MODEL_TEXT_CHUNK_ENCODING,
)
from app.services.backups import (
    create_database_backup_run,
    create_restore_run,
    estimate_backup_size,
    launch_database_backup,
    launch_database_restore,
    list_backup_runs,
    list_gcs_backup_artifacts,
    save_restore_upload,
)
from app.services.concordance import create_concordance_run, current_capabilities
from app.services.composition import active_import_cost_usd, document_composition_summary, record_import_cost_estimate, record_manual_edit
from app.services.citations import format_apa_citation, format_apa_in_text_citation, format_bibtex, format_ris, to_csl_json
from app.services.document_cache import current_document_cache_usage, document_cache_root, register_document_cache
from app.services.document_visibility import (
    document_is_library_visible,
    filter_library_visible_documents,
    library_visible_document_filter,
)
from app.services.exports import build_metadata_export, build_storage_manifest
from app.services.history import changed_snapshot_fields, document_correction_snapshot, document_page_snapshot, record_document_version
from app.services.import_sources import ImportSourceError, prepare_import_source, probe_import_source
from app.services.ai import get_ai_service
from app.services.processing import (
    apply_document_citations,
    document_metadata,
    refresh_import_batch_progress,
)
from app.services.preferences import (
    get_analysis_model,
    get_analysis_models,
    get_app_preferences,
    get_download_naming_template,
    render_download_filename,
    store_google_service_account,
    update_app_preferences,
)
from app.services.openai_usage import OpenAIUsageContext, estimated_cost_usd_for_record, openai_usage_summary
from app.services.recommendations import (
    doi_url,
    list_document_recommendations,
    normalize_doi,
    queue_recommendation_imports,
    refresh_document_recommendations,
)
from app.services.runtime_location import detect_server_ipv4, runtime_location_payload
from app.services.search import rebuild_document_search_text
from app.services.tag_governance import (
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

DUPLICATE_IMPORT_STRATEGIES = {"skip", "overwrite", "import_anyway"}
STAGED_IMPORT_STATUS = "staged"
IMPORT_JOB_QUEUE_STATUSES = ("staged", "queued", "running", "failed", "restored_paused")
IMPORT_JOB_CLEARABLE_STATUSES = ("staged", "queued", "running", "failed", "restored_paused")
IMPORT_ESTIMATE_TASK_KEYS = (
    MODEL_METADATA,
    MODEL_SUMMARY,
    MODEL_APA_CITATION,
    MODEL_KEYWORDS_TOPICS,
    MODEL_PAGE_TEXT_NORMALIZATION,
    MODEL_TEXT_CHUNK_ENCODING,
)
DEFAULT_IMPORT_ESTIMATE_USD_PER_PAGE = 0.01
IMPORT_ESTIMATE_CALIBRATION_MIN = 0.25
IMPORT_ESTIMATE_CALIBRATION_MAX = 4.0
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    global SERVER_IPV4
    SERVER_IPV4 = detect_server_ipv4()
    init_db()
    with session_scope() as db:
        ensure_admin_user(db)


@app.get("/api/runtime-location", response_model=RuntimeLocationOut)
def runtime_location(browser_host: str | None = Query(default=None, max_length=255)) -> dict[str, str | None]:
    return runtime_location_payload(browser_host, SERVER_IPV4)


def parse_json_form(value: str | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON form field: {exc}") from exc


def current_user(
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    user = user_for_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def domain_out(domain: Domain, db: Session | None = None) -> DomainOut:
    return DomainOut(
        id=domain.id,
        parent_id=domain.parent_id,
        name=domain.name,
        description=domain.description,
        color=domain.color,
        sort_order=domain.sort_order,
        document_count=domain_document_count(db, domain.id)
        if db
        else len([document for document in domain.documents if document_is_library_visible(document)]),
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


def tag_out(tag: Tag, db: Session) -> TagOut:
    return TagOut(
        id=tag.id,
        name=tag.name,
        kind=tag.kind,
        color=tag.color,
        status=tag.status,
        definition=tag.definition,
        use_guidance=tag.use_guidance,
        avoid_guidance=tag.avoid_guidance,
        document_count=tag_document_count(db, tag.id),
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


def apply_document_filters(
    query,
    *,
    q: str | None = None,
    domain_id: str | None = None,
    tag_id: str | None = None,
    read_status: str | None = None,
    priority: str | None = None,
    citation_status: str | None = None,
):
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Document.title.ilike(like),
                Document.search_text.ilike(like),
                Document.apa_citation.ilike(like),
                Document.apa_in_text_citation.ilike(like),
            )
        )
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
    return query


def document_title_order_columns(db: Session):
    title_key = func.lower(Document.title)
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        title_key = title_key.collate("C")
    return title_key, Document.title, Document.id


def normalize_document_title_spacing(value: str | None) -> str:
    return " ".join((value or "").split())


def duplicate_checksum_select():
    return (
        select(Document.checksum_sha256)
        .where(library_visible_document_filter())
        .group_by(Document.checksum_sha256)
        .having(func.count(Document.id) > 1)
    )


def duplicate_count_by_checksum(db: Session, checksums: list[str]) -> dict[str, int]:
    if not checksums:
        return {}
    rows = (
        db.query(Document.checksum_sha256, func.count(Document.id))
        .filter(library_visible_document_filter(), Document.checksum_sha256.in_(checksums))
        .group_by(Document.checksum_sha256)
        .all()
    )
    return {checksum: max(0, int(count) - 1) for checksum, count in rows}


def active_documents_for_checksum(db: Session, checksum: str) -> list[Document]:
    return (
        db.query(Document)
        .filter(Document.deleted_at.is_(None), Document.checksum_sha256 == checksum)
        .order_by(Document.created_at.desc(), Document.id)
        .all()
    )


def visible_documents_for_checksum(db: Session, checksum: str) -> list[Document]:
    return (
        db.query(Document)
        .filter(library_visible_document_filter(), Document.checksum_sha256 == checksum)
        .order_by(Document.created_at.desc(), Document.id)
        .all()
    )


def duplicate_document_out(document: Document) -> ImportDuplicateDocumentOut:
    return ImportDuplicateDocumentOut(
        id=document.id,
        title=document.title,
        original_filename=document.original_filename,
        created_at=document.created_at,
        processing_status=document.processing_status,
    )


def document_summary_out(document: Document, duplicate_count: int = 0) -> DocumentSummary:
    return DocumentSummary.model_validate(document).model_copy(update={"duplicate_count": duplicate_count})


def document_detail_out(document: Document, db: Session) -> DocumentDetail:
    duplicate_ids = [item.id for item in visible_documents_for_checksum(db, document.checksum_sha256) if item.id != document.id]
    return DocumentDetail.model_validate(document).model_copy(
        update={"duplicate_count": len(duplicate_ids), "duplicate_document_ids": duplicate_ids}
    )


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


@app.post("/api/auth/login", response_model=UserOut)
def login(payload: LoginRequest, request: Request, response: Response, db: Annotated[Session, Depends(get_db)]) -> User:
    user = db.query(User).filter(User.email == payload.email).one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_session(db, user, user_agent=request.headers.get("user-agent"))
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.session_ttl_hours * 3600,
    )
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


@app.get("/api/dashboard", response_model=DashboardOut)
def dashboard(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> DashboardOut:
    import_queued_jobs = db.query(ImportJob).filter(ImportJob.status == "queued").count()
    import_running_jobs = db.query(ImportJob).filter(ImportJob.status == "running").count()
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
    visible_documents = filter_library_visible_documents(db.query(Document))
    return DashboardOut(
        documents=visible_documents.count(),
        unread=filter_library_visible_documents(db.query(Document)).filter(Document.read_status == "unread").count(),
        needs_review=filter_library_visible_documents(db.query(Document)).filter(Document.citation_status == "needs_review").count(),
        queued_jobs=active_import_jobs + active_concordance_jobs + active_accessory_summary_jobs,
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
        projects=db.query(Project).filter(Project.deleted_at.is_(None)).count(),
    )


@app.get("/api/preferences", response_model=AppPreferencesOut)
def read_preferences(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    return get_app_preferences(db)


@app.patch("/api/preferences", response_model=AppPreferencesOut)
def patch_preferences(
    payload: AppPreferencesPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    preferences = update_app_preferences(
        db,
        import_worker_concurrency=payload.import_worker_concurrency,
        accent_color_day=payload.accent_color_day,
        accent_color_night=payload.accent_color_night,
        document_cache_size_mb=payload.document_cache_size_mb,
        library_alternating_rows=payload.library_alternating_rows,
        download_naming_template=payload.download_naming_template,
        citation_convention=payload.citation_convention,
        gcs_bucket=payload.gcs_bucket,
        analysis_models=payload.analysis_models,
    )
    db.commit()
    return preferences


@app.get("/api/document-cache/status", response_model=DocumentCacheStatusOut)
def document_cache_status(_: Annotated[User, Depends(current_user)]) -> dict[str, int]:
    return current_document_cache_usage()


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


@app.get("/api/openai/usage", response_model=OpenAIUsageOut)
def read_openai_usage(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    period: str = Query("all_time", pattern="^(last_day|last_month|last_3_months|all_time)$"),
) -> dict[str, Any]:
    return openai_usage_summary(db, period=period)


@app.get("/api/domains", response_model=list[DomainOut])
def list_domains(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[DomainOut]:
    domains = db.query(Domain).filter(Domain.deleted_at.is_(None)).order_by(Domain.sort_order, Domain.name).all()
    return [domain_out(domain, db) for domain in domains]


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
    domains = db.query(Domain).filter(Domain.deleted_at.is_(None)).order_by(Domain.sort_order, Domain.name).all()
    return [domain_out(domain, db) for domain in domains]


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

    children = db.query(Domain).filter(Domain.deleted_at.is_(None), Domain.parent_id == domain.id).order_by(Domain.sort_order, Domain.name).all()
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


@app.get("/api/tags", response_model=list[TagOut])
def list_tags(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[TagOut]:
    return [tag_out(tag, db) for tag in db.query(Tag).order_by(Tag.name).all()]


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
    if len(source_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least two tags to merge")
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
        if payload.target_tag_id not in source_by_id:
            raise HTTPException(status_code=400, detail="Kept tag must be one of the selected tags")
        target_tag = source_by_id[payload.target_tag_id]
    elif target_name:
        target_tag = db.query(Tag).filter(Tag.name == target_name).one_or_none()
        if target_tag is None:
            target_tag = resolve_tag_alias(db, target_name)
            target_name_matched_alias = target_tag is not None
        if target_tag is None:
            target_tag = source_tags[0]
    else:
        raise HTTPException(status_code=400, detail="Choose a tag to keep or enter a new tag name")

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

    inventory = [
        {
            "id": tag.id,
            "name": tag.name,
            "document_count": tag_document_count(db, tag.id),
        }
        for tag in tag_rows
    ]
    try:
        result = get_ai_service().generate_tag_optimization_suggestions(
            inventory,
            model=DEFAULT_KEYWORDS_TOPICS_MODEL,
            usage_context=OpenAIUsageContext(source="tags", capability_key="tag_optimization"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tag optimization failed: {exc}") from exc

    tag_by_id = {tag.id: tag for tag in tag_rows}
    considered_tag_by_name = {tag.name: tag for tag in tag_rows}
    all_tag_by_name = {tag.name: tag for tag in db.query(Tag).all()}
    document_counts_by_id = {item["id"]: int(item["document_count"]) for item in inventory}
    suggestions: list[TagOptimizationSuggestionOut] = []
    singleton_suggestions: list[TagOptimizationSuggestionOut] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()

    def append_suggestion(
        item: dict[str, Any],
        destination: list[TagOptimizationSuggestionOut],
        *,
        fallback_rationale: str,
        id_prefix: str = "merge",
        require_singleton: bool = False,
        limit: int = 12,
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

    raw_suggestions = result.get("suggestions") if isinstance(result, dict) else None
    suggestion_items = raw_suggestions if isinstance(raw_suggestions, list) else []
    for item in suggestion_items:
        if append_suggestion(
            item,
            suggestions,
            fallback_rationale="These tags appear to overlap and may be clearer as one tag.",
            id_prefix="merge",
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
        ):
            break

    singleton_rows = [tag for tag in tag_rows if document_counts_by_id.get(tag.id) == 1]
    variant_groups: dict[str, list[Tag]] = {}
    for tag in tag_rows:
        key = cleanup_tag_variant_key(tag.name)
        if key:
            variant_groups.setdefault(key, []).append(tag)
    for group in variant_groups.values():
        if len(singleton_suggestions) >= 12:
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
        )

    prefix_groups: dict[str, set[str]] = {}
    for singleton in singleton_rows:
        candidates = [candidate for candidate in tag_rows if candidate.id != singleton.id and cleanup_prefix_target(singleton.name, candidate.name)]
        if not candidates:
            continue
        target = sorted(candidates, key=lambda tag: (-len(cleanup_tag_tokens(tag.name)), tag.name))[0]
        prefix_groups.setdefault(target.name, {target.id}).add(singleton.id)
    for target_name, source_ids in sorted(prefix_groups.items()):
        if len(singleton_suggestions) >= 12:
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
        if len(singleton_suggestions) >= 12:
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
        )

    relationship_suggestions = [
        {
            "id": item["id"],
            "source_tag": tag_out(item["source_tag"], db),
            "target_tag": tag_out(item["target_tag"], db),
            "relationship_type": item["relationship_type"],
            "rationale": item["rationale"],
            "confidence": float(item["confidence"]),
        }
        for item in relationship_review_suggestions(db, tag_rows)
    ]
    status_suggestions = [
        {
            "id": item["id"],
            "tag": tag_out(item["tag"], db),
            "suggested_status": item["suggested_status"],
            "rationale": item["rationale"],
            "confidence": float(item["confidence"]),
        }
        for item in status_review_suggestions(db, tag_rows)
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
        for item in pruning_review_suggestions(db, tag_rows)
    ]

    return TagOptimizationOut(
        model=DEFAULT_KEYWORDS_TOPICS_MODEL,
        considered_tags=len(tag_rows),
        suggestions=suggestions,
        singleton_suggestions=singleton_suggestions,
        relationship_suggestions=relationship_suggestions,
        status_suggestions=status_suggestions,
        pruning_suggestions=pruning_suggestions,
        health_summary=tag_health_summary(db, tag_rows),
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


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[ProjectOut]:
    projects = db.query(Project).filter(Project.deleted_at.is_(None)).order_by(Project.created_at.desc()).all()
    return [project_out(project) for project in projects]


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
    limit: Annotated[int | None, Query(ge=1, le=5000)] = None,
) -> list[DocumentSummary]:
    query = filter_library_visible_documents(db.query(Document))
    query = apply_document_filters(
        query,
        q=q,
        domain_id=domain_id,
        tag_id=tag_id,
        read_status=read_status,
        priority=priority,
        citation_status=citation_status,
    )
    if duplicate_status:
        duplicate_checksums = duplicate_checksum_select()
        if duplicate_status == "duplicates":
            query = query.filter(Document.checksum_sha256.in_(duplicate_checksums))
        elif duplicate_status == "unique":
            query = query.filter(Document.checksum_sha256.notin_(duplicate_checksums))
    query = query.order_by(None).order_by(*document_title_order_columns(db))
    if limit is not None:
        query = query.limit(limit)
    documents = query.all()
    duplicate_counts = duplicate_count_by_checksum(db, [document.checksum_sha256 for document in documents])
    return [document_summary_out(document, duplicate_counts.get(document.checksum_sha256, 0)) for document in documents]


@app.get("/api/documents/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    return document_detail_out(document, db)


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
) -> ConcordanceRun:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
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


@app.post("/api/documents/{document_id}/accessory-summaries", response_model=AccessorySummaryOut)
def queue_document_accessory_summary(
    document_id: str,
    payload: AccessorySummaryCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
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
) -> list[DocumentRecommendation]:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    rows = list_document_recommendations(db, document, hide_existing=hide_existing)
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
    if not document.doi:
        raise HTTPException(status_code=400, detail="A DOI is required to refresh related-paper recommendations")
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
    query = db.query(DocumentRecommendation).filter(DocumentRecommendation.source_document_id == document.id)
    if payload.mode == "new":
        query = query.filter(
            DocumentRecommendation.existing_document_id.is_(None),
            DocumentRecommendation.imported_document_id.is_(None),
        )
    else:
        ids = payload.recommendation_ids or []
        if not ids:
            raise HTTPException(status_code=400, detail="recommendation_ids is required for selected downloads")
        query = query.filter(DocumentRecommendation.id.in_(ids))
    recommendations = query.order_by(DocumentRecommendation.title).all()
    if not recommendations:
        raise HTTPException(status_code=400, detail="No recommendations matched the download request")
    result = queue_recommendation_imports(db, document, recommendations, skip_existing=payload.skip_existing)
    db.commit()
    return DocumentRecommendationDownloadOut(**result)


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


def doi_stash_query(db: Session):
    return (
        db.query(DoiStash)
        .options(joinedload(DoiStash.imported_document), joinedload(DoiStash.import_job))
        .filter(DoiStash.deleted_at.is_(None))
    )


def doi_stash_out(stash: DoiStash) -> DoiStashOut:
    return DoiStashOut(
        id=stash.id,
        doi=stash.doi,
        title=stash.title,
        source_url=stash.source_url,
        source_provider=stash.source_provider,
        source_document_id=stash.source_document_id,
        recommendation_id=stash.recommendation_id,
        imported_document_id=stash.imported_document_id,
        imported_document_title=stash.imported_document.title if stash.imported_document else None,
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
    for stash in stashes:
        changed = sync_doi_stash_import_status(stash) or changed
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
    source_provider = payload.source_provider or (recommendation.provider if recommendation else None)
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

    existing_documents = active_documents_for_checksum(db, checksum)
    if existing_documents:
        job = create_skipped_duplicate_job(
            db,
            batch=batch,
            document=existing_documents[0],
            filename=filename,
            checksum=checksum,
            reason="matched_existing_document",
        )
        stash.imported_document_id = existing_documents[0].id
        stash.import_job_id = job.id
        stash.status = "imported"
        stash.uploaded_filename = filename
        stash.imported_at = utc_now()
        refresh_import_batch_progress(db, batch)
        db.commit()
        db.refresh(stash)
        return doi_stash_out(stash)

    document = Document(
        title=stash.title or Path(filename).stem.replace("_", " ").replace("-", " "),
        original_filename=filename,
        content_type=file.content_type or "application/pdf",
        checksum_sha256=checksum,
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
        data = get_storage_service().get_bytes(figure.asset_uri)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Figure asset is unavailable") from exc
    content_type = mimetypes.guess_type(figure.asset_uri)[0] or "application/octet-stream"
    return FastAPIResponse(content=data, media_type=content_type)


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
    attribute_values = data.pop("attribute_values", None)
    before = document_correction_snapshot(document)
    changed_fields: set[str] = set()
    for key, value in data.items():
        if getattr(document, key) != value:
            setattr(document, key, value)
            changed_fields.add(key)
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

    citation_fields = {"title", "authors", "publication_year", "journal", "publisher", "doi", "source_url"}
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


@app.delete("/api/documents/{document_id}")
def delete_document(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    document = db.get(Document, document_id)
    if not document_is_library_visible(document):
        raise HTTPException(status_code=404, detail="Document not found")
    document.deleted_at = utc_now()
    db.commit()
    return {"status": "deleted"}


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
    seen_checksums: set[str] = set()
    rows: list[ImportDuplicateFileOut] = []
    duplicate_count = 0
    for upload in files:
        data = await upload.read()
        try:
            source = probe_import_source(data, upload.filename, upload.content_type)
        except ImportSourceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        checksum = source.checksum_sha256
        existing = active_documents_for_checksum(db, checksum)
        duplicate_in_upload = checksum in seen_checksums
        seen_checksums.add(checksum)
        if existing or duplicate_in_upload:
            duplicate_count += 1
        rows.append(
            ImportDuplicateFileOut(
                filename=source.filename,
                checksum_sha256=checksum,
                file_size_bytes=source.file_size_bytes,
                source_kind=source.source_kind,
                stored_filename=source.stored_filename,
                existing_documents=[duplicate_document_out(document) for document in existing],
                duplicate_in_upload=duplicate_in_upload,
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
) -> ImportBatch:
    duplicate_strategy = validate_duplicate_strategy(duplicate_strategy)
    parsed_domain_ids = parse_json_form(domain_ids, [])
    parsed_tag_ids = parse_json_form(tag_ids, [])
    parsed_project_ids = parse_json_form(project_ids, [])
    parsed_attributes = parse_json_form(attributes, {})
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

    batch_documents_by_checksum: dict[str, Document] = {}
    for prepared in prepared_files:
        checksum = prepared.source_checksum_sha256
        filename = prepared.source_filename
        stored_filename = prepared.stored_filename
        existing_documents = active_documents_for_checksum(db, checksum)
        already_handled_document = batch_documents_by_checksum.get(checksum)
        if already_handled_document and duplicate_strategy != "import_anyway":
            create_skipped_duplicate_job(
                db,
                batch=batch,
                document=already_handled_document,
                filename=filename,
                checksum=checksum,
                reason="duplicate_in_current_batch",
            )
            continue

        if existing_documents and duplicate_strategy == "skip":
            create_skipped_duplicate_job(
                db,
                batch=batch,
                document=existing_documents[0],
                filename=filename,
                checksum=checksum,
                reason="matched_existing_document",
            )
            continue

        duplicate_source_ids = [document.id for document in existing_documents]
        if existing_documents and duplicate_strategy == "overwrite":
            document = existing_documents[0]
            reset_document_for_overwrite(db, document)
        else:
            document = Document(
                title=prepared.title,
                original_filename=stored_filename,
                content_type=prepared.stored_content_type,
                checksum_sha256=checksum,
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
            "upload_cost_estimate": {
                "estimated_page_count": estimated_page_count or None,
                "basis": "pending_exemplar_cost_model",
            },
            "import_defaults": batch.shared_defaults,
            "duplicate_import": {
                "strategy": duplicate_strategy,
                "matched_document_ids": duplicate_source_ids,
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
        estimated_cost_usd, estimate_basis, estimate_page_count = estimate_import_job_cost_usd(
            job,
            model_preferences=model_preferences,
            rates=estimate_rates,
        )
        upload_estimate = {
            "estimated_cost_usd": estimated_cost_usd,
            "estimated_page_count": estimate_page_count,
            "basis": estimate_basis,
            "calibration_factor": estimate_rates.get("estimate_calibration_factor"),
            "calibration_sample_count": estimate_rates.get("estimate_calibration_sample_count"),
            "model_preferences": model_preferences,
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
            },
        )
        batch_documents_by_checksum[checksum] = document

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
            costs[usage.import_job_id] = costs.get(usage.import_job_id, 0.0) + (estimated_cost_usd_for_record(usage) or 0.0)
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
        cost = estimated_cost_usd_for_record(record) or 0.0
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


def estimate_import_job_cost_usd(
    job: ImportJob,
    *,
    model_preferences: dict[str, str],
    rates: dict[str, Any],
) -> tuple[float, str, int | None]:
    page_count = document_estimated_page_count(job.document)
    if not page_count or page_count <= 0:
        page_count = 1
    task_model_rates: dict[tuple[str, str], float] = rates.get("task_model_rates", {})
    task_rates: dict[str, float] = rates.get("task_rates", {})
    overall_rate = float(rates.get("overall_rate") or 0.0)
    total_rate = 0.0
    exact_rate_count = 0
    fallback_rate_count = 0
    for task_key in IMPORT_ESTIMATE_TASK_KEYS:
        model = model_preferences.get(task_key)
        if not model:
            continue
        exact_rate = task_model_rates.get((task_key, model))
        if exact_rate is not None:
            total_rate += exact_rate
            exact_rate_count += 1
            continue
        fallback_rate = task_rates.get(task_key)
        if fallback_rate is not None:
            total_rate += fallback_rate
            fallback_rate_count += 1

    if total_rate > 0:
        basis = "exemplar" if exact_rate_count else "task_exemplar"
        if fallback_rate_count:
            basis = "mixed_exemplar"
        amount, basis = apply_import_estimate_calibration(round(total_rate * page_count, 6), basis, rates)
        return amount, basis, page_count
    if overall_rate > 0:
        amount, basis = apply_import_estimate_calibration(round(overall_rate * page_count, 6), "library_exemplar", rates)
        return amount, basis, page_count
    amount, basis = apply_import_estimate_calibration(round(DEFAULT_IMPORT_ESTIMATE_USD_PER_PAGE * page_count, 6), "default", rates)
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
    if step in {"extracted", "extracting_figures", "figures", "cleaning_cache", "duplicate_skipped"}:
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


def import_job_out(
    job: ImportJob,
    *,
    model_preferences: dict[str, str] | None = None,
    estimated_cost_usd: float = 0.0,
    cost_estimate: tuple[float, str, int | None] | None = None,
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
        "attempts": job.attempts,
        "last_error": last_error or (event_error if job.status == "failed" else None),
        "locked_at": job.locked_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


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
    costs = import_job_costs_usd(db, [job.id for job in jobs])
    estimate_rates = import_cost_exemplar_rates(db)
    return [
        import_job_out(
            job,
            model_preferences=model_preferences,
            estimated_cost_usd=costs.get(job.id, 0.0),
            cost_estimate=estimate_import_job_cost_usd(job, model_preferences=model_preferences, rates=estimate_rates),
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


@app.post("/api/restores/database", response_model=BackupRunOut)
def start_database_restore(
    payload: RestoreDatabaseCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> BackupRun:
    try:
        run = create_restore_run(
            db,
            source_kind="gcs",
            source_filename=Path(payload.gcs_uri).name,
            source_uri=payload.gcs_uri,
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
    return db.query(ConcordanceJob).order_by(ConcordanceJob.created_at.desc()).limit(100).all()


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
