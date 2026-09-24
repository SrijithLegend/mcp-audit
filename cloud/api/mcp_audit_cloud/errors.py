"""RFC 9457 problem+json, with stable `type` codes.

A client that has to string-match error messages breaks on every copy edit. The `type`
slug is the contract; the `detail` sentence is for humans and may change.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

BASE = "https://mcpaudit.dev/problems/"


class Problem(Exception):
    """Raised anywhere, rendered once, never as a traceback."""

    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        **extra: Any,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.extra = extra

    def response(self) -> JSONResponse:
        body: dict[str, Any] = {
            "type": BASE + self.code,
            "title": self.code.replace("_", " "),
            "status": self.status,
            "detail": self.detail,
            **self.extra,
        }
        headers = {}
        if self.status == 429 and "retry_after" in self.extra:
            headers["Retry-After"] = str(self.extra["retry_after"])
        return JSONResponse(
            body, status_code=self.status, media_type="application/problem+json", headers=headers
        )


async def problem_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, Problem)
    return exc.response()


async def capture_handler(_request: Request, exc: Exception) -> JSONResponse:
    """A target we refuse to fetch, or one that would not answer. The message is ours
    and safe to return; the status is 422 because the input is what was wrong."""
    return Problem(422, "unreachable_target", str(exc)).response()


async def unhandled_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Never leak an internal error to a caller. Sentry gets the detail; the caller
    gets a sentence and a request id from the middleware."""
    return Problem(500, "internal_error", "Something went wrong on our side.").response()


# Common ones, so the codes stay spelled the same everywhere.
def not_found(what: str = "resource") -> Problem:
    # 404 rather than 403 on cross-org access: existence itself is information.
    return Problem(404, "not_found", f"No such {what}.")


def quota_exceeded(used: int, limit: int, upgrade_url: str) -> Problem:
    return Problem(
        402,
        "quota_exceeded",
        f"This organisation has used {used} of {limit} scans this period.",
        used=used,
        limit=limit,
        upgrade_url=upgrade_url,
    )


def rate_limited(retry_after: int) -> Problem:
    return Problem(429, "rate_limited", "Too many requests. Try again shortly.", retry_after=retry_after)


def payload_too_large(limit: int) -> Problem:
    return Problem(413, "payload_too_large", f"That is larger than the {limit} byte limit.")
