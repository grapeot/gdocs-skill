# pyright: basic

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from gdocs.client import GoogleDocsClient


DEFAULT_SECRETS_DIR = Path(__file__).resolve().parent.parent / "secrets"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gdocs")
    _ = parser.add_argument("--secrets-dir", type=Path, default=DEFAULT_SECRETS_DIR)

    subparsers = parser.add_subparsers(dest="command", required=True)

    publish_parser = subparsers.add_parser("publish")
    _ = publish_parser.add_argument("file", type=Path)
    _ = publish_parser.add_argument("--title", required=True)
    _ = publish_parser.add_argument("--share")
    _ = publish_parser.add_argument("--role", default="writer")

    create_parser = subparsers.add_parser("create")
    _ = create_parser.add_argument("--title", required=True)

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

    return parser


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

    if command == "create":
        return client.create_document(title=str(data["title"]))

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

    raise RuntimeError("Unknown command")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_command(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
