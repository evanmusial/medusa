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


class DomainOut(ApiModel):
    id: str
    parent_id: str | None = None
    name: str
    description: str | None = None
    color: str | None = None
    sort_order: int
    document_count: int = 0


class TagCreate(BaseModel):
    name: str
    kind: str = "keyword"
    color: str | None = None


class TagOut(ApiModel):
    id: str
    name: str
    kind: str
    color: str | None = None


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
    attempts: int
    last_error: str | None = None
    locked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


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
    gcs_bucket: str | None = None
    analysis_models: dict[str, str] | None = None


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
