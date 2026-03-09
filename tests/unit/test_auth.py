# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnusedCallResult=false

from __future__ import annotations

import json

import pytest
from unittest.mock import MagicMock, PropertyMock, patch

from src.auth import SCOPES, get_credentials


def test_get_credentials_from_existing_token(tmp_path):
    secrets_dir = tmp_path
    (secrets_dir / "credentials.json").write_text("{}", encoding="utf-8")
    (secrets_dir / "token.json").write_text("{}", encoding="utf-8")

    creds = MagicMock(valid=True)
    with patch("src.auth.Credentials.from_authorized_user_file", return_value=creds) as from_token:
        with patch("src.auth.InstalledAppFlow.from_client_secrets_file") as flow_factory:
            result = get_credentials(secrets_dir)

    assert result is creds
    from_token.assert_called_once_with(str(secrets_dir / "token.json"), SCOPES)
    flow_factory.assert_not_called()


def test_get_credentials_refresh_expired(tmp_path):
    secrets_dir = tmp_path
    (secrets_dir / "credentials.json").write_text("{}", encoding="utf-8")
    (secrets_dir / "token.json").write_text("{}", encoding="utf-8")

    creds = MagicMock(valid=False, expired=True, refresh_token="refresh-token")
    creds.to_json.return_value = '{"token": "refreshed"}'  # pyright: ignore[reportAny]
    request_obj = object()

    with patch("src.auth.Credentials.from_authorized_user_file", return_value=creds):
        with patch("src.auth.Request", return_value=request_obj) as request_cls:
            with patch("src.auth.InstalledAppFlow.from_client_secrets_file") as flow_factory:
                result = get_credentials(secrets_dir)

    assert result is creds
    request_cls.assert_called_once_with()
    creds.refresh.assert_called_once_with(request_obj)  # pyright: ignore[reportAny]
    flow_factory.assert_not_called()


def test_get_credentials_fresh_oauth_flow(tmp_path):
    secrets_dir = tmp_path
    (secrets_dir / "credentials.json").write_text("{}", encoding="utf-8")

    oauth_creds = MagicMock(valid=True)
    oauth_creds.to_json.return_value = '{"token": "abc"}'  # pyright: ignore[reportAny]

    flow = MagicMock()
    flow.run_local_server.return_value = oauth_creds  # pyright: ignore[reportAny]

    with patch("src.auth.Credentials.from_authorized_user_file") as from_token:
        with patch("src.auth.InstalledAppFlow.from_client_secrets_file", return_value=flow) as flow_factory:
            result = get_credentials(secrets_dir)

    assert result is oauth_creds
    from_token.assert_not_called()
    flow_factory.assert_called_once_with(str(secrets_dir / "credentials.json"), SCOPES)
    flow.run_local_server.assert_called_once()  # pyright: ignore[reportAny]

    saved = (secrets_dir / "token.json").read_text(encoding="utf-8")
    assert json.loads(saved) == {"token": "abc"}


def test_get_credentials_missing_credentials_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_credentials(tmp_path)


def test_get_credentials_saves_token(tmp_path):
    secrets_dir = tmp_path
    (secrets_dir / "credentials.json").write_text("{}", encoding="utf-8")

    oauth_creds = MagicMock(valid=True)
    oauth_creds.to_json.return_value = '{"token": "saved-token", "refresh_token": "r1"}'  # pyright: ignore[reportAny]

    flow = MagicMock()
    flow.run_local_server.return_value = oauth_creds  # pyright: ignore[reportAny]

    with patch("src.auth.Credentials.from_authorized_user_file", return_value=None):
        with patch("src.auth.InstalledAppFlow.from_client_secrets_file", return_value=flow):
            get_credentials(secrets_dir)

    token_file = secrets_dir / "token.json"
    assert token_file.exists()
    assert json.loads(token_file.read_text(encoding="utf-8")) == {
        "token": "saved-token",
        "refresh_token": "r1",
    }
