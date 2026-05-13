# Skill: Google Docs

CLI tool for operating on Google Docs and Gmail via the official Python SDK. All output is JSON — designed for AI agent consumption.

- **Type**: API Guide
- **Project**: `adhoc_jobs/gdocs_skill/`
- **Updated**: 2026-05-12

## When to Use

The user says anything implying a Google Docs operation:

- "Create a Google Doc" / "Publish this to Google Docs"
- "Update the doc" / "Re-sync" / "Push changes to the doc"
- "Search my docs for ..." / "Find the document about ..."
- "Share this with ..." / "Get me a link"
- "What comments are on ..." / "Reply to that comment" / "Resolve it"
- "Add a tab" / "Rename the tab" / "Add an image to the doc"
- "Download recent email" / "Search Gmail for ..." / "Read this email"
- "Send an email" / "Reply to this thread"
- "Archive this message" / "Mark as read" / "Apply this Gmail label"

**Default to `sync` over `publish`** when the Markdown file will be edited repeatedly. `publish` always creates a new document; `sync` binds the file to a specific doc via front matter.

## Activation

Every command requires these two lines first:

```bash
cd /path/to/gdocs-skill
source .venv/bin/activate
```

## Success Criteria

A command succeeded when:
- Exit code is 0 (1 means error — check stderr)
- stdout contains a valid JSON object (not empty, not an error string)
- For create/publish/sync: output contains `id` and `link` fields
- For search: output is a JSON array
- For all others: output contains `"success": true` or the documented fields

If any of these fail, the command did not succeed. Do not assume success without checking exit code.

## Prerequisites

`secrets/credentials.json` must exist. If missing, guide the user through OAuth setup (steps in the repo `README.md`). On first run, a browser opens for Google authorization; after that, `secrets/token.json` persists the session.

Gmail commands require the `https://www.googleapis.com/auth/gmail.modify` scope. If the user authorized this tool before Gmail support existed, delete `secrets/token.json` and run `python -m gdocs gmail profile` to reauthorize. One token then covers Docs, Drive file access, and Gmail.

## CLI Reference

All commands output JSON to stdout, errors to stderr. Global flag: `--secrets-dir PATH` (default: `secrets/`).

### Document Commands

```bash
# Publish Markdown as a new Google Doc (one-shot, always creates)
python -m gdocs publish file.md --title "Title"
python -m gdocs publish file.md --title "Title" --share user@example.com --role writer
# Output: {"id": "...", "link": "https://docs.google.com/document/d/..."}

# Idempotent sync: bind Markdown file to a Google Doc via YAML front matter
python -m gdocs sync file.md --title "Title"          # First sync — creates doc
python -m gdocs sync file.md                           # Subsequent — updates bound doc
python -m gdocs sync file.md --gdoc-id ID --tab-id t.x # Bind to existing doc+tab
python -m gdocs sync file.md --dry-run                 # Preview without side effects
# Create output: {"action": "create", "doc_id": "...", "link": "...", "front_matter_updated": true}
# Replace output: {"action": "replace", "doc_id": "...", "tab_id": "...", "link": "...", "front_matter_updated": true}
# Dry-run output: {"dry_run": true, "action": "create|replace", ...}

# Create empty document
python -m gdocs create --title "Title"
# Output: {"id": "...", "link": "..."}

# Delete (trash by default — recoverable 30 days)
python -m gdocs delete DOC_ID
python -m gdocs delete DOC_ID --permanent

# Search accessible docs
python -m gdocs search "keyword"
python -m gdocs search "keyword" --max-results 20
# Output: [{"id", "name", "link", "modifiedTime"}, ...]

# Share with a user
python -m gdocs share DOC_ID --email user@example.com
python -m gdocs share DOC_ID --email user@example.com --role reader
python -m gdocs share DOC_ID --email user@example.com --role commenter --message "Please review"
# Output: {"success": true, "link": "..."}

# Rename / get link
python -m gdocs title DOC_ID "New Title"
python -m gdocs link DOC_ID
python -m gdocs link DOC_ID --public
```

### Tab Commands

```bash
python -m gdocs tab list DOC_ID               # List all tabs
python -m gdocs tab add DOC_ID "Title"        # Add empty tab
python -m gdocs tab add DOC_ID "Title" file.md # Add tab with content
python -m gdocs tab rename DOC_ID TAB_ID "New" # Rename a tab
python -m gdocs tab replace DOC_ID TAB_ID file.md  # Replace tab content (default markdown)
python -m gdocs tab replace DOC_ID TAB_ID file.txt --format plain
```

