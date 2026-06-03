# pyright: basic

from __future__ import annotations

import json
from unittest.mock import patch

from gdocs.__main__ import DEFAULT_SECRETS_DIR, main
from gdocs.mail_store import MailStore


def test_create_command_outputs_json(capsys):
    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.create_document.return_value = {"id": "doc-1", "link": "https://docs.google.com/document/d/doc-1/edit"}

        code = main(["create", "--title", "Roadmap"])

    assert code == 0
    client_cls.assert_called_once_with(secrets_dir=DEFAULT_SECRETS_DIR)
    client.create_document.assert_called_once_with(title="Roadmap")
    out = json.loads(capsys.readouterr().out)
    assert out == {"id": "doc-1", "link": "https://docs.google.com/document/d/doc-1/edit"}


def test_create_command_respects_secrets_dir(capsys, tmp_path):
    secrets_dir = tmp_path / "custom-secrets"
    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.create_document.return_value = {"id": "doc-2", "link": "https://docs.google.com/document/d/doc-2/edit"}

        code = main(["--secrets-dir", str(secrets_dir), "create", "--title", "Plan"])

    assert code == 0
    client_cls.assert_called_once_with(secrets_dir=secrets_dir)
    out = json.loads(capsys.readouterr().out)
    assert out["id"] == "doc-2"


def test_publish_without_share(capsys, tmp_path):
    file_path = tmp_path / "doc.md"
    file_path.write_text("# Hello", encoding="utf-8")

    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.create_document.return_value = {"id": "doc-3", "link": "https://docs.google.com/document/d/doc-3/edit"}

        code = main(["publish", str(file_path), "--title", "Hello Doc"])

    assert code == 0
    client.create_document.assert_called_once_with(
        title="Hello Doc",
        tabs=[{"title": "Hello Doc", "content": "# Hello"}],
        content_format="markdown",
    )
    client.share_document.assert_not_called()
    out = json.loads(capsys.readouterr().out)
    assert out == {"id": "doc-3", "link": "https://docs.google.com/document/d/doc-3/edit"}


def test_publish_with_share(capsys, tmp_path):
    file_path = tmp_path / "doc.md"
    file_path.write_text("# Hello", encoding="utf-8")

    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.create_document.return_value = {"id": "doc-4", "link": "https://docs.google.com/document/d/doc-4/edit"}

        code = main([
            "publish",
            str(file_path),
            "--title",
            "Shared Doc",
            "--share",
            "user@example.com",
            "--role",
            "reader",
        ])

    assert code == 0
    client.share_document.assert_called_once_with("doc-4", "user@example.com", role="reader")
    out = json.loads(capsys.readouterr().out)
    assert out["id"] == "doc-4"


def test_search_uses_default_max_results(capsys):
    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.search_documents.return_value = []

        code = main(["search", "roadmap"])

    assert code == 0
    client.search_documents.assert_called_once_with("roadmap", max_results=10)
    out = json.loads(capsys.readouterr().out)
    assert out == []


def test_share_command_defaults_role(capsys):
    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.share_document.return_value = {"success": True, "link": "https://docs.google.com/document/d/doc-5/edit"}

        code = main(["share", "doc-5", "--email", "writer@example.com"])

    assert code == 0
    client.share_document.assert_called_once_with(
        "doc-5", "writer@example.com", role="writer", message=None
    )
    out = json.loads(capsys.readouterr().out)
    assert out["success"] is True


def test_title_command(capsys):
    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.update_title.return_value = {"success": True, "new_title": "Renamed"}

        code = main(["title", "doc-6", "Renamed"])

    assert code == 0
    client.update_title.assert_called_once_with("doc-6", "Renamed")
    out = json.loads(capsys.readouterr().out)
    assert out == {"success": True, "new_title": "Renamed"}


