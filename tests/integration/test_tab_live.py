# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from gdocs.client import GoogleDocsClient

pytestmark = pytest.mark.skipif(
    os.getenv("GDOCS_ENABLE_LIVE_TAB_TESTS") != "1",
    reason="Tab delete live integration tests are disabled by default",
)

SECRETS_DIR = Path(__file__).resolve().parents[2] / "secrets"

CREATED_DOC_IDS: list[str] = []


@pytest.fixture(scope="module")
def client() -> Iterator[GoogleDocsClient]:
    if not (SECRETS_DIR / "credentials.json").exists():
        pytest.skip("secrets/credentials.json is not configured")
    gdocs_client = GoogleDocsClient(secrets_dir=SECRETS_DIR)
    yield gdocs_client
    for doc_id in list(CREATED_DOC_IDS):
        try:
            gdocs_client.delete_document(doc_id)
        except Exception:
            pass
        finally:
            CREATED_DOC_IDS.remove(doc_id)


@pytest.mark.live_integration
def test_tab_delete_end_to_end(client: GoogleDocsClient) -> None:
    title = f"tab-delete-live-test-{int(time.time())}"
    doc = client.create_document(title=title)
    doc_id: str = doc["id"]
    CREATED_DOC_IDS.append(doc_id)

    new_tab_title = "Temporary Tab"
    tab_result = client.add_tab(doc_id, new_tab_title)
    tab_id: str = tab_result["tab_id"]
    assert tab_result["title"] == new_tab_title

    tabs_before = client.list_tabs(doc_id)
    assert any(t["tab_id"] == tab_id for t in tabs_before)

    delete_result = client.delete_tab(doc_id, tab_id)
    assert delete_result["success"] is True
    assert delete_result["tab_id"] == tab_id
    assert delete_result["doc_id"] == doc_id

    tabs_after = client.list_tabs(doc_id)
    assert not any(t["tab_id"] == tab_id for t in tabs_after)

    client.delete_document(doc_id)
    CREATED_DOC_IDS.remove(doc_id)
