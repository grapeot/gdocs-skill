from __future__ import annotations

"""Gmail API client: direct SDK wrapper."""

import base64
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .auth import get_credentials
from .client import _http_error_message, _retry_transient


SYSTEM_LABELS = {
    "INBOX",
    "UNREAD",
    "STARRED",
    "IMPORTANT",
    "SENT",
    "DRAFT",
    "TRASH",
    "SPAM",
    "CATEGORY_SOCIAL",
    "CATEGORY_UPDATES",
    "CATEGORY_FORUMS",
    "CATEGORY_PROMOTIONS",
    "CATEGORY_PERSONAL",
}


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _headers_to_dict(headers: list[dict[str, str]]) -> dict[str, str]:
    return {item.get("name", "").lower(): item.get("value", "") for item in headers}


def _raw_headers_to_dict(raw_bytes: bytes) -> dict[str, str]:
    parsed = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    return {key.lower(): str(value) for key, value in parsed.items()}


def _message_metadata(payload: dict[str, Any]) -> dict[str, object]:
    headers = _headers_to_dict(payload.get("payload", {}).get("headers", []))
    return {
        "gmail_id": payload.get("id", ""),
        "thread_id": payload.get("threadId", ""),
        "label_ids": list(payload.get("labelIds", [])),
        "snippet": payload.get("snippet", ""),
        "size_estimate": payload.get("sizeEstimate", 0),
        "subject": headers.get("subject", ""),
        "from_addr": headers.get("from", ""),
        "to_addr": headers.get("to", ""),
        "cc_addr": headers.get("cc", ""),
        "date": headers.get("date", ""),
        "message_id": headers.get("message-id", ""),
        "references": headers.get("references", ""),
        "internal_date": payload.get("internalDate", ""),
    }


def _message_metadata_from_raw(payload: dict[str, Any], raw_bytes: bytes) -> dict[str, object]:
    metadata = _message_metadata(payload)
    raw_headers = _raw_headers_to_dict(raw_bytes)
    for key, header_name in (
        ("subject", "subject"),
        ("from_addr", "from"),
        ("to_addr", "to"),
        ("cc_addr", "cc"),
        ("date", "date"),
        ("message_id", "message-id"),
        ("references", "references"),
    ):
        if not metadata.get(key):
            metadata[key] = raw_headers.get(header_name, "")
    return metadata


