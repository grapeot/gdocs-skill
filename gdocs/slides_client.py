# pyright: basic

from __future__ import annotations

"""Google Slides API client: page-scoped inspection, backup and edits.

Every edit is limited to the pages a spec names. The client reads the deck,
validates that each referenced element lives on its page, and sends one
batchUpdate guarded by the revision it read, so a concurrent edit by a
co-author makes the write fail instead of being silently overwritten.
"""

import hashlib
import io
import json
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from .auth import get_credentials
from .client import _retry_transient
from .drive_client import DRIVE_READONLY

EMU_PER_PT = 12700
EXPORTS = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
OPS = {"set_text", "move", "delete", "add_text", "add_image", "set_notes"}
PRESENTATIONS = "https://www.googleapis.com/auth/presentations"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif"}
MAX_IMAGE_BYTES = 50 * 1024 * 1024
OBJECT_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_:-]{4,49}")


def emu_to_pt(value: float) -> float:
    return round(value / EMU_PER_PT, 2)


def element_text(element: dict[str, Any]) -> str:
    runs = element.get("shape", {}).get("text", {}).get("textElements", [])
    return "".join(run.get("textRun", {}).get("content", "") for run in runs)


def element_kind(element: dict[str, Any]) -> str:
    for key in ("image", "table", "line", "video", "sheetsChart", "elementGroup", "wordArt"):
        if key in element:
            return key
    return str(element.get("shape", {}).get("shapeType", "unknown")).lower()


def is_rotated(element: dict[str, Any]) -> bool:
    """True for rotated, sheared or flipped elements, whose box cannot be read as size * scale."""
    t = element.get("transform", {})
    return bool(t.get("shearX") or t.get("shearY") or t.get("scaleX", 1) < 0 or t.get("scaleY", 1) < 0)


def element_box(element: dict[str, Any]) -> dict[str, float]:
    """Rendered position and size in points (size scaled by the transform).

    For rotated or flipped elements w/h are not the rendered size; callers see
    ``rotated: true`` in inspect output and ``move`` only translates them.
    """
    t = element.get("transform", {})
    size = element.get("size", {})
    width = size.get("width", {}).get("magnitude", 0) * t.get("scaleX", 1)
    height = size.get("height", {}).get("magnitude", 0) * t.get("scaleY", 1)
    return {
        "x": emu_to_pt(t.get("translateX", 0)),
        "y": emu_to_pt(t.get("translateY", 0)),
        "w": emu_to_pt(width),
        "h": emu_to_pt(height),
    }


def notes_shape(page: dict[str, Any]) -> tuple[str, str]:
    notes = page.get("slideProperties", {}).get("notesPage", {})
    shape_id = notes.get("notesProperties", {}).get("speakerNotesObjectId", "")
    for element in notes.get("pageElements", []):
        if element.get("objectId") == shape_id:
            return shape_id, element_text(element)
    return shape_id, ""


def _without_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_volatile(v) for k, v in value.items() if k != "contentUrl"}
    if isinstance(value, list):
        return [_without_volatile(v) for v in value]
    return value


def page_fingerprint(page: dict[str, Any]) -> str:
    """Hash of one page's elements and speaker notes, ignoring signed image URLs that change per fetch."""
    _, notes_text = notes_shape(page)
    payload = {"elements": _without_volatile(page.get("pageElements", [])), "notes": notes_text}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def summarize_page(index: int, page: dict[str, Any]) -> dict[str, Any]:
    notes_id, notes_text = notes_shape(page)
    elements = []
    for e in page.get("pageElements", []):
        item = {"object_id": e["objectId"], "kind": element_kind(e), "text": element_text(e), **element_box(e)}
        if is_rotated(e):
            item["rotated"] = True
        elements.append(item)
    return {
        "page": index,
        "object_id": page["objectId"],
        "fingerprint": page_fingerprint(page),
        "elements": elements,
        "notes_object_id": notes_id,
        "notes": notes_text,
    }


def all_object_ids(value: Any, found: set[str] | None = None) -> set[str]:
    found = set() if found is None else found
    if isinstance(value, dict):
        if isinstance(value.get("objectId"), str):
            found.add(value["objectId"])
        for v in value.values():
            all_object_ids(v, found)
    elif isinstance(value, list):
        for v in value:
            all_object_ids(v, found)
    return found


def _rgb(color: str) -> dict[str, Any]:
    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Color must be #RRGGBB, got {color!r}")
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return {"opaqueColor": {"rgbColor": {"red": r, "green": g, "blue": b}}}


