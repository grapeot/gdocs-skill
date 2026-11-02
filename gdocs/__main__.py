# pyright: basic

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from googleapiclient.errors import HttpError

from .calendar_client import CalendarClient
from .calendar_commands import run_calendar_command
from .client import GoogleDocsClient
from .docs_commands import run_docs_command
from .drive_client import DriveClient, parse_source
from .gmail_client import GmailClient
from .gmail_commands import run_gmail_command
from .mail_store import MailStore
from .parser import DEFAULT_DATA_DIR, DEFAULT_SECRETS_DIR, build_parser
from .slides_client import SlidesClient
from .slides_commands import run_slides_command


def run_command(args: argparse.Namespace) -> object:
    data = vars(args)
    secrets_dir = Path(data["secrets_dir"])
    command = str(data["command"])
    if command == "drive":
        if data["auth_timeout"] <= 0:
            raise ValueError("--auth-timeout must be positive")
        client = DriveClient(secrets_dir, auth_timeout=data["auth_timeout"])
        if data["drive_command"] == "upload":
            result = client.upload(
                Path(data["path"]), name=data["name"], folder_id=data["folder_id"],
                dry_run=data["dry_run"],
            )
            if data.get("share") and not data["dry_run"] and result.get("success"):
                # Keep the upload result visible even if sharing fails, so nobody re-uploads.
                target = result.get("share_target_id")
                try:
                    if not target:
                        raise RuntimeError("Upload returned no id to share")
                    result["share"] = client.share(str(target), str(data["share"]), role=data["role"])
                except Exception as exc:
                    result["share"] = {"success": False, "error": str(exc)}
                    result["success"] = False
            return result
        file_id, resource_key = parse_source(data["source"])
        return client.download(
            file_id, data["output_dir"], resource_key=resource_key,
            export_format=data["export_format"], dry_run=data["dry_run"],
        )
    if command == "slides":
        return run_slides_command(data, secrets_dir, slides_client_cls=SlidesClient)
    if command == "calendar":
        return run_calendar_command(
            data,
            secrets_dir,
            calendar_client_cls=CalendarClient,
        )
    if command == "gmail":
        return run_gmail_command(
            data,
            secrets_dir,
            Path(data["mail_data_dir"]),
            gmail_client_cls=GmailClient,
            mail_store_cls=MailStore,
        )
    client = GoogleDocsClient(secrets_dir=secrets_dir)
    return run_docs_command(data, client)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_command(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "drive" and isinstance(result, dict) and not result.get("success"):
            return 1
        return 0
    except HttpError as exc:
        error_detail = {
            "error": str(exc),
            "status_code": exc.status_code,
            "response": exc.content.decode("utf-8", errors="replace") if exc.content else None,
        }
        print(json.dumps(error_detail, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
