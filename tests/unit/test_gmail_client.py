# pyright: basic

from __future__ import annotations

import base64
from unittest.mock import patch

from gdocs.gmail_client import GmailClient


def _client(tmp_path):
    with patch("gdocs.gmail_client.get_credentials", return_value=object()), patch(
        "gdocs.gmail_client.build"
    ) as build:
        client = GmailClient(tmp_path)
    return client, build, client.gmail.users.return_value


def test_builds_gmail_service(tmp_path):
    _, build, _ = _client(tmp_path)

    build.assert_called_once_with("gmail", "v1", credentials=build.call_args.kwargs["credentials"])


def test_search_messages_passes_query_and_labels(tmp_path):
    client, _, users = _client(tmp_path)
    users.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "msg-1", "threadId": "thr-1"}]
    }

    result = client.search_messages(query="from:a@example.com", label_ids=["INBOX"], max_results=5)

    users.messages.return_value.list.assert_called_once_with(
        userId="me",
        maxResults=5,
        includeSpamTrash=False,
        q="from:a@example.com",
        labelIds=["INBOX"],
    )
    assert result == [{"gmail_id": "msg-1", "thread_id": "thr-1"}]


def test_get_message_raw_decodes_base64url(tmp_path):
    client, _, users = _client(tmp_path)
    raw = b"Subject: Hello\n\nBody"
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    users.messages.return_value.get.return_value.execute.return_value = {
        "id": "msg-1",
        "threadId": "thr-1",
        "labelIds": ["INBOX"],
        "raw": encoded,
        "payload": {"headers": [{"name": "Subject", "value": "Hello"}]},
    }

    raw_bytes, metadata = client.get_message_raw("msg-1")

    assert raw_bytes == raw
    assert metadata["subject"] == "Hello"
    assert metadata["gmail_id"] == "msg-1"


def test_get_message_raw_parses_headers_when_raw_payload_has_no_headers(tmp_path):
    client, _, users = _client(tmp_path)
    raw = (
        b"Subject: Raw Subject\n"
        b"From: sender@example.com\n"
        b"To: recipient@example.com\n"
        b"Date: Tue, 12 May 2026 19:00:00 +0000\n"
        b"Message-ID: <m1@example.com>\n\n"
        b"Body"
    )
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    users.messages.return_value.get.return_value.execute.return_value = {
        "id": "msg-1",
        "threadId": "thr-1",
        "labelIds": ["INBOX"],
        "internalDate": "1778612400000",
        "raw": encoded,
    }

    raw_bytes, metadata = client.get_message_raw("msg-1")

    assert raw_bytes == raw
    assert metadata["subject"] == "Raw Subject"
    assert metadata["from_addr"] == "sender@example.com"
    assert metadata["message_id"] == "<m1@example.com>"
    assert metadata["internal_date"] == "1778612400000"


def test_send_message_dry_run_does_not_call_api(tmp_path):
    client, _, users = _client(tmp_path)

    result = client.send_message(
        to=["recipient@example.com"],
        subject="Hello",
        body_text="Body",
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["sent"] is False
    users.messages.return_value.send.assert_not_called()


def test_send_message_calls_gmail_api(tmp_path):
    client, _, users = _client(tmp_path)
    users.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent-1",
        "threadId": "thr-1",
    }

    result = client.send_message(
        to=["recipient@example.com"],
        cc=["copy@example.com"],
        subject="Hello",
        body_text="Body",
    )

    assert result["sent"] is True
    assert result["gmail_id"] == "sent-1"
    body = users.messages.return_value.send.call_args.kwargs["body"]
    decoded = base64.urlsafe_b64decode(body["raw"].encode("ascii"))
    assert b"To: recipient@example.com" in decoded
    assert b"Cc: copy@example.com" in decoded
    assert b"Subject: Hello" in decoded


def test_create_draft_allows_no_recipient(tmp_path):
    client, _, users = _client(tmp_path)
    users.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft-1",
        "message": {"id": "msg-1", "threadId": "thr-1"},
    }

    result = client.create_draft(subject="Hello", body_text="Body")

    assert result["draft_id"] == "draft-1"
    assert result["sent"] is False
    body = users.drafts.return_value.create.call_args.kwargs["body"]
    decoded = base64.urlsafe_b64decode(body["message"]["raw"].encode("ascii"))
    assert b"Subject: Hello" in decoded
    assert b"To:" not in decoded


