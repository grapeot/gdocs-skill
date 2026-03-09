# pyright: reportMissingTypeStubs=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnusedCallResult=false

from __future__ import annotations

from pathlib import Path

import pytest
from googleapiclient.errors import HttpError
from unittest.mock import MagicMock, PropertyMock, patch

from gdocs.client import GoogleDocsClient


def _make_http_error(status: int = 500, reason: str = "internal error") -> HttpError:
    response = MagicMock()
    type(response).status = PropertyMock(return_value=status)
    type(response).reason = PropertyMock(return_value=reason)
    return HttpError(response, b'{"error": "boom"}')


@pytest.fixture
def client_env():
    creds = MagicMock(name="credentials")
    docs_service = MagicMock(name="docs_service")
    drive_service = MagicMock(name="drive_service")

    def _build(api_name, version, credentials=None, **_kwargs):
        assert credentials is creds
        if (api_name, version) == ("docs", "v1"):
            return docs_service
        if (api_name, version) == ("drive", "v3"):
            return drive_service
        raise AssertionError(f"Unexpected API requested: {(api_name, version)}")

    with patch("gdocs.client.get_credentials", return_value=creds) as get_creds:
        with patch("gdocs.client.build", side_effect=_build) as build_fn:
            client = GoogleDocsClient(Path("/tmp/secrets"))

    get_creds.assert_called_once_with(Path("/tmp/secrets"))
    apis_called = {(c.args[0], c.args[1]) for c in build_fn.call_args_list}
    assert ("docs", "v1") in apis_called
    assert ("drive", "v3") in apis_called

    return client, docs_service, drive_service


def test_create_document_simple(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.create.return_value.execute.return_value = {
        "documentId": "doc-123"
    }

    result = client.create_document("Project Plan")

    assert result["id"] == "doc-123"
    assert result["link"].startswith("https://docs.google.com/")
    assert "doc-123" in result["link"]
    docs_service.documents.return_value.create.assert_called_once_with(body={"title": "Project Plan"})
    docs_service.documents.return_value.batchUpdate.assert_not_called()


def test_create_document_with_tabs(client_env):
    client, docs_service, _ = client_env
    tabs = [
        {"title": "Overview", "content": "Overview content"},
        {"title": "Notes", "content": "Notes content"},
    ]

    docs_service.documents.return_value.create.return_value.execute.return_value = {
        "documentId": "doc-tabs"
    }
    docs_service.documents.return_value.get.return_value.execute.return_value = {
        "tabs": [
            {"tabProperties": {"title": "Overview", "tabId": "tab-1"}},
            {"tabProperties": {"title": "Notes", "tabId": "tab-2"}},
        ]
    }

    result = client.create_document("Tabbed Doc", tabs=tabs)

    assert result["id"] == "doc-tabs"
    assert "doc-tabs" in result["link"]
    assert docs_service.documents.return_value.batchUpdate.call_count == 2

    add_tabs_call = docs_service.documents.return_value.batchUpdate.call_args_list[0]
    add_tabs_requests = add_tabs_call.kwargs["body"]["requests"]
    assert all("addDocumentTab" in req for req in add_tabs_requests)
    assert len(add_tabs_requests) == 2

    docs_service.documents.return_value.get.assert_called_once_with(
        documentId="doc-tabs", includeTabsContent=True, fields="tabs(tabProperties(tabId,title))"
    )

    insert_text_call = docs_service.documents.return_value.batchUpdate.call_args_list[1]
    insert_requests = insert_text_call.kwargs["body"]["requests"]
    assert len(insert_requests) == 2
    assert insert_requests[0]["insertText"]["location"]["tabId"] == "tab-1"
    assert insert_requests[1]["insertText"]["location"]["tabId"] == "tab-2"


def test_search_documents_basic(client_env):
    client, _, drive_service = client_env
    drive_service.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {
                "id": "1",
                "name": "Doc One",
                "webViewLink": "https://docs.google.com/document/d/1/edit",
                "modifiedTime": "2026-03-07T00:00:00Z",
            }
        ]
    }

    result = client.search_documents("Doc", max_results=5)

    assert result == [
        {
            "id": "1",
            "name": "Doc One",
            "link": "https://docs.google.com/document/d/1/edit",
            "modifiedTime": "2026-03-07T00:00:00Z",
        }
    ]
    list_call = drive_service.files.return_value.list.call_args
    assert list_call.kwargs["pageSize"] == 5
    assert "fullText contains 'Doc'" in list_call.kwargs["q"]


