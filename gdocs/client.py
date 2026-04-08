from __future__ import annotations

"""Google Docs client: direct SDK wrapper."""

import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .auth import get_credentials
from .markdown import markdown_to_requests


T = TypeVar("T")

# HTTP status codes that indicate transient errors worth retrying.
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _http_error_message(action: str, exc: HttpError) -> str:
    """Build a rich error message from an HttpError including status and body.

    Without this, callers see only "Failed to <action>" with no actionable
    information about whether the error is transient (worth retrying) or
    permanent (need to fix the request).
    """
    status = getattr(exc, "status_code", None) or getattr(exc.resp, "status", "?")
    body = ""
    if exc.content:
        body = exc.content.decode("utf-8", errors="replace")
        if len(body) > 1000:
            body = body[:1000] + "...(truncated)"
    return f"{action}: HTTP {status} — {body}".rstrip(" —")


def _retry_transient(call: Callable[[], T], max_attempts: int = 4, base_delay: float = 1.0) -> T:
    """Retry a callable on transient HttpError (429, 5xx).

    Uses exponential backoff: 1s, 2s, 4s. Permanent errors (4xx other than 429)
    fail immediately. Non-HTTP exceptions also fail immediately.
    """
    for attempt in range(max_attempts):
        try:
            return call()
        except HttpError as exc:
            status = getattr(exc, "status_code", None) or getattr(exc.resp, "status", None)
            if status not in TRANSIENT_STATUS_CODES or attempt == max_attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
    # Unreachable: loop above always raises or returns.
    raise RuntimeError("retry loop exited without result")


