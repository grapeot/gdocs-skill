# Google Docs Skill — Feature Reference

## Purpose

This CLI tool enables AI agents and scripts to operate on Google Docs and Gmail through the official Google Python SDK. Every operation produces JSON output for programmatic consumption. The tool is designed for consumption by AI agents within a workspace, but works equally well from any terminal.

## Document Lifecycle

**Create** — Produce a new Google Doc with optional tab structures and Markdown-formatted content.

**Delete** — Move to trash (default, recoverable for 30 days) or permanently remove. Intended for cleaning up test and scaffold documents.

**Update title** — Rename the Google Doc via Drive metadata (not Docs content API).

**Search** — Full-text search across accessible documents via Drive API. Returns doc ID, title, link, and modification time. Search scope is limited to files the app created or the user explicitly opened with it, due to the `drive.file` scope.

## Markdown Publishing

Markdown content is converted to Google Docs native formatting through a three-phase pipeline: parse (identify blocks and inline segments), flatten (strip markup to plain text), and generate (produce API formatting requests).

Supported Markdown to Google Docs mappings:

| Markdown | Google Docs rendering |
|----------|----------------------|
| `# Heading` | Heading 1 |
| `## Heading` | Heading 2 |
| `### Heading` | Heading 3 |
| `**bold**` | Bold |
| `*italic*` | Italic |
| `***bold italic***` | Bold + Italic |
| `` `code` `` | Courier New monospace |
| `[text](url)` | Hyperlink |
| `- item` / `* item` | Unordered list |
| `1. item` | Ordered list |
| `---` / `***` / `___` | Horizontal rule (gray centered line, 30× ━) |
| `> quote` | Blockquote (left indent 36pt + gray left border) |
| `| col \| col \|` | Native table (header row bolded) |

Internet links and inline code are supported within all block types. Unsupported by design: code blocks with syntax highlighting, merged table cells, column widths, alignment control, and images embedded within Markdown. Images must be inserted as a separate step.

## Idempotent Sync

The `sync` command solves the problem of repeatedly updating the same Markdown file and needing changes reflected in the same Google Doc. Without sync, each `publish` creates a new document, and finding the right document to update requires searching through past sessions.

**Design**: The Markdown file carries its own Google Doc binding via YAML front matter:

```yaml
---
gdoc_id: <Google Doc ID>
gdoc_tab_id: <tab ID, defaults to t.0>
gdoc_last_synced: <ISO 8601 timestamp>
---

# Document body
```

This means the binding stays with the file — moving or renaming it preserves the mapping. The mapping is git-trackable and human-readable. The document body (everything after the front matter) is what gets written to Google Docs, so readers see clean content.

**Behavior**: `python -m gdocs sync file.md` resolves the target document by checking, in order: the `--gdoc-id` CLI argument, the file's front matter `gdoc_id` field, or neither (triggers creation). If a doc ID is found, the tool replaces the relevant tab's content. If not, it creates a new document and writes the ID back to the file's front matter. The `--dry-run` flag previews what would happen without side effects.

See [docs/rfc.md](rfc.md) for the full decision tree and architecture rationale.

## Tab Management

Google Docs supports native document tabs since approximately October 2024. This tool works with real tabs, not heading-based simulations. Supported operations:

- List all tabs in a document (ID and title)
- Add a new tab, optionally with content from a file
- Rename a tab
- Replace a tab's entire content from a file

## Sharing

Share documents with specific users via email address. Supported roles: `reader` (view only), `commenter` (view and comment), `writer` (full edit). An optional notification message can be included.

Generate public "anyone with the link" access by setting `--public` on the `link` command. Public links set `allowFileDiscovery=False` to prevent search engine indexing.

## Comments

Read and manage document comments via Drive API v3:

- List all comments (with optional filter for unresolved only)
- Reply to a comment
- Resolve a comment (mark it as closed)

Each comment entry includes author, content, the quoted text it references, creation time, resolution status, and any replies.

## Image Insertion

Insert local images (PNG, JPEG, GIF) into a document at a specific character index, or appended to the end of a tab. Images are uploaded to Google Drive and made publicly readable for inline display within the document. Width defaults to 468 points (full width of a standard Google Doc body). When inserting images with Markdown content that references them (e.g., `![alt](path.png)`), insert images after publishing the Markdown, working from bottom to top of the document to avoid index drift from each insertion.

