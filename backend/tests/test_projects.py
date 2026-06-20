from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_session():
    from app.database import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_project_run_sheet_items_and_used_bibliography(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))

    from app.main import add_project_items, delete_project_item, patch_project_item, project_bibliography
    from app.models import Document, Project, ProjectItem
    from app.schemas import ProjectItemCreate, ProjectItemPatch

    Session = make_session()
    with Session() as db:
        project = Project(name="Cognitive Maps")
        used_document = Document(
            title="Used Resource",
            original_filename="used.pdf",
            checksum_sha256="a" * 64,
            apa_citation="Used Resource citation.",
            processing_status="ready",
        )
        candidate_document = Document(
            title="Candidate Resource",
            original_filename="candidate.pdf",
            checksum_sha256="b" * 64,
            apa_citation="Candidate Resource citation.",
            processing_status="ready",
        )
        db.add_all([project, used_document, candidate_document])
        db.commit()

        detail = add_project_items(
            project.id,
            ProjectItemCreate(document_ids=[used_document.id, candidate_document.id, used_document.id], priority="high"),
            object(),
            db,
        )

        assert detail.item_count == 2
        assert {item.document_id for item in detail.items} == {used_document.id, candidate_document.id}
        assert all(item.priority == "high" for item in detail.items)

        used_item = db.query(ProjectItem).filter(ProjectItem.document_id == used_document.id).one()
        patch_project_item(
            project.id,
            used_item.id,
            ProjectItemPatch(status="used", used_in_output=True, note="Anchor source."),
            object(),
            db,
        )
        bibliography = project_bibliography(project.id, object(), db, used_only=True)

        assert "Used Resource citation." in bibliography.apa
        assert "Candidate Resource citation." not in bibliography.apa
        assert used_item.used_in_output is True
        assert used_item.note == "Anchor source."

        candidate_item = db.query(ProjectItem).filter(ProjectItem.document_id == candidate_document.id).one()
        delete_project_item(project.id, candidate_item.id, object(), db)

        assert db.query(ProjectItem).count() == 1
