# pyright: basic

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .gmail_client import GmailClient
    from .mail_store import MailStore, StoredMessage


def run_gmail_command(
    data: dict[str, object],
    secrets_dir: Path,
    data_dir: Path,
    gmail_client_cls: type[GmailClient],
    mail_store_cls: type[MailStore],
) -> object:
    command = str(data["gmail_command"])
    store = mail_store_cls(data_dir)
    try:
        if command == "list-local":
            return [_stored_message_json(item) for item in store.list_messages(limit=_int_arg(data, "limit"))]
        if command == "read":
            return _gmail_read(store, data)
        if command == "inspect":
            return store.inspect_headers(
                gmail_id=str(data["gmail_id"]),
                include_thread=bool(data.get("thread", False)),
            )
        if command == "export-md":
            return {
                "exported": store.export_markdown(
                    output_dir=cast(Path | None, data.get("output_dir")) if isinstance(data.get("output_dir"), Path) else None,
                    allow_unsafe_output_dir=bool(data.get("unsafe_output_dir", False)),
                    force=bool(data.get("force", False)),
                    limit=_int_arg(data, "limit"),
                    subject=str(data["subject"]) if data.get("subject") else None,
                    from_filter=str(data["from_filter"]) if data.get("from_filter") else None,
                )
            }
        gmail = gmail_client_cls(secrets_dir=secrets_dir)
        if command == "profile":
            return gmail.get_profile()
        if command == "download":
            return _gmail_download(gmail, store, data)
        if command == "search":
            labels = _resolve_labels(gmail, data.get("label"))
            return gmail.search_messages(
                query=str(data["query"]),
                label_ids=labels,
                max_results=_int_arg(data, "limit"),
                include_spam_trash=bool(data.get("include_spam_trash", False)),
            )
        if command == "send":
            body_path = _path_arg(data, "body_file")
            return gmail.send_message(
                to=_list_arg(data.get("to")),
                cc=_list_arg(data.get("cc")),
                bcc=_list_arg(data.get("bcc")),
                subject=str(data["subject"]),
                body_text=body_path.read_text(encoding="utf-8"),
                body_format=_normalize_body_format(str(data["body_format"])),
                dry_run=bool(data.get("dry_run", False)),
                attachments=_path_list(data.get("attach")),
            )
        if command == "draft":
            body_path = _path_arg(data, "body_file")
            return gmail.create_draft(
                to=_list_arg(data.get("to")),
                cc=_list_arg(data.get("cc")),
                bcc=_list_arg(data.get("bcc")),
                subject=str(data["subject"]),
                body_text=body_path.read_text(encoding="utf-8"),
                body_format=_normalize_body_format(str(data["body_format"])),
                attachments=_path_list(data.get("attach")),
            )
        if command == "reply":
            body_path = _path_arg(data, "body_file")
            kwargs = {
                "gmail_id": str(data["gmail_id"]),
                "body_text": body_path.read_text(encoding="utf-8"),
                "body_format": _normalize_body_format(str(data["body_format"])),
                "to": _list_arg(data.get("to")) or None,
                "cc": _list_arg(data.get("cc")) or None,
                "reply_all": bool(data.get("reply_all", False)),
                "attachments": _path_list(data.get("attach")),
            }
            if bool(data.get("draft", False)):
                return gmail.create_reply_draft(**kwargs)
            return gmail.reply_message(
                dry_run=bool(data.get("dry_run", False)),
                **kwargs,
            )
        if command == "archive":
            return gmail.archive_message(str(data["gmail_id"]), dry_run=bool(data.get("dry_run", False)))
        if command == "trash":
            return gmail.trash_message(str(data["gmail_id"]), dry_run=bool(data.get("dry_run", False)))
        if command == "mark-read":
            return gmail.mark_read(str(data["gmail_id"]), dry_run=bool(data.get("dry_run", False)))
        if command == "mark-unread":
            return gmail.mark_unread(str(data["gmail_id"]), dry_run=bool(data.get("dry_run", False)))
        if command == "label" and str(data["gmail_label_command"]) == "list":
            labels = gmail.list_labels()
            store.upsert_labels(labels)
            return labels
        if command == "label" and str(data["gmail_label_command"]) == "apply":
            return gmail.apply_label(
                str(data["gmail_id"]), str(data["label"]), dry_run=bool(data.get("dry_run", False))
            )
        if command == "label" and str(data["gmail_label_command"]) == "remove":
            return gmail.remove_label(
                str(data["gmail_id"]), str(data["label"]), dry_run=bool(data.get("dry_run", False))
            )
        raise RuntimeError("Unknown Gmail command")
    finally:
        store.close()


