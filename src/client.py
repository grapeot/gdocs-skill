from __future__ import annotations

"""Google Docs client: direct SDK wrapper."""

from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .auth import get_credentials


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
    ) -> dict[str, str]:
        """Create a new Google Doc, optionally adding document tabs and content."""
        try:
            created = self.docs.documents().create(body={"title": title}).execute()
            doc_id = created["documentId"]

            tab_specs = tabs or []
            if tab_specs:
                add_requests: list[dict[str, Any]] = []
                for tab in tab_specs:
                    tab_title = tab.get("title")
                    if not tab_title or not isinstance(tab_title, str):
                        raise ValueError("Each tab must include a non-empty 'title'")
                    props: dict[str, str] = {"title": tab_title}
                    icon = tab.get("icon")
                    if isinstance(icon, str) and icon:
                        props["iconEmoji"] = icon
                    add_requests.append({"addDocumentTab": {"tabProperties": props}})

                self.docs.documents().batchUpdate(
                    documentId=doc_id,
                    body={"requests": add_requests},
                ).execute()

                doc_with_tabs = self.docs.documents().get(
                    documentId=doc_id,
                    includeTabsContent=True,
                    fields="tabs(tabProperties(tabId,title))",
                ).execute()
                all_tabs = doc_with_tabs.get("tabs", [])
                added_tabs = all_tabs[-len(tab_specs) :] if len(all_tabs) >= len(tab_specs) else []

                write_requests: list[dict[str, Any]] = []
                for index, spec in enumerate(tab_specs):
                    content = spec.get("content")
                    if not isinstance(content, str) or not content:
                        continue
                    if index >= len(added_tabs):
                        break
                    tab_id = added_tabs[index].get("tabProperties", {}).get("tabId")
                    if not isinstance(tab_id, str) or not tab_id:
                        continue
                    write_requests.append(
                        {
                            "insertText": {
                                "location": {"index": 1, "tabId": tab_id},
                                "text": content,
                            }
                        }
                    )

                if write_requests:
                    self.docs.documents().batchUpdate(
                        documentId=doc_id,
                        body={"requests": write_requests},
                    ).execute()

            return {"id": doc_id, "link": f"https://docs.google.com/document/d/{doc_id}/edit"}
        except HttpError as exc:
            raise RuntimeError(f"Failed to create document '{title}'") from exc

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
            raise RuntimeError("Failed to search Google Docs") from exc

    def modify_document(self, doc_id: str, text: str, tab_id: str | None = None) -> dict[str, object]:
        """Insert text into a document, optionally targeting a specific tab."""
        location: dict[str, object] = {"index": 1}
        if tab_id:
            location["tabId"] = tab_id

        request = {"insertText": {"location": location, "text": text}}
        try:
            self.docs.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [request]},
            ).execute()
            return {"success": True, "doc_id": doc_id}
        except HttpError as exc:
            raise RuntimeError(f"Failed to modify document '{doc_id}'") from exc

    def update_title(self, doc_id: str, new_title: str) -> dict[str, object]:
        """Update document title via Drive metadata."""
        try:
            self.drive.files().update(fileId=doc_id, body={"name": new_title}).execute()
            return {"success": True, "new_title": new_title}
        except HttpError as exc:
            raise RuntimeError(f"Failed to update title for document '{doc_id}'") from exc

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
            raise RuntimeError(f"Failed to share document '{doc_id}'") from exc

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
            raise RuntimeError(f"Failed to get share link for document '{doc_id}'") from exc
