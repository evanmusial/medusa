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


class AccountUpdateRequest(BaseModel):
    email: str | None = None
    current_password: str
    new_password: str | None = None
    new_password_confirmation: str | None = None


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
    tag_ids: list[str] = Field(default_factory=list)


class DomainPatch(BaseModel):
    name: str | None = None
    parent_id: str | None = None
    description: str | None = None
    color: str | None = None
    sort_order: int | None = None
    tag_ids: list[str] | None = None


class DomainReorderItem(BaseModel):
    id: str
    parent_id: str | None = None
    sort_order: int


class DomainReorder(BaseModel):
    domains: list[DomainReorderItem] = Field(min_length=1)


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


class DomainOut(ApiModel):
    id: str
    parent_id: str | None = None
    name: str
    description: str | None = None
    color: str | None = None
    sort_order: int
    document_count: int = 0
    tags: list[TagOut] = Field(default_factory=list)


class DomainDeleteOut(BaseModel):
    deleted_id: str
    updated_documents: int


class DocumentTrashRequest(BaseModel):
    document_ids: list[str] = Field(min_length=1)


class DocumentTrashOut(BaseModel):
    trashed: int
    document_ids: list[str] = Field(default_factory=list)


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


class FigurePatch(BaseModel):
    figure_label: str | None = Field(default=None, max_length=120)
    caption: str | None = None
    gist: str | None = None


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
    checksum_md5: str | None = None
    page_count: int
    processing_status: str
    read_status: str
    priority: str
    created_at: datetime
    updated_at: datetime
    duplicate_count: int = 0
    duplicate_reasons: list[str] = Field(default_factory=list)
    tags: list[TagOut] = Field(default_factory=list)
    domains: list[DomainOut] = Field(default_factory=list)
    projects: list[ProjectOut] = Field(default_factory=list)

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
    bibliography: str | None = None
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

    @field_validator("subtitle", "publisher", "source_url", "abstract", "bibliography", "search_text", mode="before")
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
    relation_family: str = "closest"
    reason_chips: list[str] = Field(default_factory=list)
    known_status: str = "new"
    hidden_reason: str | None = None
    diversity_score: float | None = None
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
    authors: list[dict[str, Any]] = Field(default_factory=list)
    publication_year: int | None = None
    journal: str | None = None
    description: str | None = None
    page_count: int | None = None
    metadata_source: str | None = None
    source_url: str | None = None
    source_provider: str | None = None
    source_document_id: str | None = None
    recommendation_id: str | None = None
    imported_document_id: str | None = None
    imported_document_title: str | None = None
    library_match_basis: str | None = None
    import_job_id: str | None = None
    import_job_status: str | None = None
    status: str
    uploaded_filename: str | None = None
    imported_at: datetime | None = None
    stash_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_validator("doi", "title", "journal", "description", "metadata_source", "source_url", "source_provider", "uploaded_filename", mode="before")
    @classmethod
    def decode_stash_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class DoiStashImportOut(BaseModel):
    stash: DoiStashOut
    batch_id: str
    queued_count: int
    skipped_existing_count: int
    unavailable_count: int
    failed_count: int
    message: str | None = None


class ImportDuplicateDocumentOut(BaseModel):
    id: str
    title: str
    original_filename: str
    created_at: datetime
    processing_status: str
    match_reasons: list[str] = Field(default_factory=list)
    match_basis: str | None = None
    match_score: int = 0


class ImportDuplicateFileOut(BaseModel):
    filename: str
    checksum_sha256: str
    checksum_md5: str | None = None
    file_size_bytes: int
    source_kind: str = "pdf"
    stored_filename: str | None = None
    detected_title: str | None = None
    existing_documents: list[ImportDuplicateDocumentOut] = Field(default_factory=list)
    duplicate_in_upload: bool = False
    duplicate_reasons: list[str] = Field(default_factory=list)


class ImportDuplicateCheckOut(BaseModel):
    files: list[ImportDuplicateFileOut]
    duplicate_file_count: int


class DuplicateDocumentOut(BaseModel):
    id: str
    title: str
    authors: list[dict[str, Any]]
    publication_year: int | None = None
    journal: str | None = None
    doi: str | None = None
    original_filename: str
    checksum_sha256: str
    checksum_md5: str | None = None
    page_count: int
    processing_status: str
    citation_status: str
    created_at: datetime
    updated_at: datetime
    version_count: int = 0
    latest_version_at: datetime | None = None


class DuplicatePairOut(BaseModel):
    id: str
    left: DuplicateDocumentOut
    right: DuplicateDocumentOut
    match_reasons: list[str]
    match_basis: str
    match_score: int


class DuplicateScanOut(BaseModel):
    pairs: list[DuplicatePairOut]
    pair_count: int
    document_count: int


class DuplicateResolveCreate(BaseModel):
    keep_document_id: str
    duplicate_document_id: str


class DuplicateResolveOut(BaseModel):
    keep_document_id: str
    duplicate_document_id: str
    status: str = "resolved"


class DuplicateDismissCreate(BaseModel):
    left_document_id: str
    right_document_id: str


