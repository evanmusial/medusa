from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
    DocumentPublication,
    DocumentRecommendation,
    DocumentTagAssessment,
    DocumentVersion,
    Domain,
    Figure,
    ImportBatch,
    ImportJob,
    Note,
    ProcessingEvent,
    PortfolioAssessmentFinding,
    PortfolioAssessmentRun,
    PortfolioAuditAnchor,
    PortfolioAuditEvent,
    PortfolioItem,
    PortfolioMaterial,
    PortfolioSuggestion,
    PortfolioVersion,
    PortfolioVersionEdge,
    Publication,
    PublicationAlias,
    Project,
    ProjectBibliography,
    ProjectItem,
    SavedSearch,
    Tag,
    TagAlias,
    TagRelationship,
    TextChunk,
)
from app.services.exports import EXPORT_SCHEMA_VERSION
from app.services.preferences import SAFE_PREFERENCE_KEYS


class RestoreValidationError(ValueError):
    pass


FORBIDDEN_EXPORT_KEYS = {
    "auth_provider_x509_cert_url",
    "client_email",
    "client_id",
    "client_x509_cert_url",
    "password_hash",
    "private_key",
    "private_key_id",
    "service_account",
    "session_token",
    "sessions",
    "token_hash",
    "two_factor_recovery_hashes",
    "two_factor_secret",
}

PARKED_JOB_STATUSES = {"queued", "running", "paused", "processing", "in_progress", "locked"}

RESTORE_SECTIONS = [
    "domains",
    "tags",
    "tag_aliases",
    "tag_relationships",
    "saved_searches",
    "attribute_definitions",
    "publications",
    "documents",
    "projects",
    "project_bibliographies",
    "portfolio_items",
    "portfolio_versions",
    "portfolio_version_edges",
    "portfolio_materials",
    "portfolio_suggestions",
    "portfolio_assessment_runs",
    "portfolio_assessment_findings",
    "portfolio_audit_events",
    "portfolio_audit_anchors",
    "notes",
    "app_preferences",
    "import_batches",
    "import_jobs",
    "processing_events",
    "document_composition_records",
    "document_tag_assessments",
    "concordance_runs",
    "concordance_jobs",
    "citation_candidates",
]


