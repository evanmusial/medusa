from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
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


domain_tags = Table(
    "domain_tags",
    Base.metadata,
    Column("domain_id", String(36), ForeignKey("domains.id", ondelete="CASCADE"), primary_key=True),
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
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    two_factor_secret: Mapped[str | None] = mapped_column(String(80), nullable=True)
    two_factor_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    two_factor_last_used_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    two_factor_recovery_hashes: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sessions: Mapped[list["SessionToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def two_factor_recovery_codes_remaining(self) -> int:
        return len(self.two_factor_recovery_hashes or [])


class SessionToken(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship(back_populates="sessions")


def _restore_session_token_timezone(session_token: SessionToken) -> None:
    for field in ("expires_at", "last_seen_at", "revoked_at"):
        value = getattr(session_token, field, None)
        if value is not None and value.tzinfo is None:
            setattr(session_token, field, value.replace(tzinfo=timezone.utc))


@event.listens_for(SessionToken, "load")
def _session_token_loaded(session_token: SessionToken, _: object) -> None:
    _restore_session_token_timezone(session_token)


@event.listens_for(SessionToken, "refresh")
def _session_token_refreshed(session_token: SessionToken, _: object, __: object) -> None:
    _restore_session_token_timezone(session_token)


class CacheRevision(Base):
    __tablename__ = "cache_revisions"

    family: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(160), nullable=True)


class AppPreference(Base, TimestampMixin):
    __tablename__ = "app_preferences"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)


class BackupRun(Base, TimestampMixin):
    __tablename__ = "backup_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(40), default="backup", nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(80), default="initializing", nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status_detail: Mapped[str | None] = mapped_column(Text)
    hostname: Mapped[str | None] = mapped_column(String(120))
    filename: Mapped[str | None] = mapped_column(String(512))
    object_key: Mapped[str | None] = mapped_column(Text)
    gcs_uri: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    source_kind: Mapped[str | None] = mapped_column(String(40))
    source_filename: Mapped[str | None] = mapped_column(String(512))
    source_uri: Mapped[str | None] = mapped_column(Text)
    source_local_path: Mapped[str | None] = mapped_column(Text)
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    safety_backup_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("backup_runs.id", ondelete="SET NULL"))
    backup_metadata: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssetDeletionQueue(Base, TimestampMixin):
    __tablename__ = "asset_deletion_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    cdn_url_path: Mapped[str | None] = mapped_column(Text)
    cdn_invalidation_path: Mapped[str | None] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_id: Mapped[str | None] = mapped_column(String(36), index=True)
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    storage_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deletion_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)


class OpenAIUsageRecord(Base, TimestampMixin):
    __tablename__ = "openai_usage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    import_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("import_jobs.id", ondelete="SET NULL"), index=True)
    concordance_run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("concordance_runs.id", ondelete="SET NULL"), index=True)
    concordance_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("concordance_jobs.id", ondelete="SET NULL"), index=True)
    source: Mapped[str | None] = mapped_column(String(80), index=True)
    capability_key: Mapped[str | None] = mapped_column(String(120), index=True)
    task_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), default="openai", nullable=False)
    endpoint: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="success", nullable=False, index=True)
    request_id: Mapped[str | None] = mapped_column(String(160), index=True)
    page_number: Mapped[int | None] = mapped_column(Integer)
    used_pdf_file: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    input_file_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_text_characters: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_text_characters: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reasoning_output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    usage_metadata: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)


class ModelPricingRecord(Base, TimestampMixin):
    __tablename__ = "model_pricing_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    price_basis: Mapped[str] = mapped_column(String(80), default="standard", nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    input_usd_per_million: Mapped[float | None] = mapped_column(Numeric(12, 6))
    cached_input_usd_per_million: Mapped[float | None] = mapped_column(Numeric(12, 6))
    output_usd_per_million: Mapped[float | None] = mapped_column(Numeric(12, 6))
    input_over_200k_usd_per_million: Mapped[float | None] = mapped_column(Numeric(12, 6))
    cached_input_over_200k_usd_per_million: Mapped[float | None] = mapped_column(Numeric(12, 6))
    output_over_200k_usd_per_million: Mapped[float | None] = mapped_column(Numeric(12, 6))
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    pricing_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "model", "price_basis", "observed_at", name="uq_model_pricing_observation"),
    )


