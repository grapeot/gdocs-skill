from pathlib import Path
from unittest.mock import MagicMock, patch
import hashlib
import json

import pytest

from gdocs.__main__ import main
from gdocs.auth import SCOPES, get_credentials
from gdocs.drive_client import DRIVE_READONLY, FOLDER, GOOGLE_PREFIX, DriveClient, parse_source


def client():
    result = DriveClient.__new__(DriveClient)
    result.drive = MagicMock()
    return result


def meta(fid, name, mime="application/octet-stream", **kwargs):
    return {"id": fid, "name": name, "mimeType": mime, **kwargs}


@pytest.mark.parametrize("source,expected", [
    ("abc_123", ("abc_123", None)),
    ("https://drive.google.com/drive/folders/abc?resourcekey=key-1", ("abc", "key-1")),
    ("https://drive.google.com/file/d/abc/view", ("abc", None)),
    ("https://docs.google.com/document/d/abc/edit", ("abc", None)),
    ("https://drive.google.com/open?id=abc", ("abc", None)),
])
def test_parse_source(source, expected):
    assert parse_source(source) == expected


@pytest.mark.parametrize("source", ["https://evil.example/d/abc", "../abc", "abc'", ""])
def test_reject_bad_source(source):
    with pytest.raises(ValueError):
        parse_source(source)


def test_folder_plan_duplicates_empty_and_unsafe_names(tmp_path):
    c = client()
    c.metadata = MagicMock(return_value=meta("root", "../root", FOLDER))
    c.children = MagicMock(side_effect=lambda fid, key=None: {
        "root": [meta("a", "same.txt"), meta("b", "SAME.txt"), meta("folder", "empty", FOLDER),
                 meta("doc", "Notes", GOOGLE_PREFIX + "document"), meta("evil", "../../escape")],
        "folder": [],
    }[fid])
    output = tmp_path / "new"
    result = c.download("root", output, dry_run=True)
    assert result["success"]
    assert result["file_count"] == 4
    paths = [Path(item["path"]) for item in result["files"]]
    assert len({str(p).casefold() for p in paths}) == 4
    assert any(p.name == "Notes.docx" for p in paths)
    assert all(p.is_relative_to(output) for p in paths)
    assert len(result["directories"]) == 2
    assert not output.exists()


def test_list_paginates_and_resource_key():
    c = client()
    request = c.drive.files.return_value.list.return_value
    request.headers = {}
    request.execute.side_effect = [{"files": [meta("b", "B")], "nextPageToken": "next"}, {"files": [meta("a", "A")]}]
    assert [x["id"] for x in c.children("root", "key")] == ["a", "b"]
    assert request.headers["X-Goog-Drive-Resource-Keys"] == "root/key"
    assert c.drive.files.return_value.list.call_args.kwargs["pageToken"] == "next"


def test_incomplete_search_fails():
    c = client()
    c.drive.files.return_value.list.return_value.execute.return_value = {"incompleteSearch": True}
    with pytest.raises(RuntimeError, match="incomplete"):
        c.children("root")


def test_shortcuts_and_blocked_files_are_explicit(tmp_path):
    c = client()
    c.metadata = MagicMock(return_value=meta("root", "Root", FOLDER))
    c.children = MagicMock(return_value=[meta("s", "shortcut", GOOGLE_PREFIX + "shortcut"),
                                       meta("b", "blocked", capabilities={"canDownload": False})])
    c._download_file = MagicMock()
    result = c.download("root", tmp_path)
    assert not result["success"]
    assert all(x["status"] == "skipped" and x["error"] for x in result["files"])
    c._download_file.assert_not_called()


def test_existing_file_and_symlink_refused(tmp_path):
    c = client()
    c.metadata = MagicMock(return_value=meta("a", "file.txt"))
    target = tmp_path / "file.txt"
    target.write_text("user content")
    with pytest.raises(FileExistsError):
        c.download("a", tmp_path)
    assert target.read_text() == "user content"
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        c.download("a", link)


