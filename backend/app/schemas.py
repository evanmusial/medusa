from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(ApiModel):
    id: str
    email: str
    display_name: str


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


class DocumentSummary(ApiModel):
    id: str
    title: str
    authors: list[dict[str, Any]]
    publication_year: int | None = None
    journal: str | None = None
    doi: str | None = None
    rich_summary: str | None = None
    apa_citation: str | None = None
    citation_status: str
    metadata_confidence: float | None = None
    original_filename: str
    checksum_sha256: str
    page_count: int
    processing_status: str
    read_status: str
    priority: str
    created_at: datetime
    tags: list[TagOut] = Field(default_factory=list)
    domains: list[DomainOut] = Field(default_factory=list)


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
    annotations: list[AnnotationOut] = Field(default_factory=list)


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
    citation_status: str | None = None
    read_status: str | None = None
    priority: str | None = None
    tag_ids: list[str] | None = None
    tag_names: list[str] | None = None
    domain_ids: list[str] | None = None
    attribute_values: dict[str, Any] | None = None


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
    status: str
    current_step: str
    attempts: int
    last_error: str | None = None
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
    source: str
    citation_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="source_metadata", serialization_alias="metadata")
    confidence: float | None = None
    status: str
    created_at: datetime


class CitationCandidatePatch(BaseModel):
    status: str | None = None
    apply_to_document: bool = False


class DashboardOut(BaseModel):
    documents: int
    unread: int
    needs_review: int
    queued_jobs: int
    failed_jobs: int
    projects: int


class BibliographyOut(BaseModel):
    project_id: str
    apa: str
    bibtex: str
    ris: str
    csl_json: list[dict[str, Any]]


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
