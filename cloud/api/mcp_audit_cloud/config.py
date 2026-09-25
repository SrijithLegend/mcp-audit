"""Settings. The app refuses to start if a required secret is missing.

A service that boots with `HEADER_ENC_KEY` unset and discovers it at 3am when a
monitor fires is a service that has already leaked something. Fail at import
(docs/SECURITY.md §4).
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: Environment = "local"
    log_level: str = "INFO"
    api_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"

    database_url: str = "postgresql+asyncpg://mcpaudit:mcpaudit@localhost:5432/mcpaudit"
    redis_url: str = "redis://localhost:6379/0"

    # Clerk (D8). Verified via JWKS -- we never accept an unsigned or `none`-alg token.
    clerk_jwks_url: str = ""
    clerk_issuer: str = ""
    clerk_authorized_parties: list[str] = Field(default_factory=list)

    # There is deliberately **no** LLM key here. Scans run on the user's own key, on their
    # machine or in their CI, and this service only ingests the finished report (D12'). A
    # test greps this package to prove no code path can call a model, which is what makes
    # our inference cost structurally zero rather than merely budgeted.

    # AES-GCM key for remote-target header values, base64, 32 bytes.
    header_enc_key: str = ""

    # Abuse limits (SECURITY.md §6). These bound our storage and bandwidth; there is no
    # inference bill to bound.
    max_report_bytes: int = 4 * 1024 * 1024
    max_inventory_bytes: int = 2 * 1024 * 1024
    max_tools: int = 500
    max_schema_nodes: int = 5000
    max_string_bytes: int = 64 * 1024
    max_schema_depth: int = 32
    max_task_chars: int = 500

    rate_limit_anon_per_min: int = 30
    rate_limit_org_per_min: int = 300
    rate_limit_scans_per_min: int = 10
    rate_limit_tokens_per_hour: int = 10
    rate_limit_shared_per_min: int = 60

    # Billing (D9). Test-mode keys in local/staging.
    billing_provider: Literal["dodo", "polar", "none"] = "none"
    billing_api_key: str = ""
    billing_webhook_secret: str = ""
    billing_checkout_base: str = ""

    resend_api_key: str = ""
    email_from: str = "mcp-audit <noreply@mcpaudit.dev>"
    sentry_dsn: str = ""

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    #: Accepts `Authorization: Bearer dev:<email>`. Local only, enforced below.
    dev_auth_bypass: bool = False

    @field_validator("clerk_authorized_parties", "cors_origins", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @model_validator(mode="after")
    def _required_in_production(self) -> Settings:
        if self.dev_auth_bypass and self.environment != "local":
            raise ValueError("DEV_AUTH_BYPASS is only allowed when ENVIRONMENT=local")
        if self.environment == "local":
            return self
        missing = [
            name
            for name in (
                "clerk_jwks_url",
                "clerk_issuer",
                "header_enc_key",
                "billing_webhook_secret",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(f"missing required settings for {self.environment}: {', '.join(missing)}")
        if not self.clerk_authorized_parties:
            raise ValueError("CLERK_AUTHORIZED_PARTIES must list the web origins allowed to call us")
        return self

    def header_key_bytes(self) -> bytes:
        """32 bytes for AES-GCM. In local dev an all-zero key is fine and obvious."""
        if not self.header_enc_key:
            return b"\x00" * 32
        raw = base64.b64decode(self.header_enc_key)
        if len(raw) != 32:
            raise ValueError("HEADER_ENC_KEY must be 32 bytes, base64 encoded")
        return raw


@lru_cache
def settings() -> Settings:
    return Settings()
