from __future__ import annotations

from datetime import datetime
from html import unescape
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def decode_html_entity_text(value: Any) -> Any:
    return unescape(value) if isinstance(value, str) else value


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(ApiModel):
    id: str
    email: str
    display_name: str


class RuntimeLocationOut(BaseModel):
    app_name: str
    expansion: str
    network_context: str
    ipv4: str | None = None
    title: str


class DomainCreate(BaseModel):
    name: str
    parent_id: str | None = None
    description: str | None = None
    color: str | None = None


class DomainPatch(BaseModel):
    name: str | None = None
    parent_id: str | None = None
    description: str | None = None
    color: str | None = None
    sort_order: int | None = None


class DomainReorderItem(BaseModel):
    id: str
    parent_id: str | None = None
    sort_order: int


class DomainReorder(BaseModel):
    domains: list[DomainReorderItem] = Field(min_length=1)


class DomainOut(ApiModel):
    id: str
    parent_id: str | None = None
    name: str
    description: str | None = None
    color: str | None = None
    sort_order: int
    document_count: int = 0


class DomainDeleteOut(BaseModel):
    deleted_id: str
    updated_documents: int


class TagCreate(BaseModel):
    name: str
    color: str | None = None


class TagRename(BaseModel):
    name: str


class TagGovernancePatch(BaseModel):
    status: str | None = None
    definition: str | None = None
    use_guidance: str | None = None
    avoid_guidance: str | None = None


class TagMerge(BaseModel):
    source_tag_ids: list[str] = Field(min_length=1)
    target_tag_id: str | None = None
    target_name: str | None = None


class TagOut(ApiModel):
    id: str
    name: str
    kind: str
    color: str | None = None
    status: str = "canonical"
    definition: str | None = None
    use_guidance: str | None = None
    avoid_guidance: str | None = None
    document_count: int = 0


class TagOperationOut(BaseModel):
    tag: TagOut
    updated_documents: int
    removed_tag_ids: list[str] = Field(default_factory=list)


class TagOptimizationCreate(BaseModel):
    tag_ids: list[str] | None = None


class TagOptimizationMergeApproval(BaseModel):
    id: str | None = None
    source_tag_ids: list[str] = Field(default_factory=list)
    target_tag_id: str | None = None
    target_name: str | None = None


class TagOptimizationRelationshipApproval(BaseModel):
    id: str | None = None
    source_tag_id: str
    target_tag_id: str
    relationship_type: str
    rationale: str | None = None
    confidence: float | None = None


class TagOptimizationStatusApproval(BaseModel):
    id: str | None = None
    tag_id: str
    suggested_status: str
    rationale: str | None = None


class TagOptimizationPruneApproval(BaseModel):
    id: str | None = None
    document_id: str
    tag_id: str
    rationale: str | None = None


class TagOptimizationOrphanPruneApproval(BaseModel):
    id: str | None = None
    tag_id: str
    rationale: str | None = None


class TagOptimizationApproveAllCreate(BaseModel):
    merge_suggestions: list[TagOptimizationMergeApproval] = Field(default_factory=list)
    relationship_suggestions: list[TagOptimizationRelationshipApproval] = Field(default_factory=list)
    status_suggestions: list[TagOptimizationStatusApproval] = Field(default_factory=list)
    pruning_suggestions: list[TagOptimizationPruneApproval] = Field(default_factory=list)
    orphan_prune_suggestions: list[TagOptimizationOrphanPruneApproval] = Field(default_factory=list)


class TagOptimizationApproveAllOut(BaseModel):
    merges_applied: int = 0
    relationships_applied: int = 0
    statuses_applied: int = 0
    prunes_applied: int = 0
    orphans_pruned: int = 0
    updated_documents: int = 0
    removed_tag_ids: list[str] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)


class TagOptimizationSuggestionOut(BaseModel):
    id: str
    target_name: str
    target_tag_id: str | None = None
    source_tag_ids: list[str]
    source_tags: list[TagOut]
    affected_documents: int
    rationale: str
    confidence: float


class TagRelationshipCreate(BaseModel):
    source_tag_id: str
    target_tag_id: str
    relationship_type: str
    rationale: str | None = None
    confidence: float | None = None


