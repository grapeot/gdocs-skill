# Working Log

## Changelog

### 2026-05-12

- Implemented Gmail integration: download, server-side search, local read/export, send, reply, archive, trash, read/unread state, and label management.
- Added `gdocs/gmail_client.py` for Gmail API operations and `gdocs/mail_store.py` for SQLite + `.eml` local storage.
- Added Gmail CLI subcommands: `profile`, `download`, `search`, `list-local`, `read`, `export-md`, `send`, `reply`, `archive`, `trash`, `mark-read`, `mark-unread`, `label list`, `label apply`, and `label remove`.
- Expanded OAuth scopes with `https://www.googleapis.com/auth/gmail.modify`. Existing Docs-only tokens need reauthorization.
- Added local cache under `data/mail/`: raw MIME in `messages/`, SQLite metadata in `mail.db`, and optional Markdown export in `markdown/`.
- Markdown export now refuses output paths outside `data/mail/` unless `--unsafe-output-dir` is set.
- Added env-gated Gmail live tests. Normal test runs skip them; send and mutation checks require separate explicit environment variables.
- Verified the gated live flow: profile, search, send, download raw MIME, reply, and archive.

### 2026-04-23

- Added `comment list`, `comment reply`, and `comment resolve` CLI subcommands via Drive API v3. Comments include author, content, quoted text reference, creation time, resolution status, and replies.
- Added `sync` CLI subcommand: idempotent Markdown-to-Google-Doc based on YAML front matter.
  - Motivation: `publish` always creates a new document, forcing the agent to search past sessions for the right doc ID to update. `sync` makes the Markdown file itself the source of truth for its Google Doc binding.
  - Schema: `gdoc_id`, `gdoc_tab_id`, and `gdoc_last_synced` fields in YAML front matter.
  - Decision tree: `--gdoc-id` CLI argument overrides front matter; if a doc ID is found, do `replace_tab_content`; if not, create a new document and write the IDs back to the file.
  - Supports `--dry-run` to preview without side effects; `--share` and `--role` on first creation.
  - New dependency: PyYAML (breaks the previous zero-third-party constraint, but a self-written YAML mini-parser would be error-prone; PyYAML is the most stable YAML library in the Python ecosystem).
  - New module: `gdocs/frontmatter.py` (~90 lines) for YAML front matter parse and serialize.
  - Sync orchestrator lives in `__main__.py` (`_sync()` function); `GoogleDocsClient` stays a pure API wrapper.
  - Added 19 unit tests (11 for frontmatter, 8 for sync) covering parse, serialize, create path, replace path, dry-run, and front matter write-back.
  - Verified end-to-end: bound a project Markdown file to a specific tab in an existing Google Doc, confirmed front matter was written back and tab content updated.

### 2026-03-09

- Added `tab list DOC_ID` CLI command: lists all tabs in a document with IDs and titles.
- Added `tab add DOC_ID "Title" [file] [--format]` CLI command: adds a new tab to an existing document, optionally with content from a file.
- Added `list_tabs()` and `add_tab()` methods to `GoogleDocsClient`.
- Added 8 unit tests for the new tab operations.
- Added Markdown table support:
  - `| col | col |` syntax renders as native Google Docs tables with bolded header rows.
  - Empty cells are correctly skipped (no empty text insertion).
  - Cell text is filled in reverse order to avoid index drift from preceding insertions.
  - Content architecture refactored to segment-based processing: `_split_at_tables()` divides content into text and table segments, each generating independent API requests.
  - Tables can interleave with text blocks.
  - `markdown_to_requests()` return type unchanged — no callers needed modification.
  - Added 10 table-specific unit tests. Total test count: 84, all passing.
  - Verified in a test document: new tab with a 3×3 table and surrounding text rendered correctly.

### 2026-03-08

- Completed technology evaluation: three paths assessed (pure MCP, hybrid, direct SDK). Direct SDK chosen for security (minimum attack surface) and controllability (300 lines of our code vs 3000+ of others). One-time cost of 16–32 hours development accepted for long-term safety.
- Discovered Google Docs API native tab support (since ~October 2024) — no need to simulate tabs with heading structures.
- Completed OAuth 2.0 setup workflow: Google Cloud project creation, API enablement, consent screen configuration (External, test users), Desktop app credential creation.
- Implemented core `GoogleDocsClient` (191 lines) via parallel sub-agents: create, search, modify, share, tab management.
- Implemented `auth.py` (63 lines) for OAuth credential lifecycle.
- Package renamed from `src/` to `gdocs/` to support `python -m gdocs` entry point.
- Implemented `__main__.py` CLI entry with argparse: `publish`, `create`, `search`, `share`, `title`, `link`, `tab rename`, `tab replace` subcommands.
- Implemented `markdown.py` (289 lines initially): three-phase pipeline (parse → flatten → generate) converting Markdown to Google Docs API requests.
- Added horizontal rule support: Google Docs has no native HR API, so implemented as 30× ━ (U+2501) characters in gray 6pt font, centered.
- Added blockquote support: left indent 36pt + gray left border via `updateParagraphStyle`.
- All CLI output set to JSON format for AI agent consumption; errors to stderr.
- Unit tests: 54 passing (auth, client, markdown, CLI). Integration tests: 8 passed, 1 skipped (share test requires `GDOCS_TEST_EMAIL` env var).
- Fixed 6 unit test failures caused by parallel agent interface mismatches: `isinstance(Credentials)` guards failing on MagicMock, missing `fields` parameter assertions, parameter name inconsistencies, `PropertyMock` issues on mock classes.