def test_search_documents_with_folder(client_env):
    client, _, drive_service = client_env
    drive_service.files.return_value.list.return_value.execute.return_value = {"files": []}

    client.search_documents("Quarterly", folder_id="folder-42")

    query = drive_service.files.return_value.list.call_args.kwargs["q"]
    assert "'folder-42' in parents" in query


def test_search_documents_empty_results(client_env):
    client, _, drive_service = client_env
    drive_service.files.return_value.list.return_value.execute.return_value = {}

    result = client.search_documents("no-match")

    assert result == []


def test_search_documents_escapes_quotes(client_env):
    client, _, drive_service = client_env
    drive_service.files.return_value.list.return_value.execute.return_value = {"files": []}

    client.search_documents("bob's draft")

    query = drive_service.files.return_value.list.call_args.kwargs["q"]
    assert "bob\\'s draft" in query


def test_modify_document_default_tab(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

    result = client.modify_document("doc-1", "Hello")

    assert result == {"success": True, "doc_id": "doc-1"}
    requests = docs_service.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]
    location = requests[0]["insertText"]["location"]
    assert location["index"] == 1
    assert "tabId" not in location


def test_modify_document_specific_tab(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

    result = client.modify_document("doc-1", "Hello tab", tab_id="tab-xyz")

    assert result == {"success": True, "doc_id": "doc-1"}
    requests = docs_service.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]
    location = requests[0]["insertText"]["location"]
    assert location["index"] == 1
    assert location["tabId"] == "tab-xyz"


def test_update_title(client_env):
    client, _, drive_service = client_env
    drive_service.files.return_value.update.return_value.execute.return_value = {
        "id": "doc-2",
        "name": "Renamed",
    }

    result = client.update_title("doc-2", "Renamed")

    assert result == {"success": True, "new_title": "Renamed"}
    drive_service.files.return_value.update.assert_called_once_with(
        fileId="doc-2", body={"name": "Renamed"}
    )


def test_share_document_as_writer(client_env):
    client, _, drive_service = client_env
    drive_service.permissions.return_value.create.return_value.execute.return_value = {}
    drive_service.files.return_value.get.return_value.execute.return_value = {
        "webViewLink": "https://docs.google.com/document/d/doc-3/edit"
    }

    result = client.share_document("doc-3", "user@example.com", role="writer")

    assert result == {
        "success": True,
        "link": "https://docs.google.com/document/d/doc-3/edit",
    }
    permission_body = drive_service.permissions.return_value.create.call_args.kwargs["body"]
    assert permission_body["type"] == "user"
    assert permission_body["role"] == "writer"
    assert permission_body["emailAddress"] == "user@example.com"


def test_share_document_as_reader(client_env):
    client, _, drive_service = client_env
    drive_service.permissions.return_value.create.return_value.execute.return_value = {}
    drive_service.files.return_value.get.return_value.execute.return_value = {
        "webViewLink": "https://docs.google.com/document/d/doc-4/edit"
    }

    client.share_document("doc-4", "reader@example.com", role="reader")

    permission_body = drive_service.permissions.return_value.create.call_args.kwargs["body"]
    assert permission_body["role"] == "reader"


