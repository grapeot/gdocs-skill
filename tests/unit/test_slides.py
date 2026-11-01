# pyright: basic

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from gdocs.__main__ import DEFAULT_SECRETS_DIR, main
from gdocs.slides_client import EMU_PER_PT, SlidesClient, build_requests, summarize_page


def text_shape(object_id, text, x=0, y=0, w=100, h=20):
    return {
        "objectId": object_id,
        "size": {"width": {"magnitude": w * EMU_PER_PT}, "height": {"magnitude": h * EMU_PER_PT}},
        "transform": {"scaleX": 1, "scaleY": 1, "translateX": x * EMU_PER_PT, "translateY": y * EMU_PER_PT},
        "shape": {"shapeType": "TEXT_BOX", "text": {"textElements": [{"textRun": {"content": text}}] if text else []}},
    }


def image(object_id, x=10, y=10, w=200, h=100):
    return {
        "objectId": object_id,
        "size": {"width": {"magnitude": 45000}, "height": {"magnitude": 22500}},
        "transform": {"scaleX": w * EMU_PER_PT / 45000, "scaleY": h * EMU_PER_PT / 22500,
                      "translateX": x * EMU_PER_PT, "translateY": y * EMU_PER_PT},
        "image": {},
    }


def page(object_id, elements, notes_text=""):
    notes_id = f"{object_id}:notes"
    return {
        "objectId": object_id,
        "pageElements": elements,
        "slideProperties": {"notesPage": {
            "notesProperties": {"speakerNotesObjectId": notes_id},
            "pageElements": [text_shape(notes_id, notes_text)],
        }},
    }


def deck():
    return {
        "revisionId": "rev-1",
        "title": "Deck",
        "pageSize": {"width": {"magnitude": 720 * EMU_PER_PT}, "height": {"magnitude": 405 * EMU_PER_PT}},
        "slides": [
            page("p1", [text_shape("p1_title", "Intro\n")], "old notes\n"),
            page("p2", [text_shape("p2_cap", "Caption\n", 50, 300), image("p2_img")], ""),
        ],
    }


def test_summarize_page_reports_points_text_and_notes():
    summary = summarize_page(2, deck()["slides"][1])
    assert summary["page"] == 2
    assert summary["elements"][0] == {"object_id": "p2_cap", "kind": "text_box", "text": "Caption\n",
                                      "x": 50.0, "y": 300.0, "w": 100.0, "h": 20.0}
    assert summary["elements"][1]["kind"] == "image"
    assert summary["elements"][1]["w"] == 200.0
    assert summary["notes_object_id"] == "p2:notes"


def test_set_text_replaces_and_styles():
    reqs = build_requests(deck(), {"pages": {"2": [
        {"op": "set_text", "element": "p2_cap", "text": "New", "font_size": 12, "color": "#ff0000"},
    ]}}, lambda p: p)
    assert reqs[0] == {"deleteText": {"objectId": "p2_cap", "textRange": {"type": "ALL"}}}
    assert reqs[1]["insertText"]["text"] == "New"
    style = reqs[2]["updateTextStyle"]
    assert style["fields"] == "fontSize,foregroundColor"
    assert style["style"]["foregroundColor"]["opaqueColor"]["rgbColor"]["red"] == 1.0


def test_set_notes_skips_delete_when_notes_empty():
    reqs = build_requests(deck(), {"pages": {"2": [{"op": "set_notes", "text": "Hello"}]}}, lambda p: p)
    assert reqs == [{"insertText": {"objectId": "p2:notes", "insertionIndex": 0, "text": "Hello"}}]
    reqs = build_requests(deck(), {"pages": {"1": [{"op": "set_notes", "text": "Hi"}]}}, lambda p: p)
    assert list(reqs[0]) == ["deleteText"]


