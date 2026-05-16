"""OAuth flow for Google Calendar (read-only) + Google Tasks.

A single ``credentials.json`` (OAuth Desktop client) gets consent for both
scopes at once on first launch. The refresh token lives in the OS keyring;
the app silently refreshes it on subsequent launches.
"""

from __future__ import annotations

import logging
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from . import tokens

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks",
]


class OAuthError(RuntimeError):
    """Raised when OAuth cannot proceed (missing credentials, user cancels, etc.)."""


class GoogleAuth:
    """Holds the OAuth client config and returns refreshed Credentials objects."""

    def __init__(self, client_secrets_path: Path) -> None:
        self._client_secrets_path = client_secrets_path
        if not client_secrets_path.is_file():
            raise OAuthError(
                "credentials.json not found in project root. "
                "See README.md step 2 for how to create one."
            )

    def get_credentials(self, *, force_reauth: bool = False) -> Credentials:
        """Return a usable, refreshed Credentials object."""
        if not force_reauth:
            stored = tokens.load_credentials()
            if stored:
                creds = Credentials.from_authorized_user_info(stored, SCOPES)
                if creds.valid:
                    return creds
                if creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except RefreshError:
                        # Stored token is no good - fall through to interactive flow.
                        log.info("auth: refresh failed; running interactive consent")
                        tokens.clear_credentials()
                    else:
                        tokens.save_credentials(_creds_to_dict(creds))
                        return creds

        # Interactive consent (browser pops up, user signs in, we get a refresh_token).
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._client_secrets_path), SCOPES
        )
        # port=0 lets the loopback flow pick any free port.
        creds = flow.run_local_server(port=0, open_browser=True)
        tokens.save_credentials(_creds_to_dict(creds))
        return creds


def _creds_to_dict(creds: Credentials) -> dict:
    # Mirror Credentials.from_authorized_user_info() shape.
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }
