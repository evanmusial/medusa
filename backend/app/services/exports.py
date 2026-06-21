from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Annotation,
    AppPreference,
    AttributeDefinition,
    CitationCandidate,
    ConcordanceJob,
    ConcordanceRun,
    Document,
    DocumentAccessorySummary,
    DocumentCompositionRecord,
    DocumentAttributeValue,
    DocumentCapability,
    DocumentPage,
    DocumentRecommendation,
    DocumentTagAssessment,
    DocumentVersion,
    Domain,
    Figure,
    ImportBatch,
    ImportJob,
    Note,
    ProcessingEvent,
    Project,
    ProjectBibliography,
    ProjectItem,
    SavedSearch,
    Tag,
    TagAlias,
    TagRelationship,
    TextChunk,
    User,
)
from app.services.preferences import SAFE_PREFERENCE_KEYS


EXPORT_SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _timestamps(row: Any) -> dict[str, Any]:
    return {
        "created_at": _value(getattr(row, "created_at", None)),
        "updated_at": _value(getattr(row, "updated_at", None)),
    }


def _soft_delete(row: Any) -> dict[str, Any]:
    return {"deleted_at": _value(getattr(row, "deleted_at", None))}


def _uri_parts(uri: str | None) -> dict[str, Any]:
    if not uri:
        return {"backend": None, "uri": None}
    parsed = urlparse(uri)
    if parsed.scheme == "gs":
        return {
            "backend": "gcs",
            "uri": uri,
            "bucket": parsed.netloc,
            "object": parsed.path.lstrip("/"),
        }
    return {"backend": "local", "uri": uri, "path": uri}


def build_storage_manifest(db: Session) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    documents = db.query(Document).order_by(Document.created_at, Document.id).all()
    for document in documents:
        if document.gcs_uri:
            objects.append(
                {
                    "kind": "original",
                    "document_id": document.id,
                    "title": document.title,
                    "filename": document.original_filename,
                    "checksum_sha256": document.checksum_sha256,
                    "content_type": document.content_type,
                    **_uri_parts(document.gcs_uri),
                }
            )
        for page in sorted(document.pages, key=lambda item: item.page_number):
            if page.image_uri:
                objects.append(
                    {
                        "kind": "page_image",
                        "document_id": document.id,
                        "page_id": page.id,
                        "page_number": page.page_number,
                        **_uri_parts(page.image_uri),
                    }
                )
        for figure in sorted(document.figures, key=lambda item: (item.page_number or 0, item.figure_label or "", item.id)):
            if figure.asset_uri:
                objects.append(
                    {
                        "kind": "figure",
                        "document_id": document.id,
                        "figure_id": figure.id,
                        "page_number": figure.page_number,
                        "label": figure.figure_label,
                        **_uri_parts(figure.asset_uri),
                    }
                )

    counts = Counter(item["kind"] for item in objects)
    return {
        "generated_at": _now_iso(),
        "object_count": len(objects),
        "counts": dict(sorted(counts.items())),
        "objects": objects,
    }