class GoogleDocsClient:
    """Single entry point for Google Docs and Drive operations."""

    def __init__(self, secrets_dir: Path):
        """Initialize Google Docs and Drive service clients."""
        creds = get_credentials(secrets_dir)
        self.docs: Any = build("docs", "v1", credentials=creds)
        self.drive: Any = build("drive", "v3", credentials=creds)

    def create_document(
        self,
        title: str,
        tabs: list[dict[str, str]] | None = None,
        content_format: str = "plain",
    ) -> dict[str, str]:
        """Create a new Google Doc, optionally adding document tabs and content.

        Wraps the initial documents.create call in retry logic because Google
        Docs API occasionally returns transient 5xx errors during document
        creation. Subsequent batchUpdate calls are not retried because they may
        have non-idempotent side effects on a partially-created document.
        """
        try:
            created = _retry_transient(
                lambda: self.docs.documents().create(body={"title": title}).execute()
            )
            doc_id = created["documentId"]

            tab_specs = tabs or []
            if not tab_specs:
                return {"id": doc_id, "link": f"https://docs.google.com/document/d/{doc_id}/edit"}

            doc_initial = self.docs.documents().get(
                documentId=doc_id,
                includeTabsContent=True,
                fields="tabs(tabProperties(tabId,title))",
            ).execute()
            default_tab_id = doc_initial["tabs"][0]["tabProperties"]["tabId"]

            first_spec = tab_specs[0]
            first_title = first_spec.get("title")
            if not first_title or not isinstance(first_title, str):
                raise ValueError("Each tab must include a non-empty 'title'")

            rename_requests: list[dict[str, Any]] = [
                {"updateDocumentTabProperties": {
                    "tabProperties": {"tabId": default_tab_id, "title": first_title},
                    "fields": "title",
                }}
            ]
            first_content = first_spec.get("content")
            if isinstance(first_content, str) and first_content:
                if content_format == "markdown":
                    md_reqs, _ = markdown_to_requests(
                        first_content, tab_id=default_tab_id, start_index=1
                    )
                    rename_requests.extend(md_reqs)
                else:
                    rename_requests.append(
                        {"insertText": {
                            "location": {"index": 1, "tabId": default_tab_id},
                            "text": first_content,
                        }}
                    )
            self.docs.documents().batchUpdate(
                documentId=doc_id, body={"requests": rename_requests},
            ).execute()

            remaining_specs = tab_specs[1:]
            if remaining_specs:
                add_requests: list[dict[str, Any]] = []
                for tab in remaining_specs:
                    tab_title = tab.get("title")
                    if not tab_title or not isinstance(tab_title, str):
                        raise ValueError("Each tab must include a non-empty 'title'")
                    props: dict[str, str] = {"title": tab_title}
                    icon = tab.get("icon")
                    if isinstance(icon, str) and icon:
                        props["iconEmoji"] = icon
                    add_requests.append({"addDocumentTab": {"tabProperties": props}})

                self.docs.documents().batchUpdate(
                    documentId=doc_id, body={"requests": add_requests},
                ).execute()

                doc_with_tabs = self.docs.documents().get(
                    documentId=doc_id,
                    includeTabsContent=True,
                    fields="tabs(tabProperties(tabId,title))",
                ).execute()
                all_tabs = doc_with_tabs.get("tabs", [])
                added_tabs = all_tabs[-len(remaining_specs):]

                write_requests: list[dict[str, Any]] = []
                for index, spec in enumerate(remaining_specs):
                    content = spec.get("content")
                    if not isinstance(content, str) or not content:
                        continue
                    if index >= len(added_tabs):
                        break
                    tab_id = added_tabs[index].get("tabProperties", {}).get("tabId")
                    if not isinstance(tab_id, str) or not tab_id:
                        continue
                    if content_format == "markdown":
                        md_requests, _ = markdown_to_requests(
                            content, tab_id=tab_id, start_index=1
                        )
                        write_requests.extend(md_requests)
                    else:
                        write_requests.append(
                            {"insertText": {
                                "location": {"index": 1, "tabId": tab_id},
                                "text": content,
                            }}
                        )

                if write_requests:
                    self.docs.documents().batchUpdate(
                        documentId=doc_id, body={"requests": write_requests},
                    ).execute()

            return {"id": doc_id, "link": f"https://docs.google.com/document/d/{doc_id}/edit"}
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to create document '{title}'", exc)) from exc

    def search_documents(
        self,
        query: str,
        folder_id: str | None = None,
        max_results: int = 10,
    ) -> list[dict[str, str]]:
        """Search Google Docs by content and title using Drive full text query."""
        escaped_query = query.replace("'", "\\'")
        clauses = [
            f"fullText contains '{escaped_query}'",
            "mimeType='application/vnd.google-apps.document'",
            "trashed=false",
        ]
        if folder_id:
            clauses.append(f"'{folder_id}' in parents")

        try:
            response = self.drive.files().list(
                q=" and ".join(clauses),
                pageSize=max_results,
                fields="files(id,name,webViewLink,modifiedTime)",
            ).execute()
            files = response.get("files", [])
            return [
                {
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "link": item.get("webViewLink", ""),
                    "modifiedTime": item.get("modifiedTime", ""),
                }
                for item in files
            ]
        except HttpError as exc:
            raise RuntimeError(_http_error_message("Failed to search Google Docs", exc)) from exc

    def modify_document(
        self, doc_id: str, text: str, tab_id: str | None = None, content_format: str = "plain"
    ) -> dict[str, object]:
        """Insert text into a document, optionally targeting a specific tab."""
        if content_format == "markdown":
            requests, _ = markdown_to_requests(text, tab_id=tab_id, start_index=1)
        else:
            location: dict[str, object] = {"index": 1}
            if tab_id:
                location["tabId"] = tab_id
            requests = [{"insertText": {"location": location, "text": text}}]
        try:
            self.docs.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests},
            ).execute()
            return {"success": True, "doc_id": doc_id}
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to modify document '{doc_id}'", exc)) from exc

    def rename_tab(self, doc_id: str, tab_id: str, new_title: str) -> dict[str, object]:
        """Rename a document tab."""
        try:
            self.docs.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [
                    {"updateDocumentTabProperties": {
                        "tabProperties": {"tabId": tab_id, "title": new_title},
                        "fields": "title",
                    }}
                ]},
            ).execute()
            return {"success": True, "tab_id": tab_id, "new_title": new_title}
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to rename tab '{tab_id}' in document '{doc_id}'", exc)) from exc

    def replace_tab_content(
        self, doc_id: str, tab_id: str, text: str, content_format: str = "plain"
    ) -> dict[str, object]:
        """Replace all content in a tab with new text. Clears existing content first."""
        try:
            doc = self.docs.documents().get(
                documentId=doc_id, includeTabsContent=True,
            ).execute()
            end_index = 1
            for tab in doc.get("tabs", []):
                if tab.get("tabProperties", {}).get("tabId") == tab_id:
                    content_elements = tab.get("documentTab", {}).get("body", {}).get("content", [])
                    if content_elements:
                        end_index = content_elements[-1].get("endIndex", 1)
                    break

            delete_requests: list[dict[str, Any]] = []
            if end_index > 2:
                delete_requests.append(
                    {"deleteContentRange": {
                        "range": {"startIndex": 1, "endIndex": end_index - 1, "tabId": tab_id}
                    }}
                )

            if content_format == "markdown":
                insert_requests, _ = markdown_to_requests(text, tab_id=tab_id, start_index=1)
            else:
                insert_requests = [
                    {"insertText": {"location": {"index": 1, "tabId": tab_id}, "text": text}}
                ]

            self.docs.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": delete_requests + insert_requests},
            ).execute()
            return {"success": True, "doc_id": doc_id, "tab_id": tab_id}
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to replace content in tab '{tab_id}'", exc)) from exc

    def list_tabs(self, doc_id: str) -> list[dict[str, str]]:
        """List all tabs in a document with their IDs and titles."""
        try:
            doc = self.docs.documents().get(
                documentId=doc_id,
                includeTabsContent=True,
                fields="tabs(tabProperties(tabId,title))",
            ).execute()
            return [
                {
                    "tab_id": tab.get("tabProperties", {}).get("tabId", ""),
                    "title": tab.get("tabProperties", {}).get("title", ""),
                }
                for tab in doc.get("tabs", [])
            ]
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to list tabs for document '{doc_id}'", exc)) from exc

    def add_tab(
        self,
        doc_id: str,
        title: str,
        content: str | None = None,
        content_format: str = "plain",
    ) -> dict[str, str]:
        """Add a new tab to a document, optionally with content."""
        try:
            self.docs.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [{"addDocumentTab": {"tabProperties": {"title": title}}}]},
            ).execute()

            doc = self.docs.documents().get(
                documentId=doc_id,
                includeTabsContent=True,
                fields="tabs(tabProperties(tabId,title))",
            ).execute()
            all_tabs = doc.get("tabs", [])
            new_tab = all_tabs[-1]
            tab_id = new_tab.get("tabProperties", {}).get("tabId", "")

            if content:
                if content_format == "markdown":
                    write_requests, _ = markdown_to_requests(content, tab_id=tab_id, start_index=1)
                else:
                    write_requests = [
                        {"insertText": {"location": {"index": 1, "tabId": tab_id}, "text": content}}
                    ]
                self.docs.documents().batchUpdate(
                    documentId=doc_id,
                    body={"requests": write_requests},
                ).execute()

            return {"doc_id": doc_id, "tab_id": tab_id, "title": title}
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to add tab '{title}' to document '{doc_id}'", exc)) from exc

    def update_title(self, doc_id: str, new_title: str) -> dict[str, object]:
        """Update document title via Drive metadata."""
        try:
            self.drive.files().update(fileId=doc_id, body={"name": new_title}).execute()
            return {"success": True, "new_title": new_title}
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to update title for document '{doc_id}'", exc)) from exc

    def delete_document(self, doc_id: str, permanent: bool = False) -> dict[str, object]:
        """Delete a Google Doc.

        By default, moves the document to Drive trash (recoverable for 30 days).
        With permanent=True, deletes immediately and irreversibly. Trash is
        the safer default and matches what users typically want when cleaning
        up scaffold or test docs.
        """
        try:
            if permanent:
                self.drive.files().delete(fileId=doc_id).execute()
                return {"success": True, "doc_id": doc_id, "mode": "permanent"}
            self.drive.files().update(
                fileId=doc_id, body={"trashed": True}
            ).execute()
            return {"success": True, "doc_id": doc_id, "mode": "trash"}
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to delete document '{doc_id}'", exc)) from exc

    def share_document(
        self,
        doc_id: str,
        email: str,
        role: str = "writer",
        send_notification: bool = True,
        message: str | None = None,
    ) -> dict[str, object]:
        """Share a document with a user email and return the resulting document link."""
        valid_roles = {"reader", "writer", "commenter"}
        if role not in valid_roles:
            raise ValueError("role must be one of: reader, writer, commenter")

        permission = {"type": "user", "role": role, "emailAddress": email}
        create_kwargs: dict[str, object] = {
            "fileId": doc_id,
            "body": permission,
            "sendNotificationEmail": send_notification,
        }
        if message:
            create_kwargs["emailMessage"] = message

        try:
            self.drive.permissions().create(**create_kwargs).execute()
            link_data = self.drive.files().get(fileId=doc_id, fields="webViewLink").execute()
            return {"success": True, "link": link_data.get("webViewLink", "")}
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to share document '{doc_id}'", exc)) from exc

    def insert_image(
        self,
        doc_id: str,
        image_path: str,
        index: int | None = None,
        tab_id: str | None = None,
        width_pts: float = 468,
    ) -> dict[str, object]:
        """Insert a local image into a Google Doc.

        Uploads the image to Drive, makes it publicly readable, then uses the
        public URL with InsertInlineImage. If index is None, appends to end.
        width_pts defaults to 468 (full width of a standard Google Doc body).
        """
        img = Path(image_path)
        if not img.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
        mime = mime_map.get(img.suffix.lower(), "image/png")

        try:
            # Upload to Drive
            media = MediaFileUpload(str(img), mimetype=mime, resumable=True)
            uploaded = self.drive.files().create(
                body={"name": img.name, "mimeType": mime},
                media_body=media,
                fields="id,webContentLink",
            ).execute()
            file_id = uploaded["id"]

            # Make publicly readable
            self.drive.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
            ).execute()

            # Get direct content link
            image_url = f"https://drive.google.com/uc?id={file_id}"

            # Find end of document if index not specified
            if index is None:
                doc = self.docs.documents().get(
                    documentId=doc_id, includeTabsContent=True,
                ).execute()
                # Find end index of the relevant tab
                end_index = 1
                for tab in doc.get("tabs", []):
                    tid = tab.get("tabProperties", {}).get("tabId")
                    if tab_id and tid != tab_id:
                        continue
                    content_elements = tab.get("documentTab", {}).get("body", {}).get("content", [])
                    if content_elements:
                        end_index = content_elements[-1].get("endIndex", 1) - 1
                    break
                index = max(end_index, 1)

            location: dict[str, object] = {"index": index}
            if tab_id:
                location["tabId"] = tab_id

            requests = [
                {"insertInlineImage": {
                    "uri": image_url,
                    "location": location,
                    "objectSize": {
                        "width": {"magnitude": width_pts, "unit": "PT"},
                    },
                }}
            ]

            self.docs.documents().batchUpdate(
                documentId=doc_id, body={"requests": requests},
            ).execute()

            return {"success": True, "doc_id": doc_id, "drive_file_id": file_id, "index": index}
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to insert image into document '{doc_id}'", exc)) from exc

    def get_share_link(self, doc_id: str, public: bool = False) -> str:
        """Return a document share link, optionally enabling public link access."""
        try:
            if public:
                self.drive.permissions().create(
                    fileId=doc_id,
                    body={
                        "type": "anyone",
                        "role": "reader",
                        "allowFileDiscovery": False,
                    },
                ).execute()
            file_data = self.drive.files().get(fileId=doc_id, fields="webViewLink").execute()
            return str(file_data.get("webViewLink", ""))
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to get share link for document '{doc_id}'", exc)) from exc