def test_move_computes_absolute_transform_in_emu():
    reqs = build_requests(deck(), {"pages": {"2": [{"op": "move", "element": "p2_img", "x": 20, "y": 40, "w": 100}]}},
                          lambda p: p)
    t = reqs[0]["updatePageElementTransform"]["transform"]
    assert t["translateX"] == 20 * EMU_PER_PT and t["translateY"] == 40 * EMU_PER_PT
    assert t["scaleX"] == pytest.approx(100 * EMU_PER_PT / 45000)
    assert t["scaleY"] == pytest.approx(100 * EMU_PER_PT / 22500)  # height unchanged


def test_move_keep_aspect_scales_height():
    reqs = build_requests(deck(), {"pages": {"2": [
        {"op": "move", "element": "p2_img", "w": 100, "keep_aspect": True}]}}, lambda p: p)
    t = reqs[0]["updatePageElementTransform"]["transform"]
    assert t["scaleY"] * 22500 / EMU_PER_PT == pytest.approx(50)


def test_add_text_and_image_use_page_and_points():
    reqs = build_requests(deck(), {"pages": {"2": [
        {"op": "add_text", "id": "take1", "text": "Hi", "x": 1, "y": 2, "w": 3, "h": 4, "bold": True, "align": "center"},
        {"op": "add_image", "id": "chart1", "path": "chart.png", "x": 5, "y": 6, "w": 7, "h": 8},
    ]}}, lambda p: f"https://x/{p}")
    shape = reqs[0]["createShape"]
    assert shape["objectId"] == "take1" and shape["elementProperties"]["pageObjectId"] == "p2"
    assert shape["elementProperties"]["transform"]["translateX"] == 1.0
    assert reqs[2]["updateTextStyle"]["fields"] == "bold"
    assert reqs[3]["updateParagraphStyle"]["style"]["alignment"] == "CENTER"
    assert reqs[4]["createImage"]["url"] == "https://x/chart.png"


@pytest.mark.parametrize("spec,message", [
    ({"pages": {"3": []}}, "out of range"),
    ({"pages": {"1": [{"op": "set_text", "element": "p2_cap", "text": "x"}]}}, "not on this page"),
    ({"pages": {"1": [{"op": "explode"}]}}, "unknown op"),
    ({"pages": {}}, "non-empty"),
    ({"pages": {"1": [{"op": "add_text", "text": "x", "x": 1}]}}, "x, y, w, h"),
])
def test_invalid_specs_fail_before_any_request(spec, message):
    with pytest.raises(ValueError, match=message):
        build_requests(deck(), spec, lambda p: p)


def client():
    c = SlidesClient.__new__(SlidesClient)
    c.slides = MagicMock()
    c.drive = MagicMock()
    c.slides.presentations.return_value.get.return_value.execute.return_value = deck()
    return c


def test_apply_sends_one_guarded_batch():
    c = client()
    batch = c.slides.presentations.return_value.batchUpdate
    batch.return_value.execute.return_value = {"writeControl": {"requiredRevisionId": "rev-2"}}
    result = c.apply("deck", {"pages": {"1": [{"op": "set_notes", "text": "x"}]}})
    body = batch.call_args.kwargs["body"]
    assert body["writeControl"] == {"requiredRevisionId": "rev-1"}
    assert result["revision_id"] == "rev-2" and result["previous_revision_id"] == "rev-1"


