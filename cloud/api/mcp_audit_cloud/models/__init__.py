"""SQLAlchemy models. One module, because they are one schema.

Conventions, applied everywhere:
- UUIDv7 primary keys: random enough not to be guessable, time-ordered so index
  locality does not fall apart at a million rows.
- `created_at` / `updated_at` on every table, set by the database.
- Every org-scoped table has `org_id` indexed, and RLS on top (docs/SECURITY.md §5).
  The repository layer is the primary enforcement; RLS is the second wall.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from uuid_extensions import uuid7

# Postgres is the production database (D5), but the whole API suite runs against
# SQLite in CI where no container is available -- so the column types carry a
# variant rather than being Postgres-only. Native JSONB and native uuid where they
# exist; portable equivalents where they do not.
PGUUID = Uuid(as_uuid=True)
Json = JSON().with_variant(JSONB(), "postgresql")


def enum_column(kind: type[enum.StrEnum], length: int = 20) -> Any:
    """A StrEnum column that comes *back* as the enum, not as a string.

    Without this, a row loaded from the database holds `"queued"`, and every
    `status is ScanStatus.QUEUED` in the codebase is silently False -- the kind of bug
    that makes a cancel button do nothing. `native_enum=False` keeps it a VARCHAR with
    a CHECK, so there is no Postgres type to migrate every time a value is added.
    """
    return Enum(
        kind,
        native_enum=False,
        length=length,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


class StringArray(TypeDecorator[list[str]]):
    """A list of short strings: Postgres ARRAY, JSON everywhere else."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(String(200)))
        return dialect.type_descriptor(JSON())