class TagRelationshipSuggestionOut(BaseModel):
    id: str
    source_tag: TagOut
    target_tag: TagOut
    relationship_type: str
    rationale: str
    confidence: float


class TagStatusSuggestionOut(BaseModel):
    id: str
    tag: TagOut
    suggested_status: str
    rationale: str
    confidence: float


class TagAssignmentPruneCreate(BaseModel):
    document_id: str
    tag_id: str
    rationale: str | None = None


class TagPruneSuggestionOut(BaseModel):
    id: str
    document_id: str
    document_title: str
    tag: TagOut
    rationale: str
    confidence: float
    relevance_score: float
    library_fit_score: float
    novelty_score: float
    overall_score: float


class TagOrphanPruneCreate(BaseModel):
    tag_id: str
    rationale: str | None = None


class TagOrphanPruneOut(BaseModel):
    tag_id: str
    tag_name: str
    removed_tag_ids: list[str] = Field(default_factory=list)


class TagOrphanPruneSuggestionOut(BaseModel):
    id: str
    tag: TagOut
    rationale: str
    confidence: float


class TagOptimizationOut(BaseModel):
    model: str
    considered_tags: int
    suggestions: list[TagOptimizationSuggestionOut] = Field(default_factory=list)
    singleton_suggestions: list[TagOptimizationSuggestionOut] = Field(default_factory=list)
    orphan_merge_suggestions: list[TagOptimizationSuggestionOut] = Field(default_factory=list)
    relationship_suggestions: list[TagRelationshipSuggestionOut] = Field(default_factory=list)
    status_suggestions: list[TagStatusSuggestionOut] = Field(default_factory=list)
    pruning_suggestions: list[TagPruneSuggestionOut] = Field(default_factory=list)
    orphan_prune_suggestions: list[TagOrphanPruneSuggestionOut] = Field(default_factory=list)
    health_summary: dict[str, Any] = Field(default_factory=dict)


class TagRelationshipOut(BaseModel):
    id: str
    source_tag: TagOut
    target_tag: TagOut
    relationship_type: str
    status: str
    rationale: str | None = None
    confidence: float | None = None


class TagPruneOut(BaseModel):
    document_id: str
    tag_id: str
    updated_documents: int


class SavedSearchCreate(BaseModel):
    name: str
    query: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)


class SavedSearchPatch(BaseModel):
    name: str | None = None
    query: str | None = None
    filters: dict[str, Any] | None = None


class SavedSearchOut(ApiModel):
    id: str
    name: str
    query: str | None = None
    filters: dict[str, Any]
    sort_order: int
    created_at: datetime


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    due_at: datetime | None = None


class ProjectOut(ApiModel):
    id: str
    name: str
    description: str | None = None
    status: str
    due_at: datetime | None = None
    item_count: int = 0


class ProjectItemCreate(BaseModel):
    document_ids: list[str]
    status: str = "candidate"
    priority: str = "normal"
    used_in_output: bool = False
    note: str | None = None


class ProjectItemPatch(BaseModel):
    status: str | None = None
    priority: str | None = None
    used_in_output: bool | None = None
    note: str | None = None


class AttributeDefinitionCreate(BaseModel):
    name: str
    value_type: str = "markdown"
    description: str | None = None


class AttributeDefinitionOut(ApiModel):
    id: str
    name: str
    value_type: str
    description: str | None = None


class DocumentAttributeValueOut(ApiModel):
    id: str
    attribute_definition_id: str
    value: dict[str, Any]
    definition: AttributeDefinitionOut


class DocumentVersionOut(ApiModel):
    id: str
    version_number: int
    change_note: str | None = None
    metadata_snapshot: dict[str, Any]
    created_at: datetime


class FigureOut(ApiModel):
    id: str
    page_number: int | None = None
    figure_label: str | None = None
    caption: str | None = None
    gist: str | None = None
    asset_uri: str | None = None
    geometry: dict[str, Any] = Field(default_factory=dict)


class DocumentPageOut(ApiModel):
    id: str
    page_number: int
    text: str | None = None
    normalized_text: str | None = None
    text_source: str
    low_text: bool
    image_uri: str | None = None


