# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnusedCallResult=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

from gdocs.markdown import markdown_to_requests, _parse_markdown, _parse_inline_segments, BlockType


def test_heading_1():
    blocks, separators = _parse_markdown("# Title")

    assert separators == [0]
    assert len(blocks) == 1
    assert blocks[0].block_type is BlockType.HEADING_1
    assert [segment.text for segment in blocks[0].segments] == ["Title"]


def test_heading_2():
    blocks, _ = _parse_markdown("## Subtitle")

    assert len(blocks) == 1
    assert blocks[0].block_type is BlockType.HEADING_2
    assert [segment.text for segment in blocks[0].segments] == ["Subtitle"]


def test_heading_3():
    blocks, _ = _parse_markdown("### Section")

    assert len(blocks) == 1
    assert blocks[0].block_type is BlockType.HEADING_3
    assert [segment.text for segment in blocks[0].segments] == ["Section"]


def test_paragraph():
    blocks, _ = _parse_markdown("plain text")

    assert len(blocks) == 1
    assert blocks[0].block_type is BlockType.PARAGRAPH
    assert [segment.text for segment in blocks[0].segments] == ["plain text"]


def test_unordered_list_dash():
    blocks, _ = _parse_markdown("- item")

    assert len(blocks) == 1
    assert blocks[0].block_type is BlockType.BULLET
    assert [segment.text for segment in blocks[0].segments] == ["item"]


def test_unordered_list_asterisk():
    blocks, _ = _parse_markdown("* item")

    assert len(blocks) == 1
    assert blocks[0].block_type is BlockType.BULLET
    assert [segment.text for segment in blocks[0].segments] == ["item"]


def test_ordered_list():
    blocks, _ = _parse_markdown("1. item")

    assert len(blocks) == 1
    assert blocks[0].block_type is BlockType.ORDERED_LIST
    assert [segment.text for segment in blocks[0].segments] == ["item"]


def test_bold():
    segments = _parse_inline_segments("**text**")

    assert len(segments) == 1
    assert segments[0].text == "text"
    assert segments[0].bold is True
    assert segments[0].italic is False


def test_italic():
    segments = _parse_inline_segments("*text*")

    assert len(segments) == 1
    assert segments[0].text == "text"
    assert segments[0].italic is True
    assert segments[0].bold is False


def test_bold_italic():
    segments = _parse_inline_segments("***text***")

    assert len(segments) == 1
    assert segments[0].text == "text"
    assert segments[0].bold is True
    assert segments[0].italic is True


def test_inline_code():
    segments = _parse_inline_segments("`code`")

    assert len(segments) == 1
    assert segments[0].text == "code"
    assert segments[0].code is True


def test_link():
    segments = _parse_inline_segments("[text](https://example.com)")

    assert len(segments) == 1
    assert segments[0].text == "text"
    assert segments[0].link_url == "https://example.com"


def test_mixed_inline():
    segments = _parse_inline_segments("plain **bold** and *italic*")

    assert [segment.text for segment in segments] == ["plain ", "bold", " and ", "italic"]
    assert segments[0].bold is False and segments[0].italic is False
    assert segments[1].bold is True
    assert segments[2].bold is False and segments[2].italic is False
    assert segments[3].italic is True


def test_insert_text_request_first():
    requests, _ = markdown_to_requests("Hello")

    assert "insertText" in requests[0]
    assert requests[0]["insertText"]["location"] == {"index": 1}
    assert requests[0]["insertText"]["text"] == "Hello\n"


def test_heading_generates_paragraph_style():
    requests, _ = markdown_to_requests("# Title")

    paragraph_requests = [request for request in requests if "updateParagraphStyle" in request]
    assert len(paragraph_requests) == 1
    payload = paragraph_requests[0]["updateParagraphStyle"]
    assert payload["paragraphStyle"]["namedStyleType"] == "HEADING_1"


def test_bold_generates_text_style():
    requests, _ = markdown_to_requests("This is **bold**")

    text_style_requests = [request for request in requests if "updateTextStyle" in request]
    assert any(request["updateTextStyle"]["textStyle"].get("bold") is True for request in text_style_requests)