def test_binary_download_integrity_and_atomic_failure(tmp_path):
    c = client()
    data = b"binary data"
    c.metadata = MagicMock(return_value=meta("a", "binary", size=str(len(data)), md5Checksum=hashlib.md5(data).hexdigest()))
    def downloader(handle, request, **kwargs):
        obj = MagicMock()
        obj.next_chunk.side_effect = lambda **kw: (handle.write(data), True)
        return obj
    with patch("gdocs.drive_client.MediaIoBaseDownload", side_effect=downloader):
        result = c.download("a", tmp_path)
    assert result["success"] and result["total_bytes"] == len(data)
    assert (tmp_path / "binary").read_bytes() == data
    c.metadata.return_value = meta("a", "broken", size="999")
    with patch("gdocs.drive_client.MediaIoBaseDownload", side_effect=downloader):
        result = c.download("a", tmp_path)
    assert not result["success"] and result["files"][0]["status"] == "failed"
    assert not (tmp_path / "broken").exists()
    assert not list(tmp_path.glob(".gdocs-download-*"))


def test_export_media_pdf(tmp_path):
    c = client()
    c.metadata = MagicMock(return_value=meta("a", "Doc", GOOGLE_PREFIX + "document"))
    with patch("gdocs.drive_client.MediaIoBaseDownload") as dl:
        dl.return_value.next_chunk.return_value = (None, True)
        result = c.download("a", tmp_path, export_format="pdf")
    assert result["success"]
    assert (tmp_path / "Doc.pdf").exists()
    c.drive.files.return_value.export_media.assert_called_once_with(fileId="a", mimeType="application/pdf")


def test_checksum_mismatch_and_transfer_failure_cleanup(tmp_path):
    c = client()
    c.metadata = MagicMock(return_value=meta("a", "bad", md5Checksum="wrong"))
    with patch("gdocs.drive_client.MediaIoBaseDownload") as dl:
        dl.return_value.next_chunk.return_value = (None, True)
        result = c.download("a", tmp_path)
    assert not result["success"]
    assert "checksum" in result["files"][0]["error"]
    assert not (tmp_path / "bad").exists()
    with patch("gdocs.drive_client.MediaIoBaseDownload") as dl:
        dl.return_value.next_chunk.side_effect = RuntimeError("transfer failed")
        result = c.download("a", tmp_path)
    assert result["files"][0]["error"] == "transfer failed"
    assert not list(tmp_path.glob(".gdocs-download-*"))