#: Named constraints, so Alembic can autogenerate a migration that drops one.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def pk() -> Mapped[UUID]:
    return mapped_column(PGUUID, primary_key=True, default=uuid7)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Role(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class Plan(enum.StrEnum):
    FREE = "free"
    PRO = "pro"
    TEAM = "team"


class ScanStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class TargetKind(enum.StrEnum):
    INVENTORY = "inventory"
    REMOTE_HTTP = "remote_http"


class SubscriptionStatus(enum.StrEnum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"


class User(Base, Timestamps):
    __tablename__ = "users"

    id: Mapped[UUID] = pk()
    clerk_user_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", lazy="selectin")


class Org(Base, Timestamps):
    __tablename__ = "orgs"

    id: Mapped[UUID] = pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    plan: Mapped[Plan] = mapped_column(enum_column(Plan, 16), default=Plan.FREE, nullable=False)
    #: Every user gets one of these on first sight, so nothing requires an org setup step.
    personal: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: Outbound notifications (ROADMAP Phase 6). The URL is a customer's choice, so it
    #: goes through the same SSRF guard as a scan target before we ever post to it.
    webhook_url: Mapped[str | None] = mapped_column(String(2048))
    webhook_secret: Mapped[str | None] = mapped_column(String(64))
    slack_webhook_url: Mapped[str | None] = mapped_column(String(2048))

    memberships: Mapped[list[Membership]] = relationship(back_populates="org", lazy="selectin")


class Membership(Base, Timestamps):
    __tablename__ = "memberships"

    org_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(enum_column(Role, 16), default=Role.MEMBER, nullable=False)

    org: Mapped[Org] = relationship(back_populates="memberships", lazy="joined")
    user: Mapped[User] = relationship(back_populates="memberships", lazy="joined")


class ApiToken(Base, Timestamps):
    """CI credentials. Shown once, stored as sha256 (docs/SECURITY.md §4)."""

    __tablename__ = "api_tokens"

    id: Mapped[UUID] = pk()
    org_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("orgs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(StringArray, default=list, nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID, ForeignKey("users.id"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Target(Base, Timestamps):
    """Something scannable. Header *values* never live here (docs/SECURITY.md §4)."""

    __tablename__ = "targets"

    id: Mapped[UUID] = pk()
    org_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("orgs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[TargetKind] = mapped_column(enum_column(TargetKind, 20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048))
    header_names: Mapped[list[str]] = mapped_column(StringArray, default=list, nullable=False)
    task: Mapped[str | None] = mapped_column(String(500))


class TargetSecret(Base, Timestamps):
    """Encrypted header values for monitored targets, in their own table.

    Separate from `targets` so a query that returns a target can never accidentally
    return its secrets, and so the encryption key lives outside the row you get by
    default.
    """

    __tablename__ = "target_secrets"

    id: Mapped[UUID] = pk()
    target_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("targets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    org_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("orgs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    header_name: Mapped[str] = mapped_column(String(120), nullable=False)
    nonce: Mapped[bytes] = mapped_column(nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(nullable=False)

    __table_args__ = (UniqueConstraint("target_id", "header_name", name="uq_target_secrets_header"),)


class InventoryRow(Base, Timestamps):
    __tablename__ = "inventories"

    id: Mapped[UUID] = pk()
    org_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("orgs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(Json, nullable=False)
    source: Mapped[str | None] = mapped_column(String(2048))
    server_name: Mapped[str | None] = mapped_column(String(200))
    tool_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("org_id", "sha256", name="uq_inventories_org_sha"),)


class Scan(Base, Timestamps):
    __tablename__ = "scans"

    id: Mapped[UUID] = pk()
    org_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("orgs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    target_id: Mapped[UUID | None] = mapped_column(
        PGUUID, ForeignKey("targets.id", ondelete="SET NULL"), index=True
    )
    inventory_id: Mapped[UUID | None] = mapped_column(
        PGUUID, ForeignKey("inventories.id", ondelete="SET NULL")
    )
    status: Mapped[ScanStatus] = mapped_column(
        enum_column(ScanStatus, 16), default=ScanStatus.QUEUED, nullable=False
    )
    trials: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    task: Mapped[str | None] = mapped_column(String(500))
    stub_mode: Mapped[str] = mapped_column(String(16), default="canary", nullable=False)
    verdict: Mapped[str | None] = mapped_column(String(16), index=True)
    report: Mapped[dict[str, Any] | None] = mapped_column(Json)
    error_code: Mapped[str | None] = mapped_column(String(60))
    error_detail: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: micro-dollars: integers, because float money in a database is how you get $0.29999
    cost_micros: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID, ForeignKey("users.id"))
    created_via: Mapped[str] = mapped_column(String(16), default="api", nullable=False)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True)

    findings: Mapped[list[ScanFinding]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (Index("ix_scans_org_created", "org_id", "created_at"),)


class ScanFinding(Base, Timestamps):
    """Findings as rows, for filtering and analytics. The report jsonb stays canonical."""

    __tablename__ = "scan_findings"

    id: Mapped[UUID] = pk()
    scan_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("scans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    org_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("orgs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tool: Mapped[str] = mapped_column(String(200), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    signal: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    real_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    san_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    p_raw: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    p_adj: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(Json)

    scan: Mapped[Scan] = relationship(back_populates="findings")


class Monitor(Base, Timestamps):
    """Rug-pull detection. The recurring-value feature, so it gets its own history."""

    __tablename__ = "monitors"

    id: Mapped[UUID] = pk()
    org_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("orgs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    target_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("targets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    cron: Mapped[str] = mapped_column(String(80), default="0 6 * * *", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    paused_reason: Mapped[str | None] = mapped_column(String(120))
    notify_email: Mapped[str | None] = mapped_column(String(320))
    notify_webhook: Mapped[str | None] = mapped_column(String(2048))
    last_sha256: Mapped[str | None] = mapped_column(String(64))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(40))


class InventoryChange(Base, Timestamps):
    __tablename__ = "inventory_changes"

    id: Mapped[UUID] = pk()
    monitor_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("monitors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    org_id: Mapped[UUID] = mapped_column(
        PGUUID, ForeignKey("orgs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    old_sha256: Mapped[str | None] = mapped_column(String(64))
    new_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    diff: Mapped[dict[str, Any]] = mapped_column(Json, nullable=False)
    scan_id: Mapped[UUID | None] = mapped_column(PGUUID, ForeignKey("scans.id", ondelete="SET NULL"))


class Usage(Base, Timestamps):
    """One row per org per billing period. The quota reservation locks this row."""

    __tablename__ = "usage"

    org_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    scans_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_micros: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Subscription(Base, Timestamps):
    __tablename__ = "subscriptions"

    org_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_id: Mapped[str | None] = mapped_column(String(120))
    subscription_id: Mapped[str | None] = mapped_column(String(120), index=True)
    plan: Mapped[Plan] = mapped_column(enum_column(Plan, 16), default=Plan.FREE, nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(enum_column(SubscriptionStatus, 20), nullable=False)
    interval: Mapped[str] = mapped_column(String(10), default="month", nullable=False)
    seats: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: When the provider says this state was true. Out-of-order webhooks are ignored.
    state_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict[str, Any] | None] = mapped_column(Json)


class WebhookEvent(Base):
    """Idempotency for inbound billing webhooks (docs/SECURITY.md §7)."""

    __tablename__ = "webhook_events"

    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_type: Mapped[str | None] = mapped_column(String(80))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[UUID] = pk()
    org_id: Mapped[UUID | None] = mapped_column(PGUUID, ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID, ForeignKey("users.id"))
    actor_token_id: Mapped[UUID | None] = mapped_column(PGUUID, ForeignKey("api_tokens.id"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target: Mapped[str | None] = mapped_column(String(200))
    meta: Mapped[dict[str, Any] | None] = mapped_column(Json)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


#: Tables that carry org_id and therefore get RLS (docs/SECURITY.md §5).
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

__all__ = [
    "ORG_SCOPED",
    "ApiToken",
    "AuditLog",
    "Base",
    "InventoryChange",
    "InventoryRow",
    "Membership",
    "Monitor",
    "Org",
    "Plan",
    "Role",
    "Scan",
    "ScanFinding",
    "ScanStatus",
    "Subscription",
    "SubscriptionStatus",
    "Target",
    "TargetKind",
    "TargetSecret",
    "Usage",
    "User",
    "WebhookEvent",
]