def test_bullet_generates_create_paragraph_bullets():
    requests, _ = markdown_to_requests("- item")

    bullet_requests = [request for request in requests if "createParagraphBullets" in request]
    assert len(bullet_requests) == 1
    assert bullet_requests[0]["createParagraphBullets"]["bulletPreset"] == "BULLET_DISC_CIRCLE_SQUARE"


def test_ordered_list_preset():
    requests, _ = markdown_to_requests("1. item")

    bullet_requests = [request for request in requests if "createParagraphBullets" in request]
    assert len(bullet_requests) == 1
    assert bullet_requests[0]["createParagraphBullets"]["bulletPreset"] == "NUMBERED_DECIMAL_ALPHA_ROMAN"


def test_tab_id_propagation():
    requests, _ = markdown_to_requests("# Title\n- **item**", tab_id="tab-123", start_index=7)

    for request in requests:
        if "insertText" in request:
            assert request["insertText"]["location"]["tabId"] == "tab-123"
        if "updateTextStyle" in request:
            assert request["updateTextStyle"]["range"]["tabId"] == "tab-123"
        if "updateParagraphStyle" in request:
            assert request["updateParagraphStyle"]["range"]["tabId"] == "tab-123"
        if "createParagraphBullets" in request:
            assert request["createParagraphBullets"]["range"]["tabId"] == "tab-123"


def test_index_arithmetic():
    text = "# H\n\nParagraph\n- item"
    requests, end_index = markdown_to_requests(text, start_index=5)

    assert requests[0]["insertText"]["text"] == "H\n\nParagraph\nitem\n"
    assert end_index == 23

    paragraph_requests = [request["updateParagraphStyle"] for request in requests if "updateParagraphStyle" in request]
    assert paragraph_requests[0]["range"] == {"startIndex": 5, "endIndex": 7}
    assert paragraph_requests[1]["range"] == {"startIndex": 8, "endIndex": 18}

    bullet_request = [request["createParagraphBullets"] for request in requests if "createParagraphBullets" in request][0]
    assert bullet_request["range"] == {"startIndex": 18, "endIndex": 23}


def test_empty_input():
    requests, end_index = markdown_to_requests("")

    assert requests == [{"insertText": {"location": {"index": 1}, "text": ""}}]
    assert end_index == 1


def test_end_index_returned():
    requests, end_index = markdown_to_requests("**bold**", start_index=10)

    plain_text = requests[0]["insertText"]["text"]
    assert plain_text == "bold\n"
    assert end_index == 10 + len(plain_text)


def test_horizontal_rule_block_parse():
    blocks, _ = _parse_markdown("---")

    assert len(blocks) == 1
    assert blocks[0].block_type is BlockType.HORIZONTAL_RULE
    assert blocks[0].segments[0].text == "━" * 30


def test_horizontal_rule_variants():
    for marker in ["---", "***", "___", "----------"]:
        blocks, _ = _parse_markdown(marker)
        assert blocks[0].block_type is BlockType.HORIZONTAL_RULE


def test_blockquote_block_parse():
    blocks, _ = _parse_markdown("> quoted text")

    assert len(blocks) == 1
    assert blocks[0].block_type is BlockType.BLOCKQUOTE
    assert blocks[0].segments[0].text == "quoted text"


def test_horizontal_rule_generates_requests():
    requests, _ = markdown_to_requests("---")

    paragraph_styles = [
        r["updateParagraphStyle"] for r in requests if "updateParagraphStyle" in r
    ]
    assert any(ps["paragraphStyle"].get("alignment") == "CENTER" for ps in paragraph_styles)

    text_styles = [r["updateTextStyle"] for r in requests if "updateTextStyle" in r]
    assert any(
        ts["textStyle"].get("fontSize") == {"magnitude": 6, "unit": "PT"}
        for ts in text_styles
    )