def _style_requests(object_id: str, op: dict[str, Any]) -> list[dict[str, Any]]:
    style: dict[str, Any] = {}
    fields = []
    if "font_size" in op:
        style["fontSize"] = {"magnitude": float(op["font_size"]), "unit": "PT"}
        fields.append("fontSize")
    if "bold" in op:
        style["bold"] = bool(op["bold"])
        fields.append("bold")
    if "color" in op:
        style["foregroundColor"] = _rgb(str(op["color"]))
        fields.append("foregroundColor")
    if "font_family" in op:
        style["fontFamily"] = str(op["font_family"])
        fields.append("fontFamily")
    requests: list[dict[str, Any]] = []
    if fields:
        requests.append({"updateTextStyle": {
            "objectId": object_id, "textRange": {"type": "ALL"}, "style": style, "fields": ",".join(fields),
        }})
    if "align" in op:
        requests.append({"updateParagraphStyle": {
            "objectId": object_id, "textRange": {"type": "ALL"},
            "style": {"alignment": str(op["align"]).upper()}, "fields": "alignment",
        }})
    return requests


def _replace_text(object_id: str, old_text: str, new_text: str) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    if old_text.strip("\n") or old_text.count("\n") > 1:
        requests.append({"deleteText": {"objectId": object_id, "textRange": {"type": "ALL"}}})
    if new_text:
        requests.append({"insertText": {"objectId": object_id, "insertionIndex": 0, "text": new_text}})
    return requests


def _box(op: dict[str, Any], page_id: str) -> dict[str, Any]:
    for key in ("x", "y", "w", "h"):
        if key not in op:
            raise ValueError(f"{op['op']} needs x, y, w, h in points")
    return {
        "pageObjectId": page_id,
        "size": {"width": {"magnitude": float(op["w"]), "unit": "PT"},
                 "height": {"magnitude": float(op["h"]), "unit": "PT"}},
        "transform": {"scaleX": 1, "scaleY": 1, "translateX": float(op["x"]),
                      "translateY": float(op["y"]), "unit": "PT"},
    }


def _move(element: dict[str, Any], op: dict[str, Any]) -> dict[str, Any]:
    """Absolute transform that places the element at x, y with rendered size w, h (points).

    Rotated, sheared or flipped elements keep their matrix and can only be
    translated; resizing them from size * scale would distort them.
    """
    t = element.get("transform", {})
    current = element_box(element)
    resize = "w" in op or "h" in op
    transform = {
        "scaleX": t.get("scaleX", 1), "scaleY": t.get("scaleY", 1),
        "shearX": t.get("shearX", 0), "shearY": t.get("shearY", 0),
        "translateX": float(op.get("x", current["x"])) * EMU_PER_PT,
        "translateY": float(op.get("y", current["y"])) * EMU_PER_PT,
        "unit": "EMU",
    }
    if resize:
        if is_rotated(element):
            raise ValueError(f"Element {element['objectId']} is rotated or flipped; move it with x/y only")
        size = element.get("size", {})
        width = size.get("width", {}).get("magnitude")
        height = size.get("height", {}).get("magnitude")
        if not width or not height:
            raise ValueError(f"Element {element['objectId']} has no intrinsic width and height; cannot resize it")
        w = float(op["w"]) if "w" in op else None
        h = float(op["h"]) if "h" in op else None
        if op.get("keep_aspect"):
            if not current["w"] or not current["h"]:
                raise ValueError(f"Element {element['objectId']} has a zero side; keep_aspect is undefined")
            ratio = current["w"] / current["h"]
            if w is not None:
                h = w / ratio
            else:
                w = h * ratio
        w = current["w"] if w is None else w
        h = current["h"] if h is None else h
        transform["scaleX"] = w * EMU_PER_PT / width
        transform["scaleY"] = h * EMU_PER_PT / height
    return {"updatePageElementTransform": {
        "objectId": element["objectId"], "applyMode": "ABSOLUTE", "transform": transform,
    }}


def _check_image(path: str) -> str:
    file = Path(path)
    if not file.is_file():
        raise ValueError(f"Image not found: {path}")
    if file.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError(f"Image must be PNG, JPEG or GIF: {path}")
    if file.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError(f"Image is larger than 50 MB: {path}")
    return path


def _new_id(op: dict[str, Any], prefix: str, taken: set[str]) -> str:
    object_id = str(op["id"]) if op.get("id") else f"{prefix}{uuid.uuid4().hex[:12]}"
    if not OBJECT_ID.fullmatch(object_id):
        raise ValueError(f"Object id {object_id!r} must be 5-50 characters of letters, digits, _ - :")
    if object_id in taken:
        raise ValueError(f"Object id {object_id!r} already exists in the deck or the spec")
    taken.add(object_id)
    return object_id


