from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Literal, TypedDict


class BlockType(Enum):
    HEADING_1 = "HEADING_1"
    HEADING_2 = "HEADING_2"
    HEADING_3 = "HEADING_3"
    PARAGRAPH = "PARAGRAPH"
    BULLET = "BULLET"
    ORDERED_LIST = "ORDERED_LIST"
    HORIZONTAL_RULE = "HORIZONTAL_RULE"
    BLOCKQUOTE = "BLOCKQUOTE"
    TABLE = "TABLE"


@dataclass
class TextSegment:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    link_url: str | None = None


@dataclass
class TableData:
    headers: list[str]
    rows: list[list[str]]
    col_count: int

    @property
    def row_count(self) -> int:
        return 1 + len(self.rows)


@dataclass
class Block:
    block_type: BlockType
    segments: list[TextSegment]
    table_data: TableData | None = None


class TextBlocksSegment(TypedDict):
    type: Literal["text"]
    blocks: list[Block]
    separators: list[int]


class TableBlockSegment(TypedDict):
    type: Literal["table"]
    table_data: TableData
    separators_before: int


SegmentGroup = TextBlocksSegment | TableBlockSegment
Request = dict[str, object]


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

    lines = text.splitlines()
    line_index = 0
    while line_index < len(lines):
        raw_line = lines[line_index]
        if raw_line.strip() == "":
            if blocks:
                pending_separators += 1
            line_index += 1
            continue

        if raw_line.startswith("|"):
            table_lines: list[str] = []
            while line_index < len(lines) and lines[line_index].startswith("|"):
                table_lines.append(lines[line_index])
                line_index += 1

            table_data = _parse_table_block(table_lines)
            blocks.append(
                Block(
                    block_type=BlockType.TABLE,
                    segments=[],
                    table_data=table_data,
                )
            )
            separators_before_block.append(pending_separators)
            pending_separators = 0
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
        line_index += 1

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


def _parse_table_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [cell.strip() for cell in cells]


def _is_table_separator_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    if "-" not in stripped:
        return False
    return all(character in "|:- " for character in stripped)


def _normalize_table_row(cells: list[str], col_count: int) -> list[str]:
    if len(cells) >= col_count:
        return cells[:col_count]
    return cells + [""] * (col_count - len(cells))


def _parse_table_block(table_lines: list[str]) -> TableData:
    headers = _parse_table_row(table_lines[0])
    col_count = max(1, len(headers))
    normalized_headers = _normalize_table_row(headers, col_count)

    row_start = 1
    if len(table_lines) > 1 and _is_table_separator_line(table_lines[1]):
        row_start = 2

    rows = [
        _normalize_table_row(_parse_table_row(line), col_count)
        for line in table_lines[row_start:]
    ]
    return TableData(headers=normalized_headers, rows=rows, col_count=col_count)


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


