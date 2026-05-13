# Google Docs Skill

CLI tool for Google Docs and Gmail automation via the official Python SDK. All output is JSON — built for both direct use and AI agent consumption.

## What it does

- Create, search, modify, share, and delete Google Docs
- Publish Markdown files to Google Docs with full formatting (headings, bold, italic, lists, tables, blockquotes, inline code, links, horizontal rules)
- Idempotent `sync` command: Markdown files carry their own Google Doc binding via YAML front matter, so repeated updates land on the same document
- Insert local images into documents
- List, reply to, and resolve comments
- Full tab management: list, add, rename, replace content
- Download, search, read, export, send, reply to, archive, trash, and label Gmail messages

## Quick install

```bash
git clone https://github.com/grapeot/gdocs-skill.git
cd gdocs-skill
uv venv
source .venv/bin/activate
uv pip install -e .
```

Dependencies: `google-api-python-client`, `google-auth`, `google-auth-oauthlib`, and `pyyaml`.

## OAuth setup (one-time)

This repo uses a **bring-your-own OAuth client** model. You create a Google Cloud project and download your own credentials. No shared client secrets are distributed.

### Step 1: Create a Google Cloud project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (name it e.g. `gdocs-skill`)
3. Wait a few seconds for the project to be created, then confirm the project selector shows the new name

### Step 2: Enable APIs

1. Search for "Google Docs API" in the console search bar and click **ENABLE**
2. Search for "Google Drive API" and click **ENABLE**
3. Search for "Gmail API" and click **ENABLE**

