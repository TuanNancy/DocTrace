"""Create the doctrace control-plane schema.

Revision ID: 0001_control_plane
Revises:
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_control_plane"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "doctrace"
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("now()")
EMPTY_OBJECT = sa.text("'{}'::jsonb")
EMPTY_ARRAY = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    op.create_table(
        "workspaces",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False, server_default=sa.text("'free'")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_by", UUID, nullable=False),
        sa.Column("personal_owner_user_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", UUID, nullable=True),
        sa.Column("purge_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind in ('personal', 'team')", name="ck_workspaces_kind"),
        sa.CheckConstraint("plan in ('free', 'pro')", name="ck_workspaces_plan"),
        sa.CheckConstraint(
            "status in ('active', 'archived', 'purging')", name="ck_workspaces_status",
        ),
        sa.CheckConstraint(
            "(kind = 'personal') = (personal_owner_user_id is not null)",
            name="ck_workspaces_personal_owner",
        ),
        sa.CheckConstraint(
            "archived_at is null or archived_at >= created_at", name="ck_workspaces_archived_at",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ux_workspaces_personal_owner", "workspaces", ["personal_owner_user_id"],
        unique=True, schema=SCHEMA, postgresql_where=sa.text("kind = 'personal'"),
    )

    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role in ('owner', 'member')", name="ck_workspace_members_role"),
        sa.CheckConstraint(
            "status in ('active', 'removing', 'removed')", name="ck_workspace_members_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], [f"{SCHEMA}.workspaces.id"], name="fk_workspace_members_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "user_id", name="pk_workspace_members"),
        schema=SCHEMA,
    )
    op.create_index(
        "ux_workspace_members_active_owner", "workspace_members", ["workspace_id"],
        unique=True, schema=SCHEMA,
        postgresql_where=sa.text("role = 'owner' and status = 'active'"),
    )
    op.create_index(
        "ix_workspace_members_user_status", "workspace_members", ["user_id", "status"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_workspace_members_workspace_status", "workspace_members",
        ["workspace_id", "status"], schema=SCHEMA,
    )

    op.create_table(
        "platform_admins",
        sa.Column("user_id", UUID, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("created_by", UUID, nullable=True),
        schema=SCHEMA,
    )

    op.create_table(
        "profiles",
        sa.Column("user_id", UUID, primary_key=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        schema=SCHEMA,
    )
    op.create_index("ix_profiles_email", "profiles", ["email"], schema=SCHEMA)

    op.create_table(
        "plan_limits",
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("limit_value", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("plan in ('free', 'pro')", name="ck_plan_limits_plan"),
        sa.CheckConstraint("limit_value >= 0", name="ck_plan_limits_value"),
        sa.PrimaryKeyConstraint("plan", "metric", name="pk_plan_limits"),
        schema=SCHEMA,
    )
    plan_limits = sa.table(
        "plan_limits",
        sa.column("plan", sa.Text()),
        sa.column("metric", sa.Text()),
        sa.column("limit_value", sa.BigInteger()),
        schema=SCHEMA,
    )
    op.bulk_insert(plan_limits, [
        {"plan": "free", "metric": "chat_questions_month", "limit_value": 10},
        {"plan": "free", "metric": "documents", "limit_value": 5},
        {"plan": "free", "metric": "workspaces", "limit_value": 1},
        {"plan": "pro", "metric": "chat_questions_month", "limit_value": 100},
        {"plan": "pro", "metric": "documents", "limit_value": 50},
        {"plan": "pro", "metric": "workspaces", "limit_value": 10},
    ])

    op.create_table(
        "audit_events",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_user_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(
            ["workspace_id"], [f"{SCHEMA}.workspaces.id"], name="fk_audit_events_workspace",
            ondelete="SET NULL",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_workspace_created", "audit_events",
        ["workspace_id", sa.text("created_at desc")], schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_actor_created", "audit_events",
        ["actor_user_id", sa.text("created_at desc")], schema=SCHEMA,
    )
    op.create_index("ix_audit_events_created", "audit_events", ["created_at"], schema=SCHEMA)

    op.create_table(
        "conversations",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("doc_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("document_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], [f"{SCHEMA}.workspaces.id"],
            name="fk_conversations_workspace", ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(document_deleted_at is null) = (purge_after is null)",
            name="ck_conversations_purge_window",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ux_conversations_active_document", "conversations",
        ["workspace_id", "user_id", "doc_id"], unique=True, schema=SCHEMA,
        postgresql_where=sa.text("document_deleted_at is null and purge_after is null"),
    )
    op.create_index(
        "ix_conversations_owner_updated", "conversations",
        ["workspace_id", "user_id", sa.text("updated_at desc")], schema=SCHEMA,
    )
    op.create_index("ix_conversations_purge_after", "conversations", ["purge_after"], schema=SCHEMA)

    op.create_table(
        "messages",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("sources", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("index_id", UUID, nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(
            ["conversation_id"], [f"{SCHEMA}.conversations.id"],
            name="fk_messages_conversation", ondelete="CASCADE",
        ),
        sa.CheckConstraint("role in ('user', 'assistant')", name="ck_messages_role"),
        sa.CheckConstraint(
            "status in ('pending', 'streaming', 'complete', 'interrupted', 'error')",
            name="ck_messages_status",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_messages_conversation_created", "messages",
        ["conversation_id", "created_at"], schema=SCHEMA,
    )

    op.create_table(
        "chat_requests",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("request_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=True),
        sa.Column("doc_id", UUID, nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], [f"{SCHEMA}.workspaces.id"],
            name="fk_chat_requests_workspace", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], [f"{SCHEMA}.conversations.id"],
            name="fk_chat_requests_conversation", ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status in ('admitted', 'streaming', 'completed', 'failed', 'interrupted')",
            name="ck_chat_requests_status",
        ),
        sa.UniqueConstraint(
            "workspace_id", "user_id", "request_id", name="ux_chat_requests_idempotency",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_chat_requests_workspace_created", "chat_requests",
        ["workspace_id", sa.text("created_at desc")], schema=SCHEMA,
    )
    op.create_index(
        "ix_chat_requests_user_created", "chat_requests",
        ["user_id", sa.text("created_at desc")], schema=SCHEMA,
    )

    op.create_table(
        "provider_calls",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("request_id", UUID, nullable=True),
        sa.Column("workspace_id", UUID, nullable=True),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("doc_id", UUID, nullable=True),
        sa.Column("job_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False, server_default=sa.text("'openrouter'")),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("generation_id", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("cached_tokens", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("reasoning_tokens", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_micros", sa.BigInteger(), nullable=True),
        sa.Column("cost_status", sa.Text(), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'ok'")),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("raw_usage", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(
            ["workspace_id"], [f"{SCHEMA}.workspaces.id"],
            name="fk_provider_calls_workspace", ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "kind in ('query_embedding', 'index_embedding', 'summary', 'answer', 'embedding_probe')",
            name="ck_provider_calls_kind",
        ),
        sa.CheckConstraint(
            "cost_status in ('reported', 'reconciled', 'estimated', 'unknown')",
            name="ck_provider_calls_cost_status",
        ),
        sa.CheckConstraint("status in ('ok', 'error')", name="ck_provider_calls_status"),
        sa.CheckConstraint(
            "prompt_tokens >= 0 and completion_tokens >= 0 and cached_tokens >= 0 "
            "and reasoning_tokens >= 0", name="ck_provider_calls_tokens",
        ),
        sa.CheckConstraint(
            "cost_micros is null or cost_micros >= 0", name="ck_provider_calls_cost",
        ),
        sa.CheckConstraint(
            "latency_ms is null or latency_ms >= 0", name="ck_provider_calls_latency",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ux_provider_calls_generation", "provider_calls", ["generation_id"],
        unique=True, schema=SCHEMA,
        postgresql_where=sa.text("generation_id is not null"),
    )
    op.create_index(
        "ix_provider_calls_workspace_created", "provider_calls",
        ["workspace_id", sa.text("created_at desc")], schema=SCHEMA,
    )
    op.create_index("ix_provider_calls_request", "provider_calls", ["request_id"], schema=SCHEMA)
    op.create_index("ix_provider_calls_doc", "provider_calls", ["doc_id"], schema=SCHEMA)
    op.create_index(
        "ix_provider_calls_created", "provider_calls", ["created_at"], schema=SCHEMA,
    )

    op.create_table(
        "usage_counters",
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("used", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(
            ["workspace_id"], [f"{SCHEMA}.workspaces.id"],
            name="fk_usage_counters_workspace", ondelete="CASCADE",
        ),
        sa.CheckConstraint("used >= 0", name="ck_usage_counters_used"),
        sa.PrimaryKeyConstraint(
            "workspace_id", "period_start", "metric", name="pk_usage_counters",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("usage_counters", schema=SCHEMA)
    op.drop_table("provider_calls", schema=SCHEMA)
    op.drop_table("chat_requests", schema=SCHEMA)
    op.drop_table("messages", schema=SCHEMA)
    op.drop_table("conversations", schema=SCHEMA)
    op.drop_table("audit_events", schema=SCHEMA)
    op.drop_table("plan_limits", schema=SCHEMA)
    op.drop_table("profiles", schema=SCHEMA)
    op.drop_table("platform_admins", schema=SCHEMA)
    op.drop_table("workspace_members", schema=SCHEMA)
    op.drop_table("workspaces", schema=SCHEMA)
