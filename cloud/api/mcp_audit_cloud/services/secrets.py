"""Remote-target header values: encrypted, write-only, never returned (§4).

A customer's `Authorization: Bearer ...` for their own MCP server is the most sensitive
thing we hold. Rules:

- One-off scans keep it in Redis, AES-GCM encrypted, TTL one hour. Nothing durable.
- Monitors need it for months, so it goes in `target_secrets` -- a separate table, with
  the key held outside the database entirely.
- The API never returns a value after creation. `targets` stores header *names* only.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import TargetSecret

ONE_OFF_TTL = 3600


def _cipher() -> AESGCM:
    return AESGCM(settings().header_key_bytes())


def encrypt(value: str, aad: str) -> tuple[bytes, bytes]:
    """(nonce, ciphertext). `aad` binds the ciphertext to where it is stored, so a row
    copied to another target does not decrypt."""
    nonce = os.urandom(12)
    return nonce, _cipher().encrypt(nonce, value.encode(), aad.encode())


def decrypt(nonce: bytes, ciphertext: bytes, aad: str) -> str:
    return _cipher().decrypt(nonce, ciphertext, aad.encode()).decode()


async def store_for_target(
    db: AsyncSession, org_id: UUID, target_id: UUID, headers: dict[str, str]
) -> list[str]:
    """Replace this target's stored headers. Returns the names, which are all the API
    will ever show again."""
    await db.execute(delete(TargetSecret).where(TargetSecret.target_id == target_id))
    for name, value in headers.items():
        nonce, ciphertext = encrypt(value, aad=f"{org_id}:{target_id}:{name.lower()}")
        db.add(
            TargetSecret(
                org_id=org_id,
                target_id=target_id,
                header_name=name,
                nonce=nonce,
                ciphertext=ciphertext,
            )
        )
    await db.flush()
    return sorted(headers)


async def load_for_target(db: AsyncSession, org_id: UUID, target_id: UUID) -> dict[str, str]:
    rows = (
        await db.execute(
            select(TargetSecret).where(TargetSecret.target_id == target_id, TargetSecret.org_id == org_id)
        )
    ).scalars()
    return {
        row.header_name: decrypt(
            row.nonce, row.ciphertext, aad=f"{org_id}:{target_id}:{row.header_name.lower()}"
        )
        for row in rows
    }


async def stash_one_off(redis_client: Any, scan_id: UUID, headers: dict[str, str]) -> None:
    """Headers for a single scan. Encrypted in Redis, gone within the hour either way."""
    if not headers:
        return
    nonce, ciphertext = encrypt(json.dumps(headers), aad=f"scan:{scan_id}")
    payload = base64.b64encode(nonce + ciphertext).decode()
    await redis_client.set(f"scanhdr:{scan_id}", payload, ex=ONE_OFF_TTL)


async def take_one_off(redis_client: Any, scan_id: UUID) -> dict[str, str]:
    """Read once and delete: the worker needs them exactly once."""
    key = f"scanhdr:{scan_id}"
    payload = await redis_client.get(key)
    if not payload:
        return {}
    await redis_client.delete(key)
    raw = base64.b64decode(payload)
    value = decrypt(raw[:12], raw[12:], aad=f"scan:{scan_id}")
    parsed: dict[str, str] = json.loads(value)
    return parsed
