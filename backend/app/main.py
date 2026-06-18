from __future__ import annotations

import hashlib
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db, init_db, is_postgres, session_scope
from app.models import (
    Annotation,
    AttributeDefinition,
    CitationCandidate,
    ConcordanceJob,
    ConcordanceRun,
    Document,
    DocumentAttributeValue,
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
    User,
    utc_now,
)
from app.schemas import (
    AnnotationCreate,
    AnnotationOut,
    AnnotationPatch,
    AttributeDefinitionCreate,
    AttributeDefinitionOut,
    BibliographyOut,
    CitationCandidatePatch,
    CitationCandidateOut,
    ConcordanceCapabilityOut,
    ConcordanceJobOut,
    ConcordanceRunCreate,
    ConcordanceRunOut,
    DashboardOut,
    DocumentDetail,
    DocumentPatch,
    DocumentSummary,
    DomainCreate,
    DomainOut,
    ImportBatchOut,
    ImportJobOut,
    LoginRequest,
    NoteCreate,
    NoteOut,
    NotePatch,
    ProcessingEventOut,
    ProjectCreate,
    ProjectDetail,
    ProjectItemCreate,
    ProjectItemOut,
    ProjectItemPatch,
    ProjectOut,
    SavedSearchCreate,
    SavedSearchOut,
    SavedSearchPatch,
    TagCreate,
    TagOut,
    UserOut,
)
from app.security import create_session, ensure_admin_user, revoke_session, user_for_token, verify_password
from app.services.concordance import create_concordance_run, current_capabilities
from app.services.citations import format_apa_citation, format_bibtex, format_ris, to_csl_json
from app.services.exports import build_metadata_export, build_storage_manifest
from app.services.processing import document_metadata, document_reading_text, refresh_import_batch_progress
from app.services.storage import get_storage_service


settings = get_settings()
app = FastAPI(title="Medusa Research Library", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    with session_scope() as db:
        ensure_admin_user(db)


def parse_json_form(value: str | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON form field: {exc}") from exc


def current_user(
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    user = user_for_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def domain_out(domain: Domain) -> DomainOut:
    return DomainOut(
        id=domain.id,
        parent_id=domain.parent_id,
        name=domain.name,
        description=domain.description,
        color=domain.color,
        sort_order=domain.sort_order,
        document_count=len(domain.documents),
    )


def project_out(project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,
        due_at=project.due_at,
        item_count=len(project.items),
    )


def project_detail_out(project: Project) -> ProjectDetail:
    items = [
        item
        for item in sorted(project.items, key=lambda value: (value.used_in_output, value.status, value.created_at, value.id))
        if item.document and item.document.deleted_at is None
    ]
    base = project_out(project).model_dump()
    base["item_count"] = len(items)
    return ProjectDetail(**base, items=items)


def apply_document_filters(
    query,
    *,
    q: str | None = None,
    domain_id: str | None = None,
    tag_id: str | None = None,
    read_status: str | None = None,
    priority: str | None = None,
    citation_status: str | None = None,
):
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Document.title.ilike(like), Document.search_text.ilike(like), Document.apa_citation.ilike(like)))
        if is_postgres():
            query = query.order_by(
                text("ts_rank(to_tsvector('english', coalesce(search_text, '')), plainto_tsquery('english', :q)) DESC")
            ).params(q=q)
    if domain_id:
        query = query.filter(Document.domains.any(Domain.id == domain_id))
    if tag_id:
        query = query.filter(Document.tags.any(Tag.id == tag_id))
    if read_status:
        query = query.filter(Document.read_status == read_status)
    if priority:
        query = query.filter(Document.priority == priority)
    if citation_status:
        query = query.filter(Document.citation_status == citation_status)
    return query


def normalize_tag_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def get_or_create_tag_by_name(db: Session, name: str, kind: str = "keyword") -> Tag | None:
    normalized = normalize_tag_name(name)
    if not normalized:
        return None
    tag = db.query(Tag).filter(Tag.name == normalized).one_or_none()
    if tag:
        return tag
    tag = Tag(name=normalized, kind=kind)
    db.add(tag)
    db.flush()
    return tag


def get_or_create_attribute_definition(db: Session, key: str) -> AttributeDefinition | None:
    name = " ".join(key.strip().split())
    if not name:
        return None
    definition = db.get(AttributeDefinition, name)
    if not definition:
        definition = db.query(AttributeDefinition).filter(AttributeDefinition.name == name).one_or_none()
    if definition:
        return definition
    definition = AttributeDefinition(name=name, value_type="markdown")
    db.add(definition)
    db.flush()
    return definition


def normalize_attribute_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"value": value}


