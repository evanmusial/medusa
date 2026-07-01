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
    otp_code: str | None = None


class AccountUpdateRequest(BaseModel):
    email: str | None = None
    current_password: str
    new_password: str | None = None
    new_password_confirmation: str | None = None


class UserOut(ApiModel):
    id: str
    email: str
    display_name: str
    two_factor_enabled: bool = False
    two_factor_recovery_codes_remaining: int = 0


class TwoFactorSetupRequest(BaseModel):
    current_password: str


class TwoFactorSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TwoFactorEnableRequest(BaseModel):
    current_password: str
    secret: str
    otp_code: str


class TwoFactorEnableOut(BaseModel):
    user: UserOut
    recovery_codes: list[str]


class TwoFactorDisableRequest(BaseModel):
    current_password: str
    otp_code: str


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
    subtree_document_count: int = 0
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


class ReconInquiryCreate(BaseModel):
    title: str | None = None
    question: str = Field(min_length=1)
    instructions: str | None = None
    scope_type: str = "library"
    scope: dict[str, Any] = Field(default_factory=dict)
    default_mode: str = "quick_answer"
    model: str | None = None


class ReconInquiryPatch(BaseModel):
    title: str | None = None
    question: str | None = None
    instructions: str | None = None
    scope_type: str | None = None
    scope: dict[str, Any] | None = None
    default_mode: str | None = None
    model: str | None = None
    status: str | None = None


class ReconRunCreate(BaseModel):
    mode: str | None = None
    model: str | None = None


class ReconEstimateOut(BaseModel):
    mode: str
    scope_type: str
    resolved_document_count: int
    estimated_evidence_count: int
    estimated_input_tokens: int
    estimated_cost_usd: float | None = None
    warnings: list[str] = Field(default_factory=list)