class DocumentCompositionRecord(Base, TimestampMixin):
    __tablename__ = "document_composition_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    import_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("import_jobs.id", ondelete="SET NULL"), index=True)
    usage_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("openai_usage_records.id", ondelete="SET NULL"),
        unique=True,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    record_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    stage_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    stage_label: Mapped[str] = mapped_column(String(180), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(80), index=True)
    method: Mapped[str | None] = mapped_column(String(160))
    model: Mapped[str | None] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(120), default="complete", nullable=False, index=True)
    amount_usd: Mapped[float | None] = mapped_column(Numeric(18, 12))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str | None] = mapped_column(Text)
    record_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="composition_records")
    import_job: Mapped["ImportJob | None"] = relationship(back_populates="composition_records")
    usage_record: Mapped["OpenAIUsageRecord | None"] = relationship()


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
    tags: Mapped[list["Tag"]] = relationship(secondary=domain_tags, back_populates="domains")

    __table_args__ = (UniqueConstraint("parent_id", "name", name="uq_domains_parent_name"),)


class Tag(Base, TimestampMixin):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), default="tag", nullable=False)
    color: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(40), default="canonical", nullable=False, index=True)
    definition: Mapped[str | None] = mapped_column(Text)
    use_guidance: Mapped[str | None] = mapped_column(Text)
    avoid_guidance: Mapped[str | None] = mapped_column(Text)
    governance_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    documents: Mapped[list["Document"]] = relationship(secondary=document_tags, back_populates="tags")
    domains: Mapped[list[Domain]] = relationship(secondary=domain_tags, back_populates="tags")
    aliases: Mapped[list["TagAlias"]] = relationship(back_populates="target_tag", cascade="all, delete-orphan")
    outgoing_relationships: Mapped[list["TagRelationship"]] = relationship(
        back_populates="source_tag",
        cascade="all, delete-orphan",
        foreign_keys="TagRelationship.source_tag_id",
    )
    incoming_relationships: Mapped[list["TagRelationship"]] = relationship(
        back_populates="target_tag",
        cascade="all, delete-orphan",
        foreign_keys="TagRelationship.target_tag_id",
    )
    tag_assessments: Mapped[list["DocumentTagAssessment"]] = relationship(back_populates="tag")


class TagAlias(Base, TimestampMixin):
    __tablename__ = "tag_aliases"

    alias_name: Mapped[str] = mapped_column(String(120), primary_key=True)
    target_tag_id: Mapped[str] = mapped_column(String(36), ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(40), default="merge", nullable=False)
    alias_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    target_tag: Mapped[Tag] = relationship(back_populates="aliases")


