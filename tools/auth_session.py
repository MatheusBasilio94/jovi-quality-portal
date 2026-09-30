"""Short-lived, signed browser sessions for the portal's existing password login."""

import hashlib
import hmac
import os
import secrets
import time
from functools import lru_cache


COOKIE_NAME = "jovi_quality_auth_v1"
SESSION_SECONDS = 30 * 24 * 60 * 60
_revoked: dict[str, int] = {}


@lru_cache(maxsize=1)
def _signing_key() -> bytes:
    configured = os.environ.get("JOVI_AUTH_COOKIE_SECRET", "")
    if not configured:
        try:
            import streamlit as st

            configured = str(st.secrets.get("JOVI_AUTH_COOKIE_SECRET", "") or "")
            if not configured:
                # Derive a separate key from the existing server-only cloud secret.
                configured = str(st.secrets.get("SUPABASE_SECRET_KEY", "") or "")
        except Exception:
            pass
    configured = configured or os.environ.get("SUPABASE_SECRET_KEY", "")
    if configured:
        return hmac.new(configured.encode("utf-8"), b"jovi/auth-cookie/v1", hashlib.sha256).digest()
    return secrets.token_bytes(32)


def _signature(body: str, username: str, password_hash: str) -> str:
    message = f"{body}|{username.strip().casefold()}|{password_hash}".encode("utf-8")
    return hmac.new(_signing_key(), message, hashlib.sha256).hexdigest()


def issue_token(username: str, password_hash: str, now: int | None = None) -> str:
    expires = (int(time.time()) if now is None else now) + SESSION_SECONDS
    body = f"v1.{expires}.{secrets.token_hex(16)}"
    return f"{body}.{_signature(body, username, password_hash)}"


def verify_token(token: str | None, username: str, password_hash: str, now: int | None = None) -> bool:
    if not token or len(token) > 200:
        return False
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != "v1" or len(parts[2]) != 32 or len(parts[3]) != 64:
        return False
    try:
        expires = int(parts[1])
        int(parts[2], 16)
        int(parts[3], 16)
    except ValueError:
        return False
    current = int(time.time()) if now is None else now
    if expires <= current or token in _revoked:
        return False
    body = ".".join(parts[:3])
    return hmac.compare_digest(parts[3], _signature(body, username, password_hash))


def revoke_token(token: str | None) -> None:
    if not token:
        return
    try:
        expires = int(token.split(".")[1])
    except (IndexError, ValueError):
        return
    now = int(time.time())
    for revoked, deadline in list(_revoked.items()):
        if deadline <= now:
            del _revoked[revoked]
    if expires > now:
        _revoked[token] = expires
