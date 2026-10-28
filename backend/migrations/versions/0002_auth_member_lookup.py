"""Add a private, hosted-compatible Auth membership lookup.

Revision ID: 0002_auth_member_lookup
Revises: 0001_control_plane
Create Date: 2026-10-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_auth_member_lookup"
down_revision: Union[str, Sequence[str], None] = "0001_control_plane"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Hosted postgres can read Auth but cannot grant custom roles schema USAGE.
    # Keep the definer in our unexposed schema, with a fixed search path and only
    # a boolean result. Backend owner authorization precedes this lookup; SQL
    # connections do not carry Data API JWT settings or use auth.uid().
    # row_security=off fails closed if the definer loses RLS bypass instead of
    # silently treating every existing user as missing. It does not grant bypass.
    op.execute("""
        CREATE FUNCTION doctrace.auth_user_exists(p_user_id uuid)
        RETURNS boolean
        LANGUAGE sql STABLE STRICT SECURITY DEFINER
        SET search_path = ''
        SET row_security = off
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM auth.users
                WHERE id = p_user_id AND deleted_at IS NULL
            )
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION doctrace.auth_user_exists(uuid) FROM PUBLIC")
    # Supabase may have per-role default function grants. Revoke them in this
    # transaction, including offline migration SQL; env.py grants runtime only.
    op.execute("""
        DO $$
        DECLARE api_role text;
        BEGIN
            FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
                    EXECUTE format(
                        'REVOKE ALL ON FUNCTION doctrace.auth_user_exists(uuid) FROM %I', api_role
                    );
                END IF;
            END LOOP;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION doctrace.auth_user_exists(uuid)")
