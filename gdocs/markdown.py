from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any


class BlockType(Enum):
    HEADING_1 = "HEADING_1"
    HEADING_2 = "HEADING_2"
    HEADING_3 = "HEADING_3"
    PARAGRAPH = "PARAGRAPH"
    BULLET = "BULLET"
    ORDERED_LIST = "ORDERED_LIST"
    HORIZONTAL_RULE = "HORIZONTAL_RULE"
    BLOCKQUOTE = "BLOCKQUOTE"


@dataclass
class TextSegment:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    link_url: str | None = None


@dataclass
class Block:
    block_type: BlockType
    segments: list[TextSegment]


_ORDERED_LIST_PATTERN = re.compile(r"^(\d+)\.\s+(.*)$")
_HR_PATTERN = re.compile(r"^[-]{3,}$|^[*]{3,}$|^[_]{3,}$")
_INLINE_PATTERN = re.compile(
    r"\[(?P<link_text>[^\]]+?)\]\((?P<link_url>[^)]+?)\)"
    + r"|`(?P<code>[^`]+?)`"
    + r"|\*\*\*(?P<bold_italic>.+?)\*\*\*"
    + r"|\*\*(?P<bold>.+?)\*\*"
    + r"|(?<!\*)\*(?!\*)(?P<italic>.+?)(?<!\*)\*(?!\*)"
)


def _parse_markdown(text: str) -> tuple[list[Block], list[int]]:
    blocks: list[Block] = []
    separators_before_block: list[int] = []
    pending_separators = 0

    for raw_line in text.splitlines():
        if raw_line.strip() == "":
            if blocks:
                pending_separators += 1
            continue

        block_type, content = _parse_block_line(raw_line)
        if block_type is BlockType.HORIZONTAL_RULE:
            segments = [TextSegment(text="━" * 30)]
        else:
            segments = _parse_inline_segments(content)
            if not segments:
                segments = [TextSegment(text="")]

        blocks.append(Block(block_type=block_type, segments=segments))
        separators_before_block.append(pending_separators)
        pending_separators = 0

    return blocks, separators_before_block


def _parse_block_line(line: str) -> tuple[BlockType, str]:
    if line.startswith("### "):
        return BlockType.HEADING_3, line[4:]
    if line.startswith("## "):
        return BlockType.HEADING_2, line[3:]
    if line.startswith("# "):
        return BlockType.HEADING_1, line[2:]
    if _HR_PATTERN.match(line.strip()):
        return BlockType.HORIZONTAL_RULE, ""
    if line.startswith("> "):
        return BlockType.BLOCKQUOTE, line[2:]
    if line.startswith("- ") or line.startswith("* "):
        return BlockType.BULLET, line[2:]

    ordered_match = _ORDERED_LIST_PATTERN.match(line)
    if ordered_match:
        return BlockType.ORDERED_LIST, ordered_match.group(2)

    return BlockType.PARAGRAPH, line


def _parse_inline_segments(content: str) -> list[TextSegment]:
    if content == "":
        return []

    segments: list[TextSegment] = []
    cursor = 0

    while cursor < len(content):
        match = _INLINE_PATTERN.search(content, cursor)
        if not match:
            trailing = content[cursor:]
            if trailing:
                segments.append(TextSegment(text=trailing))
            break

        if match.start() > cursor:
            plain_text = content[cursor : match.start()]
            if plain_text:
                segments.append(TextSegment(text=plain_text))

        matched = match.group(0)
        if matched:
            segments.append(_segment_from_match(match))

        cursor = match.end()

    return segments


def _segment_from_match(match: re.Match[str]) -> TextSegment:
    link_text = match.group("link_text")
    if link_text is not None:
        return TextSegment(text=link_text, link_url=match.group("link_url"))

    code_text = match.group("code")
    if code_text is not None:
        return TextSegment(text=code_text, code=True)

    bold_italic_text = match.group("bold_italic")
    if bold_italic_text is not None:
        return TextSegment(text=bold_italic_text, bold=True, italic=True)

    bold_text = match.group("bold")
    if bold_text is not None:
        return TextSegment(text=bold_text, bold=True)

    italic_text = match.group("italic")
    if italic_text is not None:
        return TextSegment(text=italic_text, italic=True)

    return TextSegment(text=match.group(0))


def _build_plain_text(blocks: list[Block], separators_before_block: list[int]) -> str:
    parts: list[str] = []
    for index, block in enumerate(blocks):
        separators = separators_before_block[index]
        if separators:
            parts.append("\n" * separators)

        parts.extend(segment.text for segment in block.segments)
        parts.append("\n")

    return "".join(parts)


def _build_location(index: int, tab_id: str | None) -> dict[str, object]:
    location: dict[str, object] = {"index": index}
    if tab_id is not None:
        location["tabId"] = tab_id
    return location


def _build_range(start: int, end: int, tab_id: str | None) -> dict[str, object]:
    range_obj: dict[str, object] = {"startIndex": start, "endIndex": end}
    if tab_id is not None:
        range_obj["tabId"] = tab_id
    return range_obj