class GmailClient:
    """Single entry point for Gmail operations."""

    def __init__(self, secrets_dir: Path):
        creds = get_credentials(secrets_dir)
        self.gmail: Any = build("gmail", "v1", credentials=creds)

    def get_profile(self) -> dict[str, object]:
        try:
            profile = _retry_transient(
                lambda: self.gmail.users().getProfile(userId="me").execute()
            )
            return {
                "emailAddress": profile.get("emailAddress", ""),
                "messagesTotal": profile.get("messagesTotal", 0),
                "threadsTotal": profile.get("threadsTotal", 0),
            }
        except HttpError as exc:
            raise RuntimeError(_http_error_message("Failed to get Gmail profile", exc)) from exc

    def list_labels(self) -> list[dict[str, object]]:
        try:
            response = _retry_transient(
                lambda: self.gmail.users().labels().list(userId="me").execute()
            )
            return list(response.get("labels", []))
        except HttpError as exc:
            raise RuntimeError(_http_error_message("Failed to list Gmail labels", exc)) from exc

    def resolve_label_id(self, label: str) -> str:
        if label in SYSTEM_LABELS or label.startswith("Label_"):
            return label
        for item in self.list_labels():
            if item.get("id") == label or item.get("name") == label:
                return str(item.get("id", label))
        raise ValueError(f"Gmail label not found: {label}")

    def search_messages(
        self,
        query: str | None = None,
        label_ids: list[str] | None = None,
        max_results: int = 20,
        include_spam_trash: bool = False,
    ) -> list[dict[str, str]]:
        try:
            messages: list[dict[str, str]] = []
            page_token: str | None = None
            while len(messages) < max_results:
                page_size = min(max_results - len(messages), 500)
                kwargs: dict[str, object] = {
                    "userId": "me",
                    "maxResults": page_size,
                    "includeSpamTrash": include_spam_trash,
                }
                if query:
                    kwargs["q"] = query
                if label_ids:
                    kwargs["labelIds"] = label_ids
                if page_token:
                    kwargs["pageToken"] = page_token
                response = _retry_transient(
                    lambda kw=kwargs: self.gmail.users().messages().list(**kw).execute()
                )
                messages.extend(
                    {
                        "gmail_id": str(item.get("id", "")),
                        "thread_id": str(item.get("threadId", "")),
                    }
                    for item in response.get("messages", [])
                )
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            return messages
        except HttpError as exc:
            raise RuntimeError(_http_error_message("Failed to search Gmail messages", exc)) from exc

    def get_message_metadata(self, gmail_id: str) -> dict[str, object]:
        try:
            payload = _retry_transient(
                lambda: self.gmail.users().messages().get(
                    userId="me",
                    id=gmail_id,
                    format="metadata",
                    metadataHeaders=[
                        "Subject",
                        "From",
                        "To",
                        "Cc",
                        "Date",
                        "Message-ID",
                        "References",
                    ],
                ).execute()
            )
            return _message_metadata(payload)
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to get Gmail message '{gmail_id}'", exc)) from exc

    def get_message_raw(self, gmail_id: str) -> tuple[bytes, dict[str, object]]:
        try:
            payload = _retry_transient(
                lambda: self.gmail.users().messages().get(
                    userId="me", id=gmail_id, format="raw"
                ).execute()
            )
            raw = payload.get("raw")
            if not isinstance(raw, str):
                raise RuntimeError(f"Gmail message '{gmail_id}' did not include raw MIME")
            raw_bytes = _base64url_decode(raw)
            return raw_bytes, _message_metadata_from_raw(payload, raw_bytes)
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to download Gmail message '{gmail_id}'", exc)) from exc

    def send_message(
        self,
        *,
        to: list[str],
        subject: str,
        body_text: str,
        body_format: str = "text",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, object]:
        message = _build_email_message(
            to=to,
            subject=subject,
            body_text=body_text,
            body_format=body_format,
            cc=cc or [],
            bcc=bcc or [],
        )
        payload = {"raw": _base64url_encode(message.as_bytes())}
        if dry_run:
            return {
                "dry_run": True,
                "sent": False,
                "to": to,
                "cc": cc or [],
                "bcc": bcc or [],
                "subject": subject,
            }
        try:
            sent = _retry_transient(
                lambda: self.gmail.users().messages().send(userId="me", body=payload).execute()
            )
            return {
                "dry_run": False,
                "sent": True,
                "gmail_id": sent.get("id", ""),
                "thread_id": sent.get("threadId", ""),
                "to": to,
                "subject": subject,
            }
        except HttpError as exc:
            raise RuntimeError(_http_error_message("Failed to send Gmail message", exc)) from exc

    def create_draft(
        self,
        *,
        to: list[str] | None = None,
        subject: str,
        body_text: str,
        body_format: str = "text",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict[str, object]:
        message = _build_email_message(
            to=to or [],
            subject=subject,
            body_text=body_text,
            body_format=body_format,
            cc=cc or [],
            bcc=bcc or [],
            allow_empty_to=True,
        )
        payload = {"message": {"raw": _base64url_encode(message.as_bytes())}}
        try:
            draft = _retry_transient(
                lambda: self.gmail.users().drafts().create(userId="me", body=payload).execute()
            )
            draft_message = draft.get("message", {})
            return {
                "draft_id": draft.get("id", ""),
                "gmail_id": draft_message.get("id", ""),
                "thread_id": draft_message.get("threadId", ""),
                "to": to or [],
                "cc": cc or [],
                "bcc": bcc or [],
                "subject": subject,
                "sent": False,
            }
        except HttpError as exc:
            raise RuntimeError(_http_error_message("Failed to create Gmail draft", exc)) from exc

    def reply_message(
        self,
        *,
        gmail_id: str,
        body_text: str,
        body_format: str = "text",
        to: list[str] | None = None,
        cc: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, object]:
        original = self.get_message_metadata(gmail_id)
        subject = str(original.get("subject") or "")
        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        recipients = to or [str(original.get("from_addr") or "")]
        message = _build_email_message(
            to=recipients,
            subject=reply_subject,
            body_text=body_text,
            body_format=body_format,
            cc=cc or [],
            bcc=[],
        )
        message_id = str(original.get("message_id") or "")
        references = str(original.get("references") or "")
        if message_id:
            message["In-Reply-To"] = message_id
            message["References"] = f"{references} {message_id}".strip()
        payload = {
            "raw": _base64url_encode(message.as_bytes()),
            "threadId": original.get("thread_id", ""),
        }
        if dry_run:
            return {
                "dry_run": True,
                "sent": False,
                "gmail_id": gmail_id,
                "thread_id": original.get("thread_id", ""),
                "to": recipients,
                "subject": reply_subject,
            }
        try:
            sent = _retry_transient(
                lambda: self.gmail.users().messages().send(userId="me", body=payload).execute()
            )
            return {
                "dry_run": False,
                "sent": True,
                "gmail_id": sent.get("id", ""),
                "thread_id": sent.get("threadId", ""),
                "to": recipients,
                "subject": reply_subject,
            }
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to reply to Gmail message '{gmail_id}'", exc)) from exc

    def modify_message(
        self,
        gmail_id: str,
        *,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, object]:
        body = {
            "addLabelIds": add_label_ids or [],
            "removeLabelIds": remove_label_ids or [],
        }
        if dry_run:
            return {"dry_run": True, "gmail_id": gmail_id, **body}
        try:
            result = _retry_transient(
                lambda: self.gmail.users().messages().modify(
                    userId="me", id=gmail_id, body=body
                ).execute()
            )
            return {
                "dry_run": False,
                "gmail_id": result.get("id", gmail_id),
                "thread_id": result.get("threadId", ""),
                "label_ids": result.get("labelIds", []),
            }
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to modify Gmail message '{gmail_id}'", exc)) from exc

    def archive_message(self, gmail_id: str, dry_run: bool = False) -> dict[str, object]:
        return self.modify_message(gmail_id, remove_label_ids=["INBOX"], dry_run=dry_run)

    def mark_read(self, gmail_id: str, dry_run: bool = False) -> dict[str, object]:
        return self.modify_message(gmail_id, remove_label_ids=["UNREAD"], dry_run=dry_run)

    def mark_unread(self, gmail_id: str, dry_run: bool = False) -> dict[str, object]:
        return self.modify_message(gmail_id, add_label_ids=["UNREAD"], dry_run=dry_run)

    def apply_label(self, gmail_id: str, label: str, dry_run: bool = False) -> dict[str, object]:
        return self.modify_message(gmail_id, add_label_ids=[self.resolve_label_id(label)], dry_run=dry_run)

    def remove_label(self, gmail_id: str, label: str, dry_run: bool = False) -> dict[str, object]:
        return self.modify_message(gmail_id, remove_label_ids=[self.resolve_label_id(label)], dry_run=dry_run)

    def trash_message(self, gmail_id: str, dry_run: bool = False) -> dict[str, object]:
        if dry_run:
            return {"dry_run": True, "gmail_id": gmail_id, "trashed": False}
        try:
            result = _retry_transient(
                lambda: self.gmail.users().messages().trash(userId="me", id=gmail_id).execute()
            )
            return {
                "dry_run": False,
                "gmail_id": result.get("id", gmail_id),
                "thread_id": result.get("threadId", ""),
                "trashed": True,
            }
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to trash Gmail message '{gmail_id}'", exc)) from exc


def _build_email_message(
    *,
    to: list[str],
    subject: str,
    body_text: str,
    body_format: str,
    cc: list[str],
    bcc: list[str],
    allow_empty_to: bool = False,
) -> EmailMessage:
    if not to and not allow_empty_to:
        raise ValueError("At least one recipient is required")
    message = EmailMessage()
    subtype = "html" if body_format == "html" else "plain"
    message.set_content(body_text, subtype=subtype)
    if to:
        message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject
    return message