def test_link_command_public(capsys):
    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.get_share_link.return_value = "https://docs.google.com/document/d/doc-7/edit"

        code = main(["link", "doc-7", "--public"])

    assert code == 0
    client.get_share_link.assert_called_once_with("doc-7", public=True)
    out = json.loads(capsys.readouterr().out)
    assert out == {"link": "https://docs.google.com/document/d/doc-7/edit"}


def test_tab_rename_command(capsys):
    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.rename_tab.return_value = {"success": True, "tab_id": "tab-1", "new_title": "Notes"}

        code = main(["tab", "rename", "doc-8", "tab-1", "Notes"])

    assert code == 0
    client.rename_tab.assert_called_once_with("doc-8", "tab-1", "Notes")
    out = json.loads(capsys.readouterr().out)
    assert out["success"] is True


def test_tab_replace_default_markdown(capsys, tmp_path):
    file_path = tmp_path / "tab.md"
    file_path.write_text("## Updated", encoding="utf-8")

    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.replace_tab_content.return_value = {"success": True, "doc_id": "doc-9", "tab_id": "tab-9"}

        code = main(["tab", "replace", "doc-9", "tab-9", str(file_path)])

    assert code == 0
    client.replace_tab_content.assert_called_once_with(
        "doc-9", "tab-9", "## Updated", content_format="markdown"
    )
    out = json.loads(capsys.readouterr().out)
    assert out["doc_id"] == "doc-9"


def test_tab_replace_plain_format(capsys, tmp_path):
    file_path = tmp_path / "tab.txt"
    file_path.write_text("Updated text", encoding="utf-8")

    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.replace_tab_content.return_value = {"success": True, "doc_id": "doc-10", "tab_id": "tab-10"}

        code = main(["tab", "replace", "doc-10", "tab-10", str(file_path), "--format", "plain"])

    assert code == 0
    client.replace_tab_content.assert_called_once_with(
        "doc-10", "tab-10", "Updated text", content_format="plain"
    )
    out = json.loads(capsys.readouterr().out)
    assert out["tab_id"] == "tab-10"


def test_tab_list_command(capsys):
    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.list_tabs.return_value = [{"tab_id": "tab-1", "title": "Overview"}]

        code = main(["tab", "list", "doc-11"])

    assert code == 0
    client.list_tabs.assert_called_once_with("doc-11")
    out = json.loads(capsys.readouterr().out)
    assert out == [{"tab_id": "tab-1", "title": "Overview"}]


def test_tab_add_command_no_file(capsys):
    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.add_tab.return_value = {"doc_id": "doc-12", "tab_id": "tab-12", "title": "New Tab"}

        code = main(["tab", "add", "doc-12", "New Tab"])

    assert code == 0
    client.add_tab.assert_called_once_with(
        "doc-12", "New Tab", content=None, content_format="markdown"
    )
    out = json.loads(capsys.readouterr().out)
    assert out["tab_id"] == "tab-12"


def test_tab_add_command_with_file(capsys, tmp_path):
    file_path = tmp_path / "tab.md"
    file_path.write_text("# From file", encoding="utf-8")

    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.add_tab.return_value = {"doc_id": "doc-13", "tab_id": "tab-13", "title": "From File"}

        code = main(["tab", "add", "doc-13", "From File", str(file_path), "--format", "plain"])

    assert code == 0
    client.add_tab.assert_called_once_with(
        "doc-13", "From File", content="# From file", content_format="plain"
    )
    out = json.loads(capsys.readouterr().out)
    assert out["doc_id"] == "doc-13"


def test_error_outputs_json_to_stderr(capsys):
    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.create_document.side_effect = RuntimeError("create failed")

        code = main(["create", "--title", "Broken"])

    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["error"] == "create failed"
    assert payload["type"] == "RuntimeError"


