from __future__ import annotations

from gdocs.mail_store import MailStore


def _metadata():
    return {
        "subject": "Hello",
        "from_addr": "sender@example.com",
        "to_addr": "recipient@example.com",
        "cc_addr": "",
        "date": "Tue, 12 May 2026 12:00:00 -0700",
        "snippet": "Body",
        "size_estimate": 128,
        "label_ids": ["INBOX", "UNREAD"],
    }


def test_store_saves_raw_eml_and_metadata(tmp_path):
    store = MailStore(tmp_path / "mail")
    try:
        message = store.save_message(
            account="me@example.com",
            gmail_id="msg-1",
            thread_id="thr-1",
            raw_bytes=b"Subject: Hello\nFrom: sender@example.com\nTo: recipient@example.com\n\nBody",
            metadata=_metadata(),
        )

        assert store.has_message("msg-1") is True
        assert message.mime_path.exists()
        assert message.subject == "Hello"
        assert message.labels == ["INBOX", "UNREAD"]
    finally:
        store.close()


def test_store_uses_raw_headers_when_metadata_is_missing(tmp_path):
    store = MailStore(tmp_path / "mail")
    try:
        message = store.save_message(
            account="me@example.com",
            gmail_id="msg-1",
            thread_id="thr-1",
            raw_bytes=b"Subject: From Raw\nFrom: sender@example.com\nTo: recipient@example.com\nDate: Tue, 12 May 2026 12:00:00 -0700\n\nBody",
            metadata={"label_ids": ["INBOX"]},
        )

        assert message.subject == "From Raw"
        assert message.from_addr == "sender@example.com"
        assert message.date == "Tue, 12 May 2026 12:00:00 -0700"
    finally:
        store.close()


def test_store_orders_by_parsed_date_not_rfc2822_text(tmp_path):
    store = MailStore(tmp_path / "mail")
    try:
        old = dict(_metadata(), subject="Old", date="Wed, 13 May 2026 12:00:00 +0000")
        new = dict(_metadata(), subject="New", date="Tue, 14 May 2026 12:00:00 +0000")
        store.save_message(
            account="me@example.com",
            gmail_id="old",
            thread_id="thr-old",
            raw_bytes=b"Subject: Old\n\nBody",
            metadata=old,
        )
        store.save_message(
            account="me@example.com",
            gmail_id="new",
            thread_id="thr-new",
            raw_bytes=b"Subject: New\n\nBody",
            metadata=new,
        )

        assert [message.subject for message in store.list_messages(limit=2)] == ["New", "Old"]
    finally:
        store.close()


def test_store_replaces_duplicate_gmail_id(tmp_path):
    store = MailStore(tmp_path / "mail")
    try:
        store.save_message(
            account="me@example.com",
            gmail_id="msg-1",
            thread_id="thr-1",
            raw_bytes=b"Subject: Hello\n\nBody",
            metadata=_metadata(),
        )
        changed = dict(_metadata(), subject="Changed")
        store.save_message(
            account="me@example.com",
            gmail_id="msg-1",
            thread_id="thr-1",
            raw_bytes=b"Subject: Changed\n\nBody",
            metadata=changed,
        )

        matches = store.find_messages(gmail_id="msg-1")
        assert len(matches) == 1
        assert matches[0].subject == "Changed"
    finally:
        store.close()


def test_store_reads_body_and_exports_markdown(tmp_path):
    store = MailStore(tmp_path / "mail")
    try:
        message = store.save_message(
            account="me@example.com",
            gmail_id="msg-1",
            thread_id="thr-1",
            raw_bytes=b"Subject: Hello\nFrom: sender@example.com\nTo: recipient@example.com\n\nBody",
            metadata=_metadata(),
        )

        body = store.read_body(message, full=True)
        assert body["body"] == "Body"
        exported = store.export_markdown(force=True)
        assert exported[0]["gmail_id"] == "msg-1"
        assert "Body" in (tmp_path / "mail" / "markdown").joinpath(
            exported[0]["path"].split("/markdown/")[-1]
        ).read_text(encoding="utf-8")
    finally:
        store.close()


def test_export_markdown_rejects_output_outside_data_dir_without_override(tmp_path):
    store = MailStore(tmp_path / "mail")
    try:
        store.save_message(
            account="me@example.com",
            gmail_id="msg-1",
            thread_id="thr-1",
            raw_bytes=b"Subject: Hello\n\nBody",
            metadata=_metadata(),
        )

        unsafe_dir = tmp_path / "exports"
        try:
            store.export_markdown(output_dir=unsafe_dir)
        except ValueError as exc:
            assert "--unsafe-output-dir" in str(exc)
        else:
            raise AssertionError("expected unsafe output dir to be rejected")

        exported = store.export_markdown(output_dir=unsafe_dir, allow_unsafe_output_dir=True)
        assert exported[0]["path"].startswith(str(unsafe_dir))
    finally:
        store.close()


def test_upsert_labels(tmp_path):
    store = MailStore(tmp_path / "mail")
    try:
        store.upsert_labels([
            {"id": "Label_1", "name": "Project", "type": "user"},
        ])
        row = store.connection.execute("SELECT name FROM labels WHERE id = ?", ("Label_1",)).fetchone()
        assert row == ("Project",)
    finally:
        store.close()
