from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_domain_rename_rebuilds_document_search_and_rejects_cycles(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import update_domain
    from app.models import Document, DocumentVersion, Domain
    from app.schemas import DomainPatch
    from app.services.search import rebuild_document_search_text

    Session = make_session()
    with Session() as db:
        root = Domain(name="Science")
        child = Domain(name="Physics", parent=root)
        grandchild = Domain(name="Entanglement", parent=child)
        document = Document(
            title="Domain Paper",
            original_filename="domain.pdf",
            checksum_sha256="d" * 64,
            processing_status="ready",
            domains=[child],
        )
        db.add_all([root, child, grandchild, document])
        db.commit()
        document.search_text = rebuild_document_search_text(document)
        db.commit()

        updated = update_domain(child.id, DomainPatch(name="Quantum Physics"), object(), db)

        db.refresh(document)
        version = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).one()
        assert updated.name == "Quantum Physics"
        assert "Quantum Physics" in document.search_text
        assert version.metadata_snapshot["operation"] == "domain_rename"
        assert version.metadata_snapshot["changed_fields"] == ["domains"]

        try:
            update_domain(root.id, DomainPatch(parent_id=grandchild.id), object(), db)
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("Moving a domain under its descendant should fail.")


def test_domain_delete_soft_deletes_detaches_documents_and_reparents_children(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import delete_domain
    from app.models import Document, DocumentVersion, Domain, Note
    from app.services.search import rebuild_document_search_text

    Session = make_session()
    with Session() as db:
        root = Domain(name="Security")
        child = Domain(name="Insider Threat", parent=root)
        grandchild = Domain(name="Detection", parent=child)
        document = Document(
            title="Threat Paper",
            original_filename="threat.pdf",
            checksum_sha256="e" * 64,
            processing_status="ready",
            domains=[child],
        )
        db.add_all([root, child, grandchild, document])
        db.flush()
        note = Note(title="Domain note", body="Review this domain.", domain_id=child.id)
        db.add(note)
        db.commit()
        document.search_text = rebuild_document_search_text(document)
        db.commit()

        result = delete_domain(child.id, object(), db)

        db.refresh(child)
        db.refresh(grandchild)
        db.refresh(document)
        db.refresh(note)
        version = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).one()
        assert result.deleted_id == child.id
        assert result.updated_documents == 1
        assert child.deleted_at is not None
        assert grandchild.parent_id == root.id
        assert document.domains == []
        assert note.domain_id is None
        assert "Insider Threat" not in (document.search_text or "")
        assert version.metadata_snapshot["operation"] == "domain_delete"


def test_list_domains_returns_alphabetical_names_before_manual_sort_order(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import list_domains
    from app.models import Domain

    Session = make_session()
    with Session() as db:
        zeta = Domain(name="Zeta", sort_order=0)
        alpha = Domain(name="Alpha", sort_order=10)
        beta_child = Domain(name="Beta Child", parent=alpha, sort_order=0)
        alpha_child = Domain(name="Alpha Child", parent=alpha, sort_order=99)
        db.add_all([zeta, alpha, beta_child, alpha_child])
        db.commit()

        result = list_domains(object(), db)

    assert [domain.name for domain in result] == ["Alpha", "Alpha Child", "Beta Child", "Zeta"]


def test_list_domains_includes_unique_subtree_document_counts(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import list_domains
    from app.models import Document, Domain

    Session = make_session()
    with Session() as db:
        root = Domain(name="Research")
        child = Domain(name="Methods", parent=root)
        grandchild = Domain(name="Surveys", parent=child)
        dual_assigned = Document(
            title="Direct And Child",
            original_filename="direct-child.pdf",
            checksum_sha256="a" * 64,
            processing_status="ready",
            domains=[root, child],
        )
        child_only = Document(
            title="Child Only",
            original_filename="child.pdf",
            checksum_sha256="b" * 64,
            processing_status="ready",
            domains=[child],
        )
        grandchild_only = Document(
            title="Grandchild Only",
            original_filename="grandchild.pdf",
            checksum_sha256="c" * 64,
            processing_status="ready",
            domains=[grandchild],
        )
        queued = Document(
            title="Queued",
            original_filename="queued.pdf",
            checksum_sha256="d" * 64,
            processing_status="queued",
            domains=[grandchild],
        )
        db.add_all([root, child, grandchild, dual_assigned, child_only, grandchild_only, queued])
        db.commit()

        result = {domain.name: domain for domain in list_domains(object(), db)}

    assert result["Research"].document_count == 1
    assert result["Research"].subtree_document_count == 3
    assert result["Methods"].document_count == 2
    assert result["Methods"].subtree_document_count == 3
    assert result["Surveys"].document_count == 1
    assert result["Surveys"].subtree_document_count == 1


def test_domain_tags_create_patch_and_clear(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import create_domain, update_domain
    from app.models import Domain, Tag
    from app.schemas import DomainCreate, DomainPatch

    Session = make_session()
    with Session() as db:
        methods = Tag(name="Methods")
        policy = Tag(name="Policy")
        db.add_all([methods, policy])
        db.commit()

        created = create_domain(
            DomainCreate(
                name="Responsible AI",
                description="Governance and evaluation work.",
                tag_ids=[policy.id, methods.id, policy.id],
            ),
            object(),
            db,
        )

        domain = db.get(Domain, created.id)
        assert created.description == "Governance and evaluation work."
        assert [tag.name for tag in created.tags] == ["Methods", "Policy"]
        assert sorted(tag.name for tag in domain.tags) == ["Methods", "Policy"]

        updated = update_domain(domain.id, DomainPatch(tag_ids=[methods.id]), object(), db)
        db.refresh(domain)
        assert [tag.name for tag in updated.tags] == ["Methods"]
        assert [tag.name for tag in domain.tags] == ["Methods"]

        cleared = update_domain(domain.id, DomainPatch(tag_ids=[]), object(), db)
        db.refresh(domain)
        assert cleared.tags == []
        assert domain.tags == []


def test_domain_reorder_moves_domains_and_rejects_parent_cycles(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import reorder_domains
    from app.models import Domain
    from app.schemas import DomainReorder

    Session = make_session()
    with Session() as db:
        literature = Domain(name="Literature", sort_order=0)
        philosophy = Domain(name="Philosophy", sort_order=1)
        cybernetics = Domain(name="Cybernetics", parent=literature, sort_order=0)
        db.add_all([literature, philosophy, cybernetics])
        db.commit()

        reordered = reorder_domains(
            DomainReorder(
                domains=[
                    {"id": philosophy.id, "parent_id": None, "sort_order": 0},
                    {"id": literature.id, "parent_id": None, "sort_order": 1},
                    {"id": cybernetics.id, "parent_id": philosophy.id, "sort_order": 0},
                ]
            ),
            object(),
            db,
        )

        db.refresh(cybernetics)
        assert cybernetics.parent_id == philosophy.id
        reordered_by_id = {domain.id: domain for domain in reordered}
        assert reordered_by_id[philosophy.id].sort_order == 0
        assert reordered_by_id[literature.id].sort_order == 1

        try:
            reorder_domains(
                DomainReorder(
                    domains=[
                        {"id": philosophy.id, "parent_id": cybernetics.id, "sort_order": 0},
                        {"id": cybernetics.id, "parent_id": philosophy.id, "sort_order": 0},
                    ]
                ),
                object(),
                db,
            )
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("Reorder should reject parent cycles.")