def build_metadata_export(db: Session) -> dict[str, Any]:
    settings = get_settings()
    documents = db.query(Document).order_by(Document.created_at, Document.id).all()
    users = db.query(User).order_by(User.created_at, User.id).all()
    data = {
        "users": [
            {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "is_active": user.is_active,
                **_timestamps(user),
            }
            for user in users
        ],
        "domains": [
            {
                "id": domain.id,
                "parent_id": domain.parent_id,
                "name": domain.name,
                "description": domain.description,
                "color": domain.color,
                "sort_order": domain.sort_order,
                **_timestamps(domain),
                **_soft_delete(domain),
            }
            for domain in db.query(Domain).order_by(Domain.sort_order, Domain.name).all()
        ],
        "tags": [
            {
                "id": tag.id,
                "name": tag.name,
                "kind": tag.kind,
                "color": tag.color,
                "status": tag.status,
                "definition": tag.definition,
                "use_guidance": tag.use_guidance,
                "avoid_guidance": tag.avoid_guidance,
                "metadata": tag.governance_metadata,
                **_timestamps(tag),
            }
            for tag in db.query(Tag).order_by(Tag.name).all()
        ],
        "tag_aliases": [
            {
                "alias_name": alias.alias_name,
                "target_tag_id": alias.target_tag_id,
                "source": alias.source,
                "metadata": alias.alias_metadata,
                **_timestamps(alias),
            }
            for alias in db.query(TagAlias).order_by(TagAlias.alias_name).all()
        ],
        "tag_relationships": [
            {
                "id": relationship.id,
                "source_tag_id": relationship.source_tag_id,
                "target_tag_id": relationship.target_tag_id,
                "relationship_type": relationship.relationship_type,
                "status": relationship.status,
                "confidence": _value(relationship.confidence),
                "rationale": relationship.rationale,
                "metadata": relationship.relationship_metadata,
                **_timestamps(relationship),
            }
            for relationship in db.query(TagRelationship).order_by(
                TagRelationship.relationship_type,
                TagRelationship.created_at,
                TagRelationship.id,
            ).all()
        ],
        "saved_searches": [
            {
                "id": saved.id,
                "name": saved.name,
                "query": saved.query,
                "filters": saved.filters,
                "sort_order": saved.sort_order,
                **_timestamps(saved),
                **_soft_delete(saved),
            }
            for saved in db.query(SavedSearch).order_by(SavedSearch.sort_order, SavedSearch.name).all()
        ],
        "attribute_definitions": [
            {
                "id": definition.id,
                "name": definition.name,
                "value_type": definition.value_type,
                "description": definition.description,
                **_timestamps(definition),
                **_soft_delete(definition),
            }
            for definition in db.query(AttributeDefinition).order_by(AttributeDefinition.name).all()
        ],
        "documents": [_document_export(document) for document in documents],
        "notes": [
            {
                "id": note.id,
                "document_id": note.document_id,
                "domain_id": note.domain_id,
                "project_id": note.project_id,
                "title": note.title,
                "body": note.body,
                "kind": note.kind,
                "reminder_at": _value(note.reminder_at),
                **_timestamps(note),
                **_soft_delete(note),
            }
            for note in db.query(Note).order_by(Note.created_at, Note.id).all()
        ],
        "projects": [
            {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "due_at": _value(project.due_at),
                "status": project.status,
                "items": [
                    {
                        "id": item.id,
                        "document_id": item.document_id,
                        "status": item.status,
                        "priority": item.priority,
                        "used_in_output": item.used_in_output,
                        "note": item.note,
                        **_timestamps(item),
                    }
                    for item in sorted(project.items, key=lambda value: (value.created_at, value.id))
                ],
                **_timestamps(project),
                **_soft_delete(project),
            }
            for project in db.query(Project).order_by(Project.created_at, Project.id).all()
        ],
        "project_bibliographies": [
            {
                "id": bibliography.id,
                "project_id": bibliography.project_id,
                "style": bibliography.style,
                "body": bibliography.body,
                **_timestamps(bibliography),
            }
            for bibliography in db.query(ProjectBibliography).order_by(ProjectBibliography.created_at, ProjectBibliography.id).all()
        ],
        "app_preferences": [
            {
                "key": preference.key,
                "value": preference.value,
                **_timestamps(preference),
            }
            for preference in db.query(AppPreference)
            .filter(AppPreference.key.in_(sorted(SAFE_PREFERENCE_KEYS)))
            .order_by(AppPreference.key)
            .all()
        ],
        "import_batches": [
            {
                "id": batch.id,
                "label": batch.label,
                "shared_defaults": batch.shared_defaults,
                "status": batch.status,
                "total_files": batch.total_files,
                "completed_files": batch.completed_files,
                "failed_files": batch.failed_files,
                **_timestamps(batch),
            }
            for batch in db.query(ImportBatch).order_by(ImportBatch.created_at, ImportBatch.id).all()
        ],
        "import_jobs": [
            {
                "id": job.id,
                "batch_id": job.batch_id,
                "document_id": job.document_id,
                "status": job.status,
                "current_step": job.current_step,
                "attempts": job.attempts,
                "last_error": job.last_error,
                "locked_at": _value(job.locked_at),
                **_timestamps(job),
            }
            for job in db.query(ImportJob).order_by(ImportJob.created_at, ImportJob.id).all()
        ],
        "processing_events": [
            {
                "id": event.id,
                "import_job_id": event.import_job_id,
                "document_id": event.document_id,
                "level": event.level,
                "event_type": event.event_type,
                "message": event.message,
                "payload": event.payload,
                **_timestamps(event),
            }
            for event in db.query(ProcessingEvent).order_by(ProcessingEvent.created_at, ProcessingEvent.id).all()
        ],
        "document_composition_records": [
            {
                "id": record.id,
                "document_id": record.document_id,
                "import_job_id": record.import_job_id,
                "usage_record_id": record.usage_record_id,
                "sequence": record.sequence,
                "record_kind": record.record_kind,
                "stage_key": record.stage_key,
                "stage_label": record.stage_label,
                "provider": record.provider,
                "method": record.method,
                "model": record.model,
                "status": record.status,
                "amount_usd": _value(record.amount_usd),
                "duration_ms": record.duration_ms,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "total_tokens": record.total_tokens,
                "started_at": _value(record.started_at),
                "completed_at": _value(record.completed_at),
                "message": record.message,
                "metadata": record.record_metadata,
                **_timestamps(record),
            }
            for record in db.query(DocumentCompositionRecord).order_by(
                DocumentCompositionRecord.created_at,
                DocumentCompositionRecord.id,
            ).all()
        ],
        "document_tag_assessments": [
            {
                "id": assessment.id,
                "document_id": assessment.document_id,
                "tag_id": assessment.tag_id,
                "import_job_id": assessment.import_job_id,
                "concordance_job_id": assessment.concordance_job_id,
                "candidate_name": assessment.candidate_name,
                "source": assessment.source,
                "decision": assessment.decision,
                "status": assessment.status,
                "relevance_score": _value(assessment.relevance_score),
                "library_fit_score": _value(assessment.library_fit_score),
                "novelty_score": _value(assessment.novelty_score),
                "overall_score": _value(assessment.overall_score),
                "rationale": assessment.rationale,
                "metadata": assessment.assessment_metadata,
                **_timestamps(assessment),
            }
            for assessment in db.query(DocumentTagAssessment).order_by(
                DocumentTagAssessment.created_at,
                DocumentTagAssessment.id,
            ).all()
        ],
        "concordance_runs": [
            {
                "id": run.id,
                "label": run.label,
                "scope_type": run.scope_type,
                "scope_data": run.scope_data,
                "capability_keys": run.capability_keys,
                "status": run.status,
                "total_jobs": run.total_jobs,
                "completed_jobs": run.completed_jobs,
                "failed_jobs": run.failed_jobs,
                **_timestamps(run),
            }
            for run in db.query(ConcordanceRun).order_by(ConcordanceRun.created_at, ConcordanceRun.id).all()
        ],
        "concordance_jobs": [
            {
                "id": job.id,
                "run_id": job.run_id,
                "document_id": job.document_id,
                "capability_key": job.capability_key,
                "target_version": job.target_version,
                "status": job.status,
                "attempts": job.attempts,
                "last_error": job.last_error,
                "locked_at": _value(job.locked_at),
                "completed_at": _value(job.completed_at),
                **_timestamps(job),
            }
            for job in db.query(ConcordanceJob).order_by(ConcordanceJob.created_at, ConcordanceJob.id).all()
        ],
        "citation_candidates": [
            {
                "id": candidate.id,
                "document_id": candidate.document_id,
                "source": candidate.source,
                "citation_text": candidate.citation_text,
                "metadata": candidate.source_metadata,
                "confidence": _value(candidate.confidence),
                "status": candidate.status,
                **_timestamps(candidate),
            }
            for candidate in db.query(CitationCandidate).order_by(CitationCandidate.created_at, CitationCandidate.id).all()
        ],
    }
    counts = {key: len(value) for key, value in data.items()}
    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "app": settings.app_name,
        "safety": {
            "secrets_included": False,
            "password_hashes_included": False,
            "session_tokens_included": False,
            "storage_credentials_included": False,
        },
        "counts": counts,
        "storage_manifest": build_storage_manifest(db),
        "data": data,
    }


