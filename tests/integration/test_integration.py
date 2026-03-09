# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnusedCallResult=false

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest

from src.client import GoogleDocsClient

SECRETS_DIR = Path(__file__).resolve().parents[2] / "secrets"
if not (SECRETS_DIR / "credentials.json").exists():
    pytest.skip("No credentials", allow_module_level=True)


pytestmark = pytest.mark.integration

CREATED_DOC_IDS: list[str] = []
TEST_STATE: dict[str, str] = {}


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _cleanup_documents(client: GoogleDocsClient) -> None:
    for doc_id in list(CREATED_DOC_IDS):
        try:
            client.drive.files().delete(fileId=doc_id).execute()  # pyright: ignore[reportAny]
        except Exception:
            pass
        finally:
            CREATED_DOC_IDS.remove(doc_id)


@pytest.fixture(scope="module")
def client() -> Iterator[GoogleDocsClient]:
    gdocs_client = GoogleDocsClient(secrets_dir=SECRETS_DIR)
    yield gdocs_client
    _cleanup_documents(gdocs_client)


@pytest.mark.integration
def test_create_document_simple(client: GoogleDocsClient) -> None:
    """Create a simple document and verify id/link fields are returned."""
    title = f"Integration Test - {_timestamp()}"
    result = client.create_document(title=title)

    assert isinstance(result, dict)
    assert result.get("id")
    assert result.get("link")
    assert isinstance(result["id"], str)
    assert isinstance(result["link"], str)

    CREATED_DOC_IDS.append(result["id"])
    TEST_STATE["first_doc_id"] = result["id"]


@pytest.mark.integration
def test_create_document_with_tabs(client: GoogleDocsClient) -> None:
    """Create a document with two tabs and verify id/link fields are returned."""
    title = f"Integration Test Tabs - {_timestamp()}"
    tabs = [
        {"title": "Overview", "content": "Overview content from integration test."},
        {"title": "Details", "content": "Details content from integration test."},
    ]

    result = client.create_document(title=title, tabs=tabs)

    assert isinstance(result, dict)
    assert result.get("id")
    assert result.get("link")
    assert isinstance(result["id"], str)
    assert isinstance(result["link"], str)

    CREATED_DOC_IDS.append(result["id"])
    TEST_STATE["tabs_doc_id"] = result["id"]


@pytest.mark.integration
def test_modify_document(client: GoogleDocsClient) -> None:
    """Insert text into the first created document and verify success response."""
    doc_id = TEST_STATE["first_doc_id"]
    text = f"Inserted by integration test at {_timestamp()}\n"

    result = client.modify_document(doc_id=doc_id, text=text)

    assert isinstance(result, dict)
    assert result.get("success") is True


@pytest.mark.integration
def test_update_title(client: GoogleDocsClient) -> None:
    """Rename the first created document and verify success response."""
    doc_id = TEST_STATE["first_doc_id"]
    renamed_title = f"Integration Test - Renamed - {_timestamp()}"

    result = client.update_title(doc_id=doc_id, new_title=renamed_title)

    assert isinstance(result, dict)
    assert result.get("success") is True
    TEST_STATE["renamed_title"] = renamed_title


@pytest.mark.integration
def test_search_documents(client: GoogleDocsClient) -> None:
    """Search for the renamed document title substring and verify it appears."""
    query = TEST_STATE["renamed_title"].split("-")[-1].strip()
    target_id = TEST_STATE["first_doc_id"]
    expected_title = TEST_STATE["renamed_title"]

    results: list[dict[str, str]] = []
    for _ in range(6):
        results = client.search_documents(query=query, max_results=20)
        found = any(item.get("id") == target_id for item in results)
        if found:
            break
        time.sleep(2)

    assert results
    assert any(item.get("id") == target_id for item in results)
    assert any(expected_title in item.get("name", "") for item in results)


@pytest.mark.integration
def test_share_document(client: GoogleDocsClient) -> None:
    """Share the first created document with test email and verify success response."""
    email = os.getenv("GDOCS_TEST_EMAIL")
    if not email:
        pytest.skip("GDOCS_TEST_EMAIL is not set")

    doc_id = TEST_STATE["first_doc_id"]
    result = client.share_document(doc_id=doc_id, email=email)

    assert isinstance(result, dict)
    assert result.get("success") is True


@pytest.mark.integration
def test_get_share_link_private(client: GoogleDocsClient) -> None:
    """Get private share link for the first document and validate URL format."""
    doc_id = TEST_STATE["first_doc_id"]

    link = client.get_share_link(doc_id=doc_id, public=False)

    assert isinstance(link, str)
    assert _is_valid_url(link)


@pytest.mark.integration
def test_get_share_link_public(client: GoogleDocsClient) -> None:
    """Get public share link for the first document and validate URL format."""
    doc_id = TEST_STATE["first_doc_id"]

    link = client.get_share_link(doc_id=doc_id, public=True)

    assert isinstance(link, str)
    assert _is_valid_url(link)


@pytest.mark.integration
def test_cleanup(client: GoogleDocsClient) -> None:
    """Delete all created documents through Drive API to avoid residue."""
    _cleanup_documents(client)
    assert CREATED_DOC_IDS == []
