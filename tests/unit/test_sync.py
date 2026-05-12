# pyright: basic

from __future__ import annotations

import json
from unittest.mock import patch

from gdocs.__main__ import main
from gdocs.frontmatter import parse as parse_frontmatter


def _write(path, content):
    path.write_text(content, encoding="utf-8")


def test_sync_creates_doc_on_first_run_and_writes_back_frontmatter(capsys, tmp_path):
    md = tmp_path / "note.md"
    _write(md, "# Hello\n\nBody.\n")

    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.create_document.return_value = {
            "id": "doc-new",
            "link": "https://docs.google.com/document/d/doc-new/edit",
        }
        code = main(["sync", str(md), "--title", "My Note"])

    assert code == 0
    client.create_document.assert_called_once()
    call_kwargs = client.create_document.call_args.kwargs
    assert call_kwargs["title"] == "My Note"
    assert call_kwargs["tabs"] == [{"title": "My Note", "content": "# Hello\n\nBody.\n"}]
    assert call_kwargs["content_format"] == "markdown"
    client.replace_tab_content.assert_not_called()
    client.share_document.assert_not_called()

    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "create"
    assert out["doc_id"] == "doc-new"

    fm = parse_frontmatter(md.read_text(encoding="utf-8"))
    assert fm.data["gdoc_id"] == "doc-new"
    assert "gdoc_last_synced" in fm.data
    assert fm.body == "# Hello\n\nBody.\n"


def test_sync_replaces_tab_when_frontmatter_already_present(capsys, tmp_path):
    md = tmp_path / "note.md"
    _write(
        md,
        "---\n"
        "gdoc_id: doc-existing\n"
        "gdoc_tab_id: t.mytab\n"
        "gdoc_last_synced: 2026-01-01T00:00:00Z\n"
        "---\n"
        "\n"
        "# Updated body\n",
    )

    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.replace_tab_content.return_value = {"success": True}
        code = main(["sync", str(md)])

    assert code == 0
    client.create_document.assert_not_called()
    client.replace_tab_content.assert_called_once_with(
        "doc-existing", "t.mytab", "# Updated body\n", content_format="markdown"
    )

    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "replace"
    assert out["doc_id"] == "doc-existing"
    assert out["tab_id"] == "t.mytab"

    fm = parse_frontmatter(md.read_text(encoding="utf-8"))
    assert fm.data["gdoc_id"] == "doc-existing"
    assert fm.data["gdoc_tab_id"] == "t.mytab"
    assert fm.data["gdoc_last_synced"] != "2026-01-01T00:00:00Z"


def test_sync_replace_defaults_to_t0_when_no_tab_id(capsys, tmp_path):
    md = tmp_path / "note.md"
    _write(md, "---\ngdoc_id: doc-existing\n---\n\nBody\n")

    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.replace_tab_content.return_value = {"success": True}
        _ = main(["sync", str(md)])

    client.replace_tab_content.assert_called_once_with(
        "doc-existing", "t.0", "Body\n", content_format="markdown"
    )
    out = json.loads(capsys.readouterr().out)
    assert out["tab_id"] == "t.0"


def test_sync_cli_override_binds_to_existing_doc(capsys, tmp_path):
    md = tmp_path / "note.md"
    _write(md, "# Body\n")

    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.replace_tab_content.return_value = {"success": True}
        code = main([
            "sync",
            str(md),
            "--gdoc-id",
            "doc-manual",
            "--tab-id",
            "t.manual",
        ])

    assert code == 0
    client.replace_tab_content.assert_called_once_with(
        "doc-manual", "t.manual", "# Body\n", content_format="markdown"
    )

    fm = parse_frontmatter(md.read_text(encoding="utf-8"))
    assert fm.data["gdoc_id"] == "doc-manual"
    assert fm.data["gdoc_tab_id"] == "t.manual"
    assert fm.body == "# Body\n"


def test_sync_first_run_without_title_errors(capsys, tmp_path):
    md = tmp_path / "note.md"
    _write(md, "# Body\n")

    with patch("gdocs.__main__.GoogleDocsClient"):
        code = main(["sync", str(md)])

    assert code == 1
    err = capsys.readouterr().err
    assert "title" in err.lower()


def test_sync_first_run_with_share_calls_share(capsys, tmp_path):
    md = tmp_path / "note.md"
    _write(md, "Body\n")

    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.create_document.return_value = {
            "id": "doc-new",
            "link": "https://docs.google.com/document/d/doc-new/edit",
        }
        code = main([
            "sync", str(md), "--title", "T", "--share", "a@b.com", "--role", "reader",
        ])

    assert code == 0
    client.share_document.assert_called_once_with("doc-new", "a@b.com", role="reader")


def test_sync_dry_run_does_not_call_api_or_mutate_file(capsys, tmp_path):
    md = tmp_path / "note.md"
    original = "---\ngdoc_id: doc-existing\n---\n\nBody\n"
    _write(md, original)

    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        code = main(["sync", str(md), "--dry-run"])

    assert code == 0
    client.replace_tab_content.assert_not_called()
    client.create_document.assert_not_called()
    assert md.read_text(encoding="utf-8") == original
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["action"] == "replace"
    assert out["doc_id"] == "doc-existing"


def test_sync_dry_run_for_create_path(capsys, tmp_path):
    md = tmp_path / "note.md"
    _write(md, "# Body\n")

    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        code = main(["sync", str(md), "--title", "T", "--dry-run"])

    assert code == 0
    client.create_document.assert_not_called()
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["action"] == "create"