def test_share_document_with_message(client_env):
    client, _, drive_service = client_env
    drive_service.permissions.return_value.create.return_value.execute.return_value = {}
    drive_service.files.return_value.get.return_value.execute.return_value = {
        "webViewLink": "https://docs.google.com/document/d/doc-5/edit"
    }

    client.share_document(
        "doc-5",
        "notify@example.com",
        role="writer",
        message="Please review this doc.",
    )

    create_kwargs = drive_service.permissions.return_value.create.call_args.kwargs
    assert create_kwargs["emailMessage"] == "Please review this doc."


def test_get_share_link_private(client_env):
    client, _, drive_service = client_env
    drive_service.files.return_value.get.return_value.execute.return_value = {
        "webViewLink": "https://docs.google.com/document/d/private-doc/edit"
    }

    result = client.get_share_link("private-doc", public=False)

    assert result == "https://docs.google.com/document/d/private-doc/edit"
    drive_service.permissions.return_value.create.assert_not_called()
    drive_service.files.return_value.get.assert_called_once_with(
        fileId="private-doc", fields="webViewLink"
    )


def test_get_share_link_public(client_env):
    client, _, drive_service = client_env
    drive_service.permissions.return_value.create.return_value.execute.return_value = {}
    drive_service.files.return_value.get.return_value.execute.return_value = {
        "webViewLink": "https://docs.google.com/document/d/public-doc/edit"
    }

    result = client.get_share_link("public-doc", public=True)

    assert result == "https://docs.google.com/document/d/public-doc/edit"
    create_kwargs = drive_service.permissions.return_value.create.call_args.kwargs
    assert create_kwargs["fileId"] == "public-doc"
    assert create_kwargs["body"]["type"] == "anyone"
    assert create_kwargs["body"]["role"] == "reader"


def test_modify_document_markdown(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}
    markdown_requests = [
        {"insertText": {"location": {"index": 1}, "text": "Title\n"}},
        {
            "updateParagraphStyle": {
                "range": {"startIndex": 1, "endIndex": 7},
                "paragraphStyle": {"namedStyleType": "HEADING_1"},
                "fields": "namedStyleType",
            }
        },
    ]

    with patch("gdocs.client.markdown_to_requests", return_value=(markdown_requests, 7)) as md_to_requests:
        result = client.modify_document("doc-1", "# Title", content_format="markdown")

    assert result == {"success": True, "doc_id": "doc-1"}
    md_to_requests.assert_called_once_with("# Title", tab_id=None, start_index=1)
    body = docs_service.documents.return_value.batchUpdate.call_args.kwargs["body"]
    assert body["requests"] == markdown_requests


def test_create_document_with_tabs_markdown(client_env):
    client, docs_service, _ = client_env
    tabs = [{"title": "Overview", "content": "# Intro"}]
    docs_service.documents.return_value.create.return_value.execute.return_value = {
        "documentId": "doc-tabs-md"
    }
    docs_service.documents.return_value.get.return_value.execute.return_value = {
        "tabs": [{"tabProperties": {"title": "Overview", "tabId": "tab-md-1"}}]
    }
    markdown_requests = [
        {"insertText": {"location": {"index": 1, "tabId": "tab-md-1"}, "text": "Intro\n"}},
        {
            "updateParagraphStyle": {
                "range": {"startIndex": 1, "endIndex": 7, "tabId": "tab-md-1"},
                "paragraphStyle": {"namedStyleType": "HEADING_1"},
                "fields": "namedStyleType",
            }
        },
    ]

    with patch("gdocs.client.markdown_to_requests", return_value=(markdown_requests, 7)) as md_to_requests:
        result = client.create_document("Tabbed Doc", tabs=tabs, content_format="markdown")

    assert result["id"] == "doc-tabs-md"
    md_to_requests.assert_called_once_with("# Intro", tab_id="tab-md-1", start_index=1)
    assert docs_service.documents.return_value.batchUpdate.call_count == 2
    write_call = docs_service.documents.return_value.batchUpdate.call_args_list[1]
    assert write_call.kwargs["body"]["requests"] == markdown_requests