def test_gmail_send_dry_run_reads_body_file(capsys, tmp_path):
    body_path = tmp_path / "body.txt"
    body_path.write_text("Hello", encoding="utf-8")
    with patch("gdocs.__main__.GmailClient") as gmail_cls, patch("gdocs.__main__.MailStore") as store_cls:
        gmail = gmail_cls.return_value
        gmail.send_message.return_value = {"dry_run": True, "sent": False}

        code = main([
            "--mail-data-dir",
            str(tmp_path / "mail"),
            "gmail",
            "send",
            "--to",
            "recipient@example.com",
            "--subject",
            "Hello",
            "--body-file",
            str(body_path),
            "--dry-run",
        ])

    assert code == 0
    gmail.send_message.assert_called_once_with(
        to=["recipient@example.com"],
        cc=[],
        bcc=[],
        subject="Hello",
        body_text="Hello",
        body_format="text",
        dry_run=True,
        attachments=None,
    )
    store_cls.return_value.close.assert_called_once_with()
    assert json.loads(capsys.readouterr().out) == {"dry_run": True, "sent": False}


def test_gmail_draft_reads_body_file_without_recipient(capsys, tmp_path):
    body_path = tmp_path / "body.txt"
    body_path.write_text("Hello", encoding="utf-8")
    with patch("gdocs.__main__.GmailClient") as gmail_cls, patch("gdocs.__main__.MailStore") as store_cls:
        gmail = gmail_cls.return_value
        gmail.create_draft.return_value = {"draft_id": "draft-1", "sent": False}

        code = main([
            "--mail-data-dir",
            str(tmp_path / "mail"),
            "gmail",
            "draft",
            "--subject",
            "Hello",
            "--body-file",
            str(body_path),
        ])

    assert code == 0
    gmail.create_draft.assert_called_once_with(
        to=[],
        cc=[],
        bcc=[],
        subject="Hello",
        body_text="Hello",
        body_format="text",
        attachments=None,
    )
    store_cls.return_value.close.assert_called_once_with()
    assert json.loads(capsys.readouterr().out) == {"draft_id": "draft-1", "sent": False}


def test_gmail_search_resolves_labels(capsys, tmp_path):
    with patch("gdocs.__main__.GmailClient") as gmail_cls, patch("gdocs.__main__.MailStore"):
        gmail = gmail_cls.return_value
        gmail.resolve_label_id.return_value = "INBOX"
        gmail.search_messages.return_value = [{"gmail_id": "msg-1", "thread_id": "thr-1"}]

        code = main([
            "--mail-data-dir",
            str(tmp_path / "mail"),
            "gmail",
            "search",
            "newer_than:1d",
            "--label",
            "INBOX",
            "--limit",
            "5",
        ])

    assert code == 0
    gmail.search_messages.assert_called_once_with(
        query="newer_than:1d",
        label_ids=["INBOX"],
        max_results=5,
        include_spam_trash=False,
    )
    assert json.loads(capsys.readouterr().out) == [{"gmail_id": "msg-1", "thread_id": "thr-1"}]


def test_gmail_read_lists_matches_when_no_selection(capsys, tmp_path):
    fake_message = type(
        "FakeMessage",
        (),
        {
            "gmail_id": "msg-1",
            "thread_id": "thr-1",
            "subject": "Hello",
            "from_addr": "sender@example.com",
            "to_addr": "recipient@example.com",
            "cc_addr": "",
            "date": "today",
            "labels": ["INBOX"],
            "mime_path": tmp_path / "message.eml",
            "downloaded_at": "now",
        },
    )()
    with patch("gdocs.__main__.GmailClient"), patch("gdocs.__main__.MailStore") as store_cls:
        store = store_cls.return_value
        store.find_messages.return_value = [fake_message]

        code = main([
            "--mail-data-dir",
            str(tmp_path / "mail"),
            "gmail",
            "read",
            "--subject",
            "Hello",
        ])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["match_count"] == 1
    assert payload["matches"][0]["gmail_id"] == "msg-1"


