"""Exact-answer cache observability.

Revision ID: 0004_answer_cache
Revises: 0003_admin_observability
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_answer_cache"
down_revision = "0003_admin_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A cache hit still consumes one admitted question but records no provider
    # call. This flag keeps that zero-cost path visible in admin reports.
    op.add_column("chat_requests", sa.Column("cache_hit", sa.Boolean(), nullable=False,
                                             server_default=sa.text("false")), schema="doctrace")


def downgrade() -> None:
    op.drop_column("chat_requests", "cache_hit", schema="doctrace")