def validate_metadata_export(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["Export payload must be a JSON object."], "warnings": []}

    schema_version = payload.get("export_schema_version")
    if schema_version != EXPORT_SCHEMA_VERSION:
        errors.append(f"Unsupported export schema version: {schema_version!r}. Expected {EXPORT_SCHEMA_VERSION}.")

    data = payload.get("data")
    if not isinstance(data, dict):
        errors.append("Export is missing a data object.")
    else:
        missing = [section for section in RESTORE_SECTIONS if section not in data]
        if missing:
            warnings.append(f"Export is missing optional sections: {', '.join(missing)}.")

    safety = payload.get("safety", {})
    if isinstance(safety, dict):
        unsafe_flags = [key for key, value in safety.items() if key.endswith("_included") and value is True]
        if unsafe_flags:
            errors.append(f"Export safety flags indicate sensitive data is included: {', '.join(unsafe_flags)}.")
    else:
        warnings.append("Export has no safety object; proceeding only if no forbidden keys are present.")

    forbidden_paths = _forbidden_key_paths(payload)
    if forbidden_paths:
        preview = ", ".join(forbidden_paths[:8])
        suffix = "" if len(forbidden_paths) <= 8 else f", and {len(forbidden_paths) - 8} more"
        errors.append(f"Export contains forbidden secret-bearing keys: {preview}{suffix}.")

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def build_restore_plan(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    validation = validate_metadata_export(payload)
    data = payload.get("data") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = {}

    counts = {section: len(_section(data, section)) for section in RESTORE_SECTIONS}
    skipped = {
        "users": len(_section(data, "users")),
        "text_chunk_embeddings": sum(
            1
            for document in _section(data, "documents")
            for chunk in document.get("text_chunks", [])
            if chunk.get("has_embedding")
        ),
    }
    conflicts = {
        "documents_by_id": _existing_ids(db, Document, _ids(_section(data, "documents"))),
        "documents_by_checksum": _existing_checksums(db, _section(data, "documents")),
        "domains_by_id": _existing_ids(db, Domain, _ids(_section(data, "domains"))),
        "tags_by_id": _existing_ids(db, Tag, _ids(_section(data, "tags"))),
        "tags_by_name": _existing_names(db, Tag, [item.get("name") for item in _section(data, "tags")]),
        "projects_by_id": _existing_ids(db, Project, _ids(_section(data, "projects"))),
        "projects_by_name": _existing_names(db, Project, [item.get("name") for item in _section(data, "projects")]),
    }
    warnings = list(validation["warnings"])
    if skipped["users"]:
        warnings.append("User identity rows are present but auth credentials are intentionally not restored.")
    if skipped["text_chunk_embeddings"]:
        warnings.append("Text chunk embeddings are not present in metadata exports and will need Concordance refresh.")
    if counts["import_jobs"] or counts["concordance_jobs"]:
        warnings.append("Restored active job statuses are parked as restored_paused by default.")

    return {
        "valid": validation["valid"],
        "errors": validation["errors"],
        "warnings": warnings,
        "schema_version": payload.get("export_schema_version") if isinstance(payload, dict) else None,
        "counts": counts,
        "skipped": skipped,
        "conflicts": {key: value for key, value in conflicts.items() if value},
        "storage_manifest": {
            "object_count": payload.get("storage_manifest", {}).get("object_count", 0)
            if isinstance(payload.get("storage_manifest"), dict)
            else 0,
            "counts": payload.get("storage_manifest", {}).get("counts", {})
            if isinstance(payload.get("storage_manifest"), dict)
            else {},
        },
    }


def restore_metadata_export(
    db: Session,
    payload: dict[str, Any],
    *,
    dry_run: bool = True,
    preserve_ids: bool = True,
    park_active_jobs: bool = True,
) -> dict[str, Any]:
    plan = build_restore_plan(db, payload)
    if not plan["valid"]:
        raise RestoreValidationError("; ".join(plan["errors"]))
    if dry_run:
        return {**plan, "mode": "dry_run", "applied": False}

    data = payload.get("data", {})
    id_maps: dict[str, dict[str, str]] = {
        "domains": {},
        "tags": {},
        "saved_searches": {},
        "attribute_definitions": {},
        "publications": {},
        "documents": {},
        "projects": {},
        "import_batches": {},
        "import_jobs": {},
        "openai_usage_records": {},
        "concordance_runs": {},
        "concordance_jobs": {},
        "portfolio_items": {},
        "portfolio_versions": {},
        "portfolio_materials": {},
        "portfolio_assessment_runs": {},
        "portfolio_audit_events": {},
    }
    restored_counts = {section: 0 for section in RESTORE_SECTIONS}
    skipped_rows: dict[str, int] = {}

    try:
        restored_counts["domains"] = _restore_domains(db, _section(data, "domains"), id_maps, preserve_ids)
        restored_counts["tags"] = _restore_tags(db, _section(data, "tags"), id_maps, preserve_ids)
        _restore_domain_tags(db, _section(data, "domains"), id_maps)
        restored_counts["tag_aliases"], skipped_rows["tag_aliases"] = _restore_tag_aliases(
            db,
            _section(data, "tag_aliases"),
            id_maps,
        )
        restored_counts["tag_relationships"], skipped_rows["tag_relationships"] = _restore_tag_relationships(
            db,
            _section(data, "tag_relationships"),
            id_maps,
            preserve_ids,
        )
        restored_counts["saved_searches"] = _restore_saved_searches(
            db,
            _section(data, "saved_searches"),
            id_maps,
            preserve_ids,
        )
        restored_counts["attribute_definitions"] = _restore_attribute_definitions(
            db,
            _section(data, "attribute_definitions"),
            id_maps,
            preserve_ids,
        )
        restored_counts["publications"] = _restore_publications(
            db,
            _section(data, "publications"),
            id_maps,
            preserve_ids,
        )
        restored_counts["documents"] = _restore_documents(
            db,
            _section(data, "documents"),
            id_maps,
            preserve_ids,
            park_active_jobs,
        )
        restored_counts["projects"] = _restore_projects(db, _section(data, "projects"), id_maps, preserve_ids)
        restored_counts["project_bibliographies"] = _restore_project_bibliographies(
            db,
            _section(data, "project_bibliographies"),
            id_maps,
            preserve_ids,
        )
        restored_counts["portfolio_items"] = _restore_portfolio_items(db, _section(data, "portfolio_items"), id_maps, preserve_ids)
        restored_counts["portfolio_versions"], skipped_rows["portfolio_versions"] = _restore_portfolio_versions(
            db,
            _section(data, "portfolio_versions"),
            id_maps,
            preserve_ids,
            park_active_jobs,
        )
        _restore_portfolio_current_versions(db, _section(data, "portfolio_items"), id_maps)
        restored_counts["portfolio_version_edges"], skipped_rows["portfolio_version_edges"] = _restore_portfolio_version_edges(
            db,
            _section(data, "portfolio_version_edges"),
            id_maps,
            preserve_ids,
        )
        restored_counts["portfolio_materials"], skipped_rows["portfolio_materials"] = _restore_portfolio_materials(
            db,
            _section(data, "portfolio_materials"),
            id_maps,
            preserve_ids,
        )
        restored_counts["portfolio_suggestions"], skipped_rows["portfolio_suggestions"] = _restore_portfolio_suggestions(
            db,
            _section(data, "portfolio_suggestions"),
            id_maps,
            preserve_ids,
        )
        restored_counts["portfolio_assessment_runs"], skipped_rows["portfolio_assessment_runs"] = _restore_portfolio_assessment_runs(
            db,
            _section(data, "portfolio_assessment_runs"),
            id_maps,
            preserve_ids,
            park_active_jobs,
        )
        restored_counts["portfolio_assessment_findings"], skipped_rows["portfolio_assessment_findings"] = (
            _restore_portfolio_assessment_findings(
                db,
                _section(data, "portfolio_assessment_findings"),
                id_maps,
                preserve_ids,
            )
        )
        restored_counts["portfolio_audit_events"], skipped_rows["portfolio_audit_events"] = _restore_portfolio_audit_events(
            db,
            _section(data, "portfolio_audit_events"),
            id_maps,
            preserve_ids,
        )
        restored_counts["portfolio_audit_anchors"], skipped_rows["portfolio_audit_anchors"] = _restore_portfolio_audit_anchors(
            db,
            _section(data, "portfolio_audit_anchors"),
            id_maps,
            preserve_ids,
        )
        restored_counts["notes"], skipped_rows["notes"] = _restore_notes(db, _section(data, "notes"), id_maps, preserve_ids)
        restored_counts["app_preferences"] = _restore_app_preferences(db, _section(data, "app_preferences"))
        restored_counts["import_batches"] = _restore_import_batches(
            db,
            _section(data, "import_batches"),
            id_maps,
            preserve_ids,
            park_active_jobs,
        )
        restored_counts["import_jobs"], skipped_rows["import_jobs"] = _restore_import_jobs(
            db,
            _section(data, "import_jobs"),
            id_maps,
            preserve_ids,
            park_active_jobs,
        )
        restored_counts["processing_events"], skipped_rows["processing_events"] = _restore_processing_events(
            db,
            _section(data, "processing_events"),
            id_maps,
            preserve_ids,
        )
        restored_counts["document_composition_records"], skipped_rows["document_composition_records"] = _restore_document_composition_records(
            db,
            _section(data, "document_composition_records"),
            id_maps,
            preserve_ids,
        )
        restored_counts["concordance_runs"] = _restore_concordance_runs(
            db,
            _section(data, "concordance_runs"),
            id_maps,
            preserve_ids,
            park_active_jobs,
        )
        restored_counts["concordance_jobs"], skipped_rows["concordance_jobs"] = _restore_concordance_jobs(
            db,
            _section(data, "concordance_jobs"),
            id_maps,
            preserve_ids,
            park_active_jobs,
        )
        restored_counts["document_tag_assessments"], skipped_rows["document_tag_assessments"] = _restore_document_tag_assessments(
            db,
            _section(data, "document_tag_assessments"),
            id_maps,
            preserve_ids,
        )
        restored_counts["citation_candidates"], skipped_rows["citation_candidates"] = _restore_citation_candidates(
            db,
            _section(data, "citation_candidates"),
            id_maps,
            preserve_ids,
        )
        db.flush()
    except IntegrityError as exc:
        raise RestoreValidationError(f"Restore failed due to a database constraint: {exc.orig}") from exc

    return {
        **build_restore_plan(db, payload),
        "mode": "apply",
        "applied": True,
        "restored_counts": restored_counts,
        "skipped_rows": {key: value for key, value in skipped_rows.items() if value},
    }


def _restore_domains(db: Session, rows: list[dict[str, Any]], id_maps: dict[str, dict[str, str]], preserve_ids: bool) -> int:
    count = 0
    for row in rows:
        original_id = row.get("id")
        domain = _get_existing(db, Domain, original_id)
        if not domain:
            domain = Domain(**_restore_kwargs(row, preserve_ids, name=row.get("name") or "Untitled Domain"))
            db.add(domain)
        domain.name = row.get("name") or domain.name
        domain.description = row.get("description")
        domain.color = row.get("color")
        domain.sort_order = row.get("sort_order") or 0
        _apply_timestamps(domain, row)
        db.flush()
        if original_id:
            id_maps["domains"][original_id] = domain.id
        count += 1
    for row in rows:
        original_id = row.get("id")
        parent_id = row.get("parent_id")
        mapped_id = id_maps["domains"].get(original_id)
        if not mapped_id:
            continue
        domain = db.get(Domain, mapped_id)
        if domain:
            domain.parent_id = id_maps["domains"].get(parent_id)
    db.flush()
    return count


def _restore_domain_tags(db: Session, rows: list[dict[str, Any]], id_maps: dict[str, dict[str, str]]) -> None:
    for row in rows:
        if "tag_ids" not in row:
            continue
        mapped_id = id_maps["domains"].get(row.get("id"))
        if not mapped_id:
            continue
        domain = db.get(Domain, mapped_id)
        if not domain:
            continue
        domain.tags = _mapped_rows(db, Tag, id_maps["tags"], row.get("tag_ids") or [])
    db.flush()


def _restore_tags(db: Session, rows: list[dict[str, Any]], id_maps: dict[str, dict[str, str]], preserve_ids: bool) -> int:
    count = 0
    for row in rows:
        original_id = row.get("id")
        name = row.get("name") or "untitled"
        tag = _get_existing(db, Tag, original_id) or db.query(Tag).filter(Tag.name == name).one_or_none()
        if not tag:
            tag = Tag(**_restore_kwargs(row, preserve_ids, name=name))
            db.add(tag)
        tag.name = name
        tag.kind = "tag"
        tag.color = row.get("color")
        tag.status = row.get("status") or "canonical"
        tag.definition = row.get("definition")
        tag.use_guidance = row.get("use_guidance")
        tag.avoid_guidance = row.get("avoid_guidance")
        tag.governance_metadata = row.get("metadata") or {}
        _apply_timestamps(tag, row)
        db.flush()
        if original_id:
            id_maps["tags"][original_id] = tag.id
        count += 1
    return count


def _restore_tag_aliases(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        alias_name = row.get("alias_name")
        if not alias_name:
            skipped += 1
            continue
        original_target_id = row.get("target_tag_id")
        target_id = id_maps["tags"].get(original_target_id) or original_target_id
        if not target_id or not db.get(Tag, target_id):
            skipped += 1
            continue
        alias = db.get(TagAlias, alias_name)
        if not alias:
            alias = TagAlias(alias_name=alias_name, target_tag_id=target_id)
            db.add(alias)
        alias.target_tag_id = target_id
        alias.source = row.get("source") or "merge"
        alias.alias_metadata = row.get("metadata") or {}
        _apply_timestamps(alias, row)
        count += 1
    db.flush()
    return count, skipped


def _restore_tag_relationships(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        source_tag_id = id_maps["tags"].get(row.get("source_tag_id")) or row.get("source_tag_id")
        target_tag_id = id_maps["tags"].get(row.get("target_tag_id")) or row.get("target_tag_id")
        if not source_tag_id or not target_tag_id or not db.get(Tag, source_tag_id) or not db.get(Tag, target_tag_id):
            skipped += 1
            continue
        relationship_type = row.get("relationship_type") or "related"
        relationship = _get_existing(db, TagRelationship, row.get("id"))
        if not relationship:
            relationship = (
                db.query(TagRelationship)
                .filter(
                    TagRelationship.source_tag_id == source_tag_id,
                    TagRelationship.target_tag_id == target_tag_id,
                    TagRelationship.relationship_type == relationship_type,
                )
                .one_or_none()
            )
        if not relationship:
            relationship = TagRelationship(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                    source_tag_id=source_tag_id,
                    target_tag_id=target_tag_id,
                    relationship_type=relationship_type,
                )
            )
            db.add(relationship)
        relationship.source_tag_id = source_tag_id
        relationship.target_tag_id = target_tag_id
        relationship.relationship_type = relationship_type
        relationship.status = row.get("status") or "approved"
        relationship.confidence = row.get("confidence")
        relationship.rationale = row.get("rationale")
        relationship.relationship_metadata = row.get("metadata") or {}
        _apply_timestamps(relationship, row)
        count += 1
    db.flush()
    return count, skipped


def _restore_saved_searches(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> int:
    count = 0
    for row in rows:
        original_id = row.get("id")
        name = row.get("name") or "Restored Search"
        saved = _get_existing(db, SavedSearch, original_id) or db.query(SavedSearch).filter(SavedSearch.name == name).one_or_none()
        if not saved:
            saved = SavedSearch(**_restore_kwargs(row, preserve_ids, name=name))
            db.add(saved)
        saved.name = name
        saved.query = row.get("query")
        saved.filters = row.get("filters") or {}
        saved.sort_order = row.get("sort_order") or 0
        _apply_timestamps(saved, row)
        db.flush()
        if original_id:
            id_maps["saved_searches"][original_id] = saved.id
        count += 1
    return count


def _restore_attribute_definitions(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> int:
    count = 0
    for row in rows:
        original_id = row.get("id")
        name = row.get("name") or "Restored Attribute"
        definition = _get_existing(db, AttributeDefinition, original_id) or db.query(AttributeDefinition).filter(
            AttributeDefinition.name == name
        ).one_or_none()
        if not definition:
            definition = AttributeDefinition(**_restore_kwargs(row, preserve_ids, name=name))
            db.add(definition)
        definition.name = name
        definition.value_type = row.get("value_type") or "markdown"
        definition.description = row.get("description")
        _apply_timestamps(definition, row)
        db.flush()
        if original_id:
            id_maps["attribute_definitions"][original_id] = definition.id
        count += 1
    return count


def _restore_publications(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> int:
    count = 0
    for row in rows:
        original_id = row.get("id")
        title = row.get("title") or "Restored Publication"
        publication = _get_existing(db, Publication, original_id)
        if not publication:
            publication = Publication(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                    title=title,
                    normalized_title=row.get("normalized_title") or title.casefold(),
                )
            )
            db.add(publication)
        publication.title = title
        publication.normalized_title = row.get("normalized_title") or publication.normalized_title or title.casefold()
        publication.publication_type = row.get("publication_type") or row.get("type")
        publication.publisher = row.get("publisher")
        publication.imprint = row.get("imprint")
        publication.issn_l = row.get("issn_l")
        publication.issns = row.get("issns") or []
        publication.isbns = row.get("isbns") or []
        publication.doi = row.get("doi")
        publication.source_url = row.get("source_url")
        publication.external_ids = row.get("external_ids") or {}
        publication.publication_metadata = row.get("metadata") or {}
        publication.evidence = row.get("evidence") or {}
        _apply_timestamps(publication, row)
        db.flush()
        if original_id:
            id_maps["publications"][original_id] = publication.id
        db.query(PublicationAlias).filter(PublicationAlias.publication_id == publication.id).delete(synchronize_session=False)
        for alias_row in row.get("aliases", []):
            if not isinstance(alias_row, dict):
                continue
            alias = PublicationAlias(
                **_restore_kwargs(
                    alias_row,
                    preserve_ids,
                    publication_id=publication.id,
                    alias=alias_row.get("alias") or "",
                    normalized_alias=alias_row.get("normalized_alias") or str(alias_row.get("alias") or "").casefold(),
                    source=alias_row.get("source"),
                    alias_metadata=alias_row.get("metadata") or {},
                )
            )
            _apply_timestamps(alias, alias_row)
            db.add(alias)
        count += 1
    db.flush()
    return count


def _restore_documents(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
    park_active_jobs: bool,
) -> int:
    count = 0
    for row in rows:
        original_id = row.get("id")
        checksum = row.get("checksum_sha256")
        document = _get_existing(db, Document, original_id)
        if not document and checksum:
            document = db.query(Document).filter(Document.checksum_sha256 == checksum).one_or_none()
        if not document:
            document = Document(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                title=row.get("title") or row.get("original_filename") or "Untitled Document",
                original_filename=row.get("original_filename") or "document.pdf",
                checksum_sha256=checksum or "",
                checksum_md5=row.get("checksum_md5"),
                ),
            )
            db.add(document)
        _assign_document_fields(document, row)
        _apply_timestamps(document, row)
        db.flush()
        if original_id:
            id_maps["documents"][original_id] = document.id

        document.domains = _mapped_rows(db, Domain, id_maps["domains"], row.get("domain_ids") or [])
        document.tags = _mapped_rows(db, Tag, id_maps["tags"], row.get("tag_ids") or [])
        _replace_document_children(db, document, row, id_maps, preserve_ids, park_active_jobs)
        count += 1
    db.flush()
    return count


def _restore_projects(db: Session, rows: list[dict[str, Any]], id_maps: dict[str, dict[str, str]], preserve_ids: bool) -> int:
    count = 0
    for row in rows:
        original_id = row.get("id")
        name = row.get("name") or "Restored Project"
        project = _get_existing(db, Project, original_id) or db.query(Project).filter(Project.name == name).one_or_none()
        if not project:
            project = Project(**_restore_kwargs(row, preserve_ids, name=name))
            db.add(project)
        project.name = name
        project.description = row.get("description")
        project.due_at = _dt(row.get("due_at"))
        project.status = row.get("status") or "active"
        _apply_timestamps(project, row)
        db.flush()
        if original_id:
            id_maps["projects"][original_id] = project.id

        db.query(ProjectItem).filter(ProjectItem.project_id == project.id).delete(synchronize_session=False)
        db.flush()
        for item_row in row.get("items", []):
            document_id = id_maps["documents"].get(item_row.get("document_id"))
            if not document_id:
                continue
            item = ProjectItem(
                **_restore_kwargs(
                    item_row,
                    preserve_ids,
                project_id=project.id,
                document_id=document_id,
                status=item_row.get("status") or "candidate",
                priority=item_row.get("priority") or "normal",
                used_in_output=bool(item_row.get("used_in_output")),
                note=item_row.get("note"),
                ),
            )
            _apply_timestamps(item, item_row)
            db.add(item)
        count += 1
    db.flush()
    return count


def _restore_project_bibliographies(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> int:
    count = 0
    for row in rows:
        project_id = id_maps["projects"].get(row.get("project_id"))
        if not project_id:
            continue
        bibliography = _get_existing(db, ProjectBibliography, row.get("id"))
        if not bibliography:
            bibliography = ProjectBibliography(**_restore_kwargs(row, preserve_ids, project_id=project_id, body=""))
            db.add(bibliography)
        bibliography.project_id = project_id
        bibliography.style = row.get("style") or "apa7"
        bibliography.body = row.get("body") or ""
        _apply_timestamps(bibliography, row)
        count += 1
    return count


def _restore_portfolio_items(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> int:
    count = 0
    for row in rows:
        original_id = row.get("id")
        title = row.get("title") or "Restored Assignment"
        item = _get_existing(db, PortfolioItem, original_id)
        if not item:
            item = PortfolioItem(**_restore_kwargs(row, preserve_ids, title=title))
            db.add(item)
        item.title = title
        item.description = row.get("description")
        item.status = row.get("status") or "active"
        item.current_version_id = None
        item.project_ids = [id_maps["projects"].get(value, value) for value in row.get("project_ids") or []]
        item.domain_ids = [id_maps["domains"].get(value, value) for value in row.get("domain_ids") or []]
        item.tag_ids = [id_maps["tags"].get(value, value) for value in row.get("tag_ids") or []]
        item.portfolio_metadata = row.get("metadata") or {}
        _apply_timestamps(item, row)
        db.flush()
        if original_id:
            id_maps["portfolio_items"][original_id] = item.id
        count += 1
    return count


def _restore_portfolio_versions(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
    park_active_jobs: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        portfolio_item_id = id_maps["portfolio_items"].get(row.get("portfolio_item_id"))
        document_id = id_maps["documents"].get(row.get("document_id"))
        if not portfolio_item_id or not document_id:
            skipped += 1
            continue
        version = _get_existing(db, PortfolioVersion, row.get("id"))
        if not version:
            version = PortfolioVersion(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                    portfolio_item_id=portfolio_item_id,
                    document_id=document_id,
                    version_number=row.get("version_number") or 1,
                    source_filename=row.get("source_filename") or "portfolio-source",
                    source_content_type=row.get("source_content_type") or "application/octet-stream",
                    source_checksum_sha256=row.get("source_checksum_sha256") or "",
                    source_size_bytes=row.get("source_size_bytes") or 0,
                )
            )
            db.add(version)
        version.portfolio_item_id = portfolio_item_id
        version.document_id = document_id
        version.version_number = row.get("version_number") or version.version_number or 1
        version.label = row.get("label")
        version.upload_note = row.get("upload_note")
        version.source_filename = row.get("source_filename") or version.source_filename
        version.source_content_type = row.get("source_content_type") or version.source_content_type
        version.source_checksum_sha256 = row.get("source_checksum_sha256") or version.source_checksum_sha256
        version.source_checksum_md5 = row.get("source_checksum_md5")
        version.source_storage_uri = row.get("source_storage_uri")
        version.source_size_bytes = row.get("source_size_bytes") or 0
        version.processing_status = _parked_status(row.get("processing_status"), park_active_jobs)
        version.version_metadata = row.get("metadata") or {}
        _apply_timestamps(version, row)
        db.flush()
        if row.get("id"):
            id_maps["portfolio_versions"][row["id"]] = version.id
        count += 1
    return count, skipped


def _restore_portfolio_current_versions(db: Session, rows: list[dict[str, Any]], id_maps: dict[str, dict[str, str]]) -> None:
    for row in rows:
        item_id = id_maps["portfolio_items"].get(row.get("id"))
        version_id = id_maps["portfolio_versions"].get(row.get("current_version_id"))
        if not item_id or not version_id:
            continue
        item = db.get(PortfolioItem, item_id)
        if item:
            item.current_version_id = version_id
    db.flush()


def _restore_portfolio_version_edges(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        parent_version_id = id_maps["portfolio_versions"].get(row.get("parent_version_id"))
        child_version_id = id_maps["portfolio_versions"].get(row.get("child_version_id"))
        if not parent_version_id or not child_version_id:
            skipped += 1
            continue
        relation_type = row.get("relation_type") or "supersedes"
        edge = _get_existing(db, PortfolioVersionEdge, row.get("id"))
        if not edge:
            edge = (
                db.query(PortfolioVersionEdge)
                .filter(
                    PortfolioVersionEdge.parent_version_id == parent_version_id,
                    PortfolioVersionEdge.child_version_id == child_version_id,
                    PortfolioVersionEdge.relation_type == relation_type,
                )
                .one_or_none()
            )
        if not edge:
            edge = PortfolioVersionEdge(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                    parent_version_id=parent_version_id,
                    child_version_id=child_version_id,
                    relation_type=relation_type,
                )
            )
            db.add(edge)
        edge.parent_version_id = parent_version_id
        edge.child_version_id = child_version_id
        edge.relation_type = relation_type
        edge.edge_metadata = row.get("metadata") or {}
        _apply_timestamps(edge, row)
        count += 1
    db.flush()
    return count, skipped


def _restore_portfolio_materials(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        portfolio_item_id = id_maps["portfolio_items"].get(row.get("portfolio_item_id"))
        document_id = id_maps["documents"].get(row.get("document_id"))
        version_id = id_maps["portfolio_versions"].get(row.get("version_id")) if row.get("version_id") else None
        if not portfolio_item_id or not document_id:
            skipped += 1
            continue
        material = _get_existing(db, PortfolioMaterial, row.get("id"))
        if not material:
            material = PortfolioMaterial(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                    portfolio_item_id=portfolio_item_id,
                    document_id=document_id,
                    role=row.get("role") or "reference",
                )
            )
            db.add(material)
        material.portfolio_item_id = portfolio_item_id
        material.version_id = version_id
        material.document_id = document_id
        material.role = row.get("role") or "reference"
        material.label = row.get("label")
        material.required_for_assessment = bool(row.get("required_for_assessment"))
        material.notes = row.get("notes")
        material.material_metadata = row.get("metadata") or {}
        _apply_timestamps(material, row)
        db.flush()
        if row.get("id"):
            id_maps["portfolio_materials"][row["id"]] = material.id
        count += 1
    return count, skipped


def _restore_portfolio_suggestions(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        portfolio_item_id = id_maps["portfolio_items"].get(row.get("portfolio_item_id"))
        version_id = id_maps["portfolio_versions"].get(row.get("version_id")) if row.get("version_id") else None
        library_document_id = id_maps["documents"].get(row.get("library_document_id")) or row.get("library_document_id")
        if not portfolio_item_id:
            skipped += 1
            continue
        suggestion = _get_existing(db, PortfolioSuggestion, row.get("id"))
        if not suggestion:
            suggestion = PortfolioSuggestion(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                    portfolio_item_id=portfolio_item_id,
                    source_type=row.get("source_type") or "library",
                    title=row.get("title") or "Restored suggestion",
                )
            )
            db.add(suggestion)
        suggestion.portfolio_item_id = portfolio_item_id
        suggestion.version_id = version_id
        suggestion.library_document_id = library_document_id if library_document_id and db.get(Document, library_document_id) else None
        suggestion.source_type = row.get("source_type") or "library"
        suggestion.title = row.get("title") or suggestion.title
        suggestion.source_url = row.get("source_url")
        suggestion.relation_family = row.get("relation_family") or "closest"
        suggestion.score = row.get("score")
        suggestion.status = row.get("status") or "candidate"
        suggestion.evidence = row.get("evidence") or {}
        _apply_timestamps(suggestion, row)
        count += 1
    db.flush()
    return count, skipped


def _restore_portfolio_assessment_runs(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
    park_active_jobs: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        portfolio_item_id = id_maps["portfolio_items"].get(row.get("portfolio_item_id"))
        version_id = id_maps["portfolio_versions"].get(row.get("version_id")) if row.get("version_id") else None
        if not portfolio_item_id:
            skipped += 1
            continue
        run = _get_existing(db, PortfolioAssessmentRun, row.get("id"))
        if not run:
            run = PortfolioAssessmentRun(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                    portfolio_item_id=portfolio_item_id,
                    mode=row.get("mode") or "quality_review",
                )
            )
            db.add(run)
        run.portfolio_item_id = portfolio_item_id
        run.version_id = version_id
        run.mode = row.get("mode") or "quality_review"
        run.model_ids = row.get("model_ids") or []
        run.status = _parked_status(row.get("status"), park_active_jobs)
        run.summary = row.get("summary")
        run.assessment_metadata = row.get("metadata") or {}
        run.last_error = _restored_job_error(row.get("last_error"), row.get("status"), park_active_jobs)
        run.completed_at = _dt(row.get("completed_at"))
        _apply_timestamps(run, row)
        db.flush()
        if row.get("id"):
            id_maps["portfolio_assessment_runs"][row["id"]] = run.id
        count += 1
    return count, skipped


def _restore_portfolio_assessment_findings(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        assessment_run_id = id_maps["portfolio_assessment_runs"].get(row.get("assessment_run_id"))
        if not assessment_run_id:
            skipped += 1
            continue
        finding = _get_existing(db, PortfolioAssessmentFinding, row.get("id"))
        if not finding:
            finding = PortfolioAssessmentFinding(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                    assessment_run_id=assessment_run_id,
                    category=row.get("category") or "restored",
                    title=row.get("title") or "Restored finding",
                )
            )
            db.add(finding)
        finding.assessment_run_id = assessment_run_id
        finding.category = row.get("category") or "restored"
        finding.severity = row.get("severity") or "info"
        finding.title = row.get("title") or "Restored finding"
        finding.body = row.get("body")
        finding.evidence = row.get("evidence") or {}
        finding.status = row.get("status") or "open"
        _apply_timestamps(finding, row)
        count += 1
    db.flush()
    return count, skipped


def _restore_portfolio_audit_events(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        portfolio_item_id = id_maps["portfolio_items"].get(row.get("portfolio_item_id"))
        if not portfolio_item_id:
            skipped += 1
            continue
        event = _get_existing(db, PortfolioAuditEvent, row.get("id"))
        if not event:
            event = PortfolioAuditEvent(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                    portfolio_item_id=portfolio_item_id,
                    event_type=row.get("event_type") or "restored_event",
                    sequence=row.get("sequence") or 1,
                    canonical_payload=row.get("canonical_payload") or {},
                    payload_sha256=row.get("payload_sha256") or "",
                    event_hash=row.get("event_hash") or "",
                    signature_public_key_id=row.get("signature_public_key_id") or "",
                    signature=row.get("signature") or "",
                )
            )
            db.add(event)
        event.portfolio_item_id = portfolio_item_id
        event.version_id = id_maps["portfolio_versions"].get(row.get("version_id")) if row.get("version_id") else None
        event.material_id = id_maps["portfolio_materials"].get(row.get("material_id")) if row.get("material_id") else None
        event.assessment_run_id = (
            id_maps["portfolio_assessment_runs"].get(row.get("assessment_run_id")) if row.get("assessment_run_id") else None
        )
        event.event_type = row.get("event_type") or "restored_event"
        event.sequence = row.get("sequence") or event.sequence or 1
        event.subject_type = row.get("subject_type")
        event.subject_id = row.get("subject_id")
        event.actor_type = row.get("actor_type") or "system"
        event.actor_id = row.get("actor_id")
        event.occurred_at = _dt(row.get("occurred_at")) or event.occurred_at
        event.canonical_payload = row.get("canonical_payload") or {}
        event.payload_sha256 = row.get("payload_sha256") or event.payload_sha256
        event.previous_event_hash = row.get("previous_event_hash")
        event.event_hash = row.get("event_hash") or event.event_hash
        event.signature_public_key_id = row.get("signature_public_key_id") or event.signature_public_key_id
        event.signature_algorithm = row.get("signature_algorithm") or "ed25519"
        event.signature = row.get("signature") or event.signature
        _apply_timestamps(event, row)
        db.flush()
        if row.get("id"):
            id_maps["portfolio_audit_events"][row["id"]] = event.id
        count += 1
    return count, skipped


def _restore_portfolio_audit_anchors(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        portfolio_item_id = id_maps["portfolio_items"].get(row.get("portfolio_item_id"))
        if not portfolio_item_id:
            skipped += 1
            continue
        anchor = _get_existing(db, PortfolioAuditAnchor, row.get("id"))
        if not anchor:
            anchor = PortfolioAuditAnchor(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                    portfolio_item_id=portfolio_item_id,
                    root_hash=row.get("root_hash") or "",
                )
            )
            db.add(anchor)
        anchor.portfolio_item_id = portfolio_item_id
        anchor.root_event_id = id_maps["portfolio_audit_events"].get(row.get("root_event_id")) if row.get("root_event_id") else None
        anchor.start_sequence = row.get("start_sequence")
        anchor.end_sequence = row.get("end_sequence")
        anchor.root_hash = row.get("root_hash") or anchor.root_hash
        anchor.tsa_url = row.get("tsa_url")
        anchor.tsa_policy_oid = row.get("tsa_policy_oid")
        anchor.tsa_serial_number = row.get("tsa_serial_number")
        anchor.tsa_time = _dt(row.get("tsa_time"))
        anchor.request_sha256 = row.get("request_sha256")
        anchor.response_der_base64 = row.get("response_der_base64")
        anchor.verification_status = row.get("verification_status") or "anchor_pending"
        anchor.verification_error = row.get("verification_error")
        anchor.last_verified_at = _dt(row.get("last_verified_at"))
        anchor.anchor_metadata = row.get("metadata") or {}
        _apply_timestamps(anchor, row)
        count += 1
    db.flush()
    return count, skipped


def _restore_notes(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        document_id = id_maps["documents"].get(row.get("document_id")) if row.get("document_id") else None
        domain_id = id_maps["domains"].get(row.get("domain_id")) if row.get("domain_id") else None
        project_id = id_maps["projects"].get(row.get("project_id")) if row.get("project_id") else None
        if row.get("document_id") and not document_id:
            skipped += 1
            continue
        note = _get_existing(db, Note, row.get("id"))
        if not note:
            note = Note(**_restore_kwargs(row, preserve_ids, title=row.get("title") or "Restored Note", body=row.get("body") or ""))
            db.add(note)
        note.document_id = document_id
        note.domain_id = domain_id
        note.project_id = project_id
        note.title = row.get("title") or "Restored Note"
        note.body = row.get("body") or ""
        note.kind = row.get("kind") or "note"
        note.reminder_at = _dt(row.get("reminder_at"))
        _apply_timestamps(note, row)
        count += 1
    return count, skipped


def _restore_app_preferences(db: Session, rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        key = row.get("key")
        if key not in SAFE_PREFERENCE_KEYS:
            continue
        preference = db.get(AppPreference, key)
        if not preference:
            preference = AppPreference(key=key, value={})
            db.add(preference)
        preference.value = row.get("value") if isinstance(row.get("value"), dict) else {}
        _apply_timestamps(preference, row)
        count += 1
    db.flush()
    return count


def _restore_import_batches(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
    park_active_jobs: bool,
) -> int:
    count = 0
    for row in rows:
        batch = _get_existing(db, ImportBatch, row.get("id"))
        if not batch:
            batch = ImportBatch(**_restore_kwargs(row, preserve_ids))
            db.add(batch)
        batch.label = row.get("label")
        batch.shared_defaults = row.get("shared_defaults") or {}
        batch.status = _parked_status(row.get("status"), park_active_jobs)
        batch.total_files = row.get("total_files") or 0
        batch.completed_files = row.get("completed_files") or 0
        batch.failed_files = row.get("failed_files") or 0
        _apply_timestamps(batch, row)
        db.flush()
        if row.get("id"):
            id_maps["import_batches"][row["id"]] = batch.id
        count += 1
    return count


def _restore_import_jobs(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
    park_active_jobs: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        batch_id = id_maps["import_batches"].get(row.get("batch_id"))
        if not batch_id:
            skipped += 1
            continue
        job = _get_existing(db, ImportJob, row.get("id"))
        if not job:
            job = ImportJob(**_restore_kwargs(row, preserve_ids, batch_id=batch_id))
            db.add(job)
        job.batch_id = batch_id
        job.document_id = id_maps["documents"].get(row.get("document_id")) if row.get("document_id") else None
        job.status = _parked_status(row.get("status"), park_active_jobs)
        job.current_step = row.get("current_step") or "restored"
        job.attempts = row.get("attempts") or 0
        job.last_error = _restored_job_error(row.get("last_error"), row.get("status"), park_active_jobs)
        job.locked_at = None if park_active_jobs else _dt(row.get("locked_at"))
        _apply_timestamps(job, row)
        db.flush()
        if row.get("id"):
            id_maps["import_jobs"][row["id"]] = job.id
        count += 1
    return count, skipped


def _restore_processing_events(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        import_job_id = id_maps["import_jobs"].get(row.get("import_job_id")) if row.get("import_job_id") else None
        document_id = id_maps["documents"].get(row.get("document_id")) if row.get("document_id") else None
        if row.get("import_job_id") and not import_job_id:
            skipped += 1
            continue
        event = _get_existing(db, ProcessingEvent, row.get("id"))
        if not event:
            event = ProcessingEvent(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                event_type=row.get("event_type") or "restored",
                message=row.get("message") or "",
                ),
            )
            db.add(event)
        event.import_job_id = import_job_id
        event.document_id = document_id
        event.level = row.get("level") or "info"
        event.event_type = row.get("event_type") or "restored"
        event.message = row.get("message") or ""
        event.payload = row.get("payload") or {}
        _apply_timestamps(event, row)
        count += 1
    return count, skipped


def _restore_document_composition_records(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        document_id = id_maps["documents"].get(row.get("document_id"))
        if not document_id:
            skipped += 1
            continue
        import_job_id = id_maps["import_jobs"].get(row.get("import_job_id")) if row.get("import_job_id") else None
        if row.get("import_job_id") and not import_job_id:
            skipped += 1
            continue
        record = _get_existing(db, DocumentCompositionRecord, row.get("id"))
        if not record:
            record = DocumentCompositionRecord(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                    document_id=document_id,
                    sequence=row.get("sequence") or 0,
                    record_kind=row.get("record_kind") or "local",
                    stage_key=row.get("stage_key") or "restored",
                    stage_label=row.get("stage_label") or "Restored",
                    status=row.get("status") or "complete",
                )
            )
            db.add(record)
        record.document_id = document_id
        record.import_job_id = import_job_id
        record.usage_record_id = None
        record.sequence = row.get("sequence") or 0
        record.record_kind = row.get("record_kind") or "local"
        record.stage_key = row.get("stage_key") or "restored"
        record.stage_label = row.get("stage_label") or "Restored"
        record.provider = row.get("provider")
        record.method = row.get("method")
        record.model = row.get("model")
        record.status = row.get("status") or "complete"
        record.amount_usd = row.get("amount_usd")
        record.duration_ms = row.get("duration_ms")
        record.input_tokens = row.get("input_tokens") or 0
        record.output_tokens = row.get("output_tokens") or 0
        record.total_tokens = row.get("total_tokens") or 0
        record.started_at = _dt(row.get("started_at"))
        record.completed_at = _dt(row.get("completed_at"))
        record.message = row.get("message")
        record.record_metadata = row.get("metadata") or {}
        _apply_timestamps(record, row)
        count += 1
    return count, skipped


def _restore_concordance_runs(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
    park_active_jobs: bool,
) -> int:
    count = 0
    for row in rows:
        run = _get_existing(db, ConcordanceRun, row.get("id"))
        if not run:
            run = ConcordanceRun(**_restore_kwargs(row, preserve_ids))
            db.add(run)
        run.label = row.get("label")
        run.scope_type = row.get("scope_type") or "library"
        run.scope_data = row.get("scope_data") or {}
        run.capability_keys = row.get("capability_keys") or []
        run.status = _parked_status(row.get("status"), park_active_jobs)
        run.total_jobs = row.get("total_jobs") or 0
        run.completed_jobs = row.get("completed_jobs") or 0
        run.failed_jobs = row.get("failed_jobs") or 0
        _apply_timestamps(run, row)
        db.flush()
        if row.get("id"):
            id_maps["concordance_runs"][row["id"]] = run.id
        count += 1
    return count


def _restore_concordance_jobs(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
    park_active_jobs: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        run_id = id_maps["concordance_runs"].get(row.get("run_id"))
        document_id = id_maps["documents"].get(row.get("document_id"))
        if not run_id or not document_id:
            skipped += 1
            continue
        job = _get_existing(db, ConcordanceJob, row.get("id"))
        if not job:
            job = ConcordanceJob(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                run_id=run_id,
                document_id=document_id,
                capability_key=row.get("capability_key") or "restored",
                target_version=row.get("target_version") or 1,
                ),
            )
            db.add(job)
        job.run_id = run_id
        job.document_id = document_id
        job.capability_key = row.get("capability_key") or "restored"
        job.target_version = row.get("target_version") or 1
        job.status = _parked_status(row.get("status"), park_active_jobs)
        job.attempts = row.get("attempts") or 0
        job.last_error = _restored_job_error(row.get("last_error"), row.get("status"), park_active_jobs)
        job.locked_at = None if park_active_jobs else _dt(row.get("locked_at"))
        job.completed_at = _dt(row.get("completed_at"))
        _apply_timestamps(job, row)
        db.flush()
        if row.get("id"):
            id_maps["concordance_jobs"][row["id"]] = job.id
        count += 1
    return count, skipped


def _restore_document_tag_assessments(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        document_id = id_maps["documents"].get(row.get("document_id"))
        if not document_id:
            skipped += 1
            continue
        tag_id = id_maps["tags"].get(row.get("tag_id")) if row.get("tag_id") else None
        import_job_id = id_maps["import_jobs"].get(row.get("import_job_id")) if row.get("import_job_id") else None
        concordance_job_id = id_maps["concordance_jobs"].get(row.get("concordance_job_id")) if row.get("concordance_job_id") else None
        if row.get("tag_id") and not tag_id:
            skipped += 1
            continue
        assessment = _get_existing(db, DocumentTagAssessment, row.get("id"))
        if not assessment:
            assessment = DocumentTagAssessment(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                    document_id=document_id,
                    candidate_name=row.get("candidate_name") or "restored",
                    decision=row.get("decision") or "restored",
                )
            )
            db.add(assessment)
        assessment.document_id = document_id
        assessment.tag_id = tag_id
        assessment.import_job_id = import_job_id
        assessment.concordance_job_id = concordance_job_id
        assessment.candidate_name = row.get("candidate_name") or "restored"
        assessment.source = row.get("source") or "restored"
        assessment.decision = row.get("decision") or "restored"
        assessment.status = row.get("status") or "attached"
        assessment.relevance_score = row.get("relevance_score") or 0
        assessment.library_fit_score = row.get("library_fit_score") or 0
        assessment.novelty_score = row.get("novelty_score") or 0
        assessment.overall_score = row.get("overall_score") or 0
        assessment.rationale = row.get("rationale")
        assessment.assessment_metadata = row.get("metadata") or {}
        _apply_timestamps(assessment, row)
        count += 1
    db.flush()
    return count, skipped


def _restore_citation_candidates(
    db: Session,
    rows: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
) -> tuple[int, int]:
    count = 0
    skipped = 0
    for row in rows:
        document_id = id_maps["documents"].get(row.get("document_id"))
        if not document_id:
            skipped += 1
            continue
        candidate = _get_existing(db, CitationCandidate, row.get("id"))
        if not candidate:
            candidate = CitationCandidate(
                **_restore_kwargs(
                    row,
                    preserve_ids,
                document_id=document_id,
                source=row.get("source") or "restored",
                ),
            )
            db.add(candidate)
        candidate.document_id = document_id
        candidate.source = row.get("source") or "restored"
        candidate.citation_text = row.get("citation_text")
        candidate.source_metadata = row.get("metadata") or {}
        candidate.confidence = row.get("confidence")
        candidate.status = row.get("status") or "candidate"
        _apply_timestamps(candidate, row)
        count += 1
    return count, skipped


def _assign_document_fields(document: Document, row: dict[str, Any]) -> None:
    document.title = row.get("title") or document.title
    document.subtitle = row.get("subtitle")
    document.authors = row.get("authors") or []
    document.universities = row.get("universities") or []
    document.publication_year = row.get("publication_year")
    document.publisher = row.get("publisher")
    document.journal = row.get("journal")
    document.doi = row.get("doi")
    document.source_url = row.get("source_url")
    document.abstract = row.get("abstract")
    document.rich_summary = row.get("rich_summary")
    document.bibliography = row.get("bibliography")
    document.apa_citation = row.get("apa_citation")
    document.apa_citation_model = row.get("apa_citation_model")
    document.apa_citation_source = row.get("apa_citation_source")
    document.apa_in_text_citation = row.get("apa_in_text_citation")
    document.apa_in_text_citation_model = row.get("apa_in_text_citation_model")
    document.apa_in_text_citation_source = row.get("apa_in_text_citation_source")
    document.citation_status = row.get("citation_status") or "needs_review"
    document.metadata_confidence = row.get("metadata_confidence")
    document.metadata_evidence = row.get("metadata_evidence") or {}
    document.original_filename = row.get("original_filename") or document.original_filename
    document.content_type = row.get("content_type") or "application/pdf"
    document.checksum_sha256 = row.get("checksum_sha256") or document.checksum_sha256
    document.checksum_md5 = row.get("checksum_md5")
    document.page_count = row.get("page_count") or 0
    document.gcs_uri = row.get("gcs_uri")
    document.storage_status = row.get("storage_status") or "restored"
    document.processing_status = row.get("processing_status") or "restored"
    document.read_status = row.get("read_status") or "unread"
    document.priority = row.get("priority") or "normal"
    document.locked_at = _dt(row.get("locked_at"))
    document.search_text = row.get("search_text")


def _replace_document_children(
    db: Session,
    document: Document,
    row: dict[str, Any],
    id_maps: dict[str, dict[str, str]],
    preserve_ids: bool,
    park_active_jobs: bool,
) -> None:
    for model in (
        DocumentVersion,
        DocumentPage,
        TextChunk,
        Figure,
        DocumentAccessorySummary,
        Annotation,
        DocumentAttributeValue,
        DocumentCapability,
        DocumentPublication,
    ):
        db.query(model).filter(model.document_id == document.id).delete(synchronize_session=False)
    db.query(DocumentRecommendation).filter(DocumentRecommendation.source_document_id == document.id).delete(synchronize_session=False)
    db.flush()

    for version_row in row.get("versions", []):
        version = DocumentVersion(
            **_restore_kwargs(
                version_row,
                preserve_ids,
            document_id=document.id,
            version_number=version_row.get("version_number") or 1,
            change_note=version_row.get("change_note"),
            metadata_snapshot=version_row.get("metadata_snapshot") or {},
            ),
        )
        _apply_timestamps(version, version_row)
        db.add(version)

    for capability_row in row.get("capabilities", []):
        capability = DocumentCapability(
            **_restore_kwargs(
                capability_row,
                preserve_ids,
            document_id=document.id,
            capability_key=capability_row.get("capability_key") or "restored",
            version=capability_row.get("version") or 1,
            status=capability_row.get("status") or "complete",
            evidence=capability_row.get("evidence") or {},
            completed_at=_dt(capability_row.get("completed_at")),
            ),
        )
        _apply_timestamps(capability, capability_row)
        db.add(capability)

    for publication_row in row.get("publications", []):
        if not isinstance(publication_row, dict):
            continue
        publication_id = id_maps["publications"].get(publication_row.get("publication_id")) or publication_row.get("publication_id")
        if not publication_id:
            continue
        if not _get_existing(db, Publication, publication_id):
            continue
        link = DocumentPublication(
            **_restore_kwargs(
                publication_row,
                preserve_ids,
                document_id=document.id,
                publication_id=publication_id,
                role=publication_row.get("role") or "primary",
                appearance_type=publication_row.get("appearance_type"),
                title_snapshot=publication_row.get("title_snapshot"),
                publisher_snapshot=publication_row.get("publisher_snapshot"),
                volume=publication_row.get("volume"),
                issue=publication_row.get("issue"),
                article_number=publication_row.get("article_number"),
                page_range=publication_row.get("page_range"),
                published_date=publication_row.get("published_date"),
                published_year=publication_row.get("published_year"),
                edition=publication_row.get("edition"),
                chapter=publication_row.get("chapter"),
                section=publication_row.get("section"),
                series_title=publication_row.get("series_title"),
                event_name=publication_row.get("event_name"),
                source_url=publication_row.get("source_url"),
                identifiers=publication_row.get("identifiers") or {},
                confidence=publication_row.get("confidence"),
                source=publication_row.get("source"),
                model=publication_row.get("model"),
                verification_status=publication_row.get("verification_status") or "needs_review",
                verified_at=_dt(publication_row.get("verified_at")),
                verified_by=publication_row.get("verified_by"),
                verified_by_user_id=publication_row.get("verified_by_user_id"),
                evidence=publication_row.get("evidence") or {},
            )
        )
        _apply_timestamps(link, publication_row)
        db.add(link)

    for page_row in row.get("pages", []):
        page = DocumentPage(
            **_restore_kwargs(
                page_row,
                preserve_ids,
            document_id=document.id,
            page_number=page_row.get("page_number") or 1,
            text=page_row.get("text"),
            normalized_text=page_row.get("normalized_text"),
            text_source=page_row.get("text_source") or "pdf",
            low_text=bool(page_row.get("low_text")),
            image_uri=page_row.get("image_uri"),
            ),
        )
        _apply_timestamps(page, page_row)
        db.add(page)

    for chunk_row in row.get("text_chunks", []):
        chunk = TextChunk(
            **_restore_kwargs(
                chunk_row,
                preserve_ids,
            document_id=document.id,
            page_start=chunk_row.get("page_start"),
            page_end=chunk_row.get("page_end"),
            text=chunk_row.get("text") or "",
            token_count=chunk_row.get("token_count") or 0,
            embedding=None,
            ),
        )
        _apply_timestamps(chunk, chunk_row)
        db.add(chunk)

    for figure_row in row.get("figures", []):
        figure = Figure(
            **_restore_kwargs(
                figure_row,
                preserve_ids,
            document_id=document.id,
            page_number=figure_row.get("page_number"),
            figure_label=figure_row.get("figure_label"),
            caption=figure_row.get("caption"),
            gist=figure_row.get("gist"),
            asset_uri=figure_row.get("asset_uri"),
            geometry=figure_row.get("geometry") or {},
            ),
        )
        _apply_timestamps(figure, figure_row)
        db.add(figure)

    for annotation_row in row.get("annotations", []):
        annotation = Annotation(
            **_restore_kwargs(
                annotation_row,
                preserve_ids,
            document_id=document.id,
            page_number=annotation_row.get("page_number"),
            kind=annotation_row.get("kind") or "highlight",
            body=annotation_row.get("body"),
            geometry=annotation_row.get("geometry") or {},
            color=annotation_row.get("color"),
            ),
        )
        _apply_timestamps(annotation, annotation_row)
        db.add(annotation)

    for summary_row in row.get("accessory_summaries", []):
        summary = DocumentAccessorySummary(
            **_restore_kwargs(
                summary_row,
                preserve_ids,
            document_id=document.id,
            title=summary_row.get("title"),
            prompt=summary_row.get("prompt") or "Restored Inquest",
            summary=summary_row.get("summary"),
            model=summary_row.get("model") or "gpt-5.4",
            status=_parked_status(summary_row.get("status"), park_active_jobs),
            attempts=summary_row.get("attempts") or 0,
            last_error=_restored_job_error(summary_row.get("last_error"), summary_row.get("status"), park_active_jobs),
            evidence=summary_row.get("evidence") or {},
            locked_at=None if park_active_jobs else _dt(summary_row.get("locked_at")),
            completed_at=_dt(summary_row.get("completed_at")),
            ),
        )
        _apply_timestamps(summary, summary_row)
        db.add(summary)

    for recommendation_row in row.get("recommendations", []):
        recommendation = DocumentRecommendation(
            **_restore_kwargs(
                recommendation_row,
                preserve_ids,
            source_document_id=document.id,
            existing_document_id=id_maps["documents"].get(recommendation_row.get("existing_document_id")),
            imported_document_id=id_maps["documents"].get(recommendation_row.get("imported_document_id")),
            match_key=recommendation_row.get("match_key") or "title:restored",
            title=recommendation_row.get("title") or "Restored recommendation",
            doi=recommendation_row.get("doi"),
            authors=recommendation_row.get("authors") or [],
            publication_year=recommendation_row.get("publication_year"),
            journal=recommendation_row.get("journal"),
            description=recommendation_row.get("description"),
            source_provider=recommendation_row.get("source_provider") or "restored",
            source_relation=recommendation_row.get("source_relation"),
            external_id=recommendation_row.get("external_id"),
            source_url=recommendation_row.get("source_url"),
            pdf_url=recommendation_row.get("pdf_url"),
            score=recommendation_row.get("score"),
            status=recommendation_row.get("status") or "candidate",
            raw_metadata=recommendation_row.get("raw_metadata") or {},
            last_seen_at=_dt(recommendation_row.get("last_seen_at")),
            ),
        )
        _apply_timestamps(recommendation, recommendation_row)
        db.add(recommendation)

    for attribute_row in row.get("attributes", []):
        definition_id = id_maps["attribute_definitions"].get(attribute_row.get("attribute_definition_id"))
        if not definition_id:
            continue
        value = DocumentAttributeValue(
            **_restore_kwargs(
                attribute_row,
                preserve_ids,
            document_id=document.id,
            attribute_definition_id=definition_id,
            value=attribute_row.get("value") or {},
            ),
        )
        _apply_timestamps(value, attribute_row)
        db.add(value)


def _section(data: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = data.get(name, [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _restore_kwargs(row: dict[str, Any], preserve_ids: bool, **kwargs: Any) -> dict[str, Any]:
    if preserve_ids and row.get("id"):
        return {"id": row["id"], **kwargs}
    return kwargs


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return [row["id"] for row in rows if row.get("id")]


def _existing_ids(db: Session, model: Any, ids: list[str]) -> list[str]:
    if not ids:
        return []
    return [row[0] for row in db.query(model.id).filter(model.id.in_(ids)).all()]


def _existing_names(db: Session, model: Any, names: list[str | None]) -> list[str]:
    names = [name for name in names if name]
    if not names:
        return []
    return [row[0] for row in db.query(model.name).filter(model.name.in_(names)).all()]


def _existing_checksums(db: Session, rows: list[dict[str, Any]]) -> list[str]:
    checksums = [row["checksum_sha256"] for row in rows if row.get("checksum_sha256")]
    if not checksums:
        return []
    return [row[0] for row in db.query(Document.checksum_sha256).filter(Document.checksum_sha256.in_(checksums)).all()]


def _get_existing(db: Session, model: Any, row_id: str | None) -> Any | None:
    if not row_id:
        return None
    return db.get(model, row_id)


def _mapped_rows(db: Session, model: Any, id_map: dict[str, str], original_ids: list[str]) -> list[Any]:
    mapped_ids = [id_map[item] for item in original_ids if item in id_map]
    if not mapped_ids:
        return []
    return db.query(model).filter(model.id.in_(mapped_ids)).all()


def _apply_timestamps(row: Any, values: dict[str, Any]) -> None:
    for attr in ("created_at", "updated_at", "deleted_at"):
        if hasattr(row, attr) and values.get(attr):
            setattr(row, attr, _dt(values.get(attr)))


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
    return None


def _parked_status(status: str | None, park_active_jobs: bool) -> str:
    if park_active_jobs and (status or "").lower() in PARKED_JOB_STATUSES:
        return "restored_paused"
    return status or "restored"


def _restored_job_error(last_error: str | None, status: str | None, park_active_jobs: bool) -> str | None:
    if park_active_jobs and (status or "").lower() in PARKED_JOB_STATUSES:
        note = "Restored from metadata backup and parked to avoid automatic reprocessing."
        return f"{last_error}\n{note}" if last_error else note
    return last_error


def _forbidden_key_paths(value: Any, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_path = f"{path}.{key}"
            if key in FORBIDDEN_EXPORT_KEYS:
                paths.append(nested_path)
            paths.extend(_forbidden_key_paths(nested, nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_forbidden_key_paths(nested, f"{path}[{index}]"))
    return paths


def load_export_file(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RestoreValidationError("Export file must contain a JSON object.")
    return payload
