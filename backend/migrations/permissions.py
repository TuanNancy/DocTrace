"""Explicit grants for the optional, separately bootstrapped runtime login.

Called after each successful upgrade (including a no-op upgrade). The migration
identity owns DDL; runtime cannot create schema objects, edit plan definitions,
grant platform admin, rewrite audit events or change Alembic's version stamp.
"""
from sqlalchemy import text

from app.db_contract import AUTH_LOOKUP_FUNCTION, RUNTIME_ROLE, TABLE_PRIVILEGES


def grant_runtime_access(connection) -> None:
    connection.execute(text("REVOKE ALL ON SCHEMA doctrace FROM PUBLIC"))
    connection.execute(text("REVOKE ALL ON ALL TABLES IN SCHEMA doctrace FROM PUBLIC"))
    connection.execute(text("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA doctrace FROM PUBLIC"))
    for role in ("anon", "authenticated", "service_role"):
        exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}).scalar()
        if exists:
            connection.execute(text(f'REVOKE ALL ON SCHEMA doctrace FROM "{role}"'))
            connection.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA doctrace FROM "{role}"'))
            connection.execute(text(f'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA doctrace FROM "{role}"'))
    exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": RUNTIME_ROLE}).scalar()
    if not exists:
        return  # Fresh dev/test databases can bootstrap the runtime login later.
    connection.execute(text(f'REVOKE ALL ON SCHEMA doctrace FROM "{RUNTIME_ROLE}"'))
    connection.execute(text(f'GRANT USAGE ON SCHEMA doctrace TO "{RUNTIME_ROLE}"'))
    connection.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA doctrace FROM "{RUNTIME_ROLE}"'))
    for table, privileges in TABLE_PRIVILEGES.items():
        connection.execute(text(f'GRANT {", ".join(privileges)} ON doctrace."{table}" TO "{RUNTIME_ROLE}"'))
    # No default grant on future functions: opt in explicitly. A per-schema
    # default REVOKE cannot override Postgres's global PUBLIC EXECUTE default.
    connection.execute(text(f'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA doctrace FROM "{RUNTIME_ROLE}"'))
    # Allow upgrades/downgrades to the earlier revision in isolated tests.
    if connection.execute(text("SELECT to_regprocedure(:function)"), {"function": AUTH_LOOKUP_FUNCTION}).scalar():
        connection.execute(text(f'GRANT EXECUTE ON FUNCTION {AUTH_LOOKUP_FUNCTION} TO "{RUNTIME_ROLE}"'))
