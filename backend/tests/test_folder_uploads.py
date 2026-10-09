import pytest
from fastapi.testclient import TestClient

from app.api.routes import retrieval
from app.auth.dependencies import get_current_user
from app.auth.roles import Role
from app.auth.schemas import User
from app.database.enums import TrustLevel
from app.firewall.scanner import PromptFirewall
from app.main import app
from app.policies.config import RagPolicy
from app.rag.embeddings import HashingEmbedder
from app.rag.ingestion import IngestionManager
from app.rag.knowledge_base import KnowledgeBase
from app.rag.paths import archive_location, file_source, normalize_relative_path
from app.trust.engine import TrustEngine


@pytest.fixture
def folder_api(tmp_path, monkeypatch):
    kb = KnowledgeBase(
        embedder=HashingEmbedder(384),
        firewall=PromptFirewall(),
        trust=TrustEngine(),
        policy=RagPolicy(),
        persist_dir=tmp_path / "index",
    )
    inbox, uploads = tmp_path / "inbox", tmp_path / "uploads"
    inbox.mkdir()
    uploads.mkdir()
    manager = IngestionManager(kb, inbox_dir=inbox, upload_dir=uploads)
    monkeypatch.setattr(retrieval, "get_ingestion_manager", lambda: manager)
    app.dependency_overrides[get_current_user] = lambda: User(username="admin", role=Role.ADMIN)
    try:
        yield TestClient(app), manager, kb
    finally:
        manager._queue.join()
        app.dependency_overrides.pop(get_current_user, None)


def test_folder_upload_retains_nested_paths_and_copies(folder_api):
    client, manager, kb = folder_api
    files = [("files", ("invoice.txt", b"Invoice total 50", "text/plain"))] * 2
    paths = ["Finance/Invoices/2026/invoice.txt", "Finance/Payroll/invoice.txt"]
    response = client.post("/api/retrieval/uploads", files=files, data={"relative_paths": paths})
    assert response.status_code == 202, response.text
    jobs = [manager.wait(job["id"]) for job in response.json()]
    assert all(job.stage == "COMPLETED" for job in jobs)
    assert jobs[0].document_id != jobs[1].document_id
    assert [job.source for job in jobs] == paths
    docs = [kb.document(job.document_id) for job in jobs]
    assert [doc.filename for doc in docs] == paths
    assert [(doc.section, doc.folder) for doc in docs] == [
        ("Finance", "Invoices/2026"),
        ("Finance", "Payroll"),
    ]
    assert not list(manager.upload_dir.iterdir())
    repeated = client.post(
        "/api/retrieval/uploads", files=files, data={"relative_paths": paths}
    ).json()
    assert [manager.wait(job["id"]).duplicate_of for job in repeated] == [
        doc.document_id for doc in docs
    ]
    assert len(kb.documents()) == 2
    assert kb.load()
    assert kb.document(docs[0].document_id).folder == "Invoices/2026"


@pytest.mark.parametrize(
    "path",
    [
        "../invoice.txt",
        "/Finance/invoice.txt",
        "C:\\invoice.txt",
        "Finance/../invoice.txt",
        "Finance//invoice.txt",
        "Finance/other.txt",
    ],
)
def test_invalid_folder_paths_do_not_queue_any_files(folder_api, path):
    client, manager, _ = folder_api
    response = client.post(
        "/api/retrieval/uploads",
        files=[
            ("files", ("valid.txt", b"Valid document", "text/plain")),
            ("files", ("invoice.txt", b"Invoice", "text/plain")),
        ],
        data={"relative_paths": ["Finance/valid.txt", path]},
    )
    assert response.status_code == 422
    assert manager.list_jobs() == []
    assert not list(manager.upload_dir.iterdir())


def test_folder_path_count_must_match_file_count(folder_api):
    client, manager, _ = folder_api
    response = client.post(
        "/api/retrieval/uploads",
        files=[
            ("files", ("one.txt", b"one", "text/plain")),
            ("files", ("two.txt", b"two", "text/plain")),
        ],
        data={"relative_paths": ["Finance/one.txt"]},
    )
    assert response.status_code == 422 and not manager.list_jobs()


def test_nested_inbox_files_use_the_same_archive_structure(folder_api):
    _, manager, kb = folder_api
    folder = manager.inbox_dir / "Finance" / "Invoices" / "2026"
    folder.mkdir(parents=True)
    (folder / "bill.txt").write_text("Invoice total 100")
    jobs = manager.import_inbox(
        None, source="Inbox", trust_level=TrustLevel.HIGH, source_per_file=True
    )
    job = manager.wait(jobs[0].id)
    doc = kb.document(job.document_id)
    assert (doc.section, doc.folder, doc.filename) == (
        "Finance",
        "Invoices/2026",
        "Finance/Invoices/2026/bill.txt",
    )


def test_location_overrides_and_long_source_names():
    assert archive_location("Finance/Invoices/2026/a.txt", "Unsorted", "General").model_dump() == {
        "section": "Finance",
        "folder": "Invoices/2026",
    }
    assert archive_location("Finance/a.txt", "Unsorted", "General").folder == "General"
    assert archive_location("Finance/Invoices/a.txt", "Company", "Imports").folder == (
        "Imports/Finance/Invoices"
    )
    assert normalize_relative_path("Finance\\Invoices\\a.txt") == "Finance/Invoices/a.txt"
    assert len(file_source("Finance/" + "nested/" * 80 + "a.txt")) == 255
