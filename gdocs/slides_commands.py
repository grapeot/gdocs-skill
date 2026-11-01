# pyright: basic

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .drive_client import parse_source

if TYPE_CHECKING:
    from .slides_client import SlidesClient


def run_slides_command(
    data: dict[str, object],
    secrets_dir: Path,
    slides_client_cls: type[SlidesClient],
) -> object:
    auth_timeout = int(str(data.get("auth_timeout") or 120))
    if auth_timeout <= 0:
        raise ValueError("--auth-timeout must be positive")
    presentation_id, _ = parse_source(str(data["source"]))
    command = str(data["slides_command"])
    spec = None
    if command == "apply":
        spec = json.loads(Path(str(data["spec"])).read_text(encoding="utf-8"))
    client = slides_client_cls(secrets_dir, auth_timeout=auth_timeout)
    if spec is not None:
        return client.apply(presentation_id, spec, dry_run=bool(data.get("dry_run")))
    if command == "inspect":
        pages = data.get("page") or None
        return client.inspect(presentation_id, [int(str(p)) for p in pages] if isinstance(pages, list) else None)
    if command == "backup":
        return client.backup(presentation_id, Path(str(data["output_dir"])))
    raise RuntimeError("Unknown Slides command")
