from __future__ import annotations

"""Local Gmail storage: raw .eml files plus SQLite metadata."""

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path
from collections.abc import Mapping
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    gmail_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL,
    subject TEXT,
    from_addr TEXT,
    to_addr TEXT,
    cc_addr TEXT,
    date TEXT,
    snippet TEXT,
    size INTEGER,
    labels_json TEXT NOT NULL,
    mime_path TEXT NOT NULL,
    downloaded_at TEXT NOT NULL,
    sort_timestamp TEXT NOT NULL,
    sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS labels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    message_list_visibility TEXT,
    label_list_visibility TEXT
);
"""


@dataclass(frozen=True)
class StoredMessage:
    gmail_id: str
    thread_id: str
    subject: str
    from_addr: str
    to_addr: str
    cc_addr: str
    date: str
    snippet: str
    labels: list[str]
    mime_path: Path
    downloaded_at: str


class MailStore:
    def __init__(self, data_dir: Path):
        self.data_dir: Path = data_dir
        self.messages_dir: Path = self.data_dir / "messages"
        self.markdown_dir: Path = self.data_dir / "markdown"
        self.db_path: Path = self.data_dir / "mail.db"
        self.messages_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        self.connection: sqlite3.Connection = sqlite3.connect(self.db_path)
        _ = self.connection.executescript(SCHEMA)
        self._migrate_schema()
        self.connection.commit()

    def _migrate_schema(self) -> None:
        columns = {
            str(item[1])
            for item in self.connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "sort_timestamp" not in columns:
            _ = self.connection.execute(
                "ALTER TABLE messages ADD COLUMN sort_timestamp TEXT NOT NULL DEFAULT ''"
            )
            _ = self.connection.execute(
                "UPDATE messages SET sort_timestamp = COALESCE(downloaded_at, '') WHERE sort_timestamp = ''"
            )

    def close(self) -> None:
        self.connection.close()

    def has_message(self, gmail_id: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM messages WHERE gmail_id = ?", (gmail_id,)
        ).fetchone()
        return row is not None

    def save_message(
        self,
        *,
        account: str,
        gmail_id: str,
        thread_id: str,
        raw_bytes: bytes,
        metadata: dict[str, object],
    ) -> StoredMessage:
        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        normalized = _metadata_with_raw_fallback(metadata, raw_bytes)
        mime_path = self._mime_path(normalized, gmail_id)
        mime_path.write_bytes(raw_bytes)
        downloaded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        raw_labels = normalized.get("label_ids", [])
        labels = [str(item) for item in raw_labels] if isinstance(raw_labels, list) else []
        raw_size = normalized.get("size_estimate")
        size = raw_size if isinstance(raw_size, int) else len(raw_bytes)
        row: dict[str, object] = {
            "account": account,
            "gmail_id": gmail_id,
            "thread_id": thread_id,
            "subject": str(normalized.get("subject") or ""),
            "from_addr": str(normalized.get("from_addr") or ""),
            "to_addr": str(normalized.get("to_addr") or ""),
            "cc_addr": str(normalized.get("cc_addr") or ""),
            "date": str(normalized.get("date") or ""),
            "snippet": str(normalized.get("snippet") or ""),
            "size": size,
            "labels_json": json.dumps(labels),
            "mime_path": str(mime_path.relative_to(self.data_dir)),
            "downloaded_at": downloaded_at,
            "sort_timestamp": _sort_timestamp(normalized, downloaded_at),
            "sha256": sha256,
        }
        _ = self.connection.execute(
            """
            INSERT OR REPLACE INTO messages (
                account, gmail_id, thread_id, subject, from_addr, to_addr, cc_addr,
                date, snippet, size, labels_json, mime_path, downloaded_at, sort_timestamp, sha256
            ) VALUES (
                :account, :gmail_id, :thread_id, :subject, :from_addr, :to_addr, :cc_addr,
                :date, :snippet, :size, :labels_json, :mime_path, :downloaded_at, :sort_timestamp, :sha256
            )
            """,
            row,
        )
        self.connection.commit()
        return self._stored_from_row(row)

    def upsert_labels(self, labels: list[dict[str, object]]) -> None:
        for label in labels:
            _ = self.connection.execute(
                """
                INSERT OR REPLACE INTO labels (
                    id, name, type, message_list_visibility, label_list_visibility
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(label.get("id") or ""),
                    str(label.get("name") or ""),
                    str(label.get("type") or ""),
                    str(label.get("messageListVisibility") or ""),
                    str(label.get("labelListVisibility") or ""),
                ),
            )
        self.connection.commit()

    def list_messages(self, limit: int = 50) -> list[StoredMessage]:
        rows = self.connection.execute(
            """
            SELECT * FROM messages
            ORDER BY sort_timestamp DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._stored_from_sqlite_row(row) for row in rows]

    def find_messages(
        self,
        *,
        gmail_id: str | None = None,
        subject: str | None = None,
        from_filter: str | None = None,
        limit: int = 20,
    ) -> list[StoredMessage]:
        clauses: list[str] = []
        params: list[str | int] = []
        if gmail_id:
            clauses.append("gmail_id = ?")
            params.append(gmail_id)
        if subject:
            clauses.append("LOWER(subject) LIKE ?")
            params.append(f"%{subject.lower()}%")
        if from_filter:
            clauses.append("LOWER(from_addr) LIKE ?")
            params.append(f"%{from_filter.lower()}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            f"""
            SELECT * FROM messages
            {where}
            ORDER BY sort_timestamp DESC, id DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()
        return [self._stored_from_sqlite_row(row) for row in rows]

    def read_body(self, message: StoredMessage, full: bool = False) -> dict[str, object]:
        raw = message.mime_path.read_bytes()
        parsed = BytesParser(policy=policy.default).parsebytes(raw)
        body = parsed.get_body(preferencelist=("plain", "html"))
        if body is None:
            text = ""
            source = "empty"
        else:
            text = str(body.get_content())
            source = body.get_content_type()
        truncated = False
        remaining = 0
        if not full and len(text) > 10_000:
            remaining = len(text) - 10_000
            text = text[:10_000]
            truncated = True
        return {
            "gmail_id": message.gmail_id,
            "thread_id": message.thread_id,
            "from": message.from_addr,
            "to": message.to_addr,
            "cc": message.cc_addr,
            "subject": message.subject,
            "date": message.date,
            "labels": message.labels,
            "body_source": source,
            "body": text,
            "body_truncated": truncated,
            "body_truncated_remaining_chars": remaining,
        }

    def export_markdown(
        self,
        *,
        output_dir: Path | None = None,
        allow_unsafe_output_dir: bool = False,
        force: bool = False,
        limit: int = 100,
        subject: str | None = None,
        from_filter: str | None = None,
    ) -> list[dict[str, str]]:
        target = output_dir or self.markdown_dir
        if output_dir is not None and not allow_unsafe_output_dir:
            resolved_target = target.resolve(strict=False)
            resolved_data = self.data_dir.resolve(strict=False)
            if not resolved_target.is_relative_to(resolved_data):
                raise ValueError(
                    "Refusing to export private email outside the mail data directory without --unsafe-output-dir"
                )
        target.mkdir(parents=True, exist_ok=True)
        exported: list[dict[str, str]] = []
        messages = self.find_messages(subject=subject, from_filter=from_filter, limit=limit)
        for message in messages:
            body = self.read_body(message, full=True)
            filename = _markdown_filename(message)
            path = target / filename
            if path.exists() and not force:
                continue
            path.write_text(_markdown_document(message, body), encoding="utf-8")
            exported.append({"gmail_id": message.gmail_id, "path": str(path)})
        return exported

    def _mime_path(self, metadata: dict[str, object], gmail_id: str) -> Path:
        date_part = _slug(str(metadata.get("date") or "unknown"))[:24] or "unknown"
        subject_part = _slug(str(metadata.get("subject") or "no-subject"))[:60] or "no-subject"
        return self.messages_dir / f"{date_part}_{subject_part}_{gmail_id[:12]}.eml"

    def _stored_from_sqlite_row(self, row: tuple[Any, ...]) -> StoredMessage:
        keys = [item[1] for item in self.connection.execute("PRAGMA table_info(messages)").fetchall()]
        return self._stored_from_row(dict(zip(keys, row)))

    def _stored_from_row(self, row: Mapping[str, object]) -> StoredMessage:
        labels = json.loads(str(row.get("labels_json") or "[]"))
        return StoredMessage(
            gmail_id=str(row["gmail_id"]),
            thread_id=str(row["thread_id"]),
            subject=str(row.get("subject") or ""),
            from_addr=str(row.get("from_addr") or ""),
            to_addr=str(row.get("to_addr") or ""),
            cc_addr=str(row.get("cc_addr") or ""),
            date=str(row.get("date") or ""),
            snippet=str(row.get("snippet") or ""),
            labels=[str(item) for item in labels] if isinstance(labels, list) else [],
            mime_path=self.data_dir / str(row["mime_path"]),
            downloaded_at=str(row.get("downloaded_at") or ""),
        )


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-").lower()
    return slug or "item"


def _metadata_with_raw_fallback(metadata: dict[str, object], raw_bytes: bytes) -> dict[str, object]:
    normalized = dict(metadata)
    parsed = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    for key, header_name in (
        ("subject", "Subject"),
        ("from_addr", "From"),
        ("to_addr", "To"),
        ("cc_addr", "Cc"),
        ("date", "Date"),
        ("message_id", "Message-ID"),
        ("references", "References"),
    ):
        if not normalized.get(key):
            normalized[key] = str(parsed.get(header_name, ""))
    return normalized


def _sort_timestamp(metadata: Mapping[str, object], downloaded_at: str) -> str:
    internal_date = metadata.get("internal_date")
    if internal_date:
        try:
            milliseconds = int(str(internal_date))
            return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, TypeError, ValueError) as exc:
            internal_date_error = exc
            _ = internal_date_error
    raw_date = str(metadata.get("date") or "")
    if raw_date:
        try:
            parsed = parsedate_to_datetime(raw_date)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError, IndexError, OverflowError) as exc:
            date_parse_error = exc
            _ = date_parse_error
    return downloaded_at