def test_rename_tab(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

    result = client.rename_tab("doc-1", "tab-abc", "新标题")

    assert result == {"success": True, "tab_id": "tab-abc", "new_title": "新标题"}
    body = docs_service.documents.return_value.batchUpdate.call_args.kwargs["body"]
    req = body["requests"][0]["updateDocumentTabProperties"]
    assert req["tabProperties"]["tabId"] == "tab-abc"
    assert req["tabProperties"]["title"] == "新标题"
    assert req["fields"] == "title"


def test_replace_tab_content_plain(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.get.return_value.execute.return_value = {
        "tabs": [
            {
                "tabProperties": {"tabId": "tab-xyz"},
                "documentTab": {
                    "body": {
                        "content": [
                            {"endIndex": 1},
                            {"endIndex": 50},
                        ]
                    }
                },
            }
        ]
    }
    docs_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

    result = client.replace_tab_content("doc-2", "tab-xyz", "New content")

    assert result == {"success": True, "doc_id": "doc-2", "tab_id": "tab-xyz"}
    body = docs_service.documents.return_value.batchUpdate.call_args.kwargs["body"]
    requests = body["requests"]
    assert "deleteContentRange" in requests[0]
    delete_range = requests[0]["deleteContentRange"]["range"]
    assert delete_range["startIndex"] == 1
    assert delete_range["endIndex"] == 49
    assert delete_range["tabId"] == "tab-xyz"
    assert "insertText" in requests[1]
    assert requests[1]["insertText"]["text"] == "New content"
    assert requests[1]["insertText"]["location"]["tabId"] == "tab-xyz"


def test_replace_tab_content_markdown(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.get.return_value.execute.return_value = {
        "tabs": [
            {
                "tabProperties": {"tabId": "tab-md"},
                "documentTab": {
                    "body": {
                        "content": [
                            {"endIndex": 1},
                            {"endIndex": 20},
                        ]
                    }
                },
            }
        ]
    }
    docs_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

    markdown_requests = [
        {"insertText": {"location": {"index": 1, "tabId": "tab-md"}, "text": "Title\n"}},
        {
            "updateParagraphStyle": {
                "range": {"startIndex": 1, "endIndex": 7, "tabId": "tab-md"},
                "paragraphStyle": {"namedStyleType": "HEADING_1"},
                "fields": "namedStyleType",
            }
        },
    ]

    with patch("gdocs.client.markdown_to_requests", return_value=(markdown_requests, 7)) as md_to_requests:
        result = client.replace_tab_content("doc-3", "tab-md", "# Title", content_format="markdown")

    assert result == {"success": True, "doc_id": "doc-3", "tab_id": "tab-md"}
    md_to_requests.assert_called_once_with("# Title", tab_id="tab-md", start_index=1)
    body = docs_service.documents.return_value.batchUpdate.call_args.kwargs["body"]
    requests = body["requests"]
    assert "deleteContentRange" in requests[0]
    assert requests[1:] == markdown_requests


def test_replace_tab_content_empty_tab(client_env):

    client, docs_service, _ = client_env
    docs_service.documents.return_value.get.return_value.execute.return_value = {
        "tabs": [
            {
                "tabProperties": {"tabId": "tab-empty"},
                "documentTab": {
                    "body": {
                        "content": [{"endIndex": 1}]
                    }
                },
            }
        ]
    }
    docs_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

    result = client.replace_tab_content("doc-4", "tab-empty", "Hello")

    assert result["success"] is True
    body = docs_service.documents.return_value.batchUpdate.call_args.kwargs["body"]
    requests = body["requests"]
    assert all("deleteContentRange" not in req for req in requests)
    assert requests[0]["insertText"]["text"] == "Hello"


def test_list_tabs(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.get.return_value.execute.return_value = {
        "tabs": [
            {"tabProperties": {"tabId": "tab-1", "title": "Overview"}},
            {"tabProperties": {"tabId": "tab-2", "title": "Notes"}},
        ]
    }

    result = client.list_tabs("doc-1")

    assert result == [
        {"tab_id": "tab-1", "title": "Overview"},
        {"tab_id": "tab-2", "title": "Notes"},
    ]
    docs_service.documents.return_value.get.assert_called_once_with(
        documentId="doc-1", includeTabsContent=True, fields="tabs(tabProperties(tabId,title))"
    )


def test_list_tabs_empty(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.get.return_value.execute.return_value = {}

    result = client.list_tabs("doc-empty")

    assert result == []
    docs_service.documents.return_value.get.assert_called_once_with(
        documentId="doc-empty", includeTabsContent=True, fields="tabs(tabProperties(tabId,title))"
    )


def test_add_tab_without_content(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}
    docs_service.documents.return_value.get.return_value.execute.return_value = {
        "tabs": [{"tabProperties": {"tabId": "tab-new", "title": "New Tab"}}]
    }

    result = client.add_tab("doc-2", "New Tab")

    assert result == {"doc_id": "doc-2", "tab_id": "tab-new", "title": "New Tab"}
    assert docs_service.documents.return_value.batchUpdate.call_count == 1
    add_call = docs_service.documents.return_value.batchUpdate.call_args
    assert add_call.kwargs["documentId"] == "doc-2"
    requests = add_call.kwargs["body"]["requests"]
    assert requests == [{"addDocumentTab": {"tabProperties": {"title": "New Tab"}}}]
    docs_service.documents.return_value.get.assert_called_once_with(
        documentId="doc-2", includeTabsContent=True, fields="tabs(tabProperties(tabId,title))"
    )


def test_add_tab_with_plain_content(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}
    docs_service.documents.return_value.get.return_value.execute.return_value = {
        "tabs": [{"tabProperties": {"tabId": "tab-plain", "title": "Plain Tab"}}]
    }

    result = client.add_tab("doc-3", "Plain Tab", content="Hello tab", content_format="plain")

    assert result == {"doc_id": "doc-3", "tab_id": "tab-plain", "title": "Plain Tab"}
    assert docs_service.documents.return_value.batchUpdate.call_count == 2
    content_call = docs_service.documents.return_value.batchUpdate.call_args_list[1]
    content_requests = content_call.kwargs["body"]["requests"]
    assert content_requests == [
        {"insertText": {"location": {"index": 1, "tabId": "tab-plain"}, "text": "Hello tab"}}
    ]


def test_add_tab_with_markdown_content(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}
    docs_service.documents.return_value.get.return_value.execute.return_value = {
        "tabs": [{"tabProperties": {"tabId": "tab-md", "title": "MD Tab"}}]
    }
    markdown_requests = [{"insertText": {"location": {"index": 1, "tabId": "tab-md"}, "text": "Hi\n"}}]

    with patch("gdocs.client.markdown_to_requests", return_value=(markdown_requests, 4)) as md_to_requests:
        result = client.add_tab("doc-4", "MD Tab", content="# Hi", content_format="markdown")

    assert result == {"doc_id": "doc-4", "tab_id": "tab-md", "title": "MD Tab"}
    md_to_requests.assert_called_once_with("# Hi", tab_id="tab-md", start_index=1)
    assert docs_service.documents.return_value.batchUpdate.call_count == 2
    content_call = docs_service.documents.return_value.batchUpdate.call_args_list[1]
    assert content_call.kwargs["body"]["requests"] == markdown_requests


def test_api_error_handling(client_env):
    client, docs_service, _ = client_env
    docs_service.documents.return_value.create.return_value.execute.side_effect = _make_http_error()

    with pytest.raises(RuntimeError):
        client.create_document("Will fail")