def test_apply_dry_run_never_writes_or_uploads(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    c = client()
    result = c.apply("deck", {"pages": {"2": [{"op": "add_image", "path": str(img), "x": 1, "y": 1, "w": 1, "h": 1}]}},
                     dry_run=True)
    assert result["dry_run"] and result["requests"][0]["createImage"]["url"] == f"<upload:{img}>"
    assert result["warnings"]
    c.slides.presentations.return_value.batchUpdate.assert_not_called()
    c.drive.files.return_value.create.assert_not_called()


def test_apply_invalid_spec_uploads_nothing(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    c = client()
    spec = {"pages": {"2": [{"op": "add_image", "path": str(img), "x": 1, "y": 1, "w": 1, "h": 1},
                            {"op": "delete", "element": "p1_title"}]}}
    with pytest.raises(ValueError):
        c.apply("deck", spec)
    c.drive.files.return_value.create.assert_not_called()


def test_apply_deletes_temporary_uploads_even_when_batch_fails(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    c = client()
    c.drive.files.return_value.create.return_value.execute.return_value = {"id": "tmp1"}
    c.slides.presentations.return_value.batchUpdate.return_value.execute.side_effect = RuntimeError("conflict")
    with pytest.raises(RuntimeError):
        c.apply("deck", {"pages": {"2": [{"op": "add_image", "path": str(img), "x": 1, "y": 1, "w": 1, "h": 1}]}})
    perm = c.drive.permissions.return_value.create.call_args.kwargs
    assert perm["body"] == {"type": "anyone", "role": "reader"}
    c.drive.files.return_value.delete.assert_called_once_with(fileId="tmp1")


def test_backup_writes_json_exports_and_manifest(tmp_path):
    c = client()
    c.export = MagicMock(side_effect=lambda pid, fmt: f"{fmt}-bytes".encode())
    result = c.backup("deck", tmp_path / "b")
    assert result["revision_id"] == "rev-1" and result["page_count"] == 2
    assert (tmp_path / "b" / "export.pdf").read_bytes() == b"pdf-bytes"
    manifest = json.loads((tmp_path / "b" / "manifest.json").read_text())
    assert set(manifest["files"]) == {"presentation.json", "export.pdf", "export.pptx"}


def test_cli_inspect_parses_url_and_pages(capsys):
    with patch("gdocs.__main__.SlidesClient") as cls:
        cls.return_value.inspect.return_value = {"pages": []}
        code = main(["slides", "inspect", "https://docs.google.com/presentation/d/abc123/edit", "--page", "2",
                     "--page", "3"])
    assert code == 0
    cls.assert_called_once_with(DEFAULT_SECRETS_DIR, auth_timeout=120)
    cls.return_value.inspect.assert_called_once_with("abc123", [2, 3])


def test_cli_apply_reads_spec(tmp_path, capsys):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"pages": {"1": []}}))
    with patch("gdocs.__main__.SlidesClient") as cls:
        cls.return_value.apply.return_value = {"dry_run": True}
        code = main(["slides", "apply", "abc123", "--spec", str(spec), "--dry-run"])
    assert code == 0
    cls.return_value.apply.assert_called_once_with("abc123", {"pages": {"1": []}}, dry_run=True)


def rotated_image(object_id="p2_rot"):
    e = image(object_id)
    e["transform"]["shearX"] = 0.5
    return e


def test_rotated_element_can_translate_but_not_resize():
    d = deck()
    d["slides"][1]["pageElements"].append(rotated_image())
    assert summarize_page(2, d["slides"][1])["elements"][2]["rotated"] is True
    reqs = build_requests(d, {"pages": {"2": [{"op": "move", "element": "p2_rot", "x": 5}]}}, lambda p: p)
    t = reqs[0]["updatePageElementTransform"]["transform"]
    assert t["shearX"] == 0.5 and t["translateX"] == 5 * EMU_PER_PT
    with pytest.raises(ValueError, match="rotated"):
        build_requests(d, {"pages": {"2": [{"op": "move", "element": "p2_rot", "w": 50}]}}, lambda p: p)


def test_keep_aspect_from_height_only():
    reqs = build_requests(deck(), {"pages": {"2": [
        {"op": "move", "element": "p2_img", "h": 50, "keep_aspect": True}]}}, lambda p: p)
    t = reqs[0]["updatePageElementTransform"]["transform"]
    assert t["scaleX"] * 45000 / EMU_PER_PT == pytest.approx(100)


