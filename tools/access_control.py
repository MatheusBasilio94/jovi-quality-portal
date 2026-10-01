"""Portal accounts and server-side write permissions."""

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Mapping

from tools.auth_session import verify_token


@dataclass(frozen=True)
class Account:
    username: str
    password_hash: str
    role: str


def _credential_setting(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None:
        try:
            import streamlit as st

            value = st.secrets.get(name)
        except Exception:
            pass
    return str(value if value is not None else default).strip()


def configured_accounts() -> tuple[Account, Account]:
    admin = Account(
        _credential_setting("JOVI_ADMIN_USERNAME", "Matheus"),
        _credential_setting(
            "JOVI_ADMIN_PASSWORD_SHA256",
            "fff270f88cbf18be77a4e78871e0a4c6930927355159f3c84b967fd634da40b9",
        ).lower(),
        "admin",
    )
    viewer = Account(
        _credential_setting("JOVI_STANDARD_USERNAME", "jovi"),
        _credential_setting(
            "JOVI_STANDARD_PASSWORD_SHA256",
            "e8b9691c6aeb52ca6182e60467d9b8df33a22b58ebf2c3a73144a6f6e58da68e",
        ).lower(),
        "viewer",
    )
    if not admin.username or not viewer.username or admin.username.casefold() == viewer.username.casefold():
        raise ValueError("The administrator and viewer must have distinct, nonempty usernames.")
    if any(len(account.password_hash) != 64 for account in (admin, viewer)):
        raise ValueError("Portal password hashes must be SHA-256 hex digests.")
    return admin, viewer


def authenticate(username: str, password: str, accounts: tuple[Account, ...]) -> Account | None:
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    candidate = username.strip().casefold()
    for account in accounts:
        if hmac.compare_digest(candidate, account.username.casefold()) and hmac.compare_digest(digest, account.password_hash):
            return account
    return None


def account_from_token(token: str | None, accounts: tuple[Account, ...]) -> Account | None:
    for account in accounts:
        if verify_token(token, account.username, account.password_hash):
            return account
    return None


def is_admin_session(session: Mapping[str, object]) -> bool:
    return session.get("authenticated") is True and session.get("auth_role") == "admin"


def require_admin_access(session: Mapping[str, object]) -> None:
    if not is_admin_session(session):
        raise PermissionError("Administrator access is required to add, edit, or delete portal data.")