def _markdown_filename(message: StoredMessage) -> str:
    date_part = _slug(message.date)[:24] or "unknown"
    subject_part = _slug(message.subject)[:60] or "no-subject"
    return f"{date_part}_{subject_part}_{message.gmail_id[:12]}.md"


def _markdown_document(message: StoredMessage, body: dict[str, object]) -> str:
    labels = json.dumps(message.labels, ensure_ascii=False)
    return (
        "---\n"
        f"gmail_id: {message.gmail_id}\n"
        f"thread_id: {message.thread_id}\n"
        f"from: {json.dumps(message.from_addr, ensure_ascii=False)}\n"
        f"to: {json.dumps(message.to_addr, ensure_ascii=False)}\n"
        f"cc: {json.dumps(message.cc_addr, ensure_ascii=False)}\n"
        f"subject: {json.dumps(message.subject, ensure_ascii=False)}\n"
        f"date: {json.dumps(message.date, ensure_ascii=False)}\n"
        f"labels: {labels}\n"
        f"body_source: {body.get('body_source')}\n"
        "---\n\n"
        f"# {message.subject or '(no subject)'}\n\n"
        f"From: {message.from_addr}\n\n"
        f"To: {message.to_addr}\n\n"
        f"Date: {message.date}\n\n"
        f"{body.get('body', '')}\n"
    )