def test_create_draft_sets_recipients(tmp_path):
    client, _, users = _client(tmp_path)
    users.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft-1",
        "message": {"id": "msg-1", "threadId": "thr-1"},
    }

    result = client.create_draft(
        to=["recipient@example.com"],
        cc=["copy@example.com"],
        subject="Hello",
        body_text="Body",
    )

    assert result["to"] == ["recipient@example.com"]
    body = users.drafts.return_value.create.call_args.kwargs["body"]
    decoded = base64.urlsafe_b64decode(body["message"]["raw"].encode("ascii"))
    assert b"To: recipient@example.com" in decoded
    assert b"Cc: copy@example.com" in decoded


def test_reply_message_sets_threading_headers(tmp_path):
    client, _, users = _client(tmp_path)
    users.messages.return_value.get.return_value.execute.return_value = {
        "id": "msg-1",
        "threadId": "thr-1",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Hello"},
                {"name": "From", "value": "sender@example.com"},
                {"name": "Message-ID", "value": "<m1@example.com>"},
            ]
        },
    }
    users.messages.return_value.send.return_value.execute.return_value = {
        "id": "reply-1",
        "threadId": "thr-1",
    }

    result = client.reply_message(gmail_id="msg-1", body_text="Reply")

    assert result["sent"] is True
    body = users.messages.return_value.send.call_args.kwargs["body"]
    assert body["threadId"] == "thr-1"
    decoded = base64.urlsafe_b64decode(body["raw"].encode("ascii"))
    assert b"To: sender@example.com" in decoded
    assert b"Subject: Re: Hello" in decoded
    assert b"In-Reply-To: <m1@example.com>" in decoded


def test_archive_and_mark_read_modify_labels(tmp_path):
    client, _, users = _client(tmp_path)
    users.messages.return_value.modify.return_value.execute.return_value = {
        "id": "msg-1",
        "threadId": "thr-1",
        "labelIds": [],
    }

    client.archive_message("msg-1")
    assert users.messages.return_value.modify.call_args.kwargs["body"] == {
        "addLabelIds": [],
        "removeLabelIds": ["INBOX"],
    }

    client.mark_read("msg-1")
    assert users.messages.return_value.modify.call_args.kwargs["body"] == {
        "addLabelIds": [],
        "removeLabelIds": ["UNREAD"],
    }


def test_resolve_label_id_uses_label_list(tmp_path):
    client, _, users = _client(tmp_path)
    users.labels.return_value.list.return_value.execute.return_value = {
        "labels": [{"id": "Label_123", "name": "Project"}]
    }

    assert client.resolve_label_id("Project") == "Label_123"


def test_create_draft_with_attachments(tmp_path):
    client, _, users = _client(tmp_path)
    users.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft-1",
        "message": {"id": "msg-1", "threadId": "thr-1"},
    }
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake pdf")

    result = client.create_draft(
        to=["recipient@example.com"],
        subject="Hello",
        body_text="Body",
        attachments=[pdf_path],
    )

    assert result["draft_id"] == "draft-1"
    assert result["attachment_count"] == 1
    assert result["attachments"] == [{"name": "invoice.pdf", "size": pdf_path.stat().st_size}]
    body = users.drafts.return_value.create.call_args.kwargs["body"]
    decoded = base64.urlsafe_b64decode(body["message"]["raw"].encode("ascii"))
    assert b"invoice.pdf" in decoded
    assert b"application/pdf" in decoded or b"%PDF" in decoded


def test_send_message_with_attachments(tmp_path):
    client, _, users = _client(tmp_path)
    users.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent-1",
        "threadId": "thr-1",
    }
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake pdf")

    result = client.send_message(
        to=["recipient@example.com"],
        subject="Report",
        body_text="Here is the report",
        attachments=[pdf_path],
    )

    assert result["sent"] is True
    body = users.messages.return_value.send.call_args.kwargs["body"]
    decoded = base64.urlsafe_b64decode(body["raw"].encode("ascii"))
    assert b"report.pdf" in decoded
