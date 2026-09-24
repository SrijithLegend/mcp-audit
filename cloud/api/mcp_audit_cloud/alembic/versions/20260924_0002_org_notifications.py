"""org outbound notifications

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24

Expand-only: three nullable columns. The previous version keeps serving while this runs,
which is the rule for every migration here (ROADMAP Phase 7).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orgs", sa.Column("webhook_url", sa.String(2048), nullable=True))
    op.add_column("orgs", sa.Column("webhook_secret", sa.String(64), nullable=True))
    op.add_column("orgs", sa.Column("slack_webhook_url", sa.String(2048), nullable=True))


def downgrade() -> None:
    op.drop_column("orgs", "slack_webhook_url")
    op.drop_column("orgs", "webhook_secret")
    op.drop_column("orgs", "webhook_url")