def _segment_text_style(segment: TextSegment) -> tuple[dict[str, object], str] | None:
    text_style: dict[str, object] = {}
    fields: list[str] = []

    if segment.bold:
        text_style["bold"] = True
        fields.append("bold")
    if segment.italic:
        text_style["italic"] = True
        fields.append("italic")
    if segment.code:
        text_style["weightedFontFamily"] = {"fontFamily": "Courier New"}
        fields.append("weightedFontFamily")
    if segment.link_url:
        text_style["link"] = {"url": segment.link_url}
        fields.append("link")

    if not fields:
        return None

    return text_style, ",".join(fields)


def _paragraph_named_style(block_type: BlockType) -> str | None:
    if block_type is BlockType.HEADING_1:
        return "HEADING_1"
    if block_type is BlockType.HEADING_2:
        return "HEADING_2"
    if block_type is BlockType.HEADING_3:
        return "HEADING_3"
    if block_type is BlockType.PARAGRAPH:
        return "NORMAL_TEXT"
    return None


def _bullet_preset(block_type: BlockType) -> str | None:
    if block_type is BlockType.BULLET:
        return "BULLET_DISC_CIRCLE_SQUARE"
    if block_type is BlockType.ORDERED_LIST:
        return "NUMBERED_DECIMAL_ALPHA_ROMAN"
    return None


def _custom_paragraph_style(block_type: BlockType) -> tuple[dict[str, object], str] | None:
    if block_type is BlockType.HORIZONTAL_RULE:
        return {"alignment": "CENTER"}, "alignment"
    if block_type is BlockType.BLOCKQUOTE:
        return {
            "indentStart": {"magnitude": 36, "unit": "PT"},
            "borderLeft": {
                "color": {"color": {"rgbColor": {"red": 0.7, "green": 0.7, "blue": 0.7}}},
                "width": {"magnitude": 1.5, "unit": "PT"},
                "dashStyle": "SOLID",
                "padding": {"magnitude": 8, "unit": "PT"},
            },
        }, "indentStart,borderLeft"
    return None


def markdown_to_requests(
    text: str,
    tab_id: str | None = None,
    start_index: int = 1,
) -> tuple[list[dict[str, Any]], int]:  # pyright: ignore[reportExplicitAny]
    """Convert markdown text to Google Docs API batchUpdate requests.

    Args:
        text: Markdown-formatted string.
        tab_id: Optional Google Docs tab ID for multi-tab documents.
        start_index: Character index where text insertion begins (default 1).

    Returns:
        Tuple of (requests, end_index).
        - requests: ordered list of batchUpdate request dicts.
          First request is insertText with full plain text.
          Remaining requests are formatting (updateTextStyle, updateParagraphStyle, createParagraphBullets).
        - end_index: the character index after the last inserted character.
    """
    blocks, separators_before_block = _parse_markdown(text)
    plain_text = _build_plain_text(blocks, separators_before_block)
    end_index = start_index + len(plain_text)

    requests = [
        {
            "insertText": {
                "location": _build_location(start_index, tab_id),
                "text": plain_text,
            }
        }
    ]

    current_index = start_index
    for block, separators in zip(blocks, separators_before_block):
        current_index += separators
        block_start = current_index

        for segment in block.segments:
            segment_start = current_index
            segment_end = segment_start + len(segment.text)

            style_payload = _segment_text_style(segment)
            if style_payload and segment_start < segment_end:
                text_style, fields = style_payload
                requests.append(
                    {
                        "updateTextStyle": {
                            "range": _build_range(segment_start, segment_end, tab_id),
                            "textStyle": text_style,
                            "fields": fields,
                        }
                    }
                )

            current_index = segment_end

        block_end = current_index + 1

        named_style = _paragraph_named_style(block.block_type)
        if named_style is not None:
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": _build_range(block_start, block_end, tab_id),
                        "paragraphStyle": {"namedStyleType": named_style},
                        "fields": "namedStyleType",
                    }
                }
            )

        bullet_preset = _bullet_preset(block.block_type)
        if bullet_preset is not None:
            requests.append(
                {
                    "createParagraphBullets": {
                        "range": _build_range(block_start, block_end, tab_id),
                        "bulletPreset": bullet_preset,
                    }
                }
            )

        custom_style = _custom_paragraph_style(block.block_type)
        if custom_style is not None:
            style_dict, style_fields = custom_style
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": _build_range(block_start, block_end, tab_id),
                        "paragraphStyle": style_dict,
                        "fields": style_fields,
                    }
                }
            )

        if block.block_type is BlockType.HORIZONTAL_RULE:
            requests.append(
                {
                    "updateTextStyle": {
                        "range": _build_range(block_start, block_end - 1, tab_id),
                        "textStyle": {
                            "foregroundColor": {
                                "color": {"rgbColor": {"red": 0.7, "green": 0.7, "blue": 0.7}}
                            },
                            "fontSize": {"magnitude": 6, "unit": "PT"},
                        },
                        "fields": "foregroundColor,fontSize",
                    }
                }
            )

        current_index = block_end

    return requests, end_index
