# pyright: basic

from __future__ import annotations

import pytest

from gdocs.frontmatter import FrontMatter, parse, serialize


def test_parse_no_frontmatter():
    text = "# Hello\n\nBody text."
    fm = parse(text)
    assert fm.data == {}
    assert fm.body == text


def test_parse_empty_frontmatter():
    text = "---\n---\n\n# Hello\n"
    fm = parse(text)
    assert fm.data == {}
    assert fm.body == "# Hello\n"


def test_parse_basic_frontmatter():
    text = (
        "---\n"
        "gdoc_id: 1abc\n"
        "gdoc_tab_id: t.xyz\n"
        "gdoc_last_synced: 2026-04-23T12:00:00Z\n"
        "---\n"
        "\n"
        "# Title\n"
        "\n"
        "Body.\n"
    )
    fm = parse(text)
    assert fm.data["gdoc_id"] == "1abc"
    assert fm.data["gdoc_tab_id"] == "t.xyz"
    assert fm.body.startswith("# Title")


def test_parse_frontmatter_without_trailing_blank():
    text = "---\ngdoc_id: 1abc\n---\nBody immediately.\n"
    fm = parse(text)
    assert fm.data["gdoc_id"] == "1abc"
    assert fm.body == "Body immediately.\n"


def test_parse_unterminated_frontmatter_treated_as_body():
    text = "---\ngdoc_id: 1abc\n# no closing delimiter\n"
    fm = parse(text)
    assert fm.data == {}
    assert fm.body == text


def test_parse_rejects_non_mapping():
    text = "---\n- list item\n- another\n---\nBody\n"
    with pytest.raises(ValueError):
        parse(text)


def test_serialize_empty_data_is_raw_body():
    fm = FrontMatter(data={}, body="# Hello\n")
    assert serialize(fm) == "# Hello\n"


def test_serialize_with_data_produces_valid_frontmatter():
    fm = FrontMatter(
        data={"gdoc_id": "1abc", "gdoc_tab_id": "t.xyz"},
        body="# Hello\n",
    )
    out = serialize(fm)
    assert out.startswith("---\n")
    assert "gdoc_id: 1abc" in out
    assert "gdoc_tab_id: t.xyz" in out
    assert out.endswith("# Hello\n")


def test_roundtrip_preserves_data_and_body():
    original_data = {
        "gdoc_id": "1CLveZUmbU22YT_i5TGjhysSsxxFOM9h_r_b2-tvjMQ8",
        "gdoc_tab_id": "t.t6qmc76tli6j",
        "gdoc_last_synced": "2026-04-23T19:30:00Z",
    }
    original_body = "# Title\n\nParagraph with **bold** and *italic*.\n\n## Subsection\n"
    fm = FrontMatter(data=dict(original_data), body=original_body)
    text = serialize(fm)
    parsed = parse(text)
    assert parsed.data == original_data
    assert parsed.body == original_body


def test_roundtrip_preserves_unicode_body():
    fm = FrontMatter(
        data={"gdoc_id": "1abc"},
        body="# 中文标题\n\n内容段落。\n",
    )
    text = serialize(fm)
    parsed = parse(text)
    assert parsed.data == {"gdoc_id": "1abc"}
    assert parsed.body == "# 中文标题\n\n内容段落。\n"


def test_modify_and_reserialize():
    text = "---\ngdoc_id: 1abc\n---\n\n# Body\n"
    fm = parse(text)
    fm.set("gdoc_tab_id", "t.new")
    fm.set("gdoc_last_synced", "2026-04-23T20:00:00Z")
    out = serialize(fm)
    reparsed = parse(out)
    assert reparsed.data["gdoc_id"] == "1abc"
    assert reparsed.data["gdoc_tab_id"] == "t.new"
    assert reparsed.data["gdoc_last_synced"] == "2026-04-23T20:00:00Z"
    assert reparsed.body == "# Body\n"