## Lessons Learned

### API Behavior

- Google Docs API native tab support dates to approximately October 2024. Many Stack Overflow answers and older documentation still claim tabs are unsupported — always verify against the official API reference and Discovery API schema.
- Document titles are modified through Drive API `files().update()`, not Docs API. Docs handles content; Drive handles metadata.
- `insertTable` API has an undocumented +1 index offset: a table inserted at index N occupies positions starting at N+1. The cell position formula is `insertion_index + r*(2*C+1) + 2*c + 4`. This offset is not documented in Google's official reference and was discovered through trial and error by reading the document structure after insertion.
- Table cell text must be inserted in reverse order (last cell first) to prevent earlier insertions from shifting later cell indices. This is the inverse of regular text insertion, where order does not matter after the single `insertText`.
- Mixing text, tables, and more text requires segmenting content at table boundaries, computing indices independently per segment, and chaining segments via a shared `end_index` cursor.
- Google Drive search index has propagation delay. Integration tests searching for newly created or renamed documents need retry logic (2-second intervals, up to 6 attempts).

### OAuth

- When OAuth consent screen is configured as External + unpublished (testing mode), the user's Gmail address must be explicitly added to the Test users list. Skipping this step causes `Error 403: access_denied` rather than the expected "unverified app" warning page. The 403 provides no actionable hint about the missing test user configuration.
- Token refresh is automatic through the Google SDK's `Credentials.refresh()`. Only delete `token.json` and re-authorize if the refresh token itself is revoked or expired.
- Desktop app OAuth flow uses `localhost` callback. The `InstalledAppFlow.run_local_server(port=0)` call binds to an ephemeral port, so no static port configuration is needed.
- Adding a new OAuth scope after `token.json` exists requires reauthorization. For Gmail, deleting `secrets/token.json` and running `python -m gdocs gmail profile` is the clean recovery path.
- Gmail labels need three resolution paths: system labels such as `INBOX`, raw label IDs such as `Label_123`, and user label names fetched from `users.labels.list`.
- Gmail archive is a label mutation: remove `INBOX`. Trash uses a separate recoverable API endpoint.

### Development Practice

- Parallel development of source and test files by separate agents caused interface mismatches: parameter names differed (`email_message` vs `message`), extra parameters in assertions were missing, and type guards (`isinstance(mock, Credentials)`) broke in tests where `MagicMock` is not an instance of the real class. The lesson: stabilize interface signatures before distributing implementation.
- `isinstance(obj, Credentials)` returns `False` for `MagicMock` in unit tests. Use `typing.cast` for type annotations rather than runtime `isinstance` guards when testability matters.
- Tab rename API format: `tabId` must be nested inside `tabProperties`, not as a sibling field. The correct structure is `{"updateDocumentTabProperties": {"tabProperties": {"tabId": "...", "title": "..."}, "fields": "title"}}`. This was confirmed by reading the Google Docs Discovery API schema.

### Architectural

- CLI is a better interface for AI agents than direct Python API calls. It eliminates import path errors, venv activation mistakes, and credential directory confusion. One bash command performs the entire operation, and JSON output is trivially parseable. The trade-off is less flexibility for complex multi-step operations, but the common cases (publish, sync, search, share) are well-served.
- Renaming the package from `src/` to `gdocs/` made `python -m gdocs` work automatically. Packages whose directory name matches the module name require no additional configuration.
- Keeping `_sync()` in `__main__.py` rather than in `client.py` maintains clean separation: `GoogleDocsClient` is a pure API wrapper; `_sync()` is a workflow orchestrator that composes client methods with file I/O and front matter parsing.
- Google Docs has no native horizontal rule insertion API. The simulation approach (repeated box-drawing characters in a styled paragraph) is fragile — it depends on font rendering, may break on different platforms, and does not behave like a real page break. A future API might add native support; until then, this is the best available option.