## Gmail Integration

**Implementation status**: Complete for the first Gmail milestone. The implemented surface covers download, search, local list/read/export, send, reply, archive, trash, read/unread state, and label operations.

The Gmail pipeline covers server-side search, local download, local read/export, sending, replying, and message state changes. Gmail commands are grouped under `python -m gdocs gmail ...`. Mutating operations support `--dry-run` where a preview is useful.

| Command | Description |
|---------|-------------|
| `gmail profile` | Show authenticated Gmail address and mailbox stats |
| `gmail download` | Search Gmail and download raw `.eml` to local cache |
| `gmail search` | Server-side search with native Gmail query syntax |
| `gmail list-local` | List messages in the local SQLite cache |
| `gmail read` | Read a cached message body, truncated at 10,000 chars unless `--full` is used |
| `gmail export-md` | Export cached messages as Markdown files with YAML front matter |
| `gmail send` | Send an email via the Gmail API |
| `gmail reply` | Reply to an existing thread using `In-Reply-To`, `References`, and Gmail `threadId` |
| `gmail archive` | Remove the `INBOX` label |
| `gmail trash` | Move a message to Gmail Trash |
| `gmail mark-read` | Remove the `UNREAD` label |
| `gmail mark-unread` | Add the `UNREAD` label |
| `gmail label list` | List system and user-defined labels |
| `gmail label apply` | Add a label to a message |
| `gmail label remove` | Remove a label from a message |

Downloaded messages are stored under `data/mail/` by default:

```text
data/mail/
├── messages/          # Raw .eml files
├── markdown/          # Markdown exports
└── mail.db            # SQLite metadata index
```

The SQLite index supports local filtering by Gmail ID, subject, and sender. Raw `.eml` files preserve MIME content. Messages are deduplicated by `gmail_id` during download. The global `--mail-data-dir` flag overrides the cache location. Markdown exports default to `data/mail/markdown/`; export paths outside `data/mail/` require `--unsafe-output-dir` because they contain private email bodies.

Gmail uses labels rather than folders. Archive removes the `INBOX` label rather than moving the message. User labels and system labels such as `INBOX`, `UNREAD`, `STARRED`, `IMPORTANT`, `SENT`, `DRAFT`, `TRASH`, `SPAM`, and `CATEGORY_*` can be resolved by name or ID.

## Output Contract

All commands write a single JSON object to stdout on success. On error, a JSON error object is written to stderr:

```json
{
  "error": "Failed to create document 'Title': HTTP 503 — <response body>",
  "status_code": 503,
  "response": "<API response body or null>"
}
```

Exit code is 0 on success, 1 on error. Transient API errors (HTTP 429 and 5xx) are retried up to 4 times with exponential backoff (1s, 2s, 4s) before surfacing the error.

## Architecture

```text
gdocs/
├── __main__.py      # CLI entry point: argparse, subcommand routing, sync orchestrator
├── client.py        # GoogleDocsClient — wraps Docs and Drive APIs
├── gmail_client.py  # GmailClient — wraps Gmail API
├── mail_store.py    # MailStore — SQLite + .eml local cache
├── auth.py          # OAuth credential management for Docs, Drive, and Gmail scopes
├── markdown.py      # Markdown to Google Docs API request translator (3-phase pipeline)
└── frontmatter.py   # YAML front matter parse/serialize for sync
```

`GoogleDocsClient` and `GmailClient` are the API wrapper classes, initialized once per CLI invocation with a secrets directory. CLI command handlers instantiate the relevant client and route to the appropriate method. `MailStore` handles local persistence for Gmail. No state is shared between invocations beyond filesystem-stored credentials and the optional Gmail cache. Sync orchestration lives in `__main__.py` (not in `client.py`) to keep API wrapping and workflow logic separate.

## Out of Scope

- Google Sheets, Slides, or Calendar
- Multi-user session management
- Merged table cells or column width control
- Code blocks with syntax highlighting
- Image embedding within Markdown content
- Document templates