Verify at the [API Dashboard](https://console.cloud.google.com/apis/dashboard) — all enabled APIs should appear there.

### Step 3: Configure OAuth consent screen

1. Navigate to "OAuth consent screen" in the left sidebar
2. Choose **External** as the user type (unless you have Google Workspace and only need internal use)
3. Fill in required fields: App name (any), user support email, developer contact email
4. On the Scopes page, click **ADD OR REMOVE SCOPES** and add:
   - `https://www.googleapis.com/auth/documents`
   - `https://www.googleapis.com/auth/drive.file`
   - `https://www.googleapis.com/auth/gmail.modify`
5. On the Test users page, click **ADD USERS** and add your own Gmail address
   - **Critical**: skipping this step causes `Error 403: access_denied` instead of the authorization prompt. The app runs in testing mode, and only listed test users can authorize.
6. Save and return to dashboard

### Step 4: Create OAuth credentials

1. Go to [Credentials](https://console.cloud.google.com/apis/credentials)
2. Click **+ CREATE CREDENTIALS** → **OAuth client ID**
3. Choose **Desktop app** as the application type
4. Name it anything (e.g. `gdocs-skill-desktop`)
5. Click **CREATE**, then click **DOWNLOAD JSON** in the dialog

### Step 5: Install the credentials file

```bash
mv ~/Downloads/client_secret_*.json secrets/credentials.json
chmod 600 secrets/credentials.json
```

If you closed the download dialog, go back to the Credentials page, find your OAuth client in the list, and click the download icon on the right.

### Step 6: Verify

```bash
python -m gdocs create --title "Smoke test"
```

On first run, a browser window opens for Google authorization. After authorizing, `secrets/token.json` is created and subsequent runs require no interaction.

If you previously authorized the tool before Gmail support existed, delete `secrets/token.json` and run `python -m gdocs gmail profile` to reauthorize with the new Gmail scope.

## Usage examples

```bash
# Publish a Markdown file as a new Google Doc
python -m gdocs publish report.md --title "Q4 Report"

# Idempotent sync — first run creates the doc, later runs update it
python -m gdocs sync report.md --title "Q4 Report"

# Search your docs
python -m gdocs search "quarterly review"

# Share a document
python -m gdocs share DOC_ID --email colleague@example.com --role writer

# List unresolved comments
python -m gdocs comment list DOC_ID --unresolved-only

# Insert an image
python -m gdocs image DOC_ID chart.png

# Check Gmail profile
python -m gdocs gmail profile

# Download recent inbox messages to data/mail/
python -m gdocs gmail download --days 7 --limit 100 --label INBOX

# Search Gmail server-side with native Gmail query syntax
python -m gdocs gmail search "from:user@example.com newer_than:7d"

# Send an email; use --dry-run first when testing
python -m gdocs gmail send --to user@example.com --subject "Hello" --body-file body.md --dry-run
```

## Command reference

| Command | Purpose |
|---------|---------|
| `publish <file> --title TITLE` | Publish a Markdown file as a new Google Doc (one-shot, no binding) |
| `sync <file> [--title TITLE]` | Idempotent sync: creates on first run, updates on subsequent runs via front matter |
| `create --title TITLE` | Create an empty document |
| `delete DOC_ID [--permanent]` | Move to trash (default, recoverable 30 days) or permanently delete |
| `search QUERY [--max-results N]` | Full-text search across accessible Google Docs |
| `share DOC_ID --email EMAIL [--role ROLE] [--message MSG]` | Share a document with a user |
| `title DOC_ID NEW_TITLE` | Rename a document |
| `link DOC_ID [--public]` | Get the shareable link, optionally enabling public access |
| `tab list DOC_ID` | List all tabs in a document |
| `tab add DOC_ID TITLE [FILE] [--format FMT]` | Add a new tab, optionally with content from a file |
| `tab rename DOC_ID TAB_ID NEW_TITLE` | Rename a tab |
| `tab replace DOC_ID TAB_ID FILE [--format FMT]` | Replace a tab's content from a file |
| `image DOC_ID IMAGE_PATH [--index N] [--width W] [--tab-id ID]` | Insert a local image |
| `comment list DOC_ID [--unresolved-only]` | List document comments |
| `comment reply DOC_ID COMMENT_ID TEXT` | Reply to a comment |
| `comment resolve DOC_ID COMMENT_ID` | Mark a comment as resolved |
| `gmail profile` | Show authenticated Gmail address and mailbox stats |
| `gmail download [--days N] [--limit N] [--label L] [--query Q]` | Download messages to the local `.eml` cache |
| `gmail search QUERY [--limit N] [--label L]` | Search Gmail server-side with native Gmail query syntax |
| `gmail list-local [--limit N]` | List locally cached messages |
| `gmail read [--gmail-id ID] [--subject S] [--from F] [--latest] [--index N] [--full]` | Read a cached message body |
| `gmail export-md [--limit N] [--subject S] [--from F] [--output-dir DIR] [--unsafe-output-dir] [--force]` | Export cached messages as Markdown |
| `gmail send --to ADDR --subject S --body-file F [--cc ADDR] [--bcc ADDR] [--body-format FMT] [--dry-run]` | Send an email |
| `gmail reply --gmail-id ID --body-file F [--to ADDR] [--cc ADDR] [--body-format FMT] [--dry-run]` | Reply to a Gmail thread |
| `gmail archive GMAIL_ID [--dry-run]` | Remove the `INBOX` label |
| `gmail trash GMAIL_ID [--dry-run]` | Move a message to trash |
| `gmail mark-read GMAIL_ID [--dry-run]` | Mark a message as read |
| `gmail mark-unread GMAIL_ID [--dry-run]` | Mark a message as unread |
| `gmail label list` | List Gmail labels |
| `gmail label apply GMAIL_ID --label LABEL [--dry-run]` | Apply a label |
| `gmail label remove GMAIL_ID --label LABEL [--dry-run]` | Remove a label |

All commands output JSON to stdout. Errors go to stderr as `{"error": ..., "status_code": ..., "response": ...}`. Exit code 0 on success, 1 on error.

## Markdown support

Headings (H1–H3), bold, italic, bold+italic, inline code, hyperlinks, unordered lists, ordered lists, horizontal rules, blockquotes, and native tables. See [docs/prd.md](docs/prd.md) for the full format table.

## Safety

- OAuth credentials stored in `secrets/` — excluded from git via `.gitignore`, files set to mode `600`
- OAuth scopes: `documents` (Docs content read/write), `drive.file` (file-level access only), and `gmail.modify` (Gmail read/send/label operations)
- Token auto-refresh; automatic re-authorization if refresh fails
- Retries on transient API errors (HTTP 429 and 5xx) with exponential backoff (1s, 2s, 4s)
- Gmail cache stored in `data/mail/` by default — excluded from git because it contains private email data

The global `--mail-data-dir` flag overrides the Gmail cache location. The default layout is `data/mail/messages/` for raw `.eml`, `data/mail/markdown/` for exports, and `data/mail/mail.db` for SQLite metadata. `gmail export-md --output-dir` refuses paths outside `data/mail/` unless `--unsafe-output-dir` is set, because exported Markdown contains private email bodies.

## Documentation

- [Feature reference](docs/prd.md) — what the tool can do
- [Architecture decisions](docs/rfc.md) — why it works the way it does
- [Changelog](docs/working.md) — history and lessons learned
- [AI agent skill file](docs/skill_google_docs.md) — complete CLI reference with troubleshooting