def test_translate_works_without_intrinsic_size():
    d = deck()
    line = {"objectId": "p2_line", "transform": {"scaleX": 1, "scaleY": 1}, "line": {}}
    d["slides"][1]["pageElements"].append(line)
    reqs = build_requests(d, {"pages": {"2": [{"op": "move", "element": "p2_line", "y": 9}]}}, lambda p: p)
    assert reqs[0]["updatePageElementTransform"]["transform"]["translateY"] == 9 * EMU_PER_PT


def test_page_fingerprint_detects_changes_on_that_page_only():
    d = deck()
    fp = summarize_page(2, d["slides"][1])["fingerprint"]
    spec = {"page_fingerprints": {"2": fp}, "pages": {"2": [{"op": "set_notes", "text": "x"}]}}
    assert build_requests(d, spec, lambda p: p)
    d["slides"][0]["pageElements"][0]["shape"]["text"]["textElements"][0]["textRun"]["content"] = "Other page edit"
    assert build_requests(d, spec, lambda p: p)
    d["slides"][1]["pageElements"][0]["shape"]["text"]["textElements"][0]["textRun"]["content"] = "Edited"
    with pytest.raises(ValueError, match="changed since it was inspected"):
        build_requests(d, spec, lambda p: p)


def test_fingerprint_ignores_signed_image_urls():
    d = deck()
    d["slides"][1]["pageElements"][1]["image"] = {"contentUrl": "https://signed/1"}
    first = summarize_page(2, d["slides"][1])["fingerprint"]
    d["slides"][1]["pageElements"][1]["image"] = {"contentUrl": "https://signed/2"}
    assert summarize_page(2, d["slides"][1])["fingerprint"] == first


@pytest.mark.parametrize("ops,message", [
    ([{"op": "add_text", "id": "p2_cap", "text": "x", "x": 1, "y": 1, "w": 1, "h": 1}], "already exists"),
    ([{"op": "add_text", "id": "dup01", "text": "x", "x": 1, "y": 1, "w": 1, "h": 1},
      {"op": "add_text", "id": "dup01", "text": "y", "x": 1, "y": 1, "w": 1, "h": 1}], "already exists"),
    ([{"op": "add_text", "id": "ab", "text": "x", "x": 1, "y": 1, "w": 1, "h": 1}], "5-50"),
    ([{"op": "set_text", "element": "p2_img", "text": "x"}], "holds no text"),
])
def test_id_and_target_validation(ops, message):
    with pytest.raises(ValueError, match=message):
        build_requests(deck(), {"pages": {"2": ops}}, lambda p: p)


def test_generated_ids_are_unique_and_valid():
    reqs = build_requests(deck(), {"pages": {"2": [
        {"op": "add_text", "text": "a", "x": 1, "y": 1, "w": 1, "h": 1},
        {"op": "add_text", "text": "b", "x": 1, "y": 1, "w": 1, "h": 1}]}}, lambda p: p)
    ids = [r["createShape"]["objectId"] for r in reqs if "createShape" in r]
    assert len(set(ids)) == 2 and all(5 <= len(i) <= 50 for i in ids)


@pytest.mark.parametrize("pages,message", [({"first": []}, "page number"), ({"1": {"op": "x"}}, "must be a list")])
def test_bad_page_keys_and_ops(pages, message):
    with pytest.raises(ValueError, match=message):
        build_requests(deck(), {"pages": pages}, lambda p: p)


def test_set_text_clears_newline_only_text():
    d = deck()
    d["slides"][1]["pageElements"][0]["shape"]["text"]["textElements"][0]["textRun"]["content"] = "\n\n"
    reqs = build_requests(d, {"pages": {"2": [{"op": "set_text", "element": "p2_cap", "text": "x"}]}}, lambda p: p)
    assert "deleteText" in reqs[0]