class ReconEvidenceOut(ApiModel):
    id: str
    run_id: str
    document_id: str | None = None
    text_chunk_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    evidence_kind: str
    rank: int
    score: float | None = None
    document_title: str | None = None
    snippet: str
    citation_text: str | None = None
    relevance_label: str
    evidence_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_validator("document_title", "snippet", "citation_text", mode="before")
    @classmethod
    def decode_evidence_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class ReconAnswerVersionOut(ApiModel):
    id: str
    run_id: str
    answer: str
    confidence: float | None = None
    limitations: list[str] = Field(default_factory=list)
    answer_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_validator("answer", mode="before")
    @classmethod
    def decode_answer_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class ReconRunOut(ApiModel):
    id: str
    inquiry_id: str
    mode: str
    model: str
    status: str
    progress: int
    resolved_document_count: int
    evidence_count: int
    estimated_input_tokens: int
    estimated_cost_usd: float | None = None
    answer_summary: str | None = None
    scope_snapshot: dict[str, Any] = Field(default_factory=dict)
    run_metadata: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    evidence: list[ReconEvidenceOut] = Field(default_factory=list)
    answers: list[ReconAnswerVersionOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator("answer_summary", "last_error", mode="before")
    @classmethod
    def decode_run_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class ReconInquiryOut(ApiModel):
    id: str
    title: str
    question: str
    instructions: str | None = None
    scope_type: str
    scope: dict[str, Any] = Field(default_factory=dict)
    default_mode: str
    model: str
    status: str
    inquiry_metadata: dict[str, Any] = Field(default_factory=dict)
    runs: list[ReconRunOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator("title", "question", "instructions", mode="before")
    @classmethod
    def decode_inquiry_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


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
    reader_text: str | None = None
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


class DocumentPublicationOut(BaseModel):
    id: str
    publication_id: str
    role: str = "primary"
    title: str
    type: str | None = None
    publisher: str | None = None
    imprint: str | None = None
    issn_l: str | None = None
    issns: list[str] = Field(default_factory=list)
    isbns: list[str] = Field(default_factory=list)
    doi: str | None = None
    source_url: str | None = None
    external_ids: dict[str, Any] = Field(default_factory=dict)
    appearance_type: str | None = None
    volume: str | None = None
    issue: str | None = None
    article_number: str | None = None
    page_range: str | None = None
    published_date: str | None = None
    published_year: int | None = None
    edition: str | None = None
    chapter: str | None = None
    section: str | None = None
    series_title: str | None = None
    event_name: str | None = None
    identifiers: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    source: str | None = None
    model: str | None = None
    verification_status: str = "unverified"
    verified_at: datetime | None = None
    verified_by: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "title",
        "type",
        "publisher",
        "imprint",
        "doi",
        "source_url",
        "appearance_type",
        "volume",
        "issue",
        "article_number",
        "page_range",
        "published_date",
        "edition",
        "chapter",
        "section",
        "series_title",
        "event_name",
        mode="before",
    )
    @classmethod
    def decode_publication_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class PublicationListRow(BaseModel):
    id: str
    title: str
    type: str | None = None
    publisher: str | None = None
    issn_l: str | None = None
    issns: list[str] = Field(default_factory=list)
    isbns: list[str] = Field(default_factory=list)
    doi: str | None = None
    source_url: str | None = None
    ready_document_count: int = 0

    @field_validator("title", "type", "publisher", "doi", "source_url", mode="before")
    @classmethod
    def decode_publication_row_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class DocumentPublicationPatch(BaseModel):
    clear: bool | None = None
    title: str | None = None
    publication_title: str | None = None
    type: str | None = None
    publication_type: str | None = None
    publisher: str | None = None
    imprint: str | None = None
    issn_l: str | None = None
    issns: list[str] | None = None
    isbns: list[str] | None = None
    doi: str | None = None
    source_url: str | None = None
    external_ids: dict[str, Any] | None = None
    identifiers: dict[str, Any] | None = None
    appearance_type: str | None = None
    volume: str | None = None
    issue: str | None = None
    article_number: str | None = None
    page_range: str | None = None
    published_date: str | None = None
    published_year: int | None = None
    edition: str | None = None
    chapter: str | None = None
    section: str | None = None
    series_title: str | None = None
    event_name: str | None = None
    notes: str | None = None


class DocumentSummary(ApiModel):
    id: str
    title: str
    authors: list[dict[str, Any]]
    publication_year: int | None = None
    journal: str | None = None
    publication: DocumentPublicationOut | None = None
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
    no_doi: bool = False
    original_filename: str
    checksum_sha256: str
    checksum_md5: str | None = None
    page_count: int
    processing_status: str
    read_status: str
    priority: str
    has_verified_fields: bool = False
    has_active_work: bool = False
    is_locked: bool = False
    locked_at: datetime | None = None
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


class DocumentListRow(ApiModel):
    id: str
    title: str
    authors: list[dict[str, Any]]
    publication_year: int | None = None
    publication: DocumentPublicationOut | None = None
    rich_summary: str | None = None
    citation_status: str
    no_doi: bool = False
    page_count: int
    figure_count: int = 0
    processing_status: str
    read_status: str
    priority: str
    has_verified_fields: bool = False
    has_active_work: bool = False
    is_locked: bool = False
    locked_at: datetime | None = None
    updated_at: datetime
    duplicate_count: int = 0
    duplicate_reasons: list[str] = Field(default_factory=list)
    tags: list[TagOut] = Field(default_factory=list)
    domains: list[DomainOut] = Field(default_factory=list)
    projects: list[ProjectOut] = Field(default_factory=list)

    @field_validator("title", "rich_summary", mode="before")
    @classmethod
    def decode_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class DocumentListOut(BaseModel):
    items: list[DocumentListRow]
    total_count: int
    total_page_count: int
    offset: int
    limit: int
    has_more: bool
    revision: str
    focus_document_id: str | None = None
    focus_index: int | None = None


class DocumentDetail(DocumentSummary):
    subtitle: str | None = None
    universities: list[str]
    publisher: str | None = None
    source_url: str | None = None
    abstract: str | None = None
    bibliography: str | None = None
    summary_generated_at: datetime | None = None
    summary_validated_at: datetime | None = None
    summary_validated_by: str | None = None
    bibliography_generated_at: datetime | None = None
    doi_verified_at: datetime | None = None
    doi_verified_by: str | None = None
    apa_citation_verified_at: datetime | None = None
    apa_citation_verified_by: str | None = None
    apa_in_text_citation_verified_at: datetime | None = None
    apa_in_text_citation_verified_by: str | None = None
    bibliography_verified_at: datetime | None = None
    bibliography_verified_by: str | None = None
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


class PortfolioItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=600)
    description: str | None = None
    project_ids: list[str] = Field(default_factory=list)
    domain_ids: list[str] = Field(default_factory=list)
    tag_ids: list[str] = Field(default_factory=list)