### Comment Commands

```bash
python -m gdocs comment list DOC_ID                      # All comments
python -m gdocs comment list DOC_ID --unresolved-only     # Only unresolved
# Output: [{id, author, content, quoted_text, created_time, resolved, replies}, ...]

python -m gdocs comment reply DOC_ID COMMENT_ID "Reply text"
# Output: {id, author, content, created_time}

python -m gdocs comment resolve DOC_ID COMMENT_ID
# Output: {id, resolved: ...}
```

### Image Command

```bash
python -m gdocs image DOC_ID chart.png
python -m gdocs image DOC_ID chart.png --width 468 --index 2050 --tab-id t.abc
# Output: {"success": true, "doc_id": "...", "drive_file_id": "...", "index": N}
```

- Image is uploaded to Drive and made publicly readable for inline display
- `--width` defaults to 468pt (full body width)
- Without `--index`, appends to end of doc (or specified tab)

When inserting images that correspond to `![alt](path.png)` in a Markdown file: publish the Markdown first (alt text becomes plain text), then scan the doc for the alt text positions, and insert images from bottom to top to avoid index drift.

### Gmail Commands

All Gmail commands live under `python -m gdocs gmail ...`. Server-side searches use native Gmail query syntax (`from:`, `subject:`, `newer_than:`, `is:unread`, `label:`, etc.). Local reads use the SQLite + `.eml` cache under `data/mail/` unless `--mail-data-dir` overrides it.

```bash
# Profile
python -m gdocs gmail profile
# Output: {"emailAddress": "...", "messagesTotal": N, "threadsTotal": N}

# Download recent messages to local cache
python -m gdocs gmail download
python -m gdocs gmail download --days 14 --limit 100 --label INBOX
python -m gdocs gmail download --query "from:user@example.com" --include-spam-trash

# Search Gmail server-side
python -m gdocs gmail search "subject:meeting newer_than:7d"
python -m gdocs gmail search "is:unread" --limit 50
# Output: [{"gmail_id": "...", "thread_id": "..."}, ...]

# List and read locally cached messages
python -m gdocs gmail list-local --limit 10
python -m gdocs gmail read --latest
python -m gdocs gmail read --index 0 --full
python -m gdocs gmail read --gmail-id MSG_ID

# Export cached messages as Markdown
python -m gdocs gmail export-md --limit 50
python -m gdocs gmail export-md --subject "budget" --force
python -m gdocs gmail export-md --output-dir data/mail/custom_exports

# Send and reply. Use --dry-run before real sends.
python -m gdocs gmail send --to user@example.com --subject "Hello" --body-file body.md --dry-run
python -m gdocs gmail send --to user@example.com --cc reviewer@example.com --subject "Status" --body-file report.html --body-format html
python -m gdocs gmail reply --gmail-id MSG_ID --body-file reply.md --dry-run

# Message state
python -m gdocs gmail archive GMAIL_ID
python -m gdocs gmail trash GMAIL_ID --dry-run
python -m gdocs gmail mark-read GMAIL_ID
python -m gdocs gmail mark-unread GMAIL_ID

# Labels
python -m gdocs gmail label list
python -m gdocs gmail label apply GMAIL_ID --label "Important"
python -m gdocs gmail label remove GMAIL_ID --label INBOX
```

Key semantics:
- `archive` removes the `INBOX` label. Gmail does not have an Archive folder.
- `trash` calls Gmail's recoverable trash endpoint.
- `label` accepts system label names (`INBOX`, `UNREAD`, `STARRED`, etc.), raw label IDs, or user label names.
- `--body-format` accepts `text`, `html`, `markdown`, or `md`. Markdown is sent as plain text.
- `--dry-run` is available on Gmail send, reply, archive, trash, mark-read, mark-unread, label apply, and label remove.
- `export-md --output-dir` refuses paths outside `data/mail/` unless `--unsafe-output-dir` is set. Treat exported Markdown as private email data.

## Front Matter Contract (sync)

`sync` reads and writes YAML front matter in the Markdown file:

