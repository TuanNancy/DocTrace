"""Explicit grants for the optional, separately bootstrapped runtime login.

Called after each successful upgrade (including a no-op upgrade). The migration
identity owns DDL; runtime cannot create schema objects, edit plan definitions,
grant platform admin, rewrite audit events or change Alembic's version stamp.
"""
from sqlalchemy import text

from app.db_contract import RUNTIME_ROLE, TABLE_PRIVILEGES


def grant_runtime_access(connection) -> None:
    connection.execute(text("REVOKE ALL ON SCHEMA doctrace FROM PUBLIC"))
    connection.execute(text("REVOKE ALL ON ALL TABLES IN SCHEMA doctrace FROM PUBLIC"))
    for role in ("anon", "authenticated", "service_role"):
        exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}).scalar()
        if exists:
            connection.execute(text(f'REVOKE ALL ON SCHEMA doctrace FROM "{role}"'))
            connection.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA doctrace FROM "{role}"'))
    exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": RUNTIME_ROLE}).scalar()
    if not exists:
        return  # Fresh dev/test databases can bootstrap the runtime login later.
    connection.execute(text(f'REVOKE ALL ON SCHEMA doctrace FROM "{RUNTIME_ROLE}"'))
    connection.execute(text(f'GRANT USAGE ON SCHEMA doctrace TO "{RUNTIME_ROLE}"'))
    connection.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA doctrace FROM "{RUNTIME_ROLE}"'))
    for table, privileges in TABLE_PRIVILEGES.items():
        connection.execute(text(f'GRANT {", ".join(privileges)} ON doctrace."{table}" TO "{RUNTIME_ROLE}"'))
    # No default grant on future tables/functions: each migration must opt in.
    connection.execute(text("ALTER DEFAULT PRIVILEGES IN SCHEMA doctrace REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"))