class AnnotationCreate(BaseModel):
    page_number: int | None = None
    kind: str = "highlight"
    body: str | None = None
    geometry: dict[str, Any] = Field(default_factory=dict)
    color: str | None = None


class AnnotationPatch(BaseModel):
    page_number: int | None = None
    kind: str | None = None
    body: str | None = None
    geometry: dict[str, Any] | None = None
    color: str | None = None


class AnnotationOut(ApiModel):
    id: str
    document_id: str
    page_number: int | None = None
    kind: str
    body: str | None = None
    geometry: dict[str, Any]
    color: str | None = None
    created_at: datetime
    updated_at: datetime


class AccessorySummaryCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    model: str | None = None
    title: str | None = Field(default=None, max_length=240)


class AccessorySummaryPatch(BaseModel):
    title: str | None = Field(default=None, max_length=240)


class AccessorySummaryOut(ApiModel):
    id: str
    document_id: str
    title: str | None = None
    prompt: str
    summary: str | None = None
    model: str
    status: str
    attempts: int
    last_error: str | None = None
    evidence: dict[str, Any]
    locked_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("title", "prompt", "summary", "last_error", mode="before")
    @classmethod
    def decode_summary_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class DocumentSummary(ApiModel):
    id: str
    title: str
    authors: list[dict[str, Any]]
    publication_year: int | None = None
    journal: str | None = None
    doi: str | None = None
    rich_summary: str | None = None
    apa_citation: str | None = None
    apa_citation_model: str | None = None
    apa_citation_source: str | None = None
    apa_in_text_citation: str | None = None
    apa_in_text_citation_model: str | None = None
    apa_in_text_citation_source: str | None = None
    citation_status: str
    metadata_confidence: float | None = None
    original_filename: str
    checksum_sha256: str
    page_count: int
    processing_status: str
    read_status: str
    priority: str
    created_at: datetime
    duplicate_count: int = 0
    tags: list[TagOut] = Field(default_factory=list)
    domains: list[DomainOut] = Field(default_factory=list)

    @field_validator("title", "journal", "rich_summary", "apa_citation", "apa_in_text_citation", mode="before")
    @classmethod
    def decode_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class DocumentDetail(DocumentSummary):
    subtitle: str | None = None
    universities: list[str]
    publisher: str | None = None
    source_url: str | None = None
    abstract: str | None = None
    metadata_evidence: dict[str, Any]
    gcs_uri: str | None = None
    storage_status: str
    search_text: str | None = None
    attributes: list[DocumentAttributeValueOut] = Field(default_factory=list)
    versions: list[DocumentVersionOut] = Field(default_factory=list)
    pages: list[DocumentPageOut] = Field(default_factory=list)
    figures: list[FigureOut] = Field(default_factory=list)
    accessory_summaries: list[AccessorySummaryOut] = Field(default_factory=list)
    annotations: list[AnnotationOut] = Field(default_factory=list)
    duplicate_document_ids: list[str] = Field(default_factory=list)

    @field_validator("subtitle", "publisher", "source_url", "abstract", "search_text", mode="before")
    @classmethod
    def decode_detail_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class DocumentRecommendationOut(ApiModel):
    id: str
    source_document_id: str
    existing_document_id: str | None = None
    imported_document_id: str | None = None
    existing_document_title: str | None = None
    title: str
    doi: str | None = None
    authors: list[dict[str, Any]] = Field(default_factory=list)
    publication_year: int | None = None
    journal: str | None = None
    description: str | None = None
    source_provider: str
    source_relation: str | None = None
    external_id: str | None = None
    source_url: str | None = None
    pdf_url: str | None = None
    score: float | None = None
    status: str
    raw_metadata: dict[str, Any]
    has_pdf: bool = False
    scholar_url: str
    last_seen_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("title", "journal", "description", "source_url", "pdf_url", mode="before")
    @classmethod
    def decode_recommendation_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class DocumentRecommendationRefreshOut(BaseModel):
    document_id: str
    recommendation_count: int
    recommendations: list[DocumentRecommendationOut]


class DocumentRecommendationDownloadCreate(BaseModel):
    recommendation_ids: list[str] | None = None
    mode: str = "selected"
    skip_existing: bool = True


