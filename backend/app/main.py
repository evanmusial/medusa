from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db, init_db, is_postgres, session_scope
from app.models import (
    AttributeDefinition,
    CitationCandidate,
    Document,
    DocumentAttributeValue,
    Domain,
    ImportBatch,
    ImportJob,
    Note,
    ProcessingEvent,
    Project,
    ProjectBibliography,
    ProjectItem,
    Tag,
    User,
    utc_now,
)
from app.schemas import (
    AttributeDefinitionCreate,
    AttributeDefinitionOut,
    BibliographyOut,
    CitationCandidateOut,
    DashboardOut,
    DocumentDetail,
    DocumentPatch,
    DocumentSummary,
    DomainCreate,
    DomainOut,
    ImportBatchOut,
    ImportJobOut,
    LoginRequest,
    ProcessingEventOut,
    ProjectCreate,
    ProjectOut,
    TagCreate,
    TagOut,
    UserOut,
)
from app.security import create_session, ensure_admin_user, revoke_session, user_for_token, verify_password
from app.services.citations import format_bibtex, format_ris, to_csl_json
from app.services.processing import refresh_import_batch_progress
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
        queued_jobs=db.query(ImportJob).filter(ImportJob.status.in_(["queued", "running"])).count(),
        failed_jobs=db.query(ImportJob).filter(ImportJob.status == "failed").count(),
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
    domain_ids = data.pop("domain_ids", None)
    for key, value in data.items():
        setattr(document, key, value)
    if tag_ids is not None:
        document.tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
    if domain_ids is not None:
        document.domains = db.query(Domain).filter(Domain.id.in_(domain_ids)).all() if domain_ids else []
    document.search_text = "\n\n".join(part for part in [document.title, document.abstract, document.rich_summary, document.search_text] if part)
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


@app.get("/api/projects/{project_id}/bibliography", response_model=BibliographyOut)
def project_bibliography(
    project_id: str,
    _: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> BibliographyOut:
    project = db.get(Project, project_id)
    if not project or project.deleted_at:
        raise HTTPException(status_code=404, detail="Project not found")
    documents = [item.document for item in project.items if item.document and item.document.deleted_at is None]
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


@app.get("/api/notes")
def list_notes(_: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> list[dict[str, Any]]:
    notes = db.query(Note).filter(Note.deleted_at.is_(None)).order_by(Note.created_at.desc()).limit(100).all()
    return [
        {
            "id": note.id,
            "title": note.title,
            "body": note.body,
            "kind": note.kind,
            "document_id": note.document_id,
            "domain_id": note.domain_id,
            "project_id": note.project_id,
            "reminder_at": note.reminder_at,
            "created_at": note.created_at,
        }
        for note in notes
    ]
