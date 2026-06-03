# Skill: Google Docs

CLI tool for operating on Google Docs, Gmail, and Google Calendar via the official Python SDK. All output is JSON — designed for AI agent consumption.

- **Type**: API Guide
- **Project**: `adhoc_jobs/gdocs_skill/`
- **Updated**: 2026-05-20

## When to Use

The user says anything implying a Google Docs operation:

- "Create a Google Doc" / "Publish this to Google Docs"
- "Update the doc" / "Re-sync" / "Push changes to the doc"
- "Search my docs for ..." / "Find the document about ..."
- "Share this with ..." / "Get me a link"
- "What comments are on ..." / "Reply to that comment" / "Resolve it"
- "Add a tab" / "Rename the tab" / "Add an image to the doc"
- "Download recent email" / "Search Gmail for ..." / "Read this email"
- "Inspect this Gmail message header" / "Look at cached threading headers"
- "Send an email" / "Reply to this thread"
- "Archive this message" / "Mark as read" / "Apply this Gmail label"
- "Schedule a meeting" / "Create a calendar event" / "Invite ... to a call"
- "What's on my calendar" / "List events between ..."

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

API-backed Docs, Gmail, and Calendar commands require `secrets/credentials.json`. If missing, guide the user through OAuth setup (steps in the repo `README.md`). Local Gmail cache commands can run with only `data/mail/`. On first OAuth run, a browser opens for Google authorization; after that, `secrets/token.json` persists the session.

Gmail API commands require the `https://www.googleapis.com/auth/gmail.modify` scope; Calendar commands require `https://www.googleapis.com/auth/calendar.events`. Local Gmail cache commands such as `list-local`, `read`, `inspect`, and `export-md` read `data/mail/` directly and do not fetch missing messages. Auth now checks that the stored token covers every required scope and forces reauthorization when it doesn't — so the first API-backed Gmail or Calendar command on an older token will open the OAuth browser flow automatically. If that flow fails, delete `secrets/token.json` and rerun. One token then covers Docs, Drive file access, Gmail, and Calendar.

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
python -m gdocs tab delete DOC_ID TAB_ID      # Delete a tab
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

# List, read, and inspect locally cached messages
python -m gdocs gmail list-local --limit 10
python -m gdocs gmail read --latest
python -m gdocs gmail read --index 0 --full
python -m gdocs gmail read --gmail-id MSG_ID
python -m gdocs gmail inspect --gmail-id MSG_ID
python -m gdocs gmail inspect --gmail-id MSG_ID --thread
# Inspect output includes gmail_id, thread_id, subject, headers, and raw_header_text.
# --thread adds locally cached same-thread messages only; it never fetches missing messages.

# Export cached messages as Markdown
python -m gdocs gmail export-md --limit 50
python -m gdocs gmail export-md --subject "budget" --force
python -m gdocs gmail export-md --output-dir data/mail/custom_exports

# Draft, send, and reply. Use --dry-run before real sends.
python -m gdocs gmail draft --subject "Hello" --body-file body.md
python -m gdocs gmail draft --to user@example.com --subject "Hello" --body-file body.md
python -m gdocs gmail draft --to user@example.com --subject "Invoice" --body-file body.md --attach invoice.pdf
python -m gdocs gmail send --to user@example.com --subject "Hello" --body-file body.md --dry-run
python -m gdocs gmail send --to user@example.com --cc reviewer@example.com --subject "Status" --body-file report.html --body-format html
python -m gdocs gmail send --to user@example.com --subject "Report" --body-file body.md --attach report.pdf
python -m gdocs gmail reply --gmail-id MSG_ID --body-file reply.md --dry-run
python -m gdocs gmail reply --gmail-id MSG_ID --body-file reply.md --attach chart.png

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
- `draft` creates a Gmail draft and never sends. `--to`, `--cc`, and `--bcc` are optional so agents can save no-recipient drafts for human review.
- `--attach` accepts one or more file paths and is supported by `draft`, `send`, and `reply`. Each file is inline-attached with auto-detected MIME type. The output includes `attachment_count` and per-file `name`/`size`. This is equivalent to `mail draft --attach` in Outlook Skill.
- `--dry-run` is available on Gmail send, reply, archive, trash, mark-read, mark-unread, label apply, and label remove.
- `inspect` parses the cached raw `.eml` for `Message-ID`, `In-Reply-To`, `References`, `Subject`, `From`, `To`, `Cc`, and `Date`, plus `raw_header_text` for direct experiment comparison. With `--thread`, it lists only same-thread messages already in SQLite and `messages/`.
- `export-md --output-dir` refuses paths outside `data/mail/` unless `--unsafe-output-dir` is set. Treat exported Markdown as private email data.

