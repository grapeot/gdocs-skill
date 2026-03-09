# pyright: basic

from __future__ import annotations

import json
from unittest.mock import patch

from gdocs.__main__ import DEFAULT_SECRETS_DIR, main


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


def test_error_outputs_json_to_stderr(capsys):
    with patch("gdocs.__main__.GoogleDocsClient") as client_cls:
        client = client_cls.return_value
        client.create_document.side_effect = RuntimeError("create failed")

        code = main(["create", "--title", "Broken"])

    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": "create failed"}
