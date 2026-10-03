from __future__ import annotations

"""Authentication module for Google Docs Skill."""

import json
import os
from contextlib import redirect_stdout
import sys
from pathlib import Path
from typing import cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
]


def _write_private_token(token_path: Path, token_json: str) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.parent.chmod(0o700)
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as token_file:
        _ = token_file.write(token_json)
    token_path.chmod(0o600)


def _token_has_required_scopes(token_path: Path, scopes: list[str] | None = None) -> bool:
    try:
        raw = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    stored = raw.get("scopes")
    if isinstance(stored, str):
        token_scopes = set(stored.split())
    elif isinstance(stored, list):
        token_scopes = {str(item) for item in stored}
    else:
        return False
    return set(scopes or SCOPES).issubset(token_scopes)


def get_credentials(
    secrets_dir: Path, *, extra_scopes: list[str] | None = None, auth_timeout: int | None = None,
) -> Credentials:
    """Get valid Google OAuth credentials.

    Args:
        secrets_dir: Directory containing ``credentials.json`` and ``token.json``.

    Returns:
        Valid OAuth credentials.

    Raises:
        FileNotFoundError: If ``credentials.json`` does not exist.
        RuntimeError: If token refresh or OAuth flow fails.
    """
    token_path = secrets_dir / "token.json"
    credentials_path = secrets_dir / "credentials.json"
    required_scopes = list(dict.fromkeys(SCOPES + (extra_scopes or [])))

    if secrets_dir.exists():
        secrets_dir.chmod(0o700)
    if token_path.exists():
        token_path.chmod(0o600)

    if not credentials_path.exists():
        raise FileNotFoundError(f"Missing OAuth credentials file: {credentials_path}")

    creds: Credentials | None = None
    if token_path.exists() and _token_has_required_scopes(token_path, required_scopes):
        # Keep optional grants when refreshing from an ordinary Gmail/Docs command.
        stored = json.loads(token_path.read_text(encoding="utf-8"))["scopes"]
        stored_scopes = stored.split() if isinstance(stored, str) else stored
        granted_scopes = list(dict.fromkeys(required_scopes + stored_scopes))
        creds = Credentials.from_authorized_user_file(str(token_path), granted_scopes)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _write_private_token(token_path, creds.to_json())
            return creds
        except Exception:
            creds = None

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), required_scopes)
        kwargs = {"port": 0}
        if auth_timeout is not None:
            kwargs["timeout_seconds"] = auth_timeout
        with redirect_stdout(sys.stderr):
            fresh_creds = cast(Credentials, flow.run_local_server(**kwargs))
        if not fresh_creds.has_scopes(required_scopes):
            raise RuntimeError("Google did not grant all requested scopes")
        _write_private_token(token_path, fresh_creds.to_json())
        return fresh_creds
    except Exception as exc:
        raise RuntimeError("Google OAuth flow failed") from exc