def build_requests(
    presentation: dict[str, Any],
    spec: dict[str, Any],
    image_url: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Translate a page-scoped spec into batchUpdate requests.

    Raises ValueError before any request is built if the spec names a page out
    of range, an unknown op, or an element that does not live on its page.
    """
    slides = presentation.get("slides", [])
    pages = spec.get("pages")
    if not isinstance(pages, dict) or not pages:
        raise ValueError("Spec needs a non-empty 'pages' object keyed by 1-based page number")
    fingerprints = spec.get("page_fingerprints") or {}
    taken = all_object_ids(presentation)
    requests: list[dict[str, Any]] = []
    for key, ops in pages.items():
        if not str(key).isdigit():
            raise ValueError(f"Page key {key!r} must be a 1-based page number")
        index = int(key)
        if not 1 <= index <= len(slides):
            raise ValueError(f"Page {index} is out of range (deck has {len(slides)} pages)")
        if not isinstance(ops, list):
            raise ValueError(f"Page {index}: ops must be a list")
        page = slides[index - 1]
        expected = fingerprints.get(str(key))
        if expected and expected != page_fingerprint(page):
            raise ValueError(f"Page {index} changed since it was inspected; re-run inspect and update the spec")
        page_id = page["objectId"]
        on_page = {e["objectId"]: e for e in page.get("pageElements", [])}
        for n, op in enumerate(ops):
            kind = op.get("op")
            if kind not in OPS:
                raise ValueError(f"Page {index} op {n}: unknown op {kind!r}")
            if kind in {"set_text", "move", "delete"}:
                element = on_page.get(str(op.get("element")))
                if element is None:
                    raise ValueError(f"Page {index} op {n}: element {op.get('element')!r} is not on this page")
                if kind == "set_text":
                    if "shape" not in element:
                        raise ValueError(f"Page {index} op {n}: element {element['objectId']} holds no text")
                    requests += _replace_text(element["objectId"], element_text(element), str(op["text"]))
                    requests += _style_requests(element["objectId"], op)
                elif kind == "move":
                    requests.append(_move(element, op))
                else:
                    requests.append({"deleteObject": {"objectId": element["objectId"]}})
            elif kind == "set_notes":
                shape_id, old = notes_shape(page)
                if not shape_id:
                    raise ValueError(f"Page {index} has no speaker notes shape")
                requests += _replace_text(shape_id, old, str(op["text"]))
            elif kind == "add_text":
                object_id = _new_id(op, "gdt", taken)
                requests.append({"createShape": {"objectId": object_id, "shapeType": "TEXT_BOX",
                                                 "elementProperties": _box(op, page_id)}})
                requests.append({"insertText": {"objectId": object_id, "insertionIndex": 0, "text": str(op["text"])}})
                requests += _style_requests(object_id, op)
            else:
                object_id = _new_id(op, "gdi", taken)
                requests.append({"createImage": {"objectId": object_id, "url": image_url(str(op["path"])),
                                                 "elementProperties": _box(op, page_id)}})
    return requests


class SlidesClient:
    """Page-scoped Google Slides operations backed by the Slides and Drive APIs."""

    def __init__(self, secrets_dir: Path, *, auth_timeout: int = 120, presentations_scope: bool = False):
        scopes = [DRIVE_READONLY, PRESENTATIONS] if presentations_scope else [DRIVE_READONLY]
        creds = get_credentials(secrets_dir, extra_scopes=scopes, auth_timeout=auth_timeout)
        self.slides: Any = build("slides", "v1", credentials=creds)
        self.drive: Any = build("drive", "v3", credentials=creds)

    def get(self, presentation_id: str) -> dict[str, Any]:
        return _retry_transient(lambda: self.slides.presentations().get(presentationId=presentation_id).execute())

    def inspect(self, presentation_id: str, pages: list[int] | None = None) -> dict[str, Any]:
        pres = self.get(presentation_id)
        slides = pres.get("slides", [])
        wanted = pages or list(range(1, len(slides) + 1))
        for index in wanted:
            if not 1 <= index <= len(slides):
                raise ValueError(f"Page {index} is out of range (deck has {len(slides)} pages)")
        return {
            "presentation_id": presentation_id,
            "title": pres.get("title"),
            "revision_id": pres.get("revisionId"),
            "page_count": len(slides),
            "page_size_pt": {k: emu_to_pt(v["magnitude"]) for k, v in pres.get("pageSize", {}).items()},
            "pages": [summarize_page(i, slides[i - 1]) for i in wanted],
        }

    def export(self, presentation_id: str, fmt: str) -> bytes:
        buf = io.BytesIO()
        request = self.drive.files().export_media(fileId=presentation_id, mimeType=EXPORTS[fmt])
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    def backup(self, presentation_id: str, output_dir: Path) -> dict[str, Any]:
        """Save the full API JSON plus PDF and PPTX exports, with hashes and the revision."""
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ValueError(f"Backup directory is not empty, refusing to overwrite: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
        pres = self.get(presentation_id)
        files = {"presentation.json": json.dumps(pres, ensure_ascii=False, indent=1).encode()}
        for fmt in EXPORTS:
            files[f"export.{fmt}"] = self.export(presentation_id, fmt)
        revision_after = self.get(presentation_id).get("revisionId")
        manifest = {"presentation_id": presentation_id, "title": pres.get("title"),
                    "revision_id": pres.get("revisionId"), "page_count": len(pres.get("slides", [])),
                    "revision_changed_during_backup": revision_after != pres.get("revisionId"),
                    "files": {}}
        for name, data in files.items():
            (output_dir / name).write_bytes(data)
            manifest["files"][name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
        return {"success": True, "output_dir": str(output_dir), **manifest}

    def _upload_public_image(self, path: Path, uploaded: list[dict[str, str]]) -> str:
        """Upload an image and open it to anyone with the link, so Slides can fetch it once.

        Not retried: a retried create after a server-side success would leave an untracked copy.
        """
        meta = self.drive.files().create(
            body={"name": f"gdocs-slides-tmp-{uuid.uuid4().hex[:8]}{path.suffix}"},
            media_body=MediaFileUpload(str(path), resumable=False),
            fields="id",
        ).execute()
        record = {"file_id": meta["id"]}
        uploaded.append(record)
        perm = self.drive.permissions().create(
            fileId=meta["id"], body={"type": "anyone", "role": "reader"}, fields="id",
        ).execute()
        record["permission_id"] = perm.get("id", "")
        return f"https://drive.google.com/uc?export=download&id={meta['id']}"

    def _cleanup(self, uploaded: list[dict[str, str]]) -> list[str]:
        """Delete every temporary upload; fall back to revoking the public link. Returns ids left behind."""
        left: list[str] = []
        for record in uploaded:
            file_id = record["file_id"]
            try:
                _retry_transient(lambda fid=file_id: self.drive.files().delete(fileId=fid).execute())
                continue
            except Exception:  # noqa: BLE001 - keep cleaning the rest
                pass
            try:
                if record.get("permission_id"):
                    _retry_transient(lambda fid=file_id, pid=record["permission_id"]: self.drive.permissions().delete(
                        fileId=fid, permissionId=pid).execute())
            except Exception:  # noqa: BLE001
                pass
            left.append(file_id)
        return left

    def apply(self, presentation_id: str, spec: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        pres = self.get(presentation_id)
        revision = spec.get("required_revision_id") or pres.get("revisionId")
        warnings = []
        if not spec.get("required_revision_id") and not spec.get("page_fingerprints"):
            warnings.append("No page_fingerprints or required_revision_id in the spec: edits made between your "
                            "inspect and this apply are not detected, only edits during the apply itself.")
        if dry_run:
            requests = build_requests(pres, spec, lambda path: f"<upload:{_check_image(path)}>")
            return {"dry_run": True, "revision_id": revision, "request_count": len(requests),
                    "warnings": warnings, "requests": requests}
        if not revision:
            raise ValueError("The deck returned no revisionId (no edit access?); refusing an unguarded write")
        requests = build_requests(pres, spec, lambda path: _check_image(path))
        if not requests:
            return {"success": True, "request_count": 0, "revision_id": revision, "warnings": warnings}
        uploaded: list[dict[str, str]] = []
        left: list[str] = []
        try:
            requests = build_requests(pres, spec, lambda path: self._upload_public_image(Path(path), uploaded))
            body = {"requests": requests, "writeControl": {"requiredRevisionId": revision}}
            try:
                result = self.slides.presentations().batchUpdate(presentationId=presentation_id, body=body).execute()
            except HttpError as exc:
                if getattr(exc, "status_code", None) in (403, 404):
                    raise RuntimeError(
                        "Slides refused the write. If this deck was not created by this app, the drive.file scope "
                        "cannot edit it: re-run with --presentations-scope (one-time reauthorization). "
                        f"Original error: {exc}") from exc
                raise
        except BaseException as exc:
            left = self._cleanup(uploaded)
            if left:
                # Same effect as BaseException.add_note (3.11+), kept compatible with 3.10.
                exc.__notes__ = [*getattr(exc, "__notes__", []),
                                 f"Temporary Drive uploads not deleted (public link revoked if possible): {left}"]
            raise
        left = self._cleanup(uploaded)
        return {"success": True, "request_count": len(requests), "previous_revision_id": revision,
                "revision_id": result.get("writeControl", {}).get("requiredRevisionId"),
                "temporary_uploads_deleted": len(uploaded) - len(left),
                "temporary_uploads_left_behind": left, "warnings": warnings}