def attribute_value_text(value: dict[str, Any]) -> str:
    if "value" in value:
        return str(value["value"])
    return json.dumps(value, sort_keys=True)


def document_correction_snapshot(document: Document) -> dict[str, Any]:
    return {
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
        "apa_citation": document.apa_citation,
        "citation_status": document.citation_status,
        "read_status": document.read_status,
        "priority": document.priority,
        "tags": [tag.name for tag in document.tags],
        "domains": [domain.id for domain in document.domains],
        "attributes": {value.definition.name: value.value for value in document.attributes if value.definition},
    }


def rebuild_document_search_text(document: Document) -> str:
    page_text = document_reading_text(document)
    notes = "\n\n".join(note.body for note in document.notes if not note.deleted_at)
    annotations = "\n\n".join(annotation.body or "" for annotation in document.annotations if not annotation.deleted_at)
    attributes = "\n\n".join(
        f"{value.definition.name}: {attribute_value_text(value.value)}" for value in document.attributes if value.definition
    )
    return "\n\n".join(
        part
        for part in [
            document.title,
            " ".join(" ".join(filter(None, [author.get("given"), author.get("family")])) for author in document.authors or []),
            document.abstract,
            document.rich_summary,
            document.apa_citation,
            page_text,
            " ".join(figure.gist or "" for figure in document.figures),
            notes,
            annotations,
            attributes,
            " ".join(tag.name for tag in document.tags),
            " ".join(domain.name for domain in document.domains),
        ]
        if part
    )


def json_download(payload: dict[str, Any], filename_prefix: str) -> FastAPIResponse:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{filename_prefix}-{stamp}.json"
    content = json.dumps(jsonable_encoder(payload), indent=2, sort_keys=True)
    return FastAPIResponse(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.post("/api/auth/login", response_model=UserOut)
def login(payload: LoginRequest, request: Request, response: Response, db: Annotated[Session, Depends(get_db)]) -> User:
    user = db.query(User).filter(User.email == payload.email).one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_session(db, user, user_agent=request.headers.get("user-agent"))
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.session_ttl_hours * 3600,
    )
    return user


@app.post("/api/auth/logout")
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> dict[str, str]:
    if token:
        revoke_session(db, token)
    response.delete_cookie(settings.session_cookie_name)
    return {"status": "ok"}


@app.get("/api/me", response_model=UserOut)
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user


