# pyright: basic

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.errors import HttpError
from gdocs.client import GoogleDocsClient
from gdocs.frontmatter import FrontMatter, parse as parse_frontmatter, serialize as serialize_frontmatter


DEFAULT_SECRETS_DIR = Path(__file__).resolve().parent.parent / "secrets"


FM_DOC_ID = "gdoc_id"
FM_TAB_ID = "gdoc_tab_id"
FM_LAST_SYNCED = "gdoc_last_synced"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gdocs")
    _ = parser.add_argument("--secrets-dir", type=Path, default=DEFAULT_SECRETS_DIR)

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

    return parser


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