class DuplicateDismissOut(BaseModel):
    left_document_id: str
    right_document_id: str
    status: str = "dismissed"


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
    bibliography: str | None = None
    apa_citation: str | None = None
    apa_in_text_citation: str | None = None
    citation_status: str | None = None
    read_status: str | None = None
    priority: str | None = None
    tag_ids: list[str] | None = None
    tag_names: list[str] | None = None
    domain_ids: list[str] | None = None
    project_ids: list[str] | None = None
    attribute_values: dict[str, Any] | None = None


class DocumentPagePatch(BaseModel):
    normalized_text: str


class DocumentTextScrub(BaseModel):
    text: str = Field(min_length=1)


class DocumentVisualPageScanCreate(BaseModel):
    page_number: int = Field(ge=1)


class VisualScanCandidateOut(ApiModel):
    candidate_id: str
    page_number: int
    figure_label: str | None = None
    caption: str | None = None
    gist: str | None = None
    geometry: dict[str, Any] = Field(default_factory=dict)
    image_data_url: str


class DocumentVisualPageScanReviewOut(ApiModel):
    document_id: str
    page_number: int
    figures: int
    replaced_figures: int = 0
    preserved_existing: bool = False
    candidates: list[VisualScanCandidateOut] = Field(default_factory=list)
    replaced_page_figures: list[FigureOut] = Field(default_factory=list)
    audit_warnings: list[dict[str, Any]] = Field(default_factory=list)


class DocumentVisualPageScanApplyCreate(BaseModel):
    page_number: int = Field(ge=1)
    candidates: list[VisualScanCandidateOut] = Field(default_factory=list)


class ImportBatchOut(ApiModel):
    id: str
    label: str | None = None
    status: str
    total_files: int
    completed_files: int
    failed_files: int
    shared_defaults: dict[str, Any]
    created_at: datetime


class IngestionHistoryOut(BaseModel):
    batch_id: str
    label: str | None = None
    status: str
    active: bool = False
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    queued_files: int = 0
    running_files: int = 0
    staged_files: int = 0
    cleared_files: int = 0
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    cost_variance_usd: float | None = None
    cost_per_document_usd: float | None = None
    total_size_bytes: int = 0
    processing_preset_id: str | None = None
    processing_preset_name: str | None = None
    processing_preset_mode: str | None = None
    latest_stage: str | None = None
    duration_seconds: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


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
    processing_preset_id: str | None = None
    processing_preset_name: str | None = None
    processing_preset_mode: str | None = None
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
    deleted_documents: int = 0
    deleted_cache_files: int = 0
    deleted_original_objects: int = 0


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
    domains: int
    tags: int
    notes: int
    review_items: int
    stashes: int
    queued_jobs: int
    queue_import_jobs: int
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


class DatabaseMaintenanceStatusOut(BaseModel):
    import_cache_count: int = 0
    document_hash_missing_count: int = 0
    hidden_project_item_count: int = 0
    terminal_import_job_count: int = 0
    orphan_import_job_count: int = 0
    database_size_bytes: int | None = None
    active_operation: str | None = None
    active_operation_label: str | None = None
    active_operation_started_at: datetime | None = None
    active_operation_elapsed_seconds: float | None = None
    active_operation_status_detail: str | None = None
    last_operation: str | None = None
    last_operation_status: str | None = None
    last_operation_completed_at: datetime | None = None
    last_operation_status_detail: str | None = None
    last_operation_error: str | None = None
    last_operation_database_size_before_bytes: int | None = None
    last_operation_database_size_after_bytes: int | None = None


class DatabaseMaintenanceResultOut(DatabaseMaintenanceStatusOut):
    operation: str
    status: str = "complete"
    message: str
    database_size_before_bytes: int | None = None
    database_size_after_bytes: int | None = None
    removed_import_documents: int = 0
    removed_project_items: int = 0
    removed_import_jobs: int = 0
    removed_orphan_import_jobs: int = 0
    deleted_cache_files: int = 0
    deleted_original_objects: int = 0
    hashed_documents: int = 0
    hash_failed_documents: int = 0


class ContainerFilesystemOut(BaseModel):
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int


class ContainerPathFootprintOut(BaseModel):
    label: str
    path: str
    exists: bool
    size_bytes: int = 0
    file_count: int = 0
    directory_count: int = 0


class ContainerRuntimeVersionOut(BaseModel):
    name: str
    version: str
    source: str
    status: str = "reported"
    note: str | None = None


class ContainerDockerLayerOut(BaseModel):
    id: str
    created_by: str | None = None
    size_bytes: int = 0
    tags: list[str] = Field(default_factory=list)
    comment: str | None = None


class ContainerDockerImageOut(BaseModel):
    id: str
    repo_tags: list[str] = Field(default_factory=list)
    size_bytes: int | None = None
    virtual_size_bytes: int | None = None
    shared_size_bytes: int | None = None
    unique_size_bytes: int | None = None
    containers: int | None = None
    layer_count: int = 0
    layers: list[ContainerDockerLayerOut] = Field(default_factory=list)