@app.get("/api/dashboard", response_model=DashboardOut)
def dashboard(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> DashboardOut:
    return DashboardOut(
        documents=db.query(Document).filter(Document.deleted_at.is_(None)).count(),
        unread=db.query(Document).filter(Document.deleted_at.is_(None), Document.read_status == "unread").count(),
        needs_review=db.query(Document).filter(Document.deleted_at.is_(None), Document.citation_status == "needs_review").count(),
        queued_jobs=db.query(ImportJob).filter(ImportJob.status.in_(["queued", "running"])).count()
        + db.query(ConcordanceJob).filter(ConcordanceJob.status.in_(["queued", "running"])).count(),
        failed_jobs=db.query(ImportJob).filter(ImportJob.status == "failed").count()
        + db.query(ConcordanceJob).filter(ConcordanceJob.status == "failed").count(),
        projects=db.query(Project).filter(Project.deleted_at.is_(None)).count(),
    )


@app.get("/api/domains", response_model=list[DomainOut])
def list_domains(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[DomainOut]:
    domains = db.query(Domain).filter(Domain.deleted_at.is_(None)).order_by(Domain.sort_order, Domain.name).all()
    return [domain_out(domain) for domain in domains]


@app.post("/api/domains", response_model=DomainOut)
def create_domain(
    payload: DomainCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DomainOut:
    domain = Domain(**payload.model_dump())
    db.add(domain)
    db.commit()
    db.refresh(domain)
    return domain_out(domain)


@app.get("/api/tags", response_model=list[TagOut])
def list_tags(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[Tag]:
    return db.query(Tag).order_by(Tag.kind, Tag.name).all()


@app.post("/api/tags", response_model=TagOut)
def create_tag(
    payload: TagCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Tag:
    tag = Tag(name=payload.name.strip().lower(), kind=payload.kind, color=payload.color)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@app.get("/api/saved-searches", response_model=list[SavedSearchOut])
def list_saved_searches(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[SavedSearch]:
    return db.query(SavedSearch).filter(SavedSearch.deleted_at.is_(None)).order_by(SavedSearch.sort_order, SavedSearch.name).all()


@app.post("/api/saved-searches", response_model=SavedSearchOut)
def create_saved_search(
    payload: SavedSearchCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SavedSearch:
    saved_search = SavedSearch(name=payload.name.strip(), query=(payload.query or "").strip() or None, filters=payload.filters)
    if not saved_search.name:
        raise HTTPException(status_code=400, detail="Saved search name is required")
    db.add(saved_search)
    db.commit()
    db.refresh(saved_search)
    return saved_search


@app.patch("/api/saved-searches/{saved_search_id}", response_model=SavedSearchOut)
def patch_saved_search(
    saved_search_id: str,
    payload: SavedSearchPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SavedSearch:
    saved_search = db.get(SavedSearch, saved_search_id)
    if not saved_search or saved_search.deleted_at:
        raise HTTPException(status_code=404, detail="Saved search not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key == "name" and value is not None:
            value = value.strip()
            if not value:
                raise HTTPException(status_code=400, detail="Saved search name is required")
        if key == "query" and value is not None:
            value = value.strip() or None
        setattr(saved_search, key, value)
    db.commit()
    db.refresh(saved_search)
    return saved_search


@app.delete("/api/saved-searches/{saved_search_id}")
def delete_saved_search(
    saved_search_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    saved_search = db.get(SavedSearch, saved_search_id)
    if not saved_search or saved_search.deleted_at:
        raise HTTPException(status_code=404, detail="Saved search not found")
    saved_search.deleted_at = utc_now()
    db.commit()
    return {"status": "deleted"}


@app.get("/api/attributes", response_model=list[AttributeDefinitionOut])
def list_attributes(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[AttributeDefinition]:
    return db.query(AttributeDefinition).filter(AttributeDefinition.deleted_at.is_(None)).order_by(AttributeDefinition.name).all()


@app.post("/api/attributes", response_model=AttributeDefinitionOut)
def create_attribute(
    payload: AttributeDefinitionCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AttributeDefinition:
    definition = AttributeDefinition(**payload.model_dump())
    db.add(definition)
    db.commit()
    db.refresh(definition)
    return definition


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[ProjectOut]:
    projects = db.query(Project).filter(Project.deleted_at.is_(None)).order_by(Project.created_at.desc()).all()
    return [project_out(project) for project in projects]


@app.post("/api/projects", response_model=ProjectOut)
def create_project(
    payload: ProjectCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectOut:
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project_out(project)


@app.get("/api/projects/{project_id}", response_model=ProjectDetail)
def get_project(
    project_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectDetail:
    project = db.get(Project, project_id)
    if not project or project.deleted_at:
        raise HTTPException(status_code=404, detail="Project not found")
    return project_detail_out(project)


@app.post("/api/projects/{project_id}/items", response_model=ProjectDetail)
def add_project_items(
    project_id: str,
    payload: ProjectItemCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectDetail:
    project = db.get(Project, project_id)
    if not project or project.deleted_at:
        raise HTTPException(status_code=404, detail="Project not found")
    document_ids = list(dict.fromkeys(payload.document_ids))
    if not document_ids:
        raise HTTPException(status_code=400, detail="document_ids is required")
    documents = db.query(Document).filter(Document.id.in_(document_ids), Document.deleted_at.is_(None)).all()
    existing_ids = {item.document_id for item in project.items}
    for document in documents:
        if document.id in existing_ids:
            continue
        db.add(
            ProjectItem(
                project_id=project.id,
                document_id=document.id,
                status=payload.status,
                priority=payload.priority,
                used_in_output=payload.used_in_output,
                note=payload.note,
            )
        )
    db.commit()
    db.refresh(project)
    db.expire(project, ["items"])
    return project_detail_out(project)


@app.patch("/api/projects/{project_id}/items/{item_id}", response_model=ProjectItemOut)
def patch_project_item(
    project_id: str,
    item_id: str,
    payload: ProjectItemPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectItem:
    item = db.query(ProjectItem).filter(ProjectItem.project_id == project_id, ProjectItem.id == item_id).one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Project item not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@app.delete("/api/projects/{project_id}/items/{item_id}")
def delete_project_item(
    project_id: str,
    item_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    item = db.query(ProjectItem).filter(ProjectItem.project_id == project_id, ProjectItem.id == item_id).one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Project item not found")
    db.delete(item)
    db.commit()
    return {"status": "deleted"}


@app.get("/api/documents", response_model=list[DocumentSummary])
def list_documents(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    domain_id: str | None = None,
    tag_id: str | None = None,
    read_status: str | None = None,
    priority: str | None = None,
    citation_status: str | None = None,
    limit: int = 80,
) -> list[Document]:
    query = db.query(Document).filter(Document.deleted_at.is_(None))
    query = apply_document_filters(
        query,
        q=q,
        domain_id=domain_id,
        tag_id=tag_id,
        read_status=read_status,
        priority=priority,
        citation_status=citation_status,
    )
    return query.order_by(Document.created_at.desc()).limit(limit).all()


@app.get("/api/documents/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Document:
    document = db.get(Document, document_id)
    if not document or document.deleted_at:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@app.post("/api/documents/{document_id}/citation-refresh", response_model=ConcordanceRunOut)
def refresh_document_citation(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ConcordanceRun:
    document = db.get(Document, document_id)
    if not document or document.deleted_at:
        raise HTTPException(status_code=404, detail="Document not found")
    run = create_concordance_run(
        db,
        scope_type="documents",
        scope_data={"document_ids": [document.id]},
        capability_keys=["citation_refresh"],
        force=True,
        label=f"Citation check: {document.title}",
    )
    db.commit()
    db.refresh(run)
    return run


@app.get("/api/documents/{document_id}/original")
def document_original(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FastAPIResponse:
    document = db.get(Document, document_id)
    if not document or document.deleted_at:
        raise HTTPException(status_code=404, detail="Document not found")
    if not document.gcs_uri:
        raise HTTPException(status_code=404, detail="Original document is unavailable")
    try:
        data = get_storage_service().get_bytes(document.gcs_uri)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Original document is unavailable") from exc
    filename = document.original_filename.replace('"', "")
    return FastAPIResponse(
        content=data,
        media_type=document.content_type or "application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/api/documents/{document_id}/annotations", response_model=list[AnnotationOut])
def list_annotations(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[Annotation]:
    document = db.get(Document, document_id)
    if not document or document.deleted_at:
        raise HTTPException(status_code=404, detail="Document not found")
    return (
        db.query(Annotation)
        .filter(Annotation.document_id == document_id, Annotation.deleted_at.is_(None))
        .order_by(Annotation.page_number, Annotation.created_at.desc())
        .all()
    )


@app.post("/api/documents/{document_id}/annotations", response_model=AnnotationOut)
def create_annotation(
    document_id: str,
    payload: AnnotationCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Annotation:
    document = db.get(Document, document_id)
    if not document or document.deleted_at:
        raise HTTPException(status_code=404, detail="Document not found")
    annotation = Annotation(**payload.model_dump())
    document.annotations.append(annotation)
    db.flush()
    document.search_text = rebuild_document_search_text(document)
    db.commit()
    db.refresh(annotation)
    return annotation


@app.patch("/api/annotations/{annotation_id}", response_model=AnnotationOut)
def patch_annotation(
    annotation_id: str,
    payload: AnnotationPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Annotation:
    annotation = db.get(Annotation, annotation_id)
    if not annotation or annotation.deleted_at:
        raise HTTPException(status_code=404, detail="Annotation not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(annotation, key, value)
    document = db.get(Document, annotation.document_id)
    if document and not document.deleted_at:
        document.search_text = rebuild_document_search_text(document)
    db.commit()
    db.refresh(annotation)
    return annotation


@app.delete("/api/annotations/{annotation_id}")
def delete_annotation(
    annotation_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    annotation = db.get(Annotation, annotation_id)
    if not annotation or annotation.deleted_at:
        raise HTTPException(status_code=404, detail="Annotation not found")
    annotation.deleted_at = utc_now()
    document = db.get(Document, annotation.document_id)
    if document and not document.deleted_at:
        document.search_text = rebuild_document_search_text(document)
    db.commit()
    return {"status": "deleted"}


@app.get("/api/figures/{figure_id}/asset")
def figure_asset(
    figure_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FastAPIResponse:
    figure = db.get(Figure, figure_id)
    if not figure or not figure.asset_uri:
        raise HTTPException(status_code=404, detail="Figure asset not found")
    try:
        data = get_storage_service().get_bytes(figure.asset_uri)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Figure asset is unavailable") from exc
    content_type = mimetypes.guess_type(figure.asset_uri)[0] or "application/octet-stream"
    return FastAPIResponse(content=data, media_type=content_type)


@app.patch("/api/documents/{document_id}", response_model=DocumentDetail)
def patch_document(
    document_id: str,
    payload: DocumentPatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Document:
    document = db.get(Document, document_id)
    if not document or document.deleted_at:
        raise HTTPException(status_code=404, detail="Document not found")

    data = payload.model_dump(exclude_unset=True)
    tag_ids = data.pop("tag_ids", None)
    tag_names = data.pop("tag_names", None)
    domain_ids = data.pop("domain_ids", None)
    attribute_values = data.pop("attribute_values", None)
    before = document_correction_snapshot(document)
    changed_fields: set[str] = set()
    for key, value in data.items():
        if getattr(document, key) != value:
            setattr(document, key, value)
            changed_fields.add(key)
    if tag_ids is not None:
        document.tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
        changed_fields.add("tags")
    if tag_names is not None:
        tags = []
        for name in tag_names:
            tag = get_or_create_tag_by_name(db, name)
            if tag and tag not in tags:
                tags.append(tag)
        document.tags = tags
        changed_fields.add("tags")
    if domain_ids is not None:
        document.domains = db.query(Domain).filter(Domain.id.in_(domain_ids)).all() if domain_ids else []
        changed_fields.add("domains")
    if attribute_values is not None:
        for key, value in attribute_values.items():
            definition = get_or_create_attribute_definition(db, key)
            if not definition:
                continue
            current = (
                db.query(DocumentAttributeValue)
                .filter(
                    DocumentAttributeValue.document_id == document.id,
                    DocumentAttributeValue.attribute_definition_id == definition.id,
                )
                .one_or_none()
            )
            if value in (None, ""):
                if current:
                    db.delete(current)
                    changed_fields.add("attributes")
                continue
            normalized_value = normalize_attribute_value(value)
            if current:
                if current.value != normalized_value:
                    current.value = normalized_value
                    changed_fields.add("attributes")
            else:
                db.add(
                    DocumentAttributeValue(
                        document_id=document.id,
                        attribute_definition_id=definition.id,
                        value=normalized_value,
                    )
                )
                changed_fields.add("attributes")

    citation_fields = {"title", "authors", "publication_year", "journal", "publisher", "doi", "source_url"}
    if changed_fields & citation_fields and "apa_citation" not in data:
        document.apa_citation = format_apa_citation(document_metadata(document))
        changed_fields.add("apa_citation")
    if changed_fields:
        document.search_text = rebuild_document_search_text(document)
        db.flush()
        after = document_correction_snapshot(document)
        latest_version = (
            db.query(func.max(DocumentVersion.version_number))
            .filter(DocumentVersion.document_id == document.id)
            .scalar()
            or 0
        )
        db.add(
            DocumentVersion(
                document_id=document.id,
                version_number=latest_version + 1,
                change_note="Manual correction",
                metadata_snapshot={
                    "changed_fields": sorted(changed_fields),
                    "before": before,
                    "after": after,
                },
            )
        )
    db.commit()
    db.refresh(document)
    return document


@app.delete("/api/documents/{document_id}")
def delete_document(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    document = db.get(Document, document_id)
    if not document or document.deleted_at:
        raise HTTPException(status_code=404, detail="Document not found")
    document.deleted_at = utc_now()
    db.commit()
    return {"status": "deleted"}


@app.post("/api/documents/bulk")
def bulk_update_documents(
    payload: dict[str, Any],
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    ids = payload.get("document_ids") or []
    updates = payload.get("updates") or {}
    if not ids:
        raise HTTPException(status_code=400, detail="document_ids is required")
    documents = db.query(Document).filter(Document.id.in_(ids), Document.deleted_at.is_(None)).all()
    for document in documents:
        for key in ["read_status", "priority", "citation_status"]:
            if key in updates:
                setattr(document, key, updates[key])
        if "tag_ids" in updates:
            tags = db.query(Tag).filter(Tag.id.in_(updates["tag_ids"])).all()
            document.tags = list({tag.id: tag for tag in [*document.tags, *tags]}.values())
        if "tag_names" in updates:
            tags = [tag for name in updates["tag_names"] if (tag := get_or_create_tag_by_name(db, str(name)))]
            document.tags = list({tag.id: tag for tag in [*document.tags, *tags]}.values())
        if "domain_ids" in updates:
            domains = db.query(Domain).filter(Domain.id.in_(updates["domain_ids"])).all()
            document.domains = list({domain.id: domain for domain in [*document.domains, *domains]}.values())
    db.commit()
    return {"updated": len(documents)}


@app.post("/api/imports/batches", response_model=ImportBatchOut)
async def create_import_batch(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    files: Annotated[list[UploadFile], File()],
    label: Annotated[str | None, Form()] = None,
    domain_ids: Annotated[str | None, Form()] = None,
    tag_ids: Annotated[str | None, Form()] = None,
    project_ids: Annotated[str | None, Form()] = None,
    priority: Annotated[str, Form()] = "normal",
    read_status: Annotated[str, Form()] = "unread",
    attributes: Annotated[str | None, Form()] = None,
) -> ImportBatch:
    parsed_domain_ids = parse_json_form(domain_ids, [])
    parsed_tag_ids = parse_json_form(tag_ids, [])
    parsed_project_ids = parse_json_form(project_ids, [])
    parsed_attributes = parse_json_form(attributes, {})
    batch = ImportBatch(
        label=label,
        total_files=len(files),
        shared_defaults={
            "domain_ids": parsed_domain_ids,
            "tag_ids": parsed_tag_ids,
            "project_ids": parsed_project_ids,
            "priority": priority,
            "read_status": read_status,
            "attributes": parsed_attributes,
        },
    )
    db.add(batch)
    db.flush()

    domains = db.query(Domain).filter(Domain.id.in_(parsed_domain_ids)).all() if parsed_domain_ids else []
    tags = db.query(Tag).filter(Tag.id.in_(parsed_tag_ids)).all() if parsed_tag_ids else []
    projects = db.query(Project).filter(Project.id.in_(parsed_project_ids)).all() if parsed_project_ids else []
    storage = get_storage_service()
    cache_dir = settings.data_dir / "processing-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    for upload in files:
        data = await upload.read()
        checksum = hashlib.sha256(data).hexdigest()
        existing = db.query(Document).filter(Document.checksum_sha256 == checksum).one_or_none()
        if existing:
            job = ImportJob(batch_id=batch.id, document_id=existing.id, status="complete", current_step="duplicate")
            db.add(job)
            db.add(
                ProcessingEvent(
                    import_job_id=job.id,
                    document_id=existing.id,
                    level="warning",
                    event_type="duplicate",
                    message="Duplicate upload matched an existing checksum.",
                    payload={"filename": upload.filename},
                )
            )
            continue

        filename = upload.filename or f"{checksum}.pdf"
        key = f"documents/{checksum[:2]}/{checksum}/{filename}"
        stored = storage.put_bytes(key, data, upload.content_type or "application/pdf")
        cache_path = cache_dir / f"{checksum}.pdf"
        cache_path.write_bytes(data)
        document = Document(
            title=Path(filename).stem.replace("_", " ").replace("-", " "),
            original_filename=filename,
            content_type=upload.content_type or "application/pdf",
            checksum_sha256=checksum,
            gcs_uri=stored.uri,
            storage_status=stored.backend,
            priority=priority,
            read_status=read_status,
            metadata_evidence={"local_cache_path": str(cache_path), "import_defaults": batch.shared_defaults},
        )
        document.domains = domains.copy()
        document.tags = tags.copy()
        db.add(document)
        db.flush()

        for project in projects:
            db.add(ProjectItem(project_id=project.id, document_id=document.id, priority=priority))

        for name, value in parsed_attributes.items():
            definition = db.query(AttributeDefinition).filter(AttributeDefinition.name == name).one_or_none()
            if not definition:
                definition = AttributeDefinition(name=name, value_type="markdown")
                db.add(definition)
                db.flush()
            db.add(DocumentAttributeValue(document_id=document.id, attribute_definition_id=definition.id, value={"value": value}))

        db.add(ImportJob(batch_id=batch.id, document_id=document.id, status="queued", current_step="stored"))

    refresh_import_batch_progress(db, batch)
    db.commit()
    db.refresh(batch)
    return batch


@app.get("/api/imports/batches", response_model=list[ImportBatchOut])
def list_import_batches(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[ImportBatch]:
    return db.query(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(50).all()


@app.get("/api/imports/jobs", response_model=list[ImportJobOut])
def list_import_jobs(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[ImportJob]:
    return db.query(ImportJob).order_by(ImportJob.created_at.desc()).limit(100).all()


@app.get("/api/exports/metadata")
def export_metadata(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FastAPIResponse:
    return json_download(build_metadata_export(db), "medusa-metadata")


@app.get("/api/exports/storage-manifest")
def export_storage_manifest(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FastAPIResponse:
    return json_download(build_storage_manifest(db), "medusa-storage-manifest")


@app.get("/api/concordance/capabilities", response_model=list[ConcordanceCapabilityOut])
def list_concordance_capabilities(_: Annotated[User, Depends(current_user)]) -> list[dict[str, Any]]:
    return current_capabilities()


@app.post("/api/concordance/runs", response_model=ConcordanceRunOut)
def create_concordance_run_endpoint(
    payload: ConcordanceRunCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        run = create_concordance_run(
            db,
            scope_type=payload.scope_type,
            scope_data=payload.scope_data,
            capability_keys=payload.capability_keys,
            force=payload.force,
            label=payload.label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(run)
    return run


@app.get("/api/concordance/runs", response_model=list[ConcordanceRunOut])
def list_concordance_runs(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return db.query(ConcordanceRun).order_by(ConcordanceRun.created_at.desc()).limit(50).all()


@app.get("/api/concordance/jobs", response_model=list[ConcordanceJobOut])
def list_concordance_jobs(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return db.query(ConcordanceJob).order_by(ConcordanceJob.created_at.desc()).limit(100).all()


@app.get("/api/documents/{document_id}/events", response_model=list[ProcessingEventOut])
def document_events(
    document_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ProcessingEvent]:
    return db.query(ProcessingEvent).filter(ProcessingEvent.document_id == document_id).order_by(ProcessingEvent.created_at.desc()).all()


@app.get("/api/review-queue", response_model=list[CitationCandidateOut])
def review_queue(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[CitationCandidate]:
    return db.query(CitationCandidate).filter(CitationCandidate.status == "needs_review").order_by(CitationCandidate.created_at.desc()).all()


@app.patch("/api/review-queue/{candidate_id}", response_model=CitationCandidateOut)
def patch_citation_candidate(
    candidate_id: str,
    payload: CitationCandidatePatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CitationCandidate:
    candidate = db.get(CitationCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Citation candidate not found")
    if payload.status is not None:
        if payload.status not in {"needs_review", "accepted", "rejected"}:
            raise HTTPException(status_code=400, detail="Unsupported citation candidate status")
        candidate.status = payload.status
    if payload.apply_to_document:
        document = db.get(Document, candidate.document_id)
        if not document or document.deleted_at:
            raise HTTPException(status_code=404, detail="Document not found")
        before = document_correction_snapshot(document)
        changed_fields: set[str] = set()
        metadata = candidate.source_metadata or {}
        for field in ["title", "authors", "publication_year", "journal", "publisher", "doi", "source_url"]:
            value = metadata.get(field)
            if value not in (None, "", []):
                setattr(document, field, value)
                changed_fields.add(field)
        if candidate.citation_text:
            document.apa_citation = candidate.citation_text
            changed_fields.add("apa_citation")
        document.citation_status = "verified"
        changed_fields.add("citation_status")
        candidate.status = "accepted"
        document.search_text = rebuild_document_search_text(document)
        db.flush()
        after = document_correction_snapshot(document)
        latest_version = (
            db.query(func.max(DocumentVersion.version_number))
            .filter(DocumentVersion.document_id == document.id)
            .scalar()
            or 0
        )
        db.add(
            DocumentVersion(
                document_id=document.id,
                version_number=latest_version + 1,
                change_note="Accepted citation candidate",
                metadata_snapshot={
                    "candidate_id": candidate.id,
                    "changed_fields": sorted(changed_fields),
                    "before": before,
                    "after": after,
                },
            )
        )
    db.commit()
    db.refresh(candidate)
    return candidate


@app.get("/api/projects/{project_id}/bibliography", response_model=BibliographyOut)
def project_bibliography(
    project_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    used_only: bool = False,
) -> BibliographyOut:
    project = db.get(Project, project_id)
    if not project or project.deleted_at:
        raise HTTPException(status_code=404, detail="Project not found")
    documents = [
        item.document
        for item in project.items
        if item.document and item.document.deleted_at is None and (not used_only or item.used_in_output)
    ]
    metadata = [
        {
            "title": document.title,
            "authors": document.authors,
            "publication_year": document.publication_year,
            "journal": document.journal,
            "publisher": document.publisher,
            "doi": document.doi,
            "source_url": document.source_url,
        }
        for document in documents
    ]
    apa = "\n".join(sorted(document.apa_citation or "" for document in documents if document.apa_citation))
    bibtex = "\n\n".join(format_bibtex(item) for item in metadata)
    ris = "\n\n".join(format_ris(item) for item in metadata)
    csl_json = [to_csl_json(item) for item in metadata]
    body = apa
    bibliography = ProjectBibliography(project_id=project.id, style="apa7", body=body)
    db.add(bibliography)
    db.commit()
    return BibliographyOut(project_id=project.id, apa=apa, bibtex=bibtex, ris=ris, csl_json=csl_json)


@app.get("/api/notes", response_model=list[NoteOut])
def list_notes(
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    document_id: str | None = None,
    domain_id: str | None = None,
    project_id: str | None = None,
) -> list[Note]:
    query = db.query(Note).filter(Note.deleted_at.is_(None))
    if document_id:
        query = query.filter(Note.document_id == document_id)
    if domain_id:
        query = query.filter(Note.domain_id == domain_id)
    if project_id:
        query = query.filter(Note.project_id == project_id)
    return query.order_by(Note.created_at.desc()).limit(100).all()


@app.post("/api/notes", response_model=NoteOut)
def create_note(
    payload: NoteCreate,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Note:
    note = Note(**payload.model_dump())
    db.add(note)
    db.flush()
    if note.document_id:
        document = db.get(Document, note.document_id)
        if document and not document.deleted_at:
            document.search_text = rebuild_document_search_text(document)
    db.commit()
    db.refresh(note)
    return note


@app.patch("/api/notes/{note_id}", response_model=NoteOut)
def patch_note(
    note_id: str,
    payload: NotePatch,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Note:
    note = db.get(Note, note_id)
    if not note or note.deleted_at:
        raise HTTPException(status_code=404, detail="Note not found")
    previous_document_id = note.document_id
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(note, key, value)
    affected_document_ids = {previous_document_id, note.document_id}
    for document_id in affected_document_ids:
        if document_id:
            document = db.get(Document, document_id)
            if document and not document.deleted_at:
                document.search_text = rebuild_document_search_text(document)
    db.commit()
    db.refresh(note)
    return note


@app.delete("/api/notes/{note_id}")
def delete_note(
    note_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    note = db.get(Note, note_id)
    if not note or note.deleted_at:
        raise HTTPException(status_code=404, detail="Note not found")
    note.deleted_at = utc_now()
    if note.document_id:
        document = db.get(Document, note.document_id)
        if document and not document.deleted_at:
            document.search_text = rebuild_document_search_text(document)
    db.commit()
    return {"status": "deleted"}