class TagRelationship(Base, TimestampMixin):
    __tablename__ = "tag_relationships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_tag_id: Mapped[str] = mapped_column(String(36), ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)
    target_tag_id: Mapped[str] = mapped_column(String(36), ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="approved", nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    rationale: Mapped[str | None] = mapped_column(Text)
    relationship_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    source_tag: Mapped[Tag] = relationship(foreign_keys=[source_tag_id], back_populates="outgoing_relationships")
    target_tag: Mapped[Tag] = relationship(foreign_keys=[target_tag_id], back_populates="incoming_relationships")

    __table_args__ = (
        UniqueConstraint("source_tag_id", "target_tag_id", "relationship_type", name="uq_tag_relationship"),
    )


class SavedSearch(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "saved_searches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    query: Mapped[str | None] = mapped_column(Text)
    filters: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ReconInquiry(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "recon_inquiries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text)
    scope_type: Mapped[str] = mapped_column(String(40), default="library", nullable=False, index=True)
    scope: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    default_mode: Mapped[str] = mapped_column(String(40), default="quick_answer", nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    inquiry_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    runs: Mapped[list["ReconRun"]] = relationship(
        back_populates="inquiry",
        cascade="all, delete-orphan",
        order_by="ReconRun.created_at.desc()",
    )


class ReconRun(Base, TimestampMixin):
    __tablename__ = "recon_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    inquiry_id: Mapped[str] = mapped_column(String(36), ForeignKey("recon_inquiries.id", ondelete="CASCADE"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(40), default="quick_answer", nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resolved_document_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 4))
    answer_summary: Mapped[str | None] = mapped_column(Text)
    scope_snapshot: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    run_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    inquiry: Mapped[ReconInquiry] = relationship(back_populates="runs")
    evidence: Mapped[list["ReconEvidence"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ReconEvidence.rank, ReconEvidence.created_at",
    )
    answers: Mapped[list["ReconAnswerVersion"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ReconAnswerVersion.created_at.desc()",
    )


class ReconEvidence(Base, TimestampMixin):
    __tablename__ = "recon_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("recon_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    text_chunk_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("text_chunks.id", ondelete="SET NULL"), index=True)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    evidence_kind: Mapped[str] = mapped_column(String(40), default="chunk", nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score: Mapped[float | None] = mapped_column(Numeric(8, 4))
    document_title: Mapped[str | None] = mapped_column(String(600))
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    citation_text: Mapped[str | None] = mapped_column(Text)
    relevance_label: Mapped[str] = mapped_column(String(40), default="candidate", nullable=False, index=True)
    evidence_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    run: Mapped[ReconRun] = relationship(back_populates="evidence")
    document: Mapped["Document | None"] = relationship()
    text_chunk: Mapped["TextChunk | None"] = relationship()


class ReconAnswerVersion(Base, TimestampMixin):
    __tablename__ = "recon_answer_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("recon_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    limitations: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    answer_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    run: Mapped[ReconRun] = relationship(back_populates="answers")


class Publication(Base, TimestampMixin):
    __tablename__ = "publications"
    __table_args__ = (
        Index("ix_publications_normalized_title_type", "normalized_title", "publication_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(600), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(600), nullable=False, index=True)
    publication_type: Mapped[str | None] = mapped_column(String(60), index=True)
    publisher: Mapped[str | None] = mapped_column(String(300))
    imprint: Mapped[str | None] = mapped_column(String(300))
    issn_l: Mapped[str | None] = mapped_column(String(32), index=True)
    issns: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    isbns: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    doi: Mapped[str | None] = mapped_column(String(256), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    external_ids: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    publication_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)

    aliases: Mapped[list["PublicationAlias"]] = relationship(back_populates="publication", cascade="all, delete-orphan")
    document_links: Mapped[list["DocumentPublication"]] = relationship(back_populates="publication")


class PublicationAlias(Base, TimestampMixin):
    __tablename__ = "publication_aliases"
    __table_args__ = (
        UniqueConstraint("publication_id", "normalized_alias", name="uq_publication_alias_normalized"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    publication_id: Mapped[str] = mapped_column(String(36), ForeignKey("publications.id", ondelete="CASCADE"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(600), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(600), nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(80))
    alias_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    publication: Mapped[Publication] = relationship(back_populates="aliases")


class DocumentPublication(Base, TimestampMixin):
    __tablename__ = "document_publications"
    __table_args__ = (
        UniqueConstraint("document_id", "role", name="uq_document_publication_role"),
        Index("ix_document_publications_document_role", "document_id", "role"),
        Index("ix_document_publications_publication_role", "publication_id", "role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    publication_id: Mapped[str] = mapped_column(String(36), ForeignKey("publications.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(40), default="primary", nullable=False, index=True)
    appearance_type: Mapped[str | None] = mapped_column(String(80), index=True)
    title_snapshot: Mapped[str | None] = mapped_column(String(600))
    publisher_snapshot: Mapped[str | None] = mapped_column(String(300))
    volume: Mapped[str | None] = mapped_column(String(80))
    issue: Mapped[str | None] = mapped_column(String(80))
    article_number: Mapped[str | None] = mapped_column(String(120))
    page_range: Mapped[str | None] = mapped_column(String(120))
    published_date: Mapped[str | None] = mapped_column(String(80))
    published_year: Mapped[int | None] = mapped_column(Integer)
    edition: Mapped[str | None] = mapped_column(String(160))
    chapter: Mapped[str | None] = mapped_column(String(240))
    section: Mapped[str | None] = mapped_column(String(240))
    series_title: Mapped[str | None] = mapped_column(String(600))
    event_name: Mapped[str | None] = mapped_column(String(600))
    source_url: Mapped[str | None] = mapped_column(Text)
    identifiers: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    source: Mapped[str | None] = mapped_column(String(80), index=True)
    model: Mapped[str | None] = mapped_column(String(160))
    verification_status: Mapped[str] = mapped_column(String(40), default="needs_review", nullable=False, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(320))
    verified_by_user_id: Mapped[str | None] = mapped_column(String(36))
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="publication_links")
    publication: Mapped[Publication] = relationship(back_populates="document_links")


class Document(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_kind: Mapped[str] = mapped_column(String(40), default="library", nullable=False, index=True)
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
    bibliography: Mapped[str | None] = mapped_column(Text)
    apa_citation: Mapped[str | None] = mapped_column(Text)
    apa_citation_model: Mapped[str | None] = mapped_column(String(160))
    apa_citation_source: Mapped[str | None] = mapped_column(String(40))
    apa_in_text_citation: Mapped[str | None] = mapped_column(Text)
    apa_in_text_citation_model: Mapped[str | None] = mapped_column(String(160))
    apa_in_text_citation_source: Mapped[str | None] = mapped_column(String(40))
    citation_status: Mapped[str] = mapped_column(String(40), default="needs_review", nullable=False, index=True)
    metadata_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    metadata_evidence: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), default="application/pdf", nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    checksum_md5: Mapped[str | None] = mapped_column(String(32), index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gcs_uri: Mapped[str | None] = mapped_column(Text)
    storage_status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    processing_status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    read_status: Mapped[str] = mapped_column(String(40), default="unread", nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(40), default="normal", nullable=False, index=True)
    search_text: Mapped[str | None] = mapped_column(Text)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    duplicate_reasons: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    duplicate_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    domains: Mapped[list[Domain]] = relationship(secondary=document_domains, back_populates="documents")
    tags: Mapped[list[Tag]] = relationship(secondary=document_tags, back_populates="documents")
    versions: Mapped[list["DocumentVersion"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    pages: Mapped[list["DocumentPage"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    chunks: Mapped[list["TextChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    figures: Mapped[list["Figure"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    accessory_summaries: Mapped[list["DocumentAccessorySummary"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentAccessorySummary.created_at.desc()",
    )
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        primaryjoin="and_(Document.id == Annotation.document_id, Annotation.deleted_at.is_(None))",
    )
    notes: Mapped[list["Note"]] = relationship(back_populates="document")
    attributes: Mapped[list["DocumentAttributeValue"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    capabilities: Mapped[list["DocumentCapability"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    publication_links: Mapped[list["DocumentPublication"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentPublication.role, DocumentPublication.created_at",
    )
    composition_records: Mapped[list["DocumentCompositionRecord"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentCompositionRecord.sequence, DocumentCompositionRecord.created_at, DocumentCompositionRecord.id",
    )
    recommendations: Mapped[list["DocumentRecommendation"]] = relationship(
        back_populates="source_document",
        cascade="all, delete-orphan",
        foreign_keys="DocumentRecommendation.source_document_id",
    )

    @property
    def is_locked(self) -> bool:
        return self.locked_at is not None


class DocumentVersion(Base, TimestampMixin):
    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    change_note: Mapped[str | None] = mapped_column(Text)
    metadata_snapshot: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)

    document: Mapped[Document] = relationship(back_populates="versions")


class DocumentTagAssessment(Base, TimestampMixin):
    __tablename__ = "document_tag_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tags.id", ondelete="SET NULL"), index=True)
    import_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("import_jobs.id", ondelete="SET NULL"), index=True)
    concordance_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("concordance_jobs.id", ondelete="SET NULL"), index=True)
    candidate_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(40), default="import", nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="attached", nullable=False, index=True)
    relevance_score: Mapped[float] = mapped_column(Numeric(4, 3), default=0, nullable=False)
    library_fit_score: Mapped[float] = mapped_column(Numeric(4, 3), default=0, nullable=False)
    novelty_score: Mapped[float] = mapped_column(Numeric(4, 3), default=0, nullable=False)
    overall_score: Mapped[float] = mapped_column(Numeric(4, 3), default=0, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    assessment_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    document: Mapped[Document] = relationship()
    tag: Mapped[Tag | None] = relationship(back_populates="tag_assessments")
    import_job: Mapped["ImportJob | None"] = relationship()
    concordance_job: Mapped["ConcordanceJob | None"] = relationship()


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
    geometry: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)

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


class DocumentAccessorySummary(Base, TimestampMixin):
    __tablename__ = "document_accessory_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(240))
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="accessory_summaries")


class SlipstreamClient(Base, TimestampMixin):
    __tablename__ = "slipstream_clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str | None] = mapped_column(String(120))
    capabilities: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False, index=True)
    last_check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_nonce: Mapped[str | None] = mapped_column(String(160))
    client_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    leases: Mapped[list["SlipstreamLease"]] = relationship(back_populates="client")


class SlipstreamEnrollment(Base, TimestampMixin):
    __tablename__ = "slipstream_enrollments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(160))
    capabilities: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    max_capacity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("slipstream_clients.id", ondelete="SET NULL"))


class SlipstreamLease(Base, TimestampMixin):
    __tablename__ = "slipstream_leases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    client_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("slipstream_clients.id", ondelete="SET NULL"))
    worker_kind: Mapped[str] = mapped_column(String(40), default="slipstream", nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False, index=True)
    lease_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_idempotency_key: Mapped[str | None] = mapped_column(String(120))
    last_error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)

    client: Mapped[SlipstreamClient | None] = relationship(back_populates="leases")


Index(
    "uq_slipstream_active_job_lease",
    SlipstreamLease.job_type,
    SlipstreamLease.job_id,
    unique=True,
    postgresql_where=SlipstreamLease.status == "active",
    sqlite_where=SlipstreamLease.status == "active",
)


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


class DocumentRecommendation(Base, TimestampMixin):
    __tablename__ = "document_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    existing_document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    match_key: Mapped[str] = mapped_column(String(900), nullable=False)
    title: Mapped[str] = mapped_column(String(800), nullable=False)
    doi: Mapped[str | None] = mapped_column(String(256), index=True)
    authors: Mapped[list[dict[str, Any]]] = mapped_column(JsonDict, default=list, nullable=False)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    journal: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    source_provider: Mapped[str] = mapped_column(String(160), nullable=False)
    source_relation: Mapped[str | None] = mapped_column(String(120))
    external_id: Mapped[str | None] = mapped_column(String(360))
    source_url: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Numeric(8, 3))
    status: Mapped[str] = mapped_column(String(40), default="candidate", nullable=False, index=True)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), index=True)

    source_document: Mapped[Document] = relationship(
        back_populates="recommendations",
        foreign_keys=[source_document_id],
    )
    existing_document: Mapped[Document | None] = relationship(foreign_keys=[existing_document_id])
    imported_document: Mapped[Document | None] = relationship(foreign_keys=[imported_document_id])

    @property
    def existing_document_title(self) -> str | None:
        if self.existing_document:
            return self.existing_document.title
        if self.imported_document:
            return self.imported_document.title
        return None

    @property
    def has_pdf(self) -> bool:
        return bool(self.pdf_url)

    @property
    def relation_family(self) -> str:
        metadata = self.raw_metadata if isinstance(self.raw_metadata, dict) else {}
        v2_metadata = metadata.get("recommendations_v2") if isinstance(metadata.get("recommendations_v2"), dict) else {}
        return str(v2_metadata.get("relation_family") or "closest")

    @property
    def reason_chips(self) -> list[str]:
        metadata = self.raw_metadata if isinstance(self.raw_metadata, dict) else {}
        v2_metadata = metadata.get("recommendations_v2") if isinstance(metadata.get("recommendations_v2"), dict) else {}
        chips = v2_metadata.get("reason_chips")
        if not isinstance(chips, list):
            return []
        return [str(chip) for chip in chips if chip]

    @property
    def known_status(self) -> str:
        metadata = self.raw_metadata if isinstance(self.raw_metadata, dict) else {}
        v2_metadata = metadata.get("recommendations_v2") if isinstance(metadata.get("recommendations_v2"), dict) else {}
        return str(v2_metadata.get("known_status") or "new")

    @property
    def hidden_reason(self) -> str | None:
        metadata = self.raw_metadata if isinstance(self.raw_metadata, dict) else {}
        v2_metadata = metadata.get("recommendations_v2") if isinstance(metadata.get("recommendations_v2"), dict) else {}
        reason = v2_metadata.get("hidden_reason")
        return str(reason) if reason else None

    @property
    def diversity_score(self) -> float | None:
        metadata = self.raw_metadata if isinstance(self.raw_metadata, dict) else {}
        v2_metadata = metadata.get("recommendations_v2") if isinstance(metadata.get("recommendations_v2"), dict) else {}
        score = v2_metadata.get("diversity_score")
        try:
            return float(score) if score is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def scholar_url(self) -> str:
        query = self.doi or self.title
        return f"https://scholar.google.com/scholar?q={quote_plus(query)}"

    __table_args__ = (UniqueConstraint("source_document_id", "match_key", name="uq_document_recommendation_match"),)


class DoiStash(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "doi_stashes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    doi: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(800))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_provider: Mapped[str | None] = mapped_column(String(160))
    source_document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    recommendation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("document_recommendations.id", ondelete="SET NULL"),
        index=True,
    )
    imported_document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    import_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("import_jobs.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False, index=True)
    uploaded_filename: Mapped[str | None] = mapped_column(String(512))
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stash_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    source_document: Mapped[Document | None] = relationship(foreign_keys=[source_document_id])
    recommendation: Mapped[DocumentRecommendation | None] = relationship()
    imported_document: Mapped[Document | None] = relationship(foreign_keys=[imported_document_id])
    import_job: Mapped["ImportJob | None"] = relationship()


class PortfolioItem(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "portfolio_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(600), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False, index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("portfolio_versions.id", ondelete="SET NULL"), index=True)
    project_ids: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    domain_ids: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    tag_ids: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    portfolio_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    versions: Mapped[list["PortfolioVersion"]] = relationship(
        back_populates="portfolio_item",
        cascade="all, delete-orphan",
        foreign_keys="PortfolioVersion.portfolio_item_id",
        order_by="PortfolioVersion.version_number.desc()",
    )
    materials: Mapped[list["PortfolioMaterial"]] = relationship(
        back_populates="portfolio_item",
        cascade="all, delete-orphan",
        order_by="PortfolioMaterial.created_at.desc()",
    )
    suggestions: Mapped[list["PortfolioSuggestion"]] = relationship(
        back_populates="portfolio_item",
        cascade="all, delete-orphan",
        order_by="PortfolioSuggestion.score.desc().nullslast(), PortfolioSuggestion.created_at.desc()",
    )
    assessment_runs: Mapped[list["PortfolioAssessmentRun"]] = relationship(
        back_populates="portfolio_item",
        cascade="all, delete-orphan",
        order_by="PortfolioAssessmentRun.created_at.desc()",
    )
    audit_events: Mapped[list["PortfolioAuditEvent"]] = relationship(
        back_populates="portfolio_item",
        cascade="all, delete-orphan",
        order_by="PortfolioAuditEvent.sequence",
    )
    audit_anchors: Mapped[list["PortfolioAuditAnchor"]] = relationship(
        back_populates="portfolio_item",
        cascade="all, delete-orphan",
        order_by="PortfolioAuditAnchor.created_at.desc()",
    )
    current_version: Mapped["PortfolioVersion | None"] = relationship(
        foreign_keys=[current_version_id],
        post_update=True,
    )


class PortfolioVersion(Base, TimestampMixin):
    __tablename__ = "portfolio_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    portfolio_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("portfolio_items.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(240))
    upload_note: Mapped[str | None] = mapped_column(Text)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    source_checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_checksum_md5: Mapped[str | None] = mapped_column(String(32), index=True)
    source_storage_uri: Mapped[str | None] = mapped_column(Text)
    source_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    version_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    portfolio_item: Mapped[PortfolioItem] = relationship(
        back_populates="versions",
        foreign_keys=[portfolio_item_id],
    )
    document: Mapped[Document] = relationship()
    parent_edges: Mapped[list["PortfolioVersionEdge"]] = relationship(
        back_populates="child_version",
        cascade="all, delete-orphan",
        foreign_keys="PortfolioVersionEdge.child_version_id",
    )
    child_edges: Mapped[list["PortfolioVersionEdge"]] = relationship(
        back_populates="parent_version",
        cascade="all, delete-orphan",
        foreign_keys="PortfolioVersionEdge.parent_version_id",
    )

    __table_args__ = (UniqueConstraint("portfolio_item_id", "version_number", name="uq_portfolio_version_number"),)


class PortfolioVersionEdge(Base, TimestampMixin):
    __tablename__ = "portfolio_version_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    parent_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("portfolio_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    child_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("portfolio_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(80), default="supersedes", nullable=False, index=True)
    edge_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    parent_version: Mapped[PortfolioVersion] = relationship(back_populates="child_edges", foreign_keys=[parent_version_id])
    child_version: Mapped[PortfolioVersion] = relationship(back_populates="parent_edges", foreign_keys=[child_version_id])

    __table_args__ = (UniqueConstraint("parent_version_id", "child_version_id", "relation_type", name="uq_portfolio_version_edge"),)


class PortfolioMaterial(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "portfolio_materials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    portfolio_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("portfolio_items.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("portfolio_versions.id", ondelete="SET NULL"), index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(80), default="reference", nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(240))
    required_for_assessment: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    material_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    portfolio_item: Mapped[PortfolioItem] = relationship(back_populates="materials")
    version: Mapped[PortfolioVersion | None] = relationship()
    document: Mapped[Document] = relationship()


class PortfolioSuggestion(Base, TimestampMixin):
    __tablename__ = "portfolio_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    portfolio_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("portfolio_items.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("portfolio_versions.id", ondelete="SET NULL"), index=True)
    library_document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    source_type: Mapped[str] = mapped_column(String(80), default="library", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(800), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    relation_family: Mapped[str] = mapped_column(String(80), default="closest", nullable=False, index=True)
    score: Mapped[float | None] = mapped_column(Numeric(8, 3))
    status: Mapped[str] = mapped_column(String(40), default="candidate", nullable=False, index=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)

    portfolio_item: Mapped[PortfolioItem] = relationship(back_populates="suggestions")
    version: Mapped[PortfolioVersion | None] = relationship()
    library_document: Mapped[Document | None] = relationship()

    __table_args__ = (UniqueConstraint("portfolio_item_id", "version_id", "library_document_id", "source_type", name="uq_portfolio_suggestion_source"),)


class PortfolioAssessmentRun(Base, TimestampMixin):
    __tablename__ = "portfolio_assessment_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    portfolio_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("portfolio_items.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("portfolio_versions.id", ondelete="SET NULL"), index=True)
    mode: Mapped[str] = mapped_column(String(80), default="quality_review", nullable=False, index=True)
    model_ids: Mapped[list[str]] = mapped_column(JsonDict, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    assessment_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    portfolio_item: Mapped[PortfolioItem] = relationship(back_populates="assessment_runs")
    version: Mapped[PortfolioVersion | None] = relationship()
    findings: Mapped[list["PortfolioAssessmentFinding"]] = relationship(
        back_populates="assessment_run",
        cascade="all, delete-orphan",
        order_by="PortfolioAssessmentFinding.created_at",
    )

    @property
    def scorecard(self) -> list[dict[str, Any]]:
        metadata = self.assessment_metadata if isinstance(self.assessment_metadata, dict) else {}
        value = metadata.get("scorecard")
        return value if isinstance(value, list) else []

    @property
    def grade_estimate(self) -> dict[str, Any]:
        metadata = self.assessment_metadata if isinstance(self.assessment_metadata, dict) else {}
        value = metadata.get("grade_estimate")
        return value if isinstance(value, dict) else {}

    @property
    def narrative_feedback(self) -> dict[str, Any]:
        metadata = self.assessment_metadata if isinstance(self.assessment_metadata, dict) else {}
        value = metadata.get("narrative_feedback")
        return value if isinstance(value, dict) else {}

    @property
    def revision_priorities(self) -> list[dict[str, Any]]:
        metadata = self.assessment_metadata if isinstance(self.assessment_metadata, dict) else {}
        value = metadata.get("revision_priorities")
        return value if isinstance(value, list) else []

    @property
    def model_outputs(self) -> list[dict[str, Any]]:
        metadata = self.assessment_metadata if isinstance(self.assessment_metadata, dict) else {}
        value = metadata.get("model_outputs")
        return value if isinstance(value, list) else []

    @property
    def agreement(self) -> dict[str, Any]:
        metadata = self.assessment_metadata if isinstance(self.assessment_metadata, dict) else {}
        value = metadata.get("agreement")
        return value if isinstance(value, dict) else {}


class PortfolioAssessmentFinding(Base, TimestampMixin):
    __tablename__ = "portfolio_assessment_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("portfolio_assessment_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(40), default="info", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False, index=True)

    assessment_run: Mapped[PortfolioAssessmentRun] = relationship(back_populates="findings")


class PortfolioAuditEvent(Base, TimestampMixin):
    __tablename__ = "portfolio_audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    portfolio_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("portfolio_items.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("portfolio_versions.id", ondelete="SET NULL"), index=True)
    material_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("portfolio_materials.id", ondelete="SET NULL"), index=True)
    assessment_run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("portfolio_assessment_runs.id", ondelete="SET NULL"), index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(80), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(80), index=True)
    actor_type: Mapped[str] = mapped_column(String(80), default="system", nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(120))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    canonical_payload: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    signature_public_key_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    signature_algorithm: Mapped[str] = mapped_column(String(40), default="ed25519", nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)

    portfolio_item: Mapped[PortfolioItem] = relationship(back_populates="audit_events")
    version: Mapped[PortfolioVersion | None] = relationship()
    material: Mapped[PortfolioMaterial | None] = relationship()
    assessment_run: Mapped[PortfolioAssessmentRun | None] = relationship()

    __table_args__ = (
        UniqueConstraint("portfolio_item_id", "sequence", name="uq_portfolio_audit_event_sequence"),
        Index("ix_portfolio_audit_events_item_hash", "portfolio_item_id", "event_hash"),
    )


class PortfolioAuditAnchor(Base, TimestampMixin):
    __tablename__ = "portfolio_audit_anchors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    portfolio_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("portfolio_items.id", ondelete="CASCADE"), nullable=False, index=True)
    root_event_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("portfolio_audit_events.id", ondelete="SET NULL"), index=True)
    start_sequence: Mapped[int | None] = mapped_column(Integer)
    end_sequence: Mapped[int | None] = mapped_column(Integer, index=True)
    root_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tsa_url: Mapped[str | None] = mapped_column(Text)
    tsa_policy_oid: Mapped[str | None] = mapped_column(String(160))
    tsa_serial_number: Mapped[str | None] = mapped_column(String(240))
    tsa_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    response_der_base64: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(40), default="anchor_pending", nullable=False, index=True)
    verification_error: Mapped[str | None] = mapped_column(Text)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anchor_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    portfolio_item: Mapped[PortfolioItem] = relationship(back_populates="audit_anchors")
    root_event: Mapped[PortfolioAuditEvent | None] = relationship()

    __table_args__ = (
        Index("ix_portfolio_audit_anchors_item_range", "portfolio_item_id", "start_sequence", "end_sequence"),
    )


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
    composition_records: Mapped[list["DocumentCompositionRecord"]] = relationship(back_populates="import_job")

    @property
    def document_title(self) -> str | None:
        return self.document.title if self.document else None

    @property
    def original_filename(self) -> str | None:
        return self.document.original_filename if self.document else None

    @property
    def file_size_bytes(self) -> int | None:
        if not self.document:
            return None
        value = self.document.metadata_evidence.get("file_size_bytes")
        return value if isinstance(value, int) else None


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
    document: Mapped[Document] = relationship()

    @property
    def document_title(self) -> str | None:
        return self.document.title if self.document else None