def test_blockquote_generates_requests():
    requests, _ = markdown_to_requests("> important note")

    paragraph_styles = [
        r["updateParagraphStyle"] for r in requests if "updateParagraphStyle" in r
    ]
    assert any(
        ps["paragraphStyle"].get("indentStart") == {"magnitude": 36, "unit": "PT"}
        for ps in paragraph_styles
    )
    assert any("borderLeft" in ps["paragraphStyle"] for ps in paragraph_styles)


def test_full_markdown_document():
    text = (
        "# Title\n"
        "Intro with **bold** and *italic* plus [link](https://example.com).\n"
        "\n"
        "## Tasks\n"
        "- first `code`\n"
        "1. ordered item\n"
        "### End"
    )

    requests, end_index = markdown_to_requests(text)

    expected_plain = (
        "Title\n"
        "Intro with bold and italic plus link.\n"
        "\n"
        "Tasks\n"
        "first code\n"
        "ordered item\n"
        "End\n"
    )
    assert requests[0]["insertText"]["text"] == expected_plain
    assert end_index == 1 + len(expected_plain)
    assert 8 <= len(requests) <= 30

    paragraph_styles = [
        request["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
        for request in requests
        if "updateParagraphStyle" in request
    ]
    assert "HEADING_1" in paragraph_styles
    assert "HEADING_2" in paragraph_styles
    assert "HEADING_3" in paragraph_styles

    text_styles = [request["updateTextStyle"]["textStyle"] for request in requests if "updateTextStyle" in request]
    assert any(style.get("bold") is True for style in text_styles)
    assert any(style.get("italic") is True for style in text_styles)
    assert any(style.get("weightedFontFamily") == {"fontFamily": "Courier New"} for style in text_styles)
    assert any(style.get("link") == {"url": "https://example.com"} for style in text_styles)

    bullet_presets = [
        request["createParagraphBullets"]["bulletPreset"]
        for request in requests
        if "createParagraphBullets" in request
    ]
    assert "BULLET_DISC_CIRCLE_SQUARE" in bullet_presets
    assert "NUMBERED_DECIMAL_ALPHA_ROMAN" in bullet_presets


def test_table_block_parse():
    blocks, separators = _parse_markdown("| H1 | H2 |\n|---|---|\n| A | B |")

    assert separators == [0]
    assert len(blocks) == 1
    assert blocks[0].block_type is BlockType.TABLE
    assert blocks[0].table_data is not None
    assert blocks[0].table_data.headers == ["H1", "H2"]
    assert blocks[0].table_data.rows == [["A", "B"]]
    assert blocks[0].table_data.col_count == 2
    assert blocks[0].table_data.row_count == 2


def test_table_separator_line_skipped():
    blocks, _ = _parse_markdown("| H1 | H2 |\n|---|---|\n| A | B |\n| C | D |")

    assert len(blocks) == 1
    assert blocks[0].block_type is BlockType.TABLE
    assert blocks[0].table_data is not None
    assert blocks[0].table_data.rows == [["A", "B"], ["C", "D"]]


def test_table_requests_contain_insert_table():
    requests, end_index = markdown_to_requests(
        "| H1 | H2 |\n|---|---|\n| A | B |",
        tab_id="t1",
        start_index=1,
    )

    assert "insertTable" in requests[0]
    assert requests[0]["insertTable"] == {
        "rows": 2,
        "columns": 2,
        "location": {"index": 1, "tabId": "t1"},
    }
    assert end_index == 20


def test_table_cell_insertions_reversed():
    requests, _ = markdown_to_requests("| H1 | H2 |\n|---|---|\n| A | B |", start_index=1)

    insert_text_requests = [request["insertText"] for request in requests if "insertText" in request]
    assert [request["location"]["index"] for request in insert_text_requests] == [12, 10, 7, 5]  # pyright: ignore[reportAny]
    assert [request["text"] for request in insert_text_requests] == ["B", "A", "H2", "H1"]  # pyright: ignore[reportAny]


def test_table_header_bold():
    requests, _ = markdown_to_requests("| H1 | H2 |\n|---|---|\n| A | B |", start_index=1)

    style_requests = [request["updateTextStyle"] for request in requests if "updateTextStyle" in request]
    assert len(style_requests) == 2
    assert style_requests[0] == {
        "range": {"startIndex": 5, "endIndex": 7},
        "textStyle": {"bold": True},
        "fields": "bold",
    }
    assert style_requests[1] == {
        "range": {"startIndex": 9, "endIndex": 11},
        "textStyle": {"bold": True},
        "fields": "bold",
    }


def test_table_index_math_2x2():
    requests, end_index = markdown_to_requests("| H1 | H2 |\n|---|---|\n| A | B |", start_index=1)

    locations_by_text = {
        request["insertText"]["text"]: request["insertText"]["location"]["index"]
        for request in requests
        if "insertText" in request
    }
    assert locations_by_text == {"H1": 5, "H2": 7, "A": 10, "B": 12}
    assert end_index == 20


def test_table_index_math_3x3():
    requests, end_index = markdown_to_requests(
        "| a | b | c |\n|---|---|---|\n| d | e | f |\n| g | h | i |",
        start_index=1,
    )

    locations_by_text = {
        request["insertText"]["text"]: request["insertText"]["location"]["index"]
        for request in requests
        if "insertText" in request
    }
    assert locations_by_text == {
        "a": 5,
        "b": 7,
        "c": 9,
        "d": 12,
        "e": 14,
        "f": 16,
        "g": 19,
        "h": 21,
        "i": 23,
    }
    assert end_index == 34


def test_table_mixed_with_text():
    text = "# Title\n\n| H1 | H2 |\n|---|---|\n| A | B |\n\nParagraph"
    requests, end_index = markdown_to_requests(text, start_index=1)

    assert [next(iter(request)) for request in requests[:8]] == [
        "insertText",
        "insertText",
        "insertTable",
        "insertText",
        "insertText",
        "insertText",
        "insertText",
        "insertText",
    ]
    assert requests[0]["insertText"] == {"location": {"index": 1}, "text": "Title\n"}
    assert requests[1]["insertText"] == {"location": {"index": 7}, "text": "\n"}
    assert requests[2]["insertTable"] == {
        "rows": 2,
        "columns": 2,
        "location": {"index": 8},
    }
    assert requests[3]["insertText"] == {"location": {"index": 19}, "text": "B"}
    assert requests[4]["insertText"] == {"location": {"index": 17}, "text": "A"}
    assert requests[5]["insertText"] == {"location": {"index": 14}, "text": "H2"}
    assert requests[6]["insertText"] == {"location": {"index": 12}, "text": "H1"}
    assert requests[7]["insertText"] == {"location": {"index": 27}, "text": "\nParagraph\n"}

    paragraph_styles = [
        request["updateParagraphStyle"]
        for request in requests
        if "updateParagraphStyle" in request
    ]
    assert paragraph_styles == [
        {
            "range": {"startIndex": 1, "endIndex": 7},
            "paragraphStyle": {"namedStyleType": "HEADING_1"},
            "fields": "namedStyleType",
        },
        {
            "range": {"startIndex": 28, "endIndex": 38},
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
            "fields": "namedStyleType",
        },
    ]
    assert end_index == 38


def test_table_empty_cells():
    requests, end_index = markdown_to_requests(
        "| H1 | H2 |\n|---|---|\n| A | |\n| | D |",
        start_index=1,
    )

    insert_text_requests = [request["insertText"] for request in requests if "insertText" in request]
    assert [request["text"] for request in insert_text_requests] == ["D", "A", "H2", "H1"]  # pyright: ignore[reportAny]
    assert all(request["text"] != "" for request in insert_text_requests)  # pyright: ignore[reportAny]
    assert end_index == 25


def test_table_with_tab_id():
    requests, _ = markdown_to_requests(
        "| H1 | H2 |\n|---|---|\n| A | B |",
        tab_id="tab-xyz",
        start_index=3,
    )

    for request in requests:
        if "insertTable" in request:
            assert request["insertTable"]["location"]["tabId"] == "tab-xyz"
        if "insertText" in request:
            assert request["insertText"]["location"]["tabId"] == "tab-xyz"
        if "updateTextStyle" in request:
            assert request["updateTextStyle"]["range"]["tabId"] == "tab-xyz"
