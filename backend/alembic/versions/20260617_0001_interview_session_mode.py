"""Add interview_mode column to interview_sessions."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260617_0002"
down_revision = "20260617_0001"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    if _has_column("interview_sessions", "interview_mode"):
        return
    op.add_column(
        "interview_sessions",
        sa.Column(
            "interview_mode",
            sa.String(16),
            nullable=False,
            server_default="text",
        ),
    )


def downgrade() -> None:
    if _has_column("interview_sessions", "interview_mode"):
        op.drop_column("interview_sessions", "interview_mode")
