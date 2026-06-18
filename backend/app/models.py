from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator, UserDefinedType

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class JsonDict(TypeDecorator):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB)
        return dialect.type_descriptor(JSON)


class Vector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int = 1536):
        self.dimensions = dimensions

    def get_col_spec(self, **_: Any) -> str:
        return f"VECTOR({self.dimensions})"


document_domains = Table(
    "document_domains",
    Base.metadata,
    Column("document_id", String(36), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("domain_id", String(36), ForeignKey("domains.id", ondelete="CASCADE"), primary_key=True),
)

document_tags = Table(
    "document_tags",
    Base.metadata,
    Column("document_id", String(36), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", String(36), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False, default="Medusa User")
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sessions: Mapped[list["SessionToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class SessionToken(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship(back_populates="sessions")


class Domain(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("domains.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    parent: Mapped["Domain | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Domain"]] = relationship(back_populates="parent")
    documents: Mapped[list["Document"]] = relationship(secondary=document_domains, back_populates="domains")

    __table_args__ = (UniqueConstraint("parent_id", "name", name="uq_domains_parent_name"),)


class Tag(Base, TimestampMixin):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), default="keyword", nullable=False)
    color: Mapped[str | None] = mapped_column(String(32))

    documents: Mapped[list["Document"]] = relationship(secondary=document_tags, back_populates="tags")


class SavedSearch(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "saved_searches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    query: Mapped[str | None] = mapped_column(Text)
    filters: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Document(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(600), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(600))
    authors: Mapped[list[dict[str, Any]]] = mapped_column(JsonDict, default=list, nullable=False)
    universities: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    publisher: Mapped[str | None] = mapped_column(String(300))
    journal: Mapped[str | None] = mapped_column(String(300))
    doi: Mapped[str | None] = mapped_column(String(256), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    rich_summary: Mapped[str | None] = mapped_column(Text)
    apa_citation: Mapped[str | None] = mapped_column(Text)
    citation_status: Mapped[str] = mapped_column(String(40), default="needs_review", nullable=False, index=True)
    metadata_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    metadata_evidence: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), default="application/pdf", nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gcs_uri: Mapped[str | None] = mapped_column(Text)
    storage_status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    processing_status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    read_status: Mapped[str] = mapped_column(String(40), default="unread", nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(40), default="normal", nullable=False, index=True)
    search_text: Mapped[str | None] = mapped_column(Text)

    domains: Mapped[list[Domain]] = relationship(secondary=document_domains, back_populates="documents")
    tags: Mapped[list[Tag]] = relationship(secondary=document_tags, back_populates="documents")
    versions: Mapped[list["DocumentVersion"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    pages: Mapped[list["DocumentPage"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    chunks: Mapped[list["TextChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    figures: Mapped[list["Figure"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        primaryjoin="and_(Document.id == Annotation.document_id, Annotation.deleted_at.is_(None))",
    )
    notes: Mapped[list["Note"]] = relationship(back_populates="document")
    attributes: Mapped[list["DocumentAttributeValue"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    capabilities: Mapped[list["DocumentCapability"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentVersion(Base, TimestampMixin):
    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    change_note: Mapped[str | None] = mapped_column(Text)
    metadata_snapshot: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)

    document: Mapped[Document] = relationship(back_populates="versions")


class DocumentPage(Base, TimestampMixin):
    __tablename__ = "document_pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    text_source: Mapped[str] = mapped_column(String(40), default="pdf", nullable=False)
    low_text: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image_uri: Mapped[str | None] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="pages")

    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_document_pages_page"),)


class TextChunk(Base, TimestampMixin):
    __tablename__ = "text_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Figure(Base, TimestampMixin):
    __tablename__ = "figures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    figure_label: Mapped[str | None] = mapped_column(String(120))
    caption: Mapped[str | None] = mapped_column(Text)
    gist: Mapped[str | None] = mapped_column(Text)
    asset_uri: Mapped[str | None] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="figures")


class Annotation(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40), default="highlight", nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    geometry: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    color: Mapped[str | None] = mapped_column(String(32))

    document: Mapped[Document] = relationship(back_populates="annotations")


class Note(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="SET NULL"))
    domain_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("domains.id", ondelete="SET NULL"))
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), default="note", nullable=False)
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document | None] = relationship(back_populates="notes")


class AttributeDefinition(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "attribute_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    value_type: Mapped[str] = mapped_column(String(40), default="markdown", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    values: Mapped[list["DocumentAttributeValue"]] = relationship(back_populates="definition")


class DocumentAttributeValue(Base, TimestampMixin):
    __tablename__ = "document_attribute_values"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    attribute_definition_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("attribute_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    value: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)

    document: Mapped[Document] = relationship(back_populates="attributes")
    definition: Mapped[AttributeDefinition] = relationship(back_populates="values")

    __table_args__ = (UniqueConstraint("document_id", "attribute_definition_id", name="uq_doc_attribute"),)


class DocumentCapability(Base, TimestampMixin):
    __tablename__ = "document_capabilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    capability_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="complete", nullable=False, index=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="capabilities")

    __table_args__ = (UniqueConstraint("document_id", "capability_key", name="uq_document_capability"),)


class Project(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(240), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)

    items: Mapped[list["ProjectItem"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectItem(Base, TimestampMixin):
    __tablename__ = "project_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="candidate", nullable=False)
    priority: Mapped[str] = mapped_column(String(40), default="normal", nullable=False)
    used_in_output: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="items")
    document: Mapped[Document] = relationship()

    __table_args__ = (UniqueConstraint("project_id", "document_id", name="uq_project_document"),)


class ProjectBibliography(Base, TimestampMixin):
    __tablename__ = "project_bibliographies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    style: Mapped[str] = mapped_column(String(40), default="apa7", nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class ImportBatch(Base, TimestampMixin):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    label: Mapped[str | None] = mapped_column(String(240))
    shared_defaults: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False)
    total_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    jobs: Mapped[list["ImportJob"]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class ImportJob(Base, TimestampMixin):
    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    current_step: Mapped[str] = mapped_column(String(80), default="stored", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    batch: Mapped[ImportBatch] = relationship(back_populates="jobs")
    document: Mapped[Document | None] = relationship()
    events: Mapped[list["ProcessingEvent"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class ProcessingEvent(Base, TimestampMixin):
    __tablename__ = "processing_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    import_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("import_jobs.id", ondelete="CASCADE"))
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(40), default="info", nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)

    job: Mapped[ImportJob | None] = relationship(back_populates="events")


class ConcordanceRun(Base, TimestampMixin):
    __tablename__ = "concordance_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    label: Mapped[str | None] = mapped_column(String(240))
    scope_type: Mapped[str] = mapped_column(String(40), default="library", nullable=False, index=True)
    scope_data: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    capability_keys: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    total_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    jobs: Mapped[list["ConcordanceJob"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class ConcordanceJob(Base, TimestampMixin):
    __tablename__ = "concordance_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("concordance_runs.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    capability_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    target_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[ConcordanceRun] = relationship(back_populates="jobs")
    document: Mapped[Document] = relationship()

    __table_args__ = (UniqueConstraint("run_id", "document_id", "capability_key", name="uq_concordance_job"),)


class CitationCandidate(Base, TimestampMixin):
    __tablename__ = "citation_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    citation_text: Mapped[str | None] = mapped_column(Text)
    source_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(String(40), default="candidate", nullable=False)