```yaml
---
gdoc_id: <Google Doc ID>
gdoc_tab_id: <tab ID, optional — defaults to t.0>
gdoc_last_synced: <ISO 8601 timestamp>
---
```

The file body (everything after the second `---`) is what gets written to Google Docs. The front matter is stripped before publishing.

Resolution priority: `--gdoc-id` CLI argument > front matter `gdoc_id` field > create new document.

## Supported Markdown

All commands that accept files default to `--format markdown`. Supported conversions:

| Markdown | Google Docs |
|----------|-------------|
| `# text` / `## text` / `### text` | Heading 1 / 2 / 3 |
| `**bold**` / `*italic*` / `***both***` | Bold / Italic / Bold+Italic |
| `` `code` `` | Courier New monospace |
| `[text](url)` | Hyperlink |
| `- item` / `1. item` | Unordered / ordered list |
| `---` / `***` / `___` | Horizontal rule (gray centered line) |
| `> text` | Blockquote (indent + gray left border) |
| `| col \| col \|` | Native table (header row bolded) |

Not supported: code blocks with syntax highlighting, merged table cells, column widths, image syntax (`![]()`). Images must be inserted separately.

## Error Handling

Errors go to stderr as JSON:

```json
{"error": "<message>", "status_code": 429, "response": "<API body or null>"}
```

Decision tree by HTTP status:

- **429 or 5xx** — Transient. The tool auto-retries 4 times with exponential backoff. If it still fails, retry the whole command after waiting. Do not fall back to manual `create` + `tab replace` chains.
- **400** — Bad request. Read the `response` field for the specific API error.
- **401 or 403** — Authentication problem. Delete `secrets/token.json` and re-run. For 403, also verify the user's email is in the OAuth consent screen Test users list.
- **404** — Document not found or no permission.

If `publish` or `sync` renders Markdown as plain text (no formatting), re-apply formatting to the existing doc: `python -m gdocs tab replace DOC_ID t.0 file.md --format markdown`. Use `tab list DOC_ID` to confirm the tab ID. Do not create a new document.

## Known Pitfalls

These are real failure patterns encountered in production:

**OAuth 403 with no visible error page.** When the OAuth consent screen is External + testing mode, the user's Gmail must be in the Test users list. Skipping this causes a raw `Error 403: access_denied` — not the expected "unverified app" page. Guide the user to add their email at https://console.cloud.google.com/auth/audience.

**Publish transient failure cascade.** If `publish` fails with transient errors, do not fall back to `create` → debug → `tab replace` → `share`. This creates cleanup burden and masks the real issue. Auto-retry handles most transient cases; if it exhausts retries, wait and re-run the full command.

**Search scope limitation.** `drive.file` scope means the tool can only search files it created or the user explicitly opened with it. Documents created manually in the Google Docs UI won't appear. This is a scope constraint, not a bug.

**Large files (>15,000 words).** May occasionally trigger 5xx errors. Auto-retry usually handles this. If persistent, split content across multiple tabs.

**Gmail token reauthorization.** Adding the Gmail scope to an existing token can produce an auth error on the first Gmail command. Delete `secrets/token.json` and re-run the command to trigger the full OAuth flow.

**Gmail download deduplication.** `gmail download` skips messages whose `gmail_id` already exists in the local store. Re-running the same query fetches only new messages.

**Gmail send is final.** `--dry-run` prints what would be sent without calling the API. Without `--dry-run`, Gmail sends the message.

## Constraints

- OAuth scopes include `documents`, `drive.file`, and `gmail.modify`. Drive access remains limited to app-created or user-opened files. Gmail access uses Google's restricted `gmail.modify` scope, so this repo uses a bring-your-own OAuth client.
- All output is JSON. Parse stdout for results, stderr for errors. Exit code 0 = success, 1 = error.
- Credentials live in `secrets/` (gitignored, `chmod 600`). Never commit them.
- Gmail cache lives in `data/mail/` by default (gitignored). It contains private `.eml` files, Markdown exports, and SQLite metadata.
- Export paths outside `data/mail/` require `--unsafe-output-dir`; avoid using it inside a git-tracked project unless the target path is ignored.
- `token.json` auto-refreshes. Only delete it if refresh fails entirely.
- `publish` always creates a new document. For repeated updates to the same doc, use `sync`.
- The `image` command uploads files to Drive; these Drive files persist after insertion and are not cleaned up.