def _cache_thread_for_inspection(mail_dir):
    store = MailStore(mail_dir)
    try:
        store.save_message(
            account="me@example.com",
            gmail_id="msg-1",
            thread_id="thr-1",
            raw_bytes=(
                b"Message-ID: <m1@example.com>\r\n"
                b"References: <root@example.com>\r\n"
                b"Subject: Experiment subject\r\n"
                b"From: Sender <sender@example.com>\r\n"
                b"To: Recipient <recipient@example.com>\r\n"
                b"Cc: Copy <copy@example.com>\r\n"
                b"Date: Tue, 12 May 2026 12:00:00 -0700\r\n"
                b"\r\n"
                b"First body"
            ),
            metadata={"label_ids": ["INBOX"]},
        )
        store.save_message(
            account="me@example.com",
            gmail_id="msg-2",
            thread_id="thr-1",
            raw_bytes=(
                b"Message-ID: <m2@example.com>\r\n"
                b"In-Reply-To: <m1@example.com>\r\n"
                b"References: <root@example.com> <m1@example.com>\r\n"
                b"Subject: Re: Experiment subject\r\n"
                b"From: Recipient <recipient@example.com>\r\n"
                b"To: Sender <sender@example.com>\r\n"
                b"Date: Tue, 12 May 2026 12:05:00 -0700\r\n"
                b"\r\n"
                b"Second body"
            ),
            metadata={"label_ids": ["INBOX"]},
        )
    finally:
        store.close()


def test_gmail_inspect_reads_local_headers_without_gmail_api(capsys, tmp_path):
    mail_dir = tmp_path / "mail"
    _cache_thread_for_inspection(mail_dir)

    with patch("gdocs.__main__.GmailClient") as gmail_cls:
        gmail_cls.side_effect = AssertionError("inspect should not build GmailClient")

        code = main([
            "--mail-data-dir",
            str(mail_dir),
            "gmail",
            "inspect",
            "--gmail-id",
            "msg-1",
            "--thread",
        ])

    assert code == 0
    gmail_cls.assert_not_called()
    payload = json.loads(capsys.readouterr().out)
    assert payload["gmail_id"] == "msg-1"
    assert payload["thread_id"] == "thr-1"
    assert payload["subject"] == "Experiment subject"
    assert payload["headers"] == {
        "Message-ID": "<m1@example.com>",
        "In-Reply-To": "",
        "References": "<root@example.com>",
        "Subject": "Experiment subject",
        "From": "Sender <sender@example.com>",
        "To": "Recipient <recipient@example.com>",
        "Cc": "Copy <copy@example.com>",
        "Date": "Tue, 12 May 2026 12:00:00 -0700",
    }
    assert payload["raw_header_text"].startswith("Message-ID: <m1@example.com>\r\n")
    assert [message["gmail_id"] for message in payload["thread_messages"]] == ["msg-1", "msg-2"]
    assert payload["thread_messages"][1]["headers"]["In-Reply-To"] == "<m1@example.com>"


def test_gmail_inspect_missing_local_message_fails_without_gmail_api(capsys, tmp_path):
    with patch("gdocs.__main__.GmailClient") as gmail_cls:
        gmail_cls.side_effect = AssertionError("inspect should not build GmailClient")

        code = main([
            "--mail-data-dir",
            str(tmp_path / "mail"),
            "gmail",
            "inspect",
            "--gmail-id",
            "missing-msg",
        ])

    assert code == 1
    gmail_cls.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["type"] == "ValueError"
    assert payload["error"] == "No locally cached Gmail message found for gmail_id: missing-msg"


def test_gmail_archive_dry_run(capsys, tmp_path):
    with patch("gdocs.__main__.GmailClient") as gmail_cls, patch("gdocs.__main__.MailStore"):
        gmail = gmail_cls.return_value
        gmail.archive_message.return_value = {"dry_run": True, "gmail_id": "msg-1"}

        code = main([
            "--mail-data-dir",
            str(tmp_path / "mail"),
            "gmail",
            "archive",
            "msg-1",
            "--dry-run",
        ])

    assert code == 0
    gmail.archive_message.assert_called_once_with("msg-1", dry_run=True)
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