def _gmail_download(gmail: GmailClient, store: MailStore, data: dict[str, object]) -> dict[str, object]:
    labels = _resolve_labels(gmail, data.get("label"))
    query = str(data["query"]) if data.get("query") else f"newer_than:{_int_arg(data, 'days')}d"
    matches = gmail.search_messages(
        query=query,
        label_ids=labels,
        max_results=_int_arg(data, "limit"),
        include_spam_trash=bool(data.get("include_spam_trash", False)),
    )
    profile = gmail.get_profile()
    account = str(profile.get("emailAddress") or "me")
    downloaded: list[dict[str, object]] = []
    skipped = 0
    for match in matches:
        gmail_id = match["gmail_id"]
        if store.has_message(gmail_id):
            skipped += 1
            continue
        raw_bytes, metadata = gmail.get_message_raw(gmail_id)
        message = store.save_message(
            account=account,
            gmail_id=gmail_id,
            thread_id=str(metadata.get("thread_id") or match.get("thread_id") or ""),
            raw_bytes=raw_bytes,
            metadata=metadata,
        )
        downloaded.append(_stored_message_json(message))
    return {
        "query": query,
        "labels": labels,
        "matched_count": len(matches),
        "downloaded_count": len(downloaded),
        "skipped_existing_count": skipped,
        "messages": downloaded,
    }


def _gmail_read(store: MailStore, data: dict[str, object]) -> dict[str, object]:
    matches = store.find_messages(
        gmail_id=str(data["gmail_id"]) if data.get("gmail_id") else None,
        subject=str(data["subject"]) if data.get("subject") else None,
        from_filter=str(data["from_filter"]) if data.get("from_filter") else None,
        limit=50,
    )
    if not matches:
        return {"match_count": 0, "matches": []}
    selected: StoredMessage | None = None
    if data.get("gmail_id") or data.get("latest"):
        selected = matches[0]
    elif data.get("index") is not None:
        index = _int_arg(data, "index")
        if index < 0 or index >= len(matches):
            raise ValueError(f"--index out of range: {index}")
        selected = matches[index]
    if selected is None:
        return {
            "match_count": len(matches),
            "matches": [dict(_stored_message_json(item), index=index) for index, item in enumerate(matches)],
            "note": "Use --latest, --index N, or --gmail-id to select a message.",
        }
    body = store.read_body(selected, full=bool(data.get("full", False)))
    return {"match_count": len(matches), **body}


def _resolve_labels(gmail: GmailClient, labels: object) -> list[str] | None:
    if not labels:
        return None
    return [gmail.resolve_label_id(label) for label in _list_arg(labels)]


def _list_arg(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _int_arg(data: dict[str, object], key: str) -> int:
    value = data[key]
    if isinstance(value, int):
        return value
    return int(str(value))


def _path_arg(data: dict[str, object], key: str) -> Path:
    value = data[key]
    if isinstance(value, Path):
        return value
    return Path(str(value))


def _path_list(value: object) -> list[Path] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [Path(str(item)) for item in value]
    return [Path(str(value))]


def _stored_message_json(message: StoredMessage) -> dict[str, object]:
    return {
        "gmail_id": message.gmail_id,
        "thread_id": message.thread_id,
        "subject": message.subject,
        "from_addr": message.from_addr,
        "to_addr": message.to_addr,
        "cc_addr": message.cc_addr,
        "date": message.date,
        "labels": message.labels,
        "mime_path": str(message.mime_path),
        "downloaded_at": message.downloaded_at,
    }


def _normalize_body_format(value: str) -> str:
    if value == "md":
        return "markdown"
    if value == "markdown":
        return "text"
    return value
