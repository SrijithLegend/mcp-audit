"""The app factory: middleware, error handlers, routes, lifespan.

Order matters. Body size is refused before anything parses it, the request id exists
before anything logs, and every unhandled exception becomes problem+json rather than a
stack trace on the wire.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from mcp_audit.audit import engine_version
from mcp_audit.errors import CaptureError

from . import queue, ratelimit
from .config import settings
from .db import dispose
from .errors import Problem, capture_handler, problem_handler, unhandled_handler
from .logging import configure_logging
from .routers import billing, me, scans, shared, targets

log = structlog.get_logger()

#: Anything above this is refused before we read it (docs/SECURITY.md §6).
MAX_BODY = 4 * 1024 * 1024


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    cfg = settings()
    if cfg.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=cfg.sentry_dsn,
            environment=cfg.environment,
            # Reports and inventories are customer data; never ship them to Sentry.
            send_default_pii=False,
            before_send=_scrub,
        )
    log.info("api.start", environment=cfg.environment, engine=engine_version())
    yield
    await queue.close()
    await ratelimit.close()
    await dispose()


def _scrub(event: Any, _hint: dict[str, Any]) -> Any:
    """Strip anything that could carry a token or a customer's tool inventory."""
    request = event.get("request") or {}
    request.pop("data", None)
    headers = request.get("headers") or {}
    for name in list(headers):
        if name.lower() in ("authorization", "cookie", "webhook-signature", "x-api-key"):
            headers[name] = "[redacted]"
    return event


def create_app() -> FastAPI:
    cfg = settings()
    app = FastAPI(
        title="mcp-audit Cloud",
        version="1",
        description="Hosted differential exploit confirmation for MCP servers.",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        # Bearer tokens, not cookies: no credentialed CORS, so no CSRF surface.
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["authorization", "content-type", "idempotency-key", "x-org-id"],
        max_age=600,
    )

    @app.middleware("http")
    async def context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        started = time.perf_counter()

        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY:
            return Problem(413, "payload_too_large", f"Bodies are limited to {MAX_BODY} bytes.").response()

        try:
            response = await call_next(request)
        except Problem as exc:
            response = exc.response()
        except CaptureError as exc:
            response = Problem(422, "unreachable_target", str(exc)).response()
        finally:
            structlog.contextvars.unbind_contextvars("request_id", "path")

        response.headers["x-request-id"] = request_id
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
        if cfg.environment != "local":
            response.headers["strict-transport-security"] = "max-age=31536000; includeSubDomains; preload"
        log.info(
            "request",
            method=request.method,
            status=response.status_code,
            ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return response

    @app.middleware("http")
    async def throttle(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Per-IP before auth, per-org after. The per-org one lives in the routes that
        matter; this is the blanket that stops an unauthenticated flood."""
        if request.url.path.startswith(("/healthz", "/readyz")):
            return await call_next(request)
        if not request.headers.get("authorization"):
            try:
                await ratelimit.anon(_ip(request))
            except Problem as exc:
                return exc.response()
        return await call_next(request)

    app.add_exception_handler(Problem, problem_handler)
    # A refused URL or an unreadable server is the caller's problem and their message
    # is ours (we wrote it), so it goes out as 422 rather than a bare 500.
    app.add_exception_handler(CaptureError, capture_handler)
    app.add_exception_handler(Exception, unhandled_handler)

    app.include_router(me.router)
    app.include_router(scans.router)
    app.include_router(targets.router)
    app.include_router(shared.router)
    app.include_router(billing.router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "engine": engine_version()}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> dict[str, str]:
        """Ready means the dependencies are reachable, not that the process started."""
        from sqlalchemy import text

        from .db import sessionmaker

        async with sessionmaker()() as db:
            await db.execute(text("SELECT 1"))
        await ratelimit.redis().ping()
        return {"status": "ready"}

    return app


def _ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


app = create_app()
