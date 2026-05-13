# Google Docs Skill — Architecture Decisions

## 1. Technology Choice: Direct SDK over MCP

We evaluated three implementation paths for connecting AI agents to Google Docs.

### Option A: Pure MCP server

Use a third-party MCP server (e.g., `taylorwilsdon/google_workspace_mcp`, currently the most mature option at ~1700 stars) as middleware. This would reduce our code to roughly 15–30 lines of glue. However, it introduces `fastmcp` (community of ~170 stars), the MCP server's own ~3000 lines of custom code, and an additional network abstraction layer — all of which expand the security attack surface.

### Option B: Hybrid Skill + MCP

Skill file describes workflows; MCP server handles API calls. Inherits all dependency risks of Option A.

### Option C: Direct Google SDK (chosen)

Use `google-api-python-client` to call Docs and Drive APIs directly. All authentication and business logic lives inside the skill. Approximately 300 lines of our own code. Dependencies limited to three Google-maintained packages (`google-api-python-client`, `google-auth`, `google-auth-oauthlib`) plus PyYAML for front matter handling.

**Why Option C**: Security is the primary concern. Direct SDK eliminates the `fastmcp` dependency chain and third-party server code — the attack surface shrinks to the Google-maintained SDK alone. Controllability is second: 300 lines of code we wrote is far easier to understand, debug, and modify than 3000+ lines we did not. The one-time development cost of 16–32 hours (vs. 3.5–6.5 hours for MCP) is acceptable for a tool intended for long-term use.

## 2. Key API Observations

### 2.1 Native Tab Support

Google Docs API has supported native document tabs since approximately October 2024. The relevant operations are `addDocumentTab`, `deleteTab`, and `updateDocumentTabProperties`. Content targeting uses `tabId` in the `insertText` location field. This eliminates any need to simulate tabs with heading structures — the tabs users see in the Google Docs UI are the same ones the API creates.

Tab object structure:

```json
{
  "tabProperties": {
    "tabId": "string",
    "title": "string",
    "parentTabId": "string",
    "index": 0,
    "nestingLevel": 0,
    "iconEmoji": "string"
  },
  "childTabs": [],
  "documentTab": {
    "body": { "content": [] }
  }
}
```

### 2.2 Title vs Content API Boundary

Document titles are not managed by the Docs API. They live in Drive API file metadata, modified via `files().update(fileId, body={"name": "new title"})`. The Docs API handles document content; the Drive API handles file-level metadata including name, permissions, and trashed status.

### 2.3 Search via Drive API

`files().list()` with `fullText contains 'query'` searches document body, title, and description. The query syntax supports boolean operators (`and`, `or`, `not`) and metadata filters (`modifiedTime`, `mimeType`, folder `parents`). Results are paginated via `nextPageToken` (up to 100 per page). Single quotes in search terms must be escaped: `text.replace("'", "\\'")`.

Performance note: avoid `corpora='allDrives'` (may return incomplete results); prefer `modifiedTime` sorting over `createdTime` for faster responses.

### 2.4 Permissions Model

Drive API permissions use roles and types:

| Role | UI label | Capability |
|------|---------|------------|
| `reader` | Viewer | Read only |
| `commenter` | Commenter | View and comment |
| `writer` | Editor | Full edit |
| `owner` | Owner | Full control (transfer requires `transferOwnership=true`) |

Permission types: `user` (by email), `group` (Google Group), `domain` (entire domain), `anyone` (public link).

Key behaviors: concurrent permission operations on the same file can conflict — use batch requests. "Anyone with link" should set `allowFileDiscovery=False` to prevent search engine indexing. Ownership transfer requires promoting to writer first, then to owner.

## 3. CLI Design

### 3.1 Entry Point

`python -m gdocs` via `gdocs/__main__.py`. No `console_scripts` installation needed — the project is fully self-contained. This approach avoids global installation, keeps the venv structure consistent, and works immediately after `uv pip install -e .`.

### 3.2 Output Contract

Every command writes a single JSON object to stdout (`ensure_ascii=False, indent=2`). Errors go to stderr as `{"error": "message", "status_code": N, "response": "..."}`. Exit code is 0 on success, 1 on error. This format is designed for AI agents and scripts — structured, predictable, and parseable.