def _document_export(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "title": document.title,
        "subtitle": document.subtitle,
        "authors": document.authors,
        "universities": document.universities,
        "publication_year": document.publication_year,
        "publisher": document.publisher,
        "journal": document.journal,
        "doi": document.doi,
        "source_url": document.source_url,
        "abstract": document.abstract,
        "rich_summary": document.rich_summary,
        "bibliography": document.bibliography,
        "apa_citation": document.apa_citation,
        "apa_citation_model": document.apa_citation_model,
        "apa_citation_source": document.apa_citation_source,
        "apa_in_text_citation": document.apa_in_text_citation,
        "apa_in_text_citation_model": document.apa_in_text_citation_model,
        "apa_in_text_citation_source": document.apa_in_text_citation_source,
        "citation_status": document.citation_status,
        "metadata_confidence": _value(document.metadata_confidence),
        "metadata_evidence": document.metadata_evidence,
        "original_filename": document.original_filename,
        "content_type": document.content_type,
        "checksum_sha256": document.checksum_sha256,
        "page_count": document.page_count,
        "gcs_uri": document.gcs_uri,
        "storage_status": document.storage_status,
        "processing_status": document.processing_status,
        "read_status": document.read_status,
        "priority": document.priority,
        "search_text": document.search_text,
        "domain_ids": [domain.id for domain in sorted(document.domains, key=lambda value: value.name)],
        "tag_ids": [tag.id for tag in sorted(document.tags, key=lambda value: value.name)],
        "versions": [_version_export(version) for version in sorted(document.versions, key=lambda value: value.version_number)],
        "capabilities": [
            _capability_export(capability) for capability in sorted(document.capabilities, key=lambda value: value.capability_key)
        ],
        "pages": [_page_export(page) for page in sorted(document.pages, key=lambda value: value.page_number)],
        "text_chunks": [_chunk_export(chunk) for chunk in sorted(document.chunks, key=lambda value: (value.page_start or 0, value.id))],
        "figures": [_figure_export(figure) for figure in sorted(document.figures, key=lambda value: (value.page_number or 0, value.id))],
        "accessory_summaries": [
            _accessory_summary_export(summary)
            for summary in sorted(document.accessory_summaries, key=lambda value: (value.created_at, value.id))
        ],
        "annotations": [
            _annotation_export(annotation)
            for annotation in sorted(document.annotations, key=lambda value: (value.page_number or 0, value.created_at, value.id))
        ],
        "recommendations": [
            _recommendation_export(recommendation)
            for recommendation in sorted(
                document.recommendations,
                key=lambda value: (value.source_provider, value.title, value.id),
            )
        ],
        "attributes": [
            _attribute_value_export(value)
            for value in sorted(document.attributes, key=lambda item: item.definition.name if item.definition else item.id)
        ],
        **_timestamps(document),
        **_soft_delete(document),
    }


