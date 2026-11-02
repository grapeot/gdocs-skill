from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from .auth import get_credentials
from .client import _http_error_message, _retry_transient

DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
FOLDER = "application/vnd.google-apps.folder"
GOOGLE_PREFIX = "application/vnd.google-apps."
FIELDS = "id,name,mimeType,size,md5Checksum,resourceKey,capabilities(canDownload)"
EXPORTS = {
    GOOGLE_PREFIX + "document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    GOOGLE_PREFIX + "spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    GOOGLE_PREFIX + "presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
    GOOGLE_PREFIX + "drawing": ("application/pdf", ".pdf"),
}


def parse_source(source: str) -> tuple[str, str | None]:
    source = source.strip()
    key = None
    if "://" in source:
        url = urlparse(source)
        if url.scheme != "https" or url.hostname not in {"drive.google.com", "docs.google.com"}:
            raise ValueError("Expected a Google Drive/Docs HTTPS sharing URL or file ID")
        query = parse_qs(url.query)
        match = re.search(r"/(?:folders|d)/([\w-]+)(?:/|$)", url.path)
        source = match.group(1) if match else query.get("id", [""])[0]
        key = query.get("resourcekey", [None])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", source):
        raise ValueError("Invalid Drive file ID")
    if key is not None and not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise ValueError("Invalid Drive resource key")
    return source, key


def safe_name(name: str) -> str:
    name = re.sub(r'[\x00-\x1f\x7f/\\:<>"|?*]', "_", name).strip().rstrip(". ")
    # Bound UTF-8 length to leave room for collision suffixes and export extensions.
    name = name.encode("utf-8")[:180].decode("utf-8", errors="ignore")
    return name if name and name not in {".", ".."} else "unnamed"


