# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from gdocs.gmail_client import GmailClient


pytestmark = pytest.mark.skipif(
    os.getenv("GDOCS_ENABLE_GMAIL_LIVE_TESTS") != "1",
    reason="Gmail live integration tests are disabled",
)


SECRETS_DIR = Path(__file__).resolve().parents[2] / "secrets"


@pytest.fixture(scope="module")
def gmail() -> GmailClient:
    if not (SECRETS_DIR / "credentials.json").exists():
        pytest.skip("secrets/credentials.json is not configured")
    return GmailClient(secrets_dir=SECRETS_DIR)


@pytest.mark.live_integration
def test_gmail_profile(gmail: GmailClient) -> None:
    profile = gmail.get_profile()

    assert profile["emailAddress"]


@pytest.mark.live_integration
def test_gmail_search_inbox(gmail: GmailClient) -> None:
    messages = gmail.search_messages(query="newer_than:30d", label_ids=["INBOX"], max_results=5)

    assert isinstance(messages, list)


@pytest.mark.live_integration
def test_gmail_send_download_reply_and_archive_self(gmail: GmailClient, tmp_path: Path) -> None:
    if os.getenv("GDOCS_GMAIL_LIVE_ALLOW_SEND") != "1":
        pytest.skip("set GDOCS_GMAIL_LIVE_ALLOW_SEND=1 to send live Gmail test messages")
    if os.getenv("GDOCS_GMAIL_LIVE_ALLOW_MUTATE") != "1":
        pytest.skip("set GDOCS_GMAIL_LIVE_ALLOW_MUTATE=1 to archive live Gmail test messages")

    profile = gmail.get_profile()
    recipient = os.getenv("GDOCS_GMAIL_LIVE_TEST_TO") or str(profile["emailAddress"])
    subject = f"GDocs Gmail live test {int(time.time())}"
    sent = gmail.send_message(
        to=[recipient],
        subject=subject,
        body_text="This message was created by a gated live integration test.",
    )
    assert sent["sent"] is True

    found: list[dict[str, str]] = []
    for _ in range(12):
        found = gmail.search_messages(query=f'subject:"{subject}"', max_results=10)
        if found:
            break
        time.sleep(5)
    assert found

    raw_bytes, metadata = gmail.get_message_raw(found[0]["gmail_id"])
    assert subject.encode() in raw_bytes
    assert metadata["thread_id"]
    eml_path = tmp_path / "downloaded.eml"
    eml_path.write_bytes(raw_bytes)
    assert eml_path.read_bytes() == raw_bytes

    reply = gmail.reply_message(
        gmail_id=found[0]["gmail_id"],
        body_text="Reply created by a gated live integration test.",
    )
    assert reply["sent"] is True
    assert reply["thread_id"] == metadata["thread_id"]

    archive = gmail.archive_message(found[0]["gmail_id"])
    assert archive["dry_run"] is False
