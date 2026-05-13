# pyright: basic

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from googleapiclient.errors import HttpError
from .client import GoogleDocsClient
from .frontmatter import parse as parse_frontmatter, serialize as serialize_frontmatter
from .gmail_client import GmailClient
from .mail_store import MailStore, StoredMessage


from .parser import DEFAULT_DATA_DIR, DEFAULT_SECRETS_DIR, build_parser


FM_DOC_ID = "gdoc_id"
FM_TAB_ID = "gdoc_tab_id"
FM_LAST_SYNCED = "gdoc_last_synced"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sync(
    client: GoogleDocsClient,
    file_path: Path,
    title: str | None,
    gdoc_id_override: str | None,
    tab_id_override: str | None,
    share: str | None,
    role: str,
    dry_run: bool,
) -> dict[str, object]:
    """Idempotent sync: read front matter, create-or-replace the bound doc.

    Resolution order for the doc/tab binding:
      1. CLI overrides (--gdoc-id / --tab-id)
      2. Existing front matter values
      3. If neither gives a doc id, create a new document.
    """
    raw = file_path.read_text(encoding="utf-8")
    fm = parse_frontmatter(raw)

    doc_id: str | None = gdoc_id_override or fm.get(FM_DOC_ID)
    tab_id: str | None = tab_id_override or fm.get(FM_TAB_ID)

    if doc_id:
        action = "replace"
        target_tab = tab_id or "t.0"
        if dry_run:
            return {
                "dry_run": True,
                "action": action,
                "doc_id": doc_id,
                "tab_id": target_tab,
                "file": str(file_path),
            }
        _ = client.replace_tab_content(
            doc_id, target_tab, fm.body, content_format="markdown"
        )
        fm.set(FM_DOC_ID, doc_id)
        if tab_id:
            fm.set(FM_TAB_ID, tab_id)
        fm.set(FM_LAST_SYNCED, _utc_now_iso())
        file_path.write_text(serialize_frontmatter(fm), encoding="utf-8")
        return {
            "action": action,
            "doc_id": doc_id,
            "tab_id": target_tab,
            "link": f"https://docs.google.com/document/d/{doc_id}/edit",
            "front_matter_updated": True,
        }

    if not title:
        raise ValueError(
            "First sync requires --title (no gdoc_id in front matter and no --gdoc-id given)"
        )
    if dry_run:
        return {
            "dry_run": True,
            "action": "create",
            "title": title,
            "file": str(file_path),
        }
    created = client.create_document(
        title=title,
        tabs=[{"title": title, "content": fm.body}],
        content_format="markdown",
    )
    new_doc_id = created["id"]
    if share:
        _ = client.share_document(new_doc_id, share, role=role)

    fm.set(FM_DOC_ID, new_doc_id)
    fm.set(FM_LAST_SYNCED, _utc_now_iso())
    file_path.write_text(serialize_frontmatter(fm), encoding="utf-8")
    return {
        "action": "create",
        "doc_id": new_doc_id,
        "link": created.get("link", f"https://docs.google.com/document/d/{new_doc_id}/edit"),
        "front_matter_updated": True,
    }