### 3.3 Subcommand Structure

Top-level commands for core operations (`publish`, `sync`, `create`, `delete`, `search`, `share`, `title`, `link`, `image`). Nested subcommand groups for operations that bundle related functionality: `tab` (list, add, rename, replace) and `comment` (list, reply, resolve). A global `--secrets-dir` flag allows overriding the default `secrets/` path.

## 4. Idempotent Sync Design

### 4.1 Problem

`publish` creates a new document every time. Real workflows involve repeatedly editing the same Markdown file and expecting changes to land on the same Google Doc. The early workaround — having the AI agent search past session history for the document ID — was fragile (not always findable) and expensive (scanning large session files).

### 4.2 Source of Truth Evaluation

Three options were evaluated for storing the Markdown-to-Google-Doc mapping:

1. **Independent JSON mapping file** (e.g., `~/.gdocs/mappings.json`): breaks when files are moved or renamed; mappings disperse across repos.
2. **Sidecar file** (e.g., `file.md.gdocs.yml`): doubles file count; easy to lose when moving the Markdown file.
3. **YAML front matter in the Markdown file** (chosen): the binding is inseparable from the file; survives moves and renames; human-readable; git-trackable.

The front matter schema follows Jekyll/Hugo conventions:

```yaml
---
gdoc_id: <Google Doc ID>
gdoc_tab_id: <tab ID, defaults to t.0>
gdoc_last_synced: <ISO 8601 timestamp>
---
```

### 4.3 Decision Tree

`python -m gdocs sync file.md` resolves the target document in this priority order:

1. `--gdoc-id` CLI argument (explicit override)
2. `gdoc_id` in the file's YAML front matter
3. If neither exists → create a new document

If a doc ID is resolved, the tool calls `replace_tab_content()` — it reads the current document to find the tab's content range, deletes old content, and writes the new Markdown body. If no doc ID exists, it creates a new document and writes the binding back to the file's front matter. In both paths, `gdoc_last_synced` is updated to the current UTC timestamp.

`--dry-run` prints the planned action (`create` or `replace`), doc ID, and tab ID without calling any API or modifying files.

On first creation, the document body (everything after the front matter delimiter) is what gets written to Google Docs — readers see clean content without the YAML header.

### 4.4 Architecture Separation

The sync logic (`_sync()` function) lives in `__main__.py`, not in `GoogleDocsClient`. This separation is intentional: sync is a workflow orchestrator that combines file I/O, front matter parsing, and multiple client method calls. `GoogleDocsClient` stays purely an API wrapper. The sync function composes `create_document()` and `replace_tab_content()` — both already exist as client methods — and adds the front matter read/write layer.

## 5. Markdown Conversion Pipeline

### 5.1 Three-Phase Architecture

1. **Parse**: Split Markdown text into blocks (heading, paragraph, list, table, blockquote, horizontal rule) and inline segments (bold, italic, code, link). Tables are segmented from text before block-level parsing.
2. **Flatten**: Strip Markdown syntax to produce plain text. Each block ends with `\n`.
3. **Generate**: Walk blocks and segments, compute cumulative character indices, and produce Google Docs API requests. A single `insertText` inserts all plain text first, then formatting requests (`updateTextStyle`, `updateParagraphStyle`, `createParagraphBullets`, `insertTable`) reference positions in the already-inserted text.

The "insert first, format second" strategy avoids index-shifting bugs: all formatting requests reference stable positions in the post-insertion document.

### 5.2 Table Implementation

Content is pre-segmented into text and table segments by `_split_at_tables()`. Each segment generates its own set of API requests with independent index tracking. Segments share an `end_index` variable that carries the cumulative position forward.

`insertTable` API behavior: a table inserted at index N actually occupies positions starting at N+1 (an undocumented +1 offset). The cell position formula is `insertion_index + r*(2*C+1) + 2*c + 4`. Cell text must be inserted in reverse order (last cell first) to avoid index drift from preceding cell insertions. Empty cells are skipped (no empty text insertion).

### 5.3 Limitations (by Design)

