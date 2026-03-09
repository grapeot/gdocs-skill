from __future__ import annotations

"""Authentication module for Google Docs Skill."""

from pathlib import Path
from typing import cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


def get_credentials(secrets_dir: Path) -> Credentials:
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

    if not credentials_path.exists():
        raise FileNotFoundError(f"Missing OAuth credentials file: {credentials_path}")

    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _ = token_path.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception:
            creds = None

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        fresh_creds = cast(Credentials, flow.run_local_server(port=0))
        _ = token_path.write_text(fresh_creds.to_json(), encoding="utf-8")
        return fresh_creds
    except Exception as exc:
        raise RuntimeError("Google OAuth flow failed") from exc
