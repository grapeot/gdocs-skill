# pyright: basic

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .frontmatter import parse as parse_frontmatter, serialize as serialize_frontmatter

if TYPE_CHECKING:
    from .client import GoogleDocsClient


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


def run_docs_command(data: dict[str, object], client: GoogleDocsClient) -> object:
    command = str(data["command"])

    if command == "publish":
        file_path = _path_arg(data, "file")
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
            file_path=_path_arg(data, "file"),
            title=_str_optional(data.get("title")),
            gdoc_id_override=_str_optional(data.get("gdoc_id")),
            tab_id_override=_str_optional(data.get("tab_id")),
            share=_str_optional(data.get("share")),
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
        return client.search_documents(str(data["query"]), max_results=_int_arg(data, "max_results"))

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
        file_path = _path_arg(data, "file")
        content = file_path.read_text(encoding="utf-8")
        return client.replace_tab_content(
            str(data["doc_id"]),
            str(data["tab_id"]),
            content,
            content_format=str(data["format"]),
        )

    if command == "tab" and str(data["tab_command"]) == "list":
        return client.list_tabs(str(data["doc_id"]))

    if command == "tab" and str(data["tab_command"]) == "delete":
        return client.delete_tab(
            str(data["doc_id"]),
            str(data["tab_id"]),
        )

    if command == "tab" and str(data["tab_command"]) == "add":
        content = None
        file_path = data.get("file")
        if file_path is not None:
            content = _path_value(file_path).read_text(encoding="utf-8")
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
            index=_int_optional(data.get("index")),
            tab_id=_str_optional(data.get("tab_id")),
            width_pts=_float_arg(data.get("width", 468)),
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



def _path_arg(data: dict[str, object], key: str) -> Path:
    return _path_value(data[key])


def _path_value(value: object) -> Path:
    if isinstance(value, Path):
        return value
    return Path(str(value))


def _str_optional(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _int_arg(data: dict[str, object], key: str) -> int:
    value = data[key]
    if isinstance(value, int):
        return value
    return int(str(value))


def _int_optional(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(str(value))


def _float_arg(value: object) -> float:
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    return float(str(value))