class DocumentRecommendationDownloadOut(BaseModel):
    batch_id: str
    queued_count: int
    skipped_existing_count: int
    unavailable_count: int
    failed_count: int


class DoiStashCreate(BaseModel):
    doi: str = Field(min_length=1, max_length=256)
    title: str | None = Field(default=None, max_length=800)
    source_url: str | None = None
    source_provider: str | None = Field(default=None, max_length=160)
    source_document_id: str | None = None
    recommendation_id: str | None = None


class DoiStashOut(ApiModel):
    id: str
    doi: str
    title: str | None = None
    source_url: str | None = None
    source_provider: str | None = None
    source_document_id: str | None = None
    recommendation_id: str | None = None
    imported_document_id: str | None = None
    imported_document_title: str | None = None
    import_job_id: str | None = None
    import_job_status: str | None = None
    status: str
    uploaded_filename: str | None = None
    imported_at: datetime | None = None
    stash_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_validator("doi", "title", "source_url", "source_provider", "uploaded_filename", mode="before")
    @classmethod
    def decode_stash_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class ImportDuplicateDocumentOut(BaseModel):
    id: str
    title: str
    original_filename: str
    created_at: datetime
    processing_status: str


class ImportDuplicateFileOut(BaseModel):
    filename: str
    checksum_sha256: str
    file_size_bytes: int
    source_kind: str = "pdf"
    stored_filename: str | None = None
    existing_documents: list[ImportDuplicateDocumentOut] = Field(default_factory=list)
    duplicate_in_upload: bool = False


class ImportDuplicateCheckOut(BaseModel):
    files: list[ImportDuplicateFileOut]
    duplicate_file_count: int


class ProjectItemOut(ApiModel):
    id: str
    project_id: str
    document_id: str
    status: str
    priority: str
    used_in_output: bool
    note: str | None = None
    created_at: datetime
    updated_at: datetime
    document: DocumentSummary | None = None


class ProjectDetail(ProjectOut):
    items: list[ProjectItemOut] = Field(default_factory=list)


