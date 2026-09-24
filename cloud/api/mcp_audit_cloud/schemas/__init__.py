"""Request and response models. Never a SQLAlchemy model on the wire.

Cursor pagination everywhere: OFFSET on a growing table is a sequential scan, and page
3 shifts under the reader when page 1 changes. The cursor is the opaque, time-ordered
primary key, which is what UUIDv7 buys us.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    plan: str
    personal: bool
    role: str | None = None


class UsageOut(BaseModel):
    period_start: datetime
    scans_used: int
    scans_limit: int
    cost_usd: float


class MeOut(BaseModel):
    user_id: UUID | None
    email: str | None
    orgs: list[OrgOut]
    current_org: OrgOut | None
    plan: str
    entitlements: dict[str, Any]
    usage: UsageOut


class ScanCreate(BaseModel):
    """Exactly one of `inventory` or `target_id` (invariant 3: never a command)."""

    inventory: dict[str, Any] | None = None
    target_id: UUID | None = None
    trials: int | None = Field(default=None, ge=2, le=20)
    task: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=80)
    stub_mode: Literal["canary", "inert"] = "canary"
    headers: dict[str, str] | None = Field(default=None, description="One-off headers for a remote target")

    @field_validator("headers")
    @classmethod
    def _no_giant_headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value and (len(value) > 10 or any(len(v) > 4096 for v in value.values())):
            raise ValueError("too many or too large headers")
        return value


class ScanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    verdict: str | None
    trials: int
    model: str
    task: str | None
    stub_mode: str
    target_id: UUID | None
    inventory_id: UUID | None
    created_via: str
    cost_usd: float = 0.0
    error_code: str | None = None
    error_detail: str | None = None
    share_token: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def of(cls, scan: Any) -> ScanOut:
        return cls(
            id=scan.id,
            status=str(scan.status),
            verdict=scan.verdict,
            trials=scan.trials,
            model=scan.model,
            task=scan.task,
            stub_mode=scan.stub_mode,
            target_id=scan.target_id,
            inventory_id=scan.inventory_id,
            created_via=scan.created_via,
            cost_usd=round((scan.cost_micros or 0) / 1_000_000, 6),
            error_code=scan.error_code,
            error_detail=scan.error_detail,
            share_token=scan.share_token,
            created_at=scan.created_at,
            started_at=scan.started_at,
            finished_at=scan.finished_at,
        )


class TargetCreate(BaseModel):
    name: str = Field(max_length=200)
    kind: Literal["inventory", "remote_http"] = "remote_http"
    url: str | None = Field(default=None, max_length=2048)
    task: str | None = Field(default=None, max_length=500)
    #: Write-only. Values are encrypted and never returned (docs/SECURITY.md §4).
    headers: dict[str, str] | None = None


class TargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    kind: str
    url: str | None
    task: str | None
    header_names: list[str]
    created_at: datetime


class MonitorCreate(BaseModel):
    target_id: UUID
    enabled: bool = True
    notify_email: str | None = Field(default=None, max_length=320)
    notify_webhook: str | None = Field(default=None, max_length=2048)


class MonitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    target_id: UUID
    enabled: bool
    paused_reason: str | None
    last_sha256: str | None
    last_checked_at: datetime | None
    last_status: str | None
    created_at: datetime


class ChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    monitor_id: UUID
    old_sha256: str | None
    new_sha256: str
    diff: dict[str, Any]
    scan_id: UUID | None
    created_at: datetime


class TokenCreate(BaseModel):
    name: str = Field(max_length=120)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class TokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    prefix: str
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class TokenCreated(TokenOut):
    #: The only time the full token is ever returned by this API.
    token: str


class OrgCreate(BaseModel):
    name: str = Field(max_length=200)


class MemberInvite(BaseModel):
    email: str = Field(max_length=320)
    role: Literal["admin", "member"] = "member"


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    name: str | None
    role: str


class CheckoutRequest(BaseModel):
    plan: Literal["pro", "team"]
    interval: Literal["month", "year"] = "month"


class UrlOut(BaseModel):
    url: str