def test_empty_spec_sends_nothing():
    c = client()
    result = c.apply("deck", {"pages": {"1": []}})
    assert result["request_count"] == 0
    c.slides.presentations.return_value.batchUpdate.assert_not_called()


def test_missing_revision_fails_closed():
    c = client()
    d = deck()
    d.pop("revisionId")
    c.slides.presentations.return_value.get.return_value.execute.return_value = d
    with pytest.raises(ValueError, match="no revisionId"):
        c.apply("deck", {"pages": {"1": [{"op": "set_notes", "text": "x"}]}})


def test_second_bad_image_uploads_nothing(tmp_path):
    good = tmp_path / "a.png"
    good.write_bytes(b"png")
    c = client()
    spec = {"pages": {"2": [{"op": "add_image", "path": str(good), "x": 1, "y": 1, "w": 1, "h": 1},
                            {"op": "add_image", "path": str(tmp_path / "missing.png"), "x": 1, "y": 1, "w": 1, "h": 1}]}}
    with pytest.raises(ValueError, match="Image not found"):
        c.apply("deck", spec)
    c.drive.files.return_value.create.assert_not_called()


def test_cleanup_continues_after_delete_failure_and_keeps_original_error(tmp_path):
    imgs = []
    for name in ("a.png", "b.png"):
        img = tmp_path / name
        img.write_bytes(b"png")
        imgs.append({"op": "add_image", "path": str(img), "x": 1, "y": 1, "w": 1, "h": 1})
    c = client()
    c.drive.files.return_value.create.return_value.execute.side_effect = [{"id": "f1"}, {"id": "f2"}]
    c.drive.permissions.return_value.create.return_value.execute.return_value = {"id": "perm"}
    c.drive.files.return_value.delete.return_value.execute.side_effect = [RuntimeError("net"), None]
    c.slides.presentations.return_value.batchUpdate.return_value.execute.side_effect = RuntimeError("conflict")
    with pytest.raises(RuntimeError, match="conflict") as info:
        c.apply("deck", {"pages": {"2": imgs}})
    assert "['f1']" in "".join(getattr(info.value, "__notes__", []))
    deleted = [call.kwargs["fileId"] for call in c.drive.files.return_value.delete.call_args_list]
    assert deleted[-1] == "f2"
    c.drive.permissions.return_value.delete.assert_called_with(fileId="f1", permissionId="perm")


def test_permission_failure_still_deletes_upload(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    c = client()
    c.drive.files.return_value.create.return_value.execute.return_value = {"id": "f1"}
    c.drive.permissions.return_value.create.return_value.execute.side_effect = RuntimeError("sharing disabled")
    with pytest.raises(RuntimeError, match="sharing disabled"):
        c.apply("deck", {"pages": {"2": [{"op": "add_image", "path": str(img), "x": 1, "y": 1, "w": 1, "h": 1}]}})
    c.drive.files.return_value.delete.assert_called_once_with(fileId="f1")


def test_backup_refuses_non_empty_directory(tmp_path):
    (tmp_path / "old.txt").write_text("x")
    with pytest.raises(ValueError, match="not empty"):
        client().backup("deck", tmp_path)


def test_cli_rejects_duplicate_page_keys(tmp_path, capsys):
    spec = tmp_path / "spec.json"
    spec.write_text('{"pages": {"1": [], "1": []}}')
    with patch("gdocs.__main__.SlidesClient"):
        assert main(["slides", "apply", "abc123", "--spec", str(spec)]) == 1


def test_cli_presentations_scope_flag(tmp_path, capsys):
    spec = tmp_path / "spec.json"
    spec.write_text('{"pages": {"1": []}}')
    with patch("gdocs.__main__.SlidesClient") as cls:
        cls.return_value.apply.return_value = {}
        main(["slides", "apply", "abc123", "--spec", str(spec), "--presentations-scope"])
    cls.assert_called_once_with(DEFAULT_SECRETS_DIR, auth_timeout=120, presentations_scope=True)
