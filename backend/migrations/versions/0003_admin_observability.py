"""Durable document failures and content-free chat timing.

Revision ID: 0003_admin_observability
Revises: 0002_auth_member_lookup
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_admin_observability"
down_revision = "0002_auth_member_lookup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A purge record and its identifier-only manifest survive workspace removal.
    # They are recovery state, not a second document catalog.
    op.create_table(
        "workspace_purges",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('running', 'completed')", name="ck_workspace_purges_status"),
        schema="doctrace",
    )
    op.create_index("ix_workspace_purges_pending", "workspace_purges", ["updated_at"],
                    schema="doctrace", postgresql_where=sa.text("status = 'running'"))
    op.create_table(
        "workspace_purge_documents",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("workspace_id", "doc_id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["doctrace.workspace_purges.workspace_id"], ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('pending', 'deleting', 'failed', 'deleted')", name="ck_purge_documents_status"),
        schema="doctrace",
    )
    op.create_index("ix_purge_documents_progress", "workspace_purge_documents",
                    ["workspace_id", "status", "updated_at"], schema="doctrace")
    # Append-only audit attribution must not be rewritten by a cascading FK.
    op.drop_constraint("fk_audit_events_workspace", "audit_events", schema="doctrace")
    op.create_table(
        "document_failures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Preserve historical attribution after workspace purge; no content/FK.
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt >= 0", name="ck_document_failures_attempt"),
        sa.CheckConstraint("kind IN ('index', 'delete')", name="ck_document_failures_kind"),
        sa.CheckConstraint(
            "error_code IN ('invalid_pdf', 'index_failed', 'delete_failed', 'job_interrupted')",
            name="ck_document_failures_code",
        ),
        schema="doctrace",
    )
    op.create_index("ix_document_failures_created", "document_failures", ["created_at", "id"], schema="doctrace")
    op.create_index("ix_document_failures_workspace", "document_failures", ["workspace_id", "created_at"], schema="doctrace")
    op.add_column("chat_requests", sa.Column("latency_ms", sa.Integer()), schema="doctrace")
    op.add_column("chat_requests", sa.Column("first_token_ms", sa.Integer()), schema="doctrace")
    op.create_check_constraint("ck_chat_requests_latency", "chat_requests", "latency_ms >= 0", schema="doctrace")
    op.create_check_constraint("ck_chat_requests_first_token", "chat_requests", "first_token_ms >= 0", schema="doctrace")
    op.create_index("ix_chat_requests_created", "chat_requests", ["created_at"], schema="doctrace")


def downgrade() -> None:
    # Old runtime accepts nullable attribution. Preserve the events on downgrade.
    op.execute("UPDATE doctrace.audit_events SET workspace_id = NULL WHERE workspace_id NOT IN (SELECT id FROM doctrace.workspaces)")
    op.create_foreign_key("fk_audit_events_workspace", "audit_events", "workspaces", ["workspace_id"], ["id"],
                          source_schema="doctrace", referent_schema="doctrace", ondelete="SET NULL")
    op.drop_table("workspace_purge_documents", schema="doctrace")
    op.drop_table("workspace_purges", schema="doctrace")
    op.drop_index("ix_chat_requests_created", table_name="chat_requests", schema="doctrace")
    op.drop_constraint("ck_chat_requests_first_token", "chat_requests", schema="doctrace")
    op.drop_constraint("ck_chat_requests_latency", "chat_requests", schema="doctrace")
    op.drop_column("chat_requests", "first_token_ms", schema="doctrace")
    op.drop_column("chat_requests", "latency_ms", schema="doctrace")
    op.drop_table("document_failures", schema="doctrace")
