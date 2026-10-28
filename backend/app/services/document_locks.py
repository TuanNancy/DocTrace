"""Short, transaction-scoped fences across Redis lifecycle and Postgres content.

No database row is needed for Redis-owned documents. API admissions, deletion
and transcript writes use the same namespaced advisory lock. It is released on
commit/rollback, including with a transaction pooler; never hold it over RAG,
Storage or vector operations.
"""
from hashlib import sha256
from uuid import UUID

from sqlalchemy import text


def lock_document(session, workspace_id: str, user_id: str, doc_id: str) -> None:
    scope = ":".join(str(UUID(value)) for value in (workspace_id, user_id, doc_id))
    digest = sha256(f"doctrace:document-lifecycle:v1:{scope}".encode()).digest()
    key = int.from_bytes(digest[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