class DriveClient:
    def __init__(self, secrets_dir: Path, *, auth_timeout: int = 120):
        creds = get_credentials(secrets_dir, extra_scopes=[DRIVE_READONLY], auth_timeout=auth_timeout)
        self.drive: Any = build("drive", "v3", credentials=creds)

    @staticmethod
    def _key(request: Any, file_id: str, key: str | None) -> Any:
        if key:
            request.headers["X-Goog-Drive-Resource-Keys"] = f"{file_id}/{key}"
        return request

    def metadata(self, file_id: str, key: str | None = None) -> dict[str, Any]:
        return _retry_transient(lambda: self._key(self.drive.files().get(
            fileId=file_id, fields=FIELDS, supportsAllDrives=True,
        ), file_id, key).execute())

    def children(self, file_id: str, key: str | None = None) -> list[dict[str, Any]]:
        items = []
        token = None
        while True:
            response = _retry_transient(lambda: self._key(self.drive.files().list(
                q=f"'{file_id}' in parents and trashed = false", fields=f"files({FIELDS}),nextPageToken,incompleteSearch",
                pageSize=1000, pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True,
            ), file_id, key).execute())
            if response.get("incompleteSearch"):
                raise RuntimeError("Drive returned an incomplete folder listing")
            items.extend(response.get("files", []))
            token = response.get("nextPageToken")
            if not token:
                return sorted(items, key=lambda item: (item["name"].casefold(), item["id"]))

    def download(self, file_id: str, output_dir: Path, *, resource_key: str | None = None,
                 export_format: str = "office", dry_run: bool = False) -> dict[str, Any]:
        root = output_dir.expanduser().absolute()
        plan: list[dict[str, Any]] = []
        directories: list[Path] = []
        used: dict[Path, set[str]] = {}

        def visit(meta: dict[str, Any], parent: Path, ancestors: set[str], key: str | None = None) -> None:
            mime = meta["mimeType"]
            export = EXPORTS.get(mime)
            if export and export_format == "pdf":
                export = ("application/pdf", ".pdf")
            name = safe_name(meta["name"]) + (export[1] if export else "")
            names = used.setdefault(parent, set())
            if name.casefold() in names:
                suffix = export[1] if export else Path(name).suffix
                stem = name[:-len(suffix)] if suffix else name
                name = f"{stem}__{meta['id']}{suffix}"
                while name.casefold() in names:
                    name = "_" + name
            names.add(name.casefold())
            path = parent / name
            key = meta.get("resourceKey") or key
            if mime == FOLDER:
                if meta["id"] in ancestors:
                    raise RuntimeError("Drive folder cycle detected")
                directories.append(path)
                for child in self.children(meta["id"], key):
                    visit(child, path, ancestors | {meta["id"]})
                return
            reason = None
            if mime.startswith(GOOGLE_PREFIX) and not export:
                reason = "Unsupported Google file type (shortcuts are not followed)"
            elif meta.get("capabilities", {}).get("canDownload") is False:
                reason = "Owner has disabled download"
            plan.append({"id": meta["id"], "name": meta["name"], "path": str(path),
                         "mime_type": mime, "export_mime": export[0] if export else None,
                         "size": meta.get("size"), "md5": meta.get("md5Checksum"),
                         "resource_key": key, "status": "skipped" if reason else "planned", "error": reason})

        visit(self.metadata(file_id, resource_key), root, set(), resource_key)
        # Check every existing ancestor; never traverse a local symlink or overwrite a file.
        directory_paths = {root, *directories}
        for path in [root] + directories + [Path(item["path"]) for item in plan]:
            for ancestor in [path, *path.parents]:
                if ancestor.is_symlink():
                    raise ValueError(f"Refusing symlink path: {ancestor}")
            if path in directory_paths:
                if path.exists() and not path.is_dir():
                    raise FileExistsError(f"Not a directory: {path}")
            elif path.exists():
                raise FileExistsError(f"Refusing to overwrite existing file: {path}")
        if not dry_run:
            root.mkdir(parents=True, exist_ok=True)
            for directory in directories:
                directory.mkdir(parents=True, exist_ok=True)
            for item in plan:
                if item["status"] == "skipped":
                    continue
                try:
                    self._download_file(item)
                    item["status"] = "downloaded"
                    item["bytes"] = Path(item["path"]).stat().st_size
                except Exception as exc:
                    item["status"] = "failed"
                    item["error"] = str(exc)
        return {"success": all(item["status"] not in {"failed", "skipped"} for item in plan),
                "dry_run": dry_run, "source_id": file_id, "output_dir": str(root),
                "directories": [str(path) for path in directories], "file_count": len(plan),
                "downloaded_count": sum(item["status"] == "downloaded" for item in plan),
                "total_bytes": sum(item.get("bytes", 0) for item in plan),
                "files": [{k: v for k, v in item.items() if k not in {"resource_key", "md5"}} for item in plan]}

    def _upload_file(self, path: Path, name: str, parent_id: str | None) -> dict[str, Any]:
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        metadata: dict[str, Any] = {"name": name}
        if parent_id:
            metadata["parents"] = [parent_id]
        media = MediaFileUpload(str(path), mimetype=mime, resumable=True)
        return _retry_transient(lambda: self.drive.files().create(
            body=metadata, media_body=media, fields="id,name,mimeType,size,webViewLink",
            supportsAllDrives=True,
        ).execute())

    def _create_folder(self, name: str, parent_id: str | None) -> str:
        metadata: dict[str, Any] = {"name": name, "mimeType": FOLDER}
        if parent_id:
            metadata["parents"] = [parent_id]
        created = _retry_transient(lambda: self.drive.files().create(
            body=metadata, fields="id", supportsAllDrives=True,
        ).execute())
        return str(created["id"])

    def upload(self, local_path: Path, *, name: str | None = None, folder_id: str | None = None,
               dry_run: bool = False) -> dict[str, Any]:
        root = local_path.expanduser().absolute()
        if not root.exists():
            raise FileNotFoundError(f"Upload source not found: {root}")

        # Build a plan of entries before any write.
        planned: list[dict[str, Any]] = []
        if root.is_dir():
            def walk(directory: Path, relative: str) -> None:
                for entry in sorted(directory.iterdir(), key=lambda p: p.name.casefold()):
                    if entry.name in {".DS_Store"}:
                        continue
                    child_rel = f"{relative}/{entry.name}" if relative else entry.name
                    planned.append({"path": entry, "name": entry.name, "relative": child_rel,
                                    "is_dir": entry.is_dir()})
                    if entry.is_dir():
                        walk(entry, child_rel)
            walk(root, "")
        else:
            planned.append({"path": root, "name": name or root.name, "relative": name or root.name,
                            "is_dir": False})

        if dry_run:
            return {"success": True, "dry_run": True, "source": str(root),
                    "file_count": sum(not item["is_dir"] for item in planned),
                    "folder_count": sum(item["is_dir"] for item in planned),
                    "files": [{"path": str(item["path"]), "name": item["name"]} for item in planned]}

        try:
            # Directory upload nests under a new folder named after the local directory.
            top_parent = folder_id
            if root.is_dir():
                top_parent = self._create_folder(name or root.name, folder_id)
            folder_ids: dict[str, str] = {} if top_parent is None else {"": top_parent}
            results: list[dict[str, Any]] = []
            for item in planned:
                parent_rel = item["relative"].rsplit("/", 1)[0] if "/" in item["relative"] else ""
                parent_id = folder_ids.get(parent_rel, folder_id)
                if item["is_dir"]:
                    new_id = self._create_folder(item["name"], parent_id)
                    folder_ids[item["relative"]] = new_id
                    results.append({"name": item["name"], "type": "folder", "id": new_id})
                else:
                    uploaded = self._upload_file(item["path"], item["name"], parent_id)
                    results.append({"name": uploaded.get("name", item["name"]), "type": "file",
                                    "id": uploaded.get("id"), "size": uploaded.get("size"),
                                    "link": uploaded.get("webViewLink")})
            # --share targets what was created: the top folder for a directory, the file itself otherwise.
            share_target = top_parent if root.is_dir() else (results[0]["id"] if results else None)
            return {"success": True, "dry_run": False, "source": str(root),
                    "folder_id": top_parent, "share_target_id": share_target,
                    "uploaded_count": len(results), "files": results}
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to upload '{root}'", exc)) from exc

    def share(self, file_id: str, email: str, *, role: str = "reader") -> dict[str, Any]:
        valid_roles = {"reader", "writer", "commenter"}
        if role not in valid_roles:
            raise ValueError("role must be one of: reader, writer, commenter")
        try:
            _retry_transient(lambda: self.drive.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": role, "emailAddress": email},
                sendNotificationEmail=True,
                supportsAllDrives=True,
            ).execute())
            link = _retry_transient(lambda: self.drive.files().get(
                fileId=file_id, fields="webViewLink", supportsAllDrives=True,
            ).execute())
            return {"success": True, "file_id": file_id, "link": link.get("webViewLink", "")}
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to share '{file_id}'", exc)) from exc

    def _download_file(self, item: dict[str, Any]) -> None:
        path = Path(item["path"])
        if item["export_mime"]:
            request = self.drive.files().export_media(fileId=item["id"], mimeType=item["export_mime"])
        else:
            request = self.drive.files().get_media(fileId=item["id"], supportsAllDrives=True)
        request = self._key(request, item["id"], item["resource_key"])
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".gdocs-download-", delete=False) as handle:
                temporary = Path(handle.name)
                downloader = MediaIoBaseDownload(handle, request, chunksize=8 * 1024 * 1024)
                done = False
                while not done:
                    _, done = downloader.next_chunk(num_retries=4)
                handle.flush()
                os.fsync(handle.fileno())
            if not item["export_mime"]:
                if item["size"] is not None and temporary.stat().st_size != int(item["size"]):
                    raise RuntimeError("Downloaded size does not match Drive metadata")
                if item["md5"]:
                    digest = hashlib.md5()
                    with temporary.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != item["md5"]:
                        raise RuntimeError("Downloaded checksum does not match Drive metadata")
            # Atomic publication without replacing an existing destination.
            os.link(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