No merged cells, column widths, alignment control, code blocks with syntax highlighting, or image embedding within Markdown. These are complex in the Docs API surface and not required for the primary use case (publishing narrative Markdown documents). The conversion pipeline is designed to be extended, not comprehensive.

## 6. Retry and Error Handling

Transient HTTP errors (429, 500, 502, 503, 504) are retried up to 4 times with exponential backoff (1s, 2s, 4s). Permanent errors (4xx other than 429) fail immediately with the full HTTP status code and response body in the error message.

Document creation wraps only the initial `documents().create()` call in retry logic. Subsequent `batchUpdate()` calls are not retried because they may have non-idempotent side effects on a partially-created document. Comment listing and reply operations are fully retried since GET and reply creation are safe to repeat.

Error messages include the failing action, HTTP status code, and truncated response body (capped at 1000 characters) for actionable diagnosis.

## 7. OAuth Design

### 7.1 Scope Selection

```python
SCOPES = [
    "https://www.googleapis.com/auth/documents",   # Read/write document content
    "https://www.googleapis.com/auth/drive.file",   # File-level access (not full Drive)
    "https://www.googleapis.com/auth/gmail.modify", # Gmail read/send/label operations
]
```

`drive.file` (not `drive`) is the minimum-privilege Drive choice. It restricts the app to files it created or the user explicitly opened with it. This limits the credential impact and avoids the justification burden of the full `drive` scope. Gmail uses `gmail.modify` because the implemented CLI needs to read, send, archive, trash, change labels, and update read/unread state.

### 7.2 Credential Lifecycle

```
First run:
  credentials.json → InstalledAppFlow → browser authorization → token.json

Subsequent runs:
  token.json → Credentials → check validity
    → valid: use directly
    → expired with refresh token: auto-refresh, write updated token
    → expired without refresh token, or refresh fails: restart browser flow
```

Credentials are stored in the project-local `secrets/` directory, excluded from git via `.gitignore`, with file permissions set to `600`.

### 7.3 BYO Client Model

This is a public GitHub repository. It does not bundle or distribute OAuth client credentials. Each user creates their own Google Cloud project, enables the required APIs, configures the OAuth consent screen (adding themselves as a test user), and downloads their own `credentials.json`. This model keeps client secrets out of the repository, keeps each user's quota independent, and avoids the regulatory burden of a publicly distributed OAuth application.

For Docs-only usage, OAuth setup is straightforward because `documents` and `drive.file` are sensitive scopes. Gmail scopes such as `gmail.modify` are restricted scopes. A shared pre-verified OAuth client for Gmail would require a broader Google verification process, so this project keeps the bring-your-own OAuth client model.

## 8. Gmail Integration

This section records the final state of the Gmail design originally sketched in [`docs/gmail_integration.md`](gmail_integration.md). The first milestone is implemented: direct Gmail SDK access, `gmail.modify` scope, local `.eml` + SQLite cache, JSON CLI output, dry-run support for mutating operations, and env-gated live tests.

### 8.1 Scope Decision: `gmail.modify`

The Gmail API has three relevant scope tiers:

| Scope | Permits | Limitation |
|-------|---------|------------|
| `gmail.readonly` | Read, search, download | Cannot send or modify |
| `gmail.send` | Send only | Cannot read or modify |
| `gmail.modify` | Read, send, archive, trash, label, mark | Covers all implemented operations |

The tool uses `gmail.modify` because one scope covers the complete first version: downloading, server-side search, sending, replying, archive, trash, label management, and read/unread state. Using narrower scopes would either block core commands or require a confusing multi-scope matrix.

### 8.2 Token Reauthorization

Adding `gmail.modify` after a Docs-only token has already been created requires reauthorization. The practical recovery path is to delete `secrets/token.json` and run any command, such as `python -m gdocs gmail profile`, to trigger the browser flow again. The new token then covers Docs, Drive file access, and Gmail.

### 8.3 Architecture

The Gmail implementation follows the same direct-SDK pattern as Docs:

- `GmailClient` wraps Gmail API calls and stays separate from `GoogleDocsClient` because Gmail has different resources, permissions, and state semantics.
- `MailStore` manages local cache state with raw `.eml` files plus SQLite metadata.
- `__main__.py` owns CLI routing under the `gmail` subcommand group.