def _text_blocks_to_requests(
    blocks: list[Block],
    separators_before_block: list[int],
    tab_id: str | None,
    start_index: int,
) -> tuple[list[Request], list[Request], int]:
    plain_text = _build_plain_text(blocks, separators_before_block)
    end_index = start_index + len(plain_text)

    insertion_requests: list[Request] = [
        {
            "insertText": {
                "location": _build_location(start_index, tab_id),
                "text": plain_text,
            }
        }
    ]

    formatting_requests: list[Request] = []

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
                formatting_requests.append(
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
            formatting_requests.append(
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
            formatting_requests.append(
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
            formatting_requests.append(
                {
                    "updateParagraphStyle": {
                        "range": _build_range(block_start, block_end, tab_id),
                        "paragraphStyle": style_dict,
                        "fields": style_fields,
                    }
                }
            )

        if block.block_type is BlockType.HORIZONTAL_RULE:
            formatting_requests.append(
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

    return insertion_requests, formatting_requests, end_index


def _table_to_requests(
    table_data: TableData,
    tab_id: str | None,
    start_index: int,
) -> tuple[list[Request], list[Request], int]:
    row_count = table_data.row_count
    col_count = table_data.col_count
    all_rows = [table_data.headers] + table_data.rows
    empty_table_size = row_count * (2 * col_count + 1) + 3

    insertion_requests: list[Request] = [
        {
            "insertTable": {
                "rows": row_count,
                "columns": col_count,
                "location": _build_location(start_index, tab_id),
            }
        }
    ]

    cell_insertions: list[Request] = []
    for row in range(row_count):
        for col in range(col_count):
            cell_text = all_rows[row][col]
            if not cell_text:
                continue

            empty_position = start_index + row * (2 * col_count + 1) + 2 * col + 4
            cell_insertions.append(
                {
                    "insertText": {
                        "location": _build_location(empty_position, tab_id),
                        "text": cell_text,
                    }
                }
            )
    cell_insertions.reverse()
    insertion_requests.extend(cell_insertions)

    formatting_requests: list[Request] = []
    cumulative_shift = 0
    for row in range(row_count):
        for col in range(col_count):
            cell_text = all_rows[row][col]

            if row == 0 and cell_text:
                empty_position = start_index + row * (2 * col_count + 1) + 2 * col + 4
                final_position = empty_position + cumulative_shift
                formatting_requests.append(
                    {
                        "updateTextStyle": {
                            "range": _build_range(
                                final_position,
                                final_position + len(cell_text),
                                tab_id,
                            ),
                            "textStyle": {"bold": True},
                            "fields": "bold",
                        }
                    }
                )

            cumulative_shift += len(cell_text)

    total_cell_text = sum(len(cell_text) for row in all_rows for cell_text in row)
    end_index = start_index + empty_table_size + total_cell_text
    return insertion_requests, formatting_requests, end_index


def _split_at_tables(
    blocks: list[Block],
    separators_before_block: list[int],
) -> list[SegmentGroup]:
    segments: list[SegmentGroup] = []
    current_text_blocks: list[Block] = []
    current_text_separators: list[int] = []

    for index, block in enumerate(blocks):
        if block.block_type is BlockType.TABLE:
            if current_text_blocks:
                segments.append({
                    "type": "text",
                    "blocks": current_text_blocks,
                    "separators": current_text_separators,
                })
                current_text_blocks = []
                current_text_separators = []

            if block.table_data is None:
                raise ValueError("TABLE block requires table_data")

            segments.append({
                "type": "table",
                "table_data": block.table_data,
                "separators_before": separators_before_block[index],
            })
            continue

        current_text_blocks.append(block)
        current_text_separators.append(separators_before_block[index])

    if current_text_blocks:
        segments.append({
            "type": "text",
            "blocks": current_text_blocks,
            "separators": current_text_separators,
        })

    return segments


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
          For text-only markdown, first request is insertText with full plain text.
          For markdown containing tables, requests include insertTable and per-cell insertText.
          Remaining requests are formatting (updateTextStyle, updateParagraphStyle, createParagraphBullets).
        - end_index: the character index after the last inserted character.
    """
    blocks, separators_before_block = _parse_markdown(text)

    if not any(block.block_type is BlockType.TABLE for block in blocks):
        insertion_requests, formatting_requests, end_index = _text_blocks_to_requests(
            blocks,
            separators_before_block,
            tab_id,
            start_index,
        )
        return insertion_requests + formatting_requests, end_index

    all_insertion_requests: list[Request] = []
    all_formatting_requests: list[Request] = []
    current_index = start_index

    segments = _split_at_tables(blocks, separators_before_block)
    for segment in segments:
        if segment["type"] == "text":
            insertion_requests, formatting_requests, current_index = _text_blocks_to_requests(
                segment["blocks"],
                segment["separators"],
                tab_id,
                current_index,
            )
            all_insertion_requests.extend(insertion_requests)
            all_formatting_requests.extend(formatting_requests)
            continue

        separators_before = segment["separators_before"]
        if separators_before:
            all_insertion_requests.append(
                {
                    "insertText": {
                        "location": _build_location(current_index, tab_id),
                        "text": "\n" * separators_before,
                    }
                }
            )
            current_index += separators_before

        insertion_requests, formatting_requests, current_index = _table_to_requests(
            segment["table_data"],
            tab_id,
            current_index,
        )
        all_insertion_requests.extend(insertion_requests)
        all_formatting_requests.extend(formatting_requests)

    return all_insertion_requests + all_formatting_requests, current_index
