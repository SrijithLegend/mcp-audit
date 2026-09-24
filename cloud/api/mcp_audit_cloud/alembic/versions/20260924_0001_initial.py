"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-24

Creates every table, then turns on row-level security for the org-scoped ones. RLS is
the second wall behind the repository layer (docs/SECURITY.md §5): the app sets
`app.org_id` per transaction, and a query that forgets its org filter returns nothing
rather than everything.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ORG_SCOPED = (
    "api_tokens",
    "targets",
    "target_secrets",
    "inventories",
    "scans",
    "scan_findings",
    "monitors",
    "inventory_changes",
    "usage",
    "subscriptions",
    "audit_log",
)


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    ts = sa.DateTime(timezone=True)
    now = sa.text("now()")

    op.create_table(
        "users",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("clerk_user_id", sa.String(128), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200)),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
    )
    op.create_table(
        "orgs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("plan", sa.String(16), nullable=False, server_default="free"),
        sa.Column("personal", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
    )
    op.create_table(
        "memberships",
        sa.Column("org_id", uuid, sa.ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
    )
    op.create_table(
        "api_tokens",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("org_id", uuid, sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", postgresql.ARRAY(sa.String(40)), nullable=False, server_default="{}"),
        sa.Column("created_by", uuid, sa.ForeignKey("users.id")),
        sa.Column("last_used_at", ts),
        sa.Column("expires_at", ts),
        sa.Column("revoked_at", ts),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
    )
    op.create_table(
        "targets",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("org_id", uuid, sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("url", sa.String(2048)),
        sa.Column("header_names", postgresql.ARRAY(sa.String(120)), nullable=False, server_default="{}"),
        sa.Column("task", sa.String(500)),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
    )
    op.create_table(
        "target_secrets",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "target_id", uuid, sa.ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("org_id", uuid, sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("header_name", sa.String(120), nullable=False),
        sa.Column("nonce", sa.LargeBinary, nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
        sa.UniqueConstraint("target_id", "header_name", name="uq_target_secrets_header"),
    )
    op.create_table(
        "inventories",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("org_id", uuid, sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content", postgresql.JSONB, nullable=False),
        sa.Column("source", sa.String(2048)),
        sa.Column("server_name", sa.String(200)),
        sa.Column("tool_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("captured_at", ts),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
        sa.UniqueConstraint("org_id", "sha256", name="uq_inventories_org_sha"),
    )
    op.create_table(
        "scans",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("org_id", uuid, sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("target_id", uuid, sa.ForeignKey("targets.id", ondelete="SET NULL"), index=True),
        sa.Column("inventory_id", uuid, sa.ForeignKey("inventories.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("trials", sa.Integer, nullable=False, server_default="5"),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("task", sa.String(500)),
        sa.Column("stub_mode", sa.String(16), nullable=False, server_default="canary"),
        sa.Column("verdict", sa.String(16), index=True),
        sa.Column("report", postgresql.JSONB),
        sa.Column("error_code", sa.String(60)),
        sa.Column("error_detail", sa.Text),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_micros", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", uuid, sa.ForeignKey("users.id")),
        sa.Column("created_via", sa.String(16), nullable=False, server_default="api"),
        sa.Column("queued_at", ts),
        sa.Column("started_at", ts),
        sa.Column("finished_at", ts),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("share_token", sa.String(64), unique=True),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
    )
    op.create_index("ix_scans_org_created", "scans", ["org_id", "created_at"])
    op.create_table(
        "scan_findings",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("scan_id", uuid, sa.ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("org_id", uuid, sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tool", sa.String(200), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("signal", sa.String(80), nullable=False),
        sa.Column("detail", sa.String(120), nullable=False, server_default=""),
        sa.Column("real_rate", sa.Float, nullable=False, server_default="0"),
        sa.Column("san_rate", sa.Float, nullable=False, server_default="0"),
        sa.Column("p_raw", sa.Float, nullable=False, server_default="1"),
        sa.Column("p_adj", sa.Float, nullable=False, server_default="1"),
        sa.Column("evidence", postgresql.JSONB),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
    )
    op.create_table(
        "monitors",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("org_id", uuid, sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column(
            "target_id", uuid, sa.ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("cron", sa.String(80), nullable=False, server_default="0 6 * * *"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("paused_reason", sa.String(120)),
        sa.Column("notify_email", sa.String(320)),
        sa.Column("notify_webhook", sa.String(2048)),
        sa.Column("last_sha256", sa.String(64)),
        sa.Column("last_checked_at", ts),
        sa.Column("last_status", sa.String(40)),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
    )
    op.create_table(
        "inventory_changes",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "monitor_id", uuid, sa.ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("org_id", uuid, sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("old_sha256", sa.String(64)),
        sa.Column("new_sha256", sa.String(64), nullable=False),
        sa.Column("diff", postgresql.JSONB, nullable=False),
        sa.Column("scan_id", uuid, sa.ForeignKey("scans.id", ondelete="SET NULL")),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
    )
    op.create_table(
        "usage",
        sa.Column("org_id", uuid, sa.ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("period_start", ts, primary_key=True),
        sa.Column("scans_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_micros", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
    )
    op.create_table(
        "subscriptions",
        sa.Column("org_id", uuid, sa.ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("customer_id", sa.String(120)),
        sa.Column("subscription_id", sa.String(120), index=True),
        sa.Column("plan", sa.String(16), nullable=False, server_default="free"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("interval", sa.String(10), nullable=False, server_default="month"),
        sa.Column("seats", sa.Integer, nullable=False, server_default="1"),
        sa.Column("current_period_end", ts),
        sa.Column("cancel_at_period_end", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("state_at", ts),
        sa.Column("raw", postgresql.JSONB),
        sa.Column("created_at", ts, server_default=now, nullable=False),
        sa.Column("updated_at", ts, server_default=now, nullable=False),
    )
    op.create_table(
        "webhook_events",
        sa.Column("provider", sa.String(20), primary_key=True),
        sa.Column("event_id", sa.String(200), primary_key=True),
        sa.Column("received_at", ts, server_default=now, nullable=False),
        sa.Column("processed_at", ts),
        sa.Column("event_type", sa.String(80)),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("org_id", uuid, sa.ForeignKey("orgs.id", ondelete="CASCADE"), index=True),
        sa.Column("actor_user_id", uuid, sa.ForeignKey("users.id")),
        sa.Column("actor_token_id", uuid, sa.ForeignKey("api_tokens.id")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target", sa.String(200)),
        sa.Column("meta", postgresql.JSONB),
        sa.Column("ip", sa.String(64)),
        sa.Column("created_at", ts, server_default=now, nullable=False),
    )

    # RLS. `app.org_id` is set per transaction by db.set_org(); a session that never
    # sets it sees nothing at all, which is the correct default for a bug.
    for table in ORG_SCOPED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_org_isolation ON {table}
            USING (org_id::text = current_setting('app.org_id', true))
            WITH CHECK (org_id::text = current_setting('app.org_id', true))
            """
        )


def downgrade() -> None:
    for table in ORG_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}")
    for table in (
        "audit_log",
        "webhook_events",
        "subscriptions",
        "usage",
        "inventory_changes",
        "monitors",
        "scan_findings",
        "scans",
        "inventories",
        "target_secrets",
        "targets",
        "api_tokens",
        "memberships",
        "orgs",
        "users",
    ):
        op.drop_table(table)