class ContainerFootprintStatusOut(BaseModel):
    checked_at: datetime
    hostname: str
    containerized: bool
    docker_socket_available: bool
    docker_engine_note: str
    docker_image: ContainerDockerImageOut | None = None
    restart_available: bool
    restart_mode: str
    restart_note: str
    restart_requested_at: datetime | None = None
    process_uptime_seconds: int
    memory_current_bytes: int | None = None
    memory_limit_bytes: int | None = None
    memory_peak_bytes: int | None = None
    process_rss_bytes: int | None = None
    cpu_limit_cores: float | None = None
    cpu_usage_seconds: float | None = None
    process_count: int | None = None
    thread_count: int | None = None
    platform: str
    python_version: str
    data_dir: str
    data_dir_size_bytes: int
    data_filesystem: ContainerFilesystemOut | None = None
    root_filesystem: ContainerFilesystemOut | None = None
    paths: list[ContainerPathFootprintOut] = Field(default_factory=list)
    runtime_versions: list[ContainerRuntimeVersionOut] = Field(default_factory=list)


class ContainerRestartOut(BaseModel):
    status: str
    message: str
    restart_mode: str
    poll_after_seconds: float = 2.0


class ReleaseVersionOut(BaseModel):
    version: str | None = None
    git_sha: str | None = None
    git_sha_short: str | None = None
    branch: str | None = None
    built_at: str | None = None
    source: str = "unknown"


class ReleaseStatusOut(BaseModel):
    checked_at: datetime
    running: ReleaseVersionOut
    available: ReleaseVersionOut | None = None
    update_available: bool = False
    apply_available: bool = False
    browser_reload_recommended: bool = False
    phase: str = "unknown"
    message: str
    status_source: str
    requested_at: datetime | None = None
    request_id: str | None = None
    last_error: str | None = None
    dirty: bool = False


class HAProxyServiceStatOut(BaseModel):
    proxy_name: str
    service_name: str
    kind: str
    status: str | None = None
    current_sessions: int = 0
    max_sessions: int = 0
    total_sessions: int = 0
    session_rate: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    denied_requests: int = 0
    denied_responses: int = 0
    error_requests: int = 0
    error_connections: int = 0
    error_responses: int = 0
    retries: int = 0
    redispatches: int = 0
    active_servers: int | None = None
    backup_servers: int | None = None
    check_status: str | None = None
    check_code: int | None = None
    check_duration_ms: int | None = None
    last_change_seconds: int | None = None
    downtime_seconds: int | None = None


class HAProxyStatsStatusOut(BaseModel):
    checked_at: datetime
    available: bool
    message: str
    public_url: str
    stats_url: str
    total_current_sessions: int = 0
    total_sessions: int = 0
    total_bytes_in: int = 0
    total_bytes_out: int = 0
    total_errors: int = 0
    services: list[HAProxyServiceStatOut] = Field(default_factory=list)


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


class ModelPricingStatusOut(BaseModel):
    basis: str
    price_basis: str = "standard"
    openai_pricing_tier: str = "standard"
    source_url: str
    source_urls: dict[str, str] = Field(default_factory=dict)
    updated_at: str
    last_refreshed_at: datetime | None = None
    stale: bool = True
    stale_after_days: int = 2
    model_count: int = 0
    current_model_count: int = 0
    missing_current_model_count: int = 0
    provider_counts: dict[str, int] = Field(default_factory=dict)
    checked_count: int = 0
    inserted_count: int = 0
    changed_count: int = 0
    unchanged_count: int = 0


class ImportProcessingStepOut(BaseModel):
    key: str
    label: str
    description: str
    accomplishes: str
    tooltip: str
    default_enabled: bool = True
    configurable: bool = True


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
    model_pricing: ModelPricingStatusOut
    import_processing_presets: list[dict[str, Any]] = Field(default_factory=list)
    default_import_processing_preset_id: str = "balanced"
    import_processing_steps: list[ImportProcessingStepOut] = Field(default_factory=list)
    second_pass_processing_enabled: bool = True


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
    import_processing_presets: list[dict[str, Any]] | None = None
    default_import_processing_preset_id: str | None = None
    second_pass_processing_enabled: bool | None = None


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


class OpenAIUsagePricingOut(ModelPricingStatusOut):
    pass


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


class ConcordanceEstimateItemOut(BaseModel):
    document_id: str
    document_title: str | None = None
    capability_key: str
    capability_label: str
    target_version: int
    status: str
    reason: str | None = None
    estimated_cost_usd: float = 0.0
    estimate_basis: str = "none"
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    cost_steps: list[dict[str, Any]] = Field(default_factory=list)


class ConcordanceRunEstimateOut(BaseModel):
    scope_type: str
    scope_data: dict[str, Any]
    capability_keys: list[str]
    document_count: int
    planned_jobs: int
    skipped_jobs: int
    model_no_op_jobs: int
    already_queued_jobs: int
    current_version_jobs: int
    estimated_cost_usd: float
    priced_call_count: int
    unpriced_call_count: int
    local_job_count: int
    items: list[ConcordanceEstimateItemOut]


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
