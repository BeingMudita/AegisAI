"""Verify all ORM models register on the shared metadata."""

from app.database.models import Base

EXPECTED_TABLES = {
    "users",
    "agents",
    "policies",
    "agent_sessions",
    "document_sources",
    "documents",
    "document_chunks",
    "embeddings",
    "trust_assessments",
    "tool_definitions",
    "tool_requests",
    "security_events",
}


def test_all_tables_registered() -> None:
    tables = set(Base.metadata.tables.keys())
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Missing tables: {missing}"


def test_embeddings_has_vector_column() -> None:
    embeddings = Base.metadata.tables["embeddings"]
    assert "vector" in embeddings.columns