class DocumentPatch(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    authors: list[dict[str, Any]] | None = None
    universities: list[str] | None = None
    publication_year: int | None = None
    publisher: str | None = None
    journal: str | None = None
    doi: str | None = None
    source_url: str | None = None
    abstract: str | None = None
    rich_summary: str | None = None
    apa_citation: str | None = None
    apa_in_text_citation: str | None = None
    citation_status: str | None = None
    read_status: str | None = None
    priority: str | None = None
    tag_ids: list[str] | None = None
    tag_names: list[str] | None = None
    domain_ids: list[str] | None = None
    attribute_values: dict[str, Any] | None = None


class DocumentPagePatch(BaseModel):
    normalized_text: str


class DocumentTextScrub(BaseModel):
    text: str = Field(min_length=1)


class ImportBatchOut(ApiModel):
    id: str
    label: str | None = None
    status: str
    total_files: int
    completed_files: int
    failed_files: int
    shared_defaults: dict[str, Any]
    created_at: datetime


class ImportJobOut(ApiModel):
    id: str
    batch_id: str
    document_id: str | None = None
    document_title: str | None = None
    original_filename: str | None = None
    file_size_bytes: int | None = None
    document_page_count: int | None = None
    status: str
    current_step: str
    current_model: str | None = None
    estimated_cost_usd: float = 0.0
    estimated_cost_basis: str = "none"
    estimated_cost_page_count: int | None = None
    attempts: int
    last_error: str | None = None
    locked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ImportQueueActionOut(ApiModel):
    matched_count: int
    updated_count: int
    skipped_running_count: int = 0
    skipped_unretryable_count: int = 0


class ProcessingEventOut(ApiModel):
    id: str
    import_job_id: str | None = None
    document_id: str | None = None
    level: str
    event_type: str
    message: str
    payload: dict[str, Any]
    created_at: datetime


class DocumentCompositionEntryOut(BaseModel):
    label: str | None = None
    stage_key: str | None = None
    stage_label: str | None = None
    provider: str | None = None
    method: str | None = None
    model: str | None = None
    record_kind: str | None = None
    status: str | None = None
    message: str | None = None
    amount_usd: float = 0.0
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    sequence: int | None = None
    created_at: datetime | None = None


class DocumentCompositionEstimateOut(BaseModel):
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    variance_usd: float | None = None
    variance_percent: float | None = None
    actual_to_estimate_ratio: float | None = None
    estimated_page_count: int | None = None
    basis: str | None = None
    status: str = "pending"
    created_at: datetime | None = None


class DocumentCompositionOut(BaseModel):
    document_id: str
    available: bool
    total_estimated_cost_usd: float = 0.0
    total_duration_seconds: int = 0
    cost_entries: list[DocumentCompositionEntryOut] = Field(default_factory=list)
    provider_breakdown: list[DocumentCompositionEntryOut] = Field(default_factory=list)
    local_duration_entries: list[DocumentCompositionEntryOut] = Field(default_factory=list)
    pipeline: list[DocumentCompositionEntryOut] = Field(default_factory=list)
    errata: list[DocumentCompositionEntryOut] = Field(default_factory=list)
    estimate_comparison: DocumentCompositionEstimateOut | None = None


class NoteCreate(BaseModel):
    title: str
    body: str
    kind: str = "note"
    document_id: str | None = None
    domain_id: str | None = None
    project_id: str | None = None
    reminder_at: datetime | None = None


class NotePatch(BaseModel):
    title: str | None = None
    body: str | None = None
    kind: str | None = None
    document_id: str | None = None
    domain_id: str | None = None
    project_id: str | None = None
    reminder_at: datetime | None = None


class NoteOut(ApiModel):
    id: str
    title: str
    body: str
    kind: str
    document_id: str | None = None
    domain_id: str | None = None
    project_id: str | None = None
    reminder_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CitationCandidateOut(ApiModel):
    id: str
    document_id: str
    document_title: str | None = None
    source: str
    citation_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="source_metadata", serialization_alias="metadata")
    confidence: float | None = None
    status: str
    created_at: datetime

    @field_validator("document_title", "citation_text", mode="before")
    @classmethod
    def decode_citation_text(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class CitationCandidatePatch(BaseModel):
    status: str | None = None
    apply_to_document: bool = False


class DashboardOut(BaseModel):
    documents: int
    unread: int
    needs_review: int
    queued_jobs: int
    active_import_jobs: int
    import_queued_jobs: int
    import_running_jobs: int
    import_progress_total: int
    import_progress_completed: int
    import_progress_failed: int
    import_active_step: str | None = None
    import_active_elapsed_seconds: int | None = None
    import_active_cost_usd: float = 0.0
    active_concordance_jobs: int
    active_accessory_summary_jobs: int = 0
    failed_jobs: int
    failed_import_jobs: int
    failed_concordance_jobs: int
    failed_accessory_summary_jobs: int = 0
    projects: int


class BackupRunOut(ApiModel):
    id: str
    kind: str
    reason: str | None = None
    status: str
    phase: str
    progress: int
    status_detail: str | None = None
    hostname: str | None = None
    filename: str | None = None
    object_key: str | None = None
    gcs_uri: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    source_kind: str | None = None
    source_filename: str | None = None
    source_uri: str | None = None
    safety_backup_id: str | None = None
    backup_metadata: dict[str, Any]
    last_error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class BackupEstimateOut(BaseModel):
    database_size_bytes: int | None = None
    estimated_size_bytes: int | None = None
    latest_backup_size_bytes: int | None = None
    latest_backup_completed_at: str | None = None
    basis: str


class BackupArtifactOut(BaseModel):
    id: str
    filename: str
    object_key: str
    gcs_uri: str
    size_bytes: int
    sha256: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    hostname: str | None = None
    verified: bool = False
    manifest: dict[str, Any] = Field(default_factory=dict)


class RestoreDatabaseCreate(BaseModel):
    gcs_uri: str


class ModelOptionGroupOut(BaseModel):
    label: str
    options: list[str]


class AnalysisModelTaskOut(BaseModel):
    key: str
    label: str
    model_kind: str
    default_model: str
    selected_model: str
    description: str
    option_groups: list[ModelOptionGroupOut] = Field(default_factory=list)


class AppPreferencesOut(BaseModel):
    import_worker_concurrency: int
    recommended_import_worker_concurrency: int
    import_worker_cost_warning_threshold: int
    accent_color_day: str
    accent_color_night: str
    document_cache_size_mb: int
    library_alternating_rows: bool
    download_naming_template: str
    citation_convention: str
    gcs_bucket: str
    gcs_bucket_saved: bool
    google_service_account_name: str
    google_service_account_project_id: str | None = None
    google_service_account_uploaded: bool
    google_service_account_source: str
    google_service_account_uploaded_at: str | None = None
    analysis_models: dict[str, str]
    analysis_model_tasks: list[AnalysisModelTaskOut]
    model_options: dict[str, list[str]]


class AppPreferencesPatch(BaseModel):
    import_worker_concurrency: int | None = Field(default=None, ge=1)
    accent_color_day: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    accent_color_night: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    document_cache_size_mb: int | None = Field(default=None, ge=0)
    library_alternating_rows: bool | None = None
    download_naming_template: str | None = Field(default=None, max_length=240)
    citation_convention: str | None = Field(default=None, pattern=r"^apa_7$")
    gcs_bucket: str | None = None
    analysis_models: dict[str, str] | None = None


class DocumentCacheStatusOut(BaseModel):
    current_size_bytes: int
    current_size_mb: int
    file_count: int


class OpenAIUsageTotalsOut(BaseModel):
    request_count: int
    successful_request_count: int
    failed_request_count: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    input_file_bytes: int
    input_text_characters: int
    output_text_characters: int
    oldest_created_at: datetime | None = None
    newest_created_at: datetime | None = None
    estimated_cost_usd: float
    priced_request_count: int
    unpriced_request_count: int


class OpenAIUsageGroupOut(BaseModel):
    group_key: str | None = None
    label: str | None = None
    request_count: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    input_file_bytes: int
    failed_request_count: int
    task_key: str | None = None
    model: str | None = None
    provider: str | None = None
    document_id: str | None = None
    calendar_start: datetime | None = None
    estimated_cost_usd: float
    priced_request_count: int
    unpriced_request_count: int


class OpenAIUsageRecentOut(BaseModel):
    id: str
    created_at: datetime
    document_id: str | None = None
    source: str | None = None
    task_key: str
    operation: str
    provider: str = "openai"
    model: str
    endpoint: str
    status: str
    page_number: int | None = None
    used_pdf_file: bool
    input_file_bytes: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None = None
    error_message: str | None = None


class OpenAIUsagePricingOut(BaseModel):
    basis: str
    source_url: str
    source_urls: dict[str, str] = Field(default_factory=dict)
    updated_at: str


class OpenAIUsageOut(BaseModel):
    period: str
    summary: OpenAIUsageTotalsOut
    by_task: list[OpenAIUsageGroupOut]
    by_model: list[OpenAIUsageGroupOut]
    by_document: list[OpenAIUsageGroupOut] = Field(default_factory=list)
    by_calendar_day: list[OpenAIUsageGroupOut] = Field(default_factory=list)
    by_calendar_hour: list[OpenAIUsageGroupOut] = Field(default_factory=list)
    recent: list[OpenAIUsageRecentOut]
    pricing: OpenAIUsagePricingOut


class BibliographyOut(BaseModel):
    project_id: str
    apa: str
    bibtex: str
    ris: str
    csl_json: list[dict[str, Any]]

    @field_validator("apa", "bibtex", "ris", mode="before")
    @classmethod
    def decode_bibliography_text(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class ConcordanceCapabilityOut(BaseModel):
    key: str
    label: str
    version: int
    description: str


class ConcordanceRunCreate(BaseModel):
    label: str | None = None
    scope_type: str = "library"
    scope_data: dict[str, Any] = Field(default_factory=dict)
    capability_keys: list[str] | None = None
    force: bool = False


class ConcordanceRunOut(ApiModel):
    id: str
    label: str | None = None
    scope_type: str
    scope_data: dict[str, Any]
    capability_keys: list[str]
    status: str
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    created_at: datetime
    updated_at: datetime


class ConcordanceJobOut(ApiModel):
    id: str
    run_id: str
    document_id: str
    capability_key: str
    target_version: int
    status: str
    attempts: int
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
