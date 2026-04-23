# pyright: basic

"""YAML front matter parsing and serialization for Markdown files.

Supports the standard Jekyll-style front matter:

    ---
    key: value
    ---

    # body starts here

Used by `gdocs sync` to persist a Markdown file's binding to a Google Doc
(doc id, tab id, last-synced timestamp) inside the file itself, making the
MD file the single source of truth for its own cloud counterpart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


DELIMITER = "---"


@dataclass
class FrontMatter:
    data: dict[str, Any]
    body: str

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value


def parse(text: str) -> FrontMatter:
    """Split a Markdown string into front matter metadata and body.

    If the text does not begin with a front matter block, returns an empty
    dict and the original text as body.
    """
    if not text.startswith(DELIMITER):
        return FrontMatter(data={}, body=text)

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != DELIMITER:
        return FrontMatter(data={}, body=text)

    end_index: int | None = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == DELIMITER:
            end_index = i
            break

    if end_index is None:
        return FrontMatter(data={}, body=text)

    yaml_block = "".join(lines[1:end_index])
    body = "".join(lines[end_index + 1:])
    # Strip a single leading newline if present so body starts at content.
    if body.startswith("\n"):
        body = body[1:]
    elif body.startswith("\r\n"):
        body = body[2:]

    parsed = yaml.safe_load(yaml_block) if yaml_block.strip() else {}
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise ValueError(
            f"Front matter must be a YAML mapping, got {type(parsed).__name__}"
        )
    return FrontMatter(data=parsed, body=body)


def serialize(fm: FrontMatter) -> str:
    """Write front matter + body back to a Markdown string.

    If `fm.data` is empty, the output is just the body without any front
    matter delimiters.
    """
    if not fm.data:
        return fm.body
    yaml_block = yaml.safe_dump(
        fm.data,
        default_flow_style=False,
        sort_keys=True,
        allow_unicode=True,
    )
    return f"{DELIMITER}\n{yaml_block}{DELIMITER}\n\n{fm.body}"