The default cache layout is:

```text
data/mail/
├── messages/           # Raw .eml files
├── markdown/           # Markdown export output
└── mail.db             # SQLite database
```

Messages are downloaded via `users.messages.get(format="raw")`, base64url decoded, and saved as `.eml` files. SQLite stores `gmail_id`, `thread_id`, headers, labels as JSON, size, downloaded timestamp, and a SHA-256 content hash. Existing messages are skipped by `gmail_id` on subsequent downloads.

Markdown exports default to `data/mail/markdown/`. A custom `--output-dir` is accepted only when it stays under `data/mail/`; writing outside the mail data directory requires `--unsafe-output-dir` so private email content is not accidentally written into a git-tracked path.

### 8.4 Label Semantics

Gmail uses labels rather than folders. A message can have multiple labels at once, and inbox membership is represented by the `INBOX` label. Archiving removes `INBOX`; marking read removes `UNREAD`; marking unread adds `UNREAD`. User labels and system labels are resolved by name or ID before calling `users.messages.modify`.

`trash` uses the dedicated `users.messages.trash` endpoint because Gmail treats trash as a recoverable state transition rather than a normal label mutation.

### 8.5 Sending and Replying

`send` composes a MIME message with Python's stdlib `EmailMessage` and sends it through `users.messages.send`. `reply` first fetches original message metadata, sets `In-Reply-To` and `References`, includes the original `threadId` in the API payload, and sends through the same endpoint. This keeps replies attached to the existing Gmail conversation.

Both commands support `--body-format text`, `html`, `markdown`, or `md`. Markdown is treated as plain text; HTML is sent as `text/html`.

### 8.6 Live Tests

Gmail live tests are opt-in and never run during a normal test invocation:

- `GDOCS_ENABLE_GMAIL_LIVE_TESTS=1` enables the module
- `GDOCS_GMAIL_LIVE_ALLOW_SEND=1` enables the test that sends a real email
- `GDOCS_GMAIL_LIVE_ALLOW_MUTATE=1` enables the archive mutation in that test
- `GDOCS_GMAIL_LIVE_TEST_TO` optionally overrides the recipient; default is the authenticated account

The tests are marked `pytest.mark.live_integration`.

## 9. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Google API rate limiting | Requests rejected | Exponential backoff retry for transient errors; respect quota |
| Token expiry beyond refresh | Feature interruption | Auto-trigger browser re-authorization |
| Tab API behavior changes | Tab operations break | Monitor Google Workspace changelog; tabs are a relatively new feature |
| Incomplete search results | Missed documents | Avoid `corpora='allDrives'`; check `incompleteSearch` response field |
| Credential file leakage | Security incident | `.gitignore` exclusion; mode `600` on all secret files |
| `insertTable` index behavior changes | Table rendering breaks | The undocumented +1 offset may be API version-dependent; verify on SDK upgrades |
| Gmail restricted scope verification | Shared OAuth client becomes costly to distribute | BYO OAuth client model |
| Local email cache leakage | Private email content exposed | `data/` gitignore entry and explicit docs warning |
| Exported Markdown leakage | Private email bodies written outside ignored cache | Refuse output paths outside `data/mail/` unless `--unsafe-output-dir` is set |

## 10. References

- [Google Docs API Reference](https://developers.google.com/workspace/docs/api/reference/rest)
- [Google Docs Tabs Guide](https://developers.google.com/workspace/docs/api/how-tos/tabs)
- [Drive API v3 Permissions](https://developers.google.com/workspace/drive/api/reference/rest/v3/permissions)
- [Drive Search Query Syntax](https://developers.google.com/workspace/drive/api/guides/search-files)
- [google-api-python-client](https://github.com/googleapis/google-api-python-client)
- [Google OAuth 2.0 Best Practices](https://developers.google.com/identity/protocols/oauth2/resources/best-practices)
- [Gmail API Reference](https://developers.google.com/gmail/api/reference/rest)
- [Gmail API Policy](https://developers.google.com/gmail/api/policy)