def run_command(args: argparse.Namespace) -> object:
    data = vars(args)
    secrets_dir = Path(data["secrets_dir"])
    command = str(data["command"])
    if command == "gmail":
        return _run_gmail_command(data, secrets_dir, Path(data["mail_data_dir"]))
    client = GoogleDocsClient(secrets_dir=secrets_dir)

    if command == "publish":
        file_path = Path(data["file"])
        title = str(data["title"])
        content = file_path.read_text(encoding="utf-8")
        created = client.create_document(
            title=title,
            tabs=[{"title": title, "content": content}],
            content_format="markdown",
        )
        share_target = data["share"]
        if share_target:
            _ = client.share_document(created["id"], str(share_target), role=str(data["role"]))
        return {"id": created["id"], "link": created["link"]}

    if command == "sync":
        return _sync(
            client,
            file_path=Path(data["file"]),
            title=data.get("title"),
            gdoc_id_override=data.get("gdoc_id"),
            tab_id_override=data.get("tab_id"),
            share=data.get("share"),
            role=str(data.get("role") or "writer"),
            dry_run=bool(data.get("dry_run", False)),
        )

    if command == "create":
        return client.create_document(title=str(data["title"]))

    if command == "delete":
        return client.delete_document(
            str(data["doc_id"]),
            permanent=bool(data["permanent"]),
        )

    if command == "search":
        return client.search_documents(str(data["query"]), max_results=int(data["max_results"]))

    if command == "share":
        return client.share_document(
            str(data["doc_id"]),
            str(data["email"]),
            role=str(data["role"]),
            message=str(data["message"]) if data["message"] else None,
        )

    if command == "title":
        return client.update_title(str(data["doc_id"]), str(data["new_title"]))

    if command == "link":
        return {"link": client.get_share_link(str(data["doc_id"]), public=bool(data["public"]))}

    if command == "tab" and str(data["tab_command"]) == "rename":
        return client.rename_tab(
            str(data["doc_id"]),
            str(data["tab_id"]),
            str(data["new_title"]),
        )

    if command == "tab" and str(data["tab_command"]) == "replace":
        file_path = Path(data["file"])
        content = file_path.read_text(encoding="utf-8")
        return client.replace_tab_content(
            str(data["doc_id"]),
            str(data["tab_id"]),
            content,
            content_format=str(data["format"]),
        )

    if command == "tab" and str(data["tab_command"]) == "list":
        return client.list_tabs(str(data["doc_id"]))

    if command == "tab" and str(data["tab_command"]) == "add":
        content = None
        file_path = data.get("file")
        if file_path is not None:
            content = Path(file_path).read_text(encoding="utf-8")
        return client.add_tab(
            str(data["doc_id"]),
            str(data["title"]),
            content=content,
            content_format=str(data["format"]),
        )

    if command == "image":
        return client.insert_image(
            str(data["doc_id"]),
            str(data["image_path"]),
            index=data.get("index"),
            tab_id=data.get("tab_id"),
            width_pts=float(data.get("width", 468)),
        )

    if command == "comment" and str(data["comment_command"]) == "list":
        include_resolved = not bool(data.get("unresolved_only", False))
        return client.list_comments(str(data["doc_id"]), include_resolved=include_resolved)

    if command == "comment" and str(data["comment_command"]) == "reply":
        return client.reply_comment(
            str(data["doc_id"]),
            str(data["comment_id"]),
            str(data["content"]),
        )

    if command == "comment" and str(data["comment_command"]) == "resolve":
        return client.resolve_comment(
            str(data["doc_id"]),
            str(data["comment_id"]),
        )

    raise RuntimeError("Unknown command")


def _run_gmail_command(data: dict[str, object], secrets_dir: Path, data_dir: Path) -> object:
    gmail = GmailClient(secrets_dir=secrets_dir)
    store = MailStore(data_dir)
    try:
        command = str(data["gmail_command"])
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
        if command == "list-local":
            return [_stored_message_json(item) for item in store.list_messages(limit=_int_arg(data, "limit"))]
        if command == "read":
            return _gmail_read(store, data)
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
            )
        if command == "reply":
            body_path = _path_arg(data, "body_file")
            return gmail.reply_message(
                gmail_id=str(data["gmail_id"]),
                body_text=body_path.read_text(encoding="utf-8"),
                body_format=_normalize_body_format(str(data["body_format"])),
                to=_list_arg(data.get("to")) or None,
                cc=_list_arg(data.get("cc")),
                dry_run=bool(data.get("dry_run", False)),
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_command(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except HttpError as exc:
        error_detail = {
            "error": str(exc),
            "status_code": exc.status_code,
            "response": exc.content.decode("utf-8", errors="replace") if exc.content else None,
        }
        print(json.dumps(error_detail, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