def test_folder_cycle_fails_before_writes(tmp_path):
    c = client()
    c.metadata = MagicMock(return_value=meta("root", "Root", FOLDER))
    c.children = MagicMock(return_value=[meta("root", "Cycle", FOLDER)])
    with pytest.raises(RuntimeError, match="cycle"):
        c.download("root", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_cli_failed_download_nonzero(capsys, tmp_path):
    with patch("gdocs.__main__.DriveClient") as cls:
        cls.return_value.download.return_value = {"success": False, "files": [{"status": "failed"}]}
        assert main(["drive", "download", "abc", "--output-dir", str(tmp_path)]) == 1
    assert not json.loads(capsys.readouterr().out)["success"]


def test_upload_single_file_dry_run(tmp_path):
    c = client()
    src = tmp_path / "handoff.zip"
    src.write_bytes(b"zipbytes")
    result = c.upload(src, dry_run=True)
    assert result["success"] and result["dry_run"]
    assert result["file_count"] == 1 and result["folder_count"] == 0
    c.drive.files.return_value.create.assert_not_called()


def test_upload_directory_creates_folders_and_files(tmp_path):
    c = client()
    root = tmp_path / "handoff"
    (root / "sub").mkdir(parents=True)
    (root / "README.md").write_text("hi")
    (root / "sub" / "code.py").write_text("print(1)")
    (root / ".DS_Store").write_text("junk")

    created_ids = iter(["folder-top", "folder-sub", "file-1", "file-2"])
    def create(**kwargs):
        request = MagicMock()
        request.execute.return_value = {"id": next(created_ids),
                                        "name": kwargs.get("body", {}).get("name"),
                                        "webViewLink": "https://drive.example/x"}
        return request
    c.drive.files.return_value.create.side_effect = create
    c.drive.files.return_value.get.return_value.execute.return_value = {"webViewLink": "https://drive.example/root"}

    result = c.upload(root)
    assert result["success"]
    names = [item["name"] for item in result["files"]]
    assert ".DS_Store" not in names
    assert result["folder_id"] == "folder-top"
    assert sum(item["type"] == "folder" for item in result["files"]) == 1
    assert sum(item["type"] == "file" for item in result["files"]) == 2


def test_cli_upload_with_share(tmp_path):
    src = tmp_path / "handoff.zip"
    src.write_bytes(b"zip")
    with patch("gdocs.__main__.DriveClient") as cls:
        cls.return_value.upload.return_value = {"success": True, "folder_id": "fold", "share_target_id": "file-1"}
        cls.return_value.share.return_value = {"success": True, "file_id": "fold"}
        assert main(["drive", "upload", str(src), "--share", "partner@example.com", "--role", "writer"]) == 0
    cls.return_value.share.assert_called_once_with("file-1", "partner@example.com", role="writer")


def test_upload_single_file_share_target_is_the_file(tmp_path):
    c = client()
    src = tmp_path / "handoff.zip"
    src.write_bytes(b"zip")
    c.drive.files.return_value.create.return_value.execute.return_value = {"id": "file-9", "name": "handoff.zip"}
    result = c.upload(src, folder_id="dest-folder")
    assert result["share_target_id"] == "file-9"
    assert result["folder_id"] == "dest-folder"


def test_upload_directory_share_target_is_top_folder(tmp_path):
    c = client()
    root = tmp_path / "handoff"
    root.mkdir()
    (root / "a.txt").write_text("a")
    ids = iter(["top", "file-1"])
    c.drive.files.return_value.create.side_effect = lambda **kw: MagicMock(
        execute=MagicMock(return_value={"id": next(ids)}))
    assert c.upload(root)["share_target_id"] == "top"


def test_cli_upload_dry_run_never_shares(tmp_path):
    src = tmp_path / "handoff.zip"
    src.write_bytes(b"zip")
    with patch("gdocs.__main__.DriveClient") as cls:
        cls.return_value.upload.return_value = {"success": True, "dry_run": True}
        assert main(["drive", "upload", str(src), "--share", "partner@example.com", "--dry-run"]) == 0
    cls.return_value.share.assert_not_called()


def test_drive_auth_failure_preserves_token_and_uses_timeout(tmp_path):
    (tmp_path / "credentials.json").write_text("{}")
    token = json.dumps({"scopes": SCOPES, "token": "old"})
    (tmp_path / "token.json").write_text(token)
    with patch("gdocs.auth.InstalledAppFlow.from_client_secrets_file") as factory:
        factory.return_value.run_local_server.side_effect = TimeoutError()
        with pytest.raises(RuntimeError, match="OAuth"):
            get_credentials(tmp_path, extra_scopes=[DRIVE_READONLY], auth_timeout=1)
    assert (tmp_path / "token.json").read_text() == token
    factory.return_value.run_local_server.assert_called_once_with(port=0, timeout_seconds=1)


def test_normal_auth_keeps_optional_grants(tmp_path):
    (tmp_path / "credentials.json").write_text("{}")
    (tmp_path / "token.json").write_text(json.dumps({"scopes": SCOPES + [DRIVE_READONLY]}))
    with patch("gdocs.auth.Credentials.from_authorized_user_file", return_value=MagicMock(valid=True)) as load:
        get_credentials(tmp_path)
    assert DRIVE_READONLY in load.call_args.args[1]
