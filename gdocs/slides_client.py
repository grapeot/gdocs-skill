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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
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


def element_box(element: dict[str, Any]) -> dict[str, float]:
    """Rendered position and size in points (size scaled by the transform)."""
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


def summarize_page(index: int, page: dict[str, Any]) -> dict[str, Any]:
    notes_id, notes_text = notes_shape(page)
    return {
        "page": index,
        "object_id": page["objectId"],
        "elements": [
            {"object_id": e["objectId"], "kind": element_kind(e), "text": element_text(e), **element_box(e)}
            for e in page.get("pageElements", [])
        ],
        "notes_object_id": notes_id,
        "notes": notes_text,
    }


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
    if old_text.strip("\n"):
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
    """Absolute transform that places the element at x, y with rendered size w, h (points)."""
    size = element.get("size", {})
    width = size.get("width", {}).get("magnitude")
    height = size.get("height", {}).get("magnitude")
    if not width or not height:
        raise ValueError(f"Element {element['objectId']} has no intrinsic size; cannot move it")
    t = element.get("transform", {})
    current = element_box(element)
    w = float(op.get("w", current["w"]))
    h = float(op.get("h", current["h"]))
    if op.get("keep_aspect"):
        ratio = current["w"] / current["h"] if current["h"] else 1
        h = w / ratio
    return {"updatePageElementTransform": {
        "objectId": element["objectId"],
        "applyMode": "ABSOLUTE",
        "transform": {
            "scaleX": w * EMU_PER_PT / width,
            "scaleY": h * EMU_PER_PT / height,
            "shearX": t.get("shearX", 0),
            "shearY": t.get("shearY", 0),
            "translateX": float(op.get("x", current["x"])) * EMU_PER_PT,
            "translateY": float(op.get("y", current["y"])) * EMU_PER_PT,
            "unit": "EMU",
        },
    }}


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
    requests: list[dict[str, Any]] = []
    for key, ops in pages.items():
        index = int(key)
        if not 1 <= index <= len(slides):
            raise ValueError(f"Page {index} is out of range (deck has {len(slides)} pages)")
        page = slides[index - 1]
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
                object_id = str(op.get("id") or f"gd_{page_id}_t{n}")
                requests.append({"createShape": {"objectId": object_id, "shapeType": "TEXT_BOX",
                                                 "elementProperties": _box(op, page_id)}})
                requests.append({"insertText": {"objectId": object_id, "insertionIndex": 0, "text": str(op["text"])}})
                requests += _style_requests(object_id, op)
            else:
                object_id = str(op.get("id") or f"gd_{page_id}_i{n}")
                requests.append({"createImage": {"objectId": object_id, "url": image_url(str(op["path"])),
                                                 "elementProperties": _box(op, page_id)}})
    return requests


class SlidesClient:
    """Page-scoped Google Slides operations backed by the Slides and Drive APIs."""

    def __init__(self, secrets_dir: Path, *, auth_timeout: int = 120):
        creds = get_credentials(secrets_dir, extra_scopes=[DRIVE_READONLY], auth_timeout=auth_timeout)
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
        output_dir.mkdir(parents=True, exist_ok=True)
        pres = self.get(presentation_id)
        files = {"presentation.json": json.dumps(pres, ensure_ascii=False, indent=1).encode()}
        for fmt in EXPORTS:
            files[f"export.{fmt}"] = self.export(presentation_id, fmt)
        manifest = {"presentation_id": presentation_id, "title": pres.get("title"),
                    "revision_id": pres.get("revisionId"), "page_count": len(pres.get("slides", [])),
                    "files": {}}
        for name, data in files.items():
            (output_dir / name).write_bytes(data)
            manifest["files"][name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
        return {"success": True, "output_dir": str(output_dir), **manifest}

    def _upload_public_image(self, path: Path, uploaded: list[str]) -> str:
        """Upload an image and open it to anyone with the link, so Slides can fetch it once."""
        if not path.is_file():
            raise ValueError(f"Image not found: {path}")
        meta = _retry_transient(lambda: self.drive.files().create(
            body={"name": f"gdocs-slides-tmp-{path.name}"},
            media_body=MediaFileUpload(str(path), resumable=False),
            fields="id",
        ).execute())
        uploaded.append(meta["id"])
        _retry_transient(lambda: self.drive.permissions().create(
            fileId=meta["id"], body={"type": "anyone", "role": "reader"}, fields="id",
        ).execute())
        return f"https://drive.google.com/uc?export=download&id={meta['id']}"

    def apply(self, presentation_id: str, spec: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        pres = self.get(presentation_id)
        revision = spec.get("required_revision_id") or pres.get("revisionId")
        if dry_run:
            requests = build_requests(pres, spec, lambda path: f"<upload:{path}>")
            return {"dry_run": True, "revision_id": revision, "request_count": len(requests), "requests": requests}
        build_requests(pres, spec, lambda path: "<validate>")
        uploaded: list[str] = []
        try:
            requests = build_requests(pres, spec, lambda path: self._upload_public_image(Path(path), uploaded))
            body: dict[str, Any] = {"requests": requests}
            if revision:
                body["writeControl"] = {"requiredRevisionId": revision}
            result = self.slides.presentations().batchUpdate(presentationId=presentation_id, body=body).execute()
        finally:
            for file_id in uploaded:
                _retry_transient(lambda fid=file_id: self.drive.files().delete(fileId=fid).execute())
        return {"success": True, "request_count": len(requests), "previous_revision_id": revision,
                "revision_id": result.get("writeControl", {}).get("requiredRevisionId"),
                "temporary_uploads_deleted": len(uploaded)}