class PortfolioItemPatch(BaseModel):
    title: str | None = Field(default=None, max_length=600)
    description: str | None = None
    status: str | None = Field(default=None, max_length=40)
    current_version_id: str | None = None
    project_ids: list[str] | None = None
    domain_ids: list[str] | None = None
    tag_ids: list[str] | None = None


class PortfolioVersionEdgeOut(ApiModel):
    id: str
    parent_version_id: str
    child_version_id: str
    relation_type: str
    edge_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PortfolioVersionOut(ApiModel):
    id: str
    portfolio_item_id: str
    document_id: str
    version_number: int
    label: str | None = None
    upload_note: str | None = None
    source_filename: str
    source_content_type: str
    source_checksum_sha256: str
    source_checksum_md5: str | None = None
    source_storage_uri: str | None = None
    source_size_bytes: int
    processing_status: str
    version_metadata: dict[str, Any] = Field(default_factory=dict)
    document: DocumentSummary | None = None
    parent_edges: list[PortfolioVersionEdgeOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator("label", "upload_note", "source_filename", mode="before")
    @classmethod
    def decode_version_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class PortfolioMaterialOut(ApiModel):
    id: str
    portfolio_item_id: str
    version_id: str | None = None
    document_id: str
    role: str
    label: str | None = None
    required_for_assessment: bool
    notes: str | None = None
    material_metadata: dict[str, Any] = Field(default_factory=dict)
    document: DocumentSummary | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("label", "notes", mode="before")
    @classmethod
    def decode_material_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class PortfolioSuggestionOut(ApiModel):
    id: str
    portfolio_item_id: str
    version_id: str | None = None
    library_document_id: str | None = None
    source_type: str
    title: str
    source_url: str | None = None
    relation_family: str
    score: float | None = None
    status: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    library_document: DocumentSummary | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("title", "source_url", mode="before")
    @classmethod
    def decode_suggestion_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class PortfolioSuggestionRefreshOut(BaseModel):
    portfolio_item_id: str
    suggestion_count: int
    suggestions: list[PortfolioSuggestionOut]


class PortfolioAssessmentCreate(BaseModel):
    mode: str = Field(default="quality_review", max_length=80)
    version_id: str | None = None
    model_ids: list[str] | None = None


class PortfolioAssessmentFindingOut(ApiModel):
    id: str
    assessment_run_id: str
    category: str
    severity: str
    title: str
    body: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: datetime
    updated_at: datetime

    @field_validator("title", "body", mode="before")
    @classmethod
    def decode_finding_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class PortfolioAssessmentRunOut(ApiModel):
    id: str
    portfolio_item_id: str
    version_id: str | None = None
    mode: str
    model_ids: list[str] = Field(default_factory=list)
    status: str
    summary: str | None = None
    assessment_metadata: dict[str, Any] = Field(default_factory=dict)
    scorecard: list[dict[str, Any]] = Field(default_factory=list)
    grade_estimate: dict[str, Any] = Field(default_factory=dict)
    narrative_feedback: dict[str, Any] = Field(default_factory=dict)
    revision_priorities: list[dict[str, Any]] = Field(default_factory=list)
    model_outputs: list[dict[str, Any]] = Field(default_factory=list)
    agreement: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None
    completed_at: datetime | None = None
    findings: list[PortfolioAssessmentFindingOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator("summary", "last_error", mode="before")
    @classmethod
    def decode_assessment_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


class PortfolioItemOut(ApiModel):
    id: str
    title: str
    description: str | None = None
    status: str
    current_version_id: str | None = None
    project_ids: list[str] = Field(default_factory=list)
    domain_ids: list[str] = Field(default_factory=list)
    tag_ids: list[str] = Field(default_factory=list)
    portfolio_metadata: dict[str, Any] = Field(default_factory=dict)
    current_version: PortfolioVersionOut | None = None
    versions: list[PortfolioVersionOut] = Field(default_factory=list)
    materials: list[PortfolioMaterialOut] = Field(default_factory=list)
    suggestions: list[PortfolioSuggestionOut] = Field(default_factory=list)
    assessment_runs: list[PortfolioAssessmentRunOut] = Field(default_factory=list)
    audit_status: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_validator("title", "description", mode="before")
    @classmethod
    def decode_portfolio_text_fields(cls, value: Any) -> Any:
        return decode_html_entity_text(value)


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
    publication: DocumentPublicationPatch | None = None
    confirm_verified_doi_edit: bool | None = None
    confirm_verified_publication_edit: bool | None = None
    confirm_verified_apa_citation_edit: bool | None = None
    confirm_verified_apa_in_text_citation_edit: bool | None = None
    confirm_verified_bibliography_edit: bool | None = None
    confirm_validated_summary_edit: bool | None = None
    apa_citation: str | None = None
    apa_in_text_citation: str | None = None
    citation_status: str | None = None
    no_doi: bool | None = None
    read_status: str | None = None
    priority: str | None = None
    tag_ids: list[str] | None = None
    tag_names: list[str] | None = None
    domain_ids: list[str] | None = None
    project_ids: list[str] | None = None
    attribute_values: dict[str, Any] | None = None


class DocumentLockPatch(BaseModel):
    is_locked: bool


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
    execution_location: str | None = None
    next_stage: str | None = None
    estimated_cost_usd: float = 0.0
    estimated_cost_basis: str = "none"
    estimated_cost_page_count: int | None = None
    processing_preset_id: str | None = None
    processing_preset_name: str | None = None
    processing_preset_mode: str | None = None
    attempts: int
    last_error: str | None = None
    locked_at: datetime | None = None
    assigned_worker_kind: str | None = None
    assigned_client_id: str | None = None
    assigned_client_name: str | None = None
    lease_heartbeat_at: datetime | None = None
    lease_expires_at: datetime | None = None
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


class AIFailureNoticeOut(BaseModel):
    id: str
    created_at: datetime
    document_id: str | None = None
    document_title: str | None = None
    source: str | None = None
    task_key: str
    operation: str
    provider: str = "openai"
    model: str
    endpoint: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    error_message: str | None = None
    estimated_cost_usd: float | None = None


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
    concordance_queued_jobs: int = 0
    concordance_running_jobs: int = 0
    active_accessory_summary_jobs: int = 0
    accessory_summary_queued_jobs: int = 0
    accessory_summary_running_jobs: int = 0
    failed_jobs: int
    failed_import_jobs: int
    failed_concordance_jobs: int
    failed_accessory_summary_jobs: int = 0
    recent_failed_ai_calls: list[AIFailureNoticeOut] = Field(default_factory=list)
    projects: int


class LibraryFunStatsOut(BaseModel):
    checked_at: datetime
    document_count: int = 0
    page_count: int = 0
    page_record_count: int = 0
    figure_count: int = 0
    bibliography_reference_count: int = 0
    bibliography_document_count: int = 0
    parsed_word_count: int = 0
    indexed_word_count: int = 0
    parsed_character_count: int = 0
    indexed_character_count: int = 0
    text_chunk_count: int = 0
    text_chunk_token_count: int = 0
    doi_count: int = 0
    verified_citation_count: int = 0
    unique_author_count: int = 0
    annotation_count: int = 0
    note_count: int = 0
    project_resource_count: int = 0
    used_project_resource_count: int = 0
    domain_count: int = 0
    tag_count: int = 0


class CacheFamilyStatsOut(BaseModel):
    family: str
    hits: int = 0
    misses: int = 0
    bypasses: int = 0
    errors: int = 0
    writes: int = 0
    hit_rate: float = 0.0


class CacheRequestMetricOut(BaseModel):
    route: str
    count: int = 0
    p95_ms: float = 0.0
    average_ms: float = 0.0
    slow_count: int = 0
    last_status: int | None = None


class CacheDatabaseFootprintOut(BaseModel):
    name: str
    kind: str
    total_bytes: int = 0
    relation_bytes: int = 0


class CacheStorageFootprintOut(BaseModel):
    label: str
    path: str
    exists: bool = False
    size_bytes: int = 0
    file_count: int = 0


class CacheQueueStatOut(BaseModel):
    queue: str
    active_count: int = 0
    oldest_age_seconds: int | None = None


class CacheStatusOut(BaseModel):
    checked_at: datetime
    backend: str
    enabled: bool
    reachable: bool
    mode: str
    message: str
    version: str | None = None
    uptime_seconds: int | None = None
    used_memory_bytes: int | None = None
    peak_memory_bytes: int | None = None
    rss_memory_bytes: int | None = None
    maxmemory_bytes: int | None = None
    maxmemory_policy: str | None = None
    key_count: int = 0
    hit_count: int = 0
    miss_count: int = 0
    hit_rate: float = 0.0
    evicted_keys: int = 0
    expired_keys: int = 0
    connected_clients: int = 0
    ops_per_second: float = 0.0
    latency_ms: float | None = None
    last_refresh_at: datetime | None = None
    last_hydration_at: datetime | None = None
    last_invalidation_at: datetime | None = None
    families: list[CacheFamilyStatsOut] = Field(default_factory=list)
    request_metrics: list[CacheRequestMetricOut] = Field(default_factory=list)
    queue_stats: list[CacheQueueStatOut] = Field(default_factory=list)
    database_footprints: list[CacheDatabaseFootprintOut] = Field(default_factory=list)
    storage_footprints: list[CacheStorageFootprintOut] = Field(default_factory=list)


class CacheRefreshOut(BaseModel):
    status: str
    message: str
    refreshed_at: datetime
    refreshed_families: list[str] = Field(default_factory=list)
    warmed_keys: int = 0
    before: CacheStatusOut
    after: CacheStatusOut


class CacheHydrateOut(BaseModel):
    status: str
    message: str
    hydrated_at: datetime
    hydrated_keys: int = 0
    base_keys: int = 0
    document_count: int = 0
    document_detail_keys: int = 0
    list_page_keys: int = 0
    saved_search_keys: int = 0
    organization_keys: int = 0
    skipped_payloads: int = 0
    errored_payloads: int = 0
    before: CacheStatusOut
    after: CacheStatusOut


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
    storage_kind: str | None = None
    storage_label: str | None = None


class BackupArtifactOut(BaseModel):
    id: str
    filename: str
    object_key: str
    uri: str
    storage_kind: str = "local"
    gcs_uri: str | None = None
    local_path: str | None = None
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


class ReleaseHistoryChangeOut(BaseModel):
    title: str
    description: str


class ReleaseHistoryEntryOut(BaseModel):
    id: str
    released_at: datetime
    commit_date: datetime | None = None
    version: str | None = None
    git_sha: str | None = None
    git_sha_short: str | None = None
    previous_git_sha: str | None = None
    branch: str | None = None
    source: str = "release-agent"
    summary: str | None = None
    changes: list[ReleaseHistoryChangeOut] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)


class ReleaseHistoryOut(BaseModel):
    updated_at: datetime | None = None
    entries: list[ReleaseHistoryEntryOut] = Field(default_factory=list)


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
    maintenance_phase: str = "idle"
    maintenance_message: str | None = None
    maintenance_auto_apply_eligible: bool = False
    maintenance_requires_approval: bool = False
    maintenance_update_classification: str = "unknown"
    maintenance_backup_required: bool = False
    maintenance_backup_status: str = "not_required"
    maintenance_backup_run_id: str | None = None
    maintenance_idle: bool = True
    maintenance_active_session_count: int = 0
    maintenance_blockers: list[str] = Field(default_factory=list)
    maintenance_window: str | None = None
    maintenance_last_checked_at: datetime | None = None
    docker_engine_version: str | None = None
    docker_compose_version: str | None = None
    docker_host_updates: str = "report_only"


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
    uri: str | None = None
    gcs_uri: str | None = None


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
    cloud_run_workers_enabled: bool = False
    cloud_run_worker_concurrency: int = 1
    cloud_run_worker_flavor: str = "economy"
    cloud_run_worker_flavor_options: list[dict[str, Any]] = Field(default_factory=list)
    accent_color_day: str
    accent_color_night: str
    document_cache_size_mb: int
    valkey_maxmemory: str
    library_alternating_rows: bool
    library_page_size: int
    library_density: str
    detail_sticky_fields: list[str] = Field(default_factory=list)
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
    cloud_run_workers_enabled: bool | None = None
    cloud_run_worker_concurrency: int | None = Field(default=None, ge=1)
    cloud_run_worker_flavor: str | None = Field(default=None, pattern=r"^(economy|balanced|performance|high_memory)$")
    accent_color_day: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    accent_color_night: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    document_cache_size_mb: int | None = Field(default=None, ge=0)
    valkey_maxmemory: str | None = Field(default=None, max_length=32)
    library_alternating_rows: bool | None = None
    library_page_size: int | None = Field(default=None, ge=10)
    library_density: str | None = Field(default=None, pattern=r"^(compact|comfortable|reading)$")
    detail_sticky_fields: list[str] | None = None
    download_naming_template: str | None = Field(default=None, max_length=240)
    citation_convention: str | None = Field(default=None, pattern=r"^apa_7$")
    gcs_bucket: str | None = None
    analysis_models: dict[str, str] | None = None
    import_processing_presets: list[dict[str, Any]] | None = None
    default_import_processing_preset_id: str | None = None
    second_pass_processing_enabled: bool | None = None


class GcsBucketLifecycleRuleOut(BaseModel):
    index: int
    action_type: str
    action_label: str
    storage_class: str | None = None
    condition_labels: list[str] = Field(default_factory=list)
    summary: str


class GcsBucketLifecycleOut(BaseModel):
    bucket: str
    available: bool = False
    status: str
    summary: str
    rules: list[GcsBucketLifecycleRuleOut] = Field(default_factory=list)
    checked_at: datetime
    error: str | None = None
    storage_class: str | None = None
    location: str | None = None


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
    execution_location: str | None = None
    next_stage: str | None = None
    attempts: int
    last_error: str | None = None
    locked_at: datetime | None = None
    assigned_worker_kind: str | None = None
    assigned_client_id: str | None = None
    assigned_client_name: str | None = None
    lease_heartbeat_at: datetime | None = None
    lease_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SlipstreamRegisterCreate(BaseModel):
    enrollment_token: str
    name: str
    public_key: str
    version: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    capacity: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class SlipstreamClientOut(ApiModel):
    id: str
    name: str
    version: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    capacity: int
    max_capacity: int = 1
    allowed_capabilities: list[str] = Field(default_factory=list)
    active_lease_count: int = 0
    available_capacity: int = 0
    last_detail: str | None = None
    status: str
    last_check_in_at: datetime | None = None
    online: bool = False
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SlipstreamEnrollmentCreate(BaseModel):
    label: str | None = None
    ttl_minutes: int = 60
    capabilities: list[str] = Field(default_factory=lambda: ["import_preprocess"])
    max_capacity: int = 1


class SlipstreamEnrollmentOut(BaseModel):
    id: str
    label: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    max_capacity: int = 1
    status: str
    expires_at: datetime
    used_at: datetime | None = None
    client_id: str | None = None
    token: str | None = None
    created_at: datetime


class SlipstreamCheckInCreate(BaseModel):
    version: str | None = None
    capabilities: list[str] | None = None
    capacity: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SlipstreamClaimCreate(BaseModel):
    job_types: list[str] = Field(default_factory=list)
    worker_kind: str | None = None


class SlipstreamHeartbeatCreate(BaseModel):
    detail: str | None = None


class SlipstreamEventCreate(BaseModel):
    event_type: str = "slipstream_client_event"
    message: str
    level: str = "info"
    payload: dict[str, Any] = Field(default_factory=dict)


class SlipstreamFailCreate(BaseModel):
    error: str
    payload: dict[str, Any] = Field(default_factory=dict)


class SlipstreamResultCreate(BaseModel):
    idempotency_key: str | None = None
    result_kind: str | None = None
    current_step: str | None = None
    document: dict[str, Any] = Field(default_factory=dict)
    pages: list[dict[str, Any]] = Field(default_factory=list)
    capabilities: list[dict[str, Any]] = Field(default_factory=list)
    composition: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SlipstreamLeaseOut(BaseModel):
    id: str
    client_id: str | None = None
    client_name: str | None = None
    worker_kind: str
    job_type: str
    job_id: str
    status: str
    claimed_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    completed_at: datetime | None = None
    canceled_at: datetime | None = None
    last_error: str | None = None


class SlipstreamWorkOut(BaseModel):
    job_type: str
    job_id: str
    lease_id: str
    worker_kind: str = "slipstream"
    work_kind: str = "generic"
    result_mode: str = "complete"
    document_id: str | None = None
    document_title: str | None = None
    original_filename: str | None = None
    checksum_sha256: str | None = None
    artifact_url: str
    idempotency_key: str
    model_preferences: dict[str, str] = Field(default_factory=dict)
    capability_versions: dict[str, int] = Field(default_factory=dict)
    batch_id: str | None = None
    current_step: str | None = None
    processing_preset: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    capability_keys: list[str] = Field(default_factory=list)
    target_version: int | None = None
    cloud_run: dict[str, Any] = Field(default_factory=dict)


class SlipstreamClaimOut(BaseModel):
    lease: SlipstreamLeaseOut | None = None
    lease_token: str | None = None
    work: SlipstreamWorkOut | None = None


class SlipstreamStatusOut(BaseModel):
    enabled: bool
    public_base_url: str | None = None
    heartbeat_seconds: int
    lease_ttl_seconds: int
    require_tls: bool
    clients: list[SlipstreamClientOut] = Field(default_factory=list)
    active_leases: list[SlipstreamLeaseOut] = Field(default_factory=list)
    online_client_count: int = 0
    active_lease_count: int = 0
    oldest_active_lease_age_seconds: int | None = None
    failed_or_expired_lease_count: int = 0


class CloudRunWorkerScalePlanCreate(BaseModel):
    desired_instances: int = Field(ge=0)
    force: bool = False


class CloudRunWorkerStatusOut(BaseModel):
    enabled: bool
    desired_instances: int
    effective_target_instances: int
    max_instances: int
    active_lease_count: int
    online_client_count: int
    job_types: list[str] = Field(default_factory=list)
    flavor: str
    flavor_label: str
    flavor_description: str | None = None
    cpu: float
    memory_gib: float
    region: str
    project: str | None = None
    worker_pool: str
    image: str | None = None
    service_account: str | None = None
    cost: dict[str, Any] = Field(default_factory=dict)
    missing_config: list[str] = Field(default_factory=list)
    commands: dict[str, str] = Field(default_factory=dict)
    can_scale_to_zero: bool
    scale_down_blocked_reason: str | None = None
    clients: list[SlipstreamClientOut] = Field(default_factory=list)
    active_leases: list[SlipstreamLeaseOut] = Field(default_factory=list)


class CloudRunWorkerScalePlanOut(BaseModel):
    desired_instances: int
    effective_target_instances: int
    blocked: bool
    reason: str | None = None
    command: str | None = None
    status: CloudRunWorkerStatusOut