def _version_export(version: DocumentVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "version_number": version.version_number,
        "change_note": version.change_note,
        "metadata_snapshot": version.metadata_snapshot,
        **_timestamps(version),
    }


def _capability_export(capability: DocumentCapability) -> dict[str, Any]:
    return {
        "id": capability.id,
        "capability_key": capability.capability_key,
        "version": capability.version,
        "status": capability.status,
        "evidence": capability.evidence,
        "completed_at": _value(capability.completed_at),
        **_timestamps(capability),
    }


def _page_export(page: DocumentPage) -> dict[str, Any]:
    return {
        "id": page.id,
        "page_number": page.page_number,
        "text": page.text,
        "normalized_text": page.normalized_text,
        "text_source": page.text_source,
        "low_text": page.low_text,
        "image_uri": page.image_uri,
        **_timestamps(page),
    }


def _chunk_export(chunk: TextChunk) -> dict[str, Any]:
    embedding = chunk.embedding or []
    return {
        "id": chunk.id,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "text": chunk.text,
        "token_count": chunk.token_count,
        "has_embedding": bool(embedding),
        "embedding_dimensions": len(embedding),
        **_timestamps(chunk),
    }


def _figure_export(figure: Figure) -> dict[str, Any]:
    return {
        "id": figure.id,
        "page_number": figure.page_number,
        "figure_label": figure.figure_label,
        "caption": figure.caption,
        "gist": figure.gist,
        "asset_uri": figure.asset_uri,
        "geometry": figure.geometry,
        **_timestamps(figure),
    }


def _annotation_export(annotation: Annotation) -> dict[str, Any]:
    return {
        "id": annotation.id,
        "page_number": annotation.page_number,
        "kind": annotation.kind,
        "body": annotation.body,
        "geometry": annotation.geometry,
        "color": annotation.color,
        **_timestamps(annotation),
        **_soft_delete(annotation),
    }


def _accessory_summary_export(summary: DocumentAccessorySummary) -> dict[str, Any]:
    return {
        "id": summary.id,
        "title": summary.title,
        "prompt": summary.prompt,
        "summary": summary.summary,
        "model": summary.model,
        "status": summary.status,
        "attempts": summary.attempts,
        "last_error": summary.last_error,
        "evidence": summary.evidence,
        "locked_at": _value(summary.locked_at),
        "completed_at": _value(summary.completed_at),
        **_timestamps(summary),
    }


def _recommendation_export(recommendation: DocumentRecommendation) -> dict[str, Any]:
    return {
        "id": recommendation.id,
        "existing_document_id": recommendation.existing_document_id,
        "imported_document_id": recommendation.imported_document_id,
        "match_key": recommendation.match_key,
        "title": recommendation.title,
        "doi": recommendation.doi,
        "authors": recommendation.authors,
        "publication_year": recommendation.publication_year,
        "journal": recommendation.journal,
        "description": recommendation.description,
        "source_provider": recommendation.source_provider,
        "source_relation": recommendation.source_relation,
        "external_id": recommendation.external_id,
        "source_url": recommendation.source_url,
        "pdf_url": recommendation.pdf_url,
        "score": _value(recommendation.score),
        "status": recommendation.status,
        "raw_metadata": recommendation.raw_metadata,
        "last_seen_at": _value(recommendation.last_seen_at),
        **_timestamps(recommendation),
    }


def _attribute_value_export(value: DocumentAttributeValue) -> dict[str, Any]:
    return {
        "id": value.id,
        "attribute_definition_id": value.attribute_definition_id,
        "definition_name": value.definition.name if value.definition else None,
        "value": value.value,
        **_timestamps(value),
    }
