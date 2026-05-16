"""Refresh-token persistence via the OS keyring.

We never write tokens to plaintext files on disk. On Windows this lands in the
Credential Manager; on macOS Keychain; on Linux Secret Service / kwallet.
"""

from __future__ import annotations

import json
import logging

import keyring

log = logging.getLogger(__name__)

SERVICE_NAME = "dashboard-cal"
ACCOUNT_NAME = "google-oauth"


def save_credentials(payload: dict) -> None:
    """Persist the credentials JSON blob (refresh_token, client_id, etc.)."""
    # We log only that a save happened, never the payload itself (logging rule:
    # tokens are sensitive data and must never be logged in clear text).
    keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, json.dumps(payload))
    log.info("auth: credentials persisted to OS keyring")


def load_credentials() -> dict | None:
    blob = keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
    if not blob:
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # Don't echo the corrupt blob anywhere - it may contain partial token bytes.
        log.warning("auth: stored credentials blob unreadable; will re-auth")
        return None


def clear_credentials() -> None:
    try:
        keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
        log.info("auth: credentials cleared from keyring")
    except keyring.errors.PasswordDeleteError:
        pass
