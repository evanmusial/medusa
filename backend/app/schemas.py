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


class AttributeDefinitionCreate(BaseModel):
    name: str
    value_type: str = "markdown"
    description: str | None = None


class AttributeDefinitionOut(ApiModel):
    id: str
    name: str
    value_type: str
    description: str | None = None


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
    domain_ids: list[str] | None = None


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


class CitationCandidateOut(ApiModel):
    id: str
    document_id: str
    source: str
    citation_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="source_metadata", serialization_alias="metadata")
    confidence: float | None = None
    status: str
    created_at: datetime


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