### Calendar Commands

All Calendar commands live under `python -m gdocs calendar ...`. Times are RFC 3339 strings (`2026-05-20T10:00:00-07:00` or `2026-05-20T17:00:00Z`); `--calendar-id` defaults to `primary`.

```bash
# Create an event, optionally inviting attendees
python -m gdocs calendar create-event \
  --summary "Planning sync" \
  --start "2026-05-20T10:00:00-07:00" \
  --end "2026-05-20T10:30:00-07:00" \
  --attendee user@example.com --attendee teammate@example.com \
  --description "Quarter kickoff" --location "Zoom" --timezone "America/Los_Angeles"
# Output: {"event_id": "...", "html_link": "...", ...}

# Update an existing event (only --summary is settable for now)
python -m gdocs calendar update-event EVENT_ID --summary "New title"

# Delete an event
python -m gdocs calendar delete-event EVENT_ID

# List events in a window
python -m gdocs calendar list-events \
  --time-min "2026-05-20T00:00:00-07:00" \
  --time-max "2026-05-21T00:00:00-07:00" \
  --max-results 20
# Output: [{"event_id", "summary", "start", "end", "html_link"}, ...]
```

Key semantics:
- `--attendee` is repeatable; each occurrence adds one invitee. Google sends invitation emails automatically.
- `update-event` is currently scoped to title changes. Reschedules/attendee edits aren't exposed via CLI yet — fall back to `delete-event` + `create-event`.
- `list-events` requires `--time-min`. `--time-max` is optional but recommended to bound results.

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

**Gmail/Calendar token reauthorization.** Adding a new scope to an existing token used to surface as an auth error on the first command. The auth module now compares stored scopes against `SCOPES` and reruns the OAuth flow when a scope is missing, so the first Gmail or Calendar command on an old token simply opens the browser. If the auto-flow fails, delete `secrets/token.json` and re-run.

**Gmail download deduplication.** `gmail download` skips messages whose `gmail_id` already exists in the local store. Re-running the same query fetches only new messages.

**Gmail inspect is cache-only.** `gmail inspect --gmail-id ID [--thread]` opens the local SQLite index and cached `.eml` file. It does not initialize the Gmail API client and will fail if the message is missing locally.

**Gmail send is final.** `--dry-run` prints what would be sent without calling the API. Without `--dry-run`, Gmail sends the message.

## Constraints

- OAuth scopes include `documents`, `drive.file`, `gmail.modify`, and `calendar.events`. Drive access remains limited to app-created or user-opened files. Gmail access uses Google's restricted `gmail.modify` scope, so this repo uses a bring-your-own OAuth client. Calendar access is limited to events (not calendar list management).
- All output is JSON. Parse stdout for results, stderr for errors. Exit code 0 = success, 1 = error.
- Credentials live in `secrets/` (gitignored, `chmod 600`). Never commit them.
- Gmail cache lives in `data/mail/` by default (gitignored). It contains private `.eml` files, Markdown exports, and SQLite metadata.
- Export paths outside `data/mail/` require `--unsafe-output-dir`; avoid using it inside a git-tracked project unless the target path is ignored.
- `token.json` auto-refreshes. Only delete it if refresh fails entirely.
- `publish` always creates a new document. For repeated updates to the same doc, use `sync`.
- The `image` command uploads files to Drive; these Drive files persist after insertion and are not cleaned up.
