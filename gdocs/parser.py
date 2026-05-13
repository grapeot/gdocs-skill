# pyright: basic

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_SECRETS_DIR = Path(__file__).resolve().parent.parent / "secrets"
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "mail"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gdocs")
    _ = parser.add_argument("--secrets-dir", type=Path, default=DEFAULT_SECRETS_DIR)
    _ = parser.add_argument("--mail-data-dir", type=Path, default=DEFAULT_DATA_DIR)

    subparsers = parser.add_subparsers(dest="command", required=True)

    publish_parser = subparsers.add_parser("publish")
    _ = publish_parser.add_argument("file", type=Path)
    _ = publish_parser.add_argument("--title", required=True)
    _ = publish_parser.add_argument("--share")
    _ = publish_parser.add_argument("--role", default="writer")

    sync_parser = subparsers.add_parser(
        "sync",
        help="Idempotent publish: read front matter, create or update the bound Google Doc.",
    )
    _ = sync_parser.add_argument("file", type=Path)
    _ = sync_parser.add_argument("--title", help="Doc title (required on first sync)")
    _ = sync_parser.add_argument(
        "--gdoc-id",
        help="Bind this MD to an existing Google Doc (writes to front matter)",
    )
    _ = sync_parser.add_argument(
        "--tab-id",
        help="Bind this MD to a specific tab inside the Google Doc (writes to front matter)",
    )
    _ = sync_parser.add_argument(
        "--share",
        help="On first create, share with this email",
    )
    _ = sync_parser.add_argument("--role", default="writer")
    _ = sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without calling any API or mutating the file",
    )

    create_parser = subparsers.add_parser("create")
    _ = create_parser.add_argument("--title", required=True)

    delete_parser = subparsers.add_parser("delete")
    _ = delete_parser.add_argument("doc_id")
    _ = delete_parser.add_argument(
        "--permanent",
        action="store_true",
        help="Permanently delete instead of moving to trash (default is trash, recoverable)",
    )

    search_parser = subparsers.add_parser("search")
    _ = search_parser.add_argument("query")
    _ = search_parser.add_argument("--max-results", type=int, default=10)

    share_parser = subparsers.add_parser("share")
    _ = share_parser.add_argument("doc_id")
    _ = share_parser.add_argument("--email", required=True)
    _ = share_parser.add_argument("--role", default="writer")
    _ = share_parser.add_argument("--message")

    title_parser = subparsers.add_parser("title")
    _ = title_parser.add_argument("doc_id")
    _ = title_parser.add_argument("new_title")

    link_parser = subparsers.add_parser("link")
    _ = link_parser.add_argument("doc_id")
    _ = link_parser.add_argument("--public", action="store_true")

    tab_parser = subparsers.add_parser("tab")
    tab_subparsers = tab_parser.add_subparsers(dest="tab_command", required=True)

    tab_rename_parser = tab_subparsers.add_parser("rename")
    _ = tab_rename_parser.add_argument("doc_id")
    _ = tab_rename_parser.add_argument("tab_id")
    _ = tab_rename_parser.add_argument("new_title")

    tab_replace_parser = tab_subparsers.add_parser("replace")
    _ = tab_replace_parser.add_argument("doc_id")
    _ = tab_replace_parser.add_argument("tab_id")
    _ = tab_replace_parser.add_argument("file", type=Path)
    _ = tab_replace_parser.add_argument("--format", choices=["plain", "markdown"], default="markdown")

    tab_list_parser = tab_subparsers.add_parser("list")
    _ = tab_list_parser.add_argument("doc_id")

    tab_add_parser = tab_subparsers.add_parser("add")
    _ = tab_add_parser.add_argument("doc_id")
    _ = tab_add_parser.add_argument("title")
    _ = tab_add_parser.add_argument("file", type=Path, nargs="?", default=None)
    _ = tab_add_parser.add_argument("--format", choices=["plain", "markdown"], default="markdown")

    comment_parser = subparsers.add_parser("comment")
    comment_subparsers = comment_parser.add_subparsers(dest="comment_command", required=True)

    comment_list_parser = comment_subparsers.add_parser("list")
    _ = comment_list_parser.add_argument("doc_id")
    _ = comment_list_parser.add_argument(
        "--include-resolved",
        action="store_true",
        default=True,
        help="Include resolved comments (default: True)",
    )
    _ = comment_list_parser.add_argument(
        "--unresolved-only",
        action="store_true",
        default=False,
        help="Show only unresolved comments",
    )

    comment_reply_parser = comment_subparsers.add_parser("reply")
    _ = comment_reply_parser.add_argument("doc_id")
    _ = comment_reply_parser.add_argument("comment_id")
    _ = comment_reply_parser.add_argument("content")

    comment_resolve_parser = comment_subparsers.add_parser("resolve")
    _ = comment_resolve_parser.add_argument("doc_id")
    _ = comment_resolve_parser.add_argument("comment_id")

    image_parser = subparsers.add_parser("image")
    _ = image_parser.add_argument("doc_id")
    _ = image_parser.add_argument("image_path", type=Path)
    _ = image_parser.add_argument("--index", type=int, default=None)
    _ = image_parser.add_argument("--tab-id")
    _ = image_parser.add_argument("--width", type=float, default=468, help="Width in points (468 = full width)")

    gmail_parser = subparsers.add_parser("gmail")
    gmail_subparsers = gmail_parser.add_subparsers(dest="gmail_command", required=True)

    gmail_profile = gmail_subparsers.add_parser("profile")
    _ = gmail_profile

    gmail_download = gmail_subparsers.add_parser("download")
    _ = gmail_download.add_argument("--days", type=int, default=7)
    _ = gmail_download.add_argument("--limit", type=int, default=200)
    _ = gmail_download.add_argument("--label", action="append")
    _ = gmail_download.add_argument("--query")
    _ = gmail_download.add_argument("--include-spam-trash", action="store_true")

    gmail_search = gmail_subparsers.add_parser("search")
    _ = gmail_search.add_argument("query")
    _ = gmail_search.add_argument("--limit", type=int, default=20)
    _ = gmail_search.add_argument("--label", action="append")
    _ = gmail_search.add_argument("--include-spam-trash", action="store_true")

    gmail_list_local = gmail_subparsers.add_parser("list-local")
    _ = gmail_list_local.add_argument("--limit", type=int, default=50)

    gmail_read = gmail_subparsers.add_parser("read")
    _ = gmail_read.add_argument("--gmail-id")
    _ = gmail_read.add_argument("--subject")
    _ = gmail_read.add_argument("--from", dest="from_filter")
    _ = gmail_read.add_argument("--latest", action="store_true")
    _ = gmail_read.add_argument("--index", type=int)
    _ = gmail_read.add_argument("--full", action="store_true")

    gmail_export_md = gmail_subparsers.add_parser("export-md")
    _ = gmail_export_md.add_argument("--limit", type=int, default=100)
    _ = gmail_export_md.add_argument("--subject")
    _ = gmail_export_md.add_argument("--from", dest="from_filter")
    _ = gmail_export_md.add_argument("--output-dir", type=Path)
    _ = gmail_export_md.add_argument("--unsafe-output-dir", action="store_true")
    _ = gmail_export_md.add_argument("--force", action="store_true")

    gmail_send = gmail_subparsers.add_parser("send")
    _ = gmail_send.add_argument("--to", action="append", required=True)
    _ = gmail_send.add_argument("--cc", action="append")
    _ = gmail_send.add_argument("--bcc", action="append")
    _ = gmail_send.add_argument("--subject", required=True)
    _ = gmail_send.add_argument("--body-file", type=Path, required=True)
    _ = gmail_send.add_argument("--body-format", choices=["text", "html", "markdown", "md"], default="text")
    _ = gmail_send.add_argument("--dry-run", action="store_true")

    gmail_reply = gmail_subparsers.add_parser("reply")
    _ = gmail_reply.add_argument("--gmail-id", required=True)
    _ = gmail_reply.add_argument("--body-file", type=Path, required=True)
    _ = gmail_reply.add_argument("--body-format", choices=["text", "html", "markdown", "md"], default="text")
    _ = gmail_reply.add_argument("--to", action="append")
    _ = gmail_reply.add_argument("--cc", action="append")
    _ = gmail_reply.add_argument("--dry-run", action="store_true")

    for command_name in ("archive", "trash", "mark-read", "mark-unread"):
        command_parser = gmail_subparsers.add_parser(command_name)
        _ = command_parser.add_argument("gmail_id")
        _ = command_parser.add_argument("--dry-run", action="store_true")

    gmail_label = gmail_subparsers.add_parser("label")
    gmail_label_subparsers = gmail_label.add_subparsers(dest="gmail_label_command", required=True)
    gmail_label_list = gmail_label_subparsers.add_parser("list")
    _ = gmail_label_list
    for command_name in ("apply", "remove"):
        command_parser = gmail_label_subparsers.add_parser(command_name)
        _ = command_parser.add_argument("gmail_id")
        _ = command_parser.add_argument("--label", required=True)
        _ = command_parser.add_argument("--dry-run", action="store_true")

    calendar_parser = subparsers.add_parser("calendar")
    calendar_subparsers = calendar_parser.add_subparsers(dest="calendar_command", required=True)

    calendar_create = calendar_subparsers.add_parser("create-event")
    _ = calendar_create.add_argument("--calendar-id", default="primary")
    _ = calendar_create.add_argument("--summary", required=True)
    _ = calendar_create.add_argument("--start", required=True)
    _ = calendar_create.add_argument("--end", required=True)
    _ = calendar_create.add_argument("--attendee", action="append")
    _ = calendar_create.add_argument("--description")
    _ = calendar_create.add_argument("--location")
    _ = calendar_create.add_argument("--timezone")

    calendar_update = calendar_subparsers.add_parser("update-event")
    _ = calendar_update.add_argument("event_id")
    _ = calendar_update.add_argument("--calendar-id", default="primary")
    _ = calendar_update.add_argument("--summary")

    calendar_delete = calendar_subparsers.add_parser("delete-event")
    _ = calendar_delete.add_argument("event_id")
    _ = calendar_delete.add_argument("--calendar-id", default="primary")

    calendar_list = calendar_subparsers.add_parser("list-events")
    _ = calendar_list.add_argument("--calendar-id", default="primary")
    _ = calendar_list.add_argument("--time-min", required=True)
    _ = calendar_list.add_argument("--time-max")
    _ = calendar_list.add_argument("--max-results", type=int, default=10)

    return parser

