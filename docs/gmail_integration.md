# Gmail Integration Design

## 背景

GDocs skill 现在通过 Google 官方 SDK 操作 Docs 和 Drive。OAuth scope 只有：

```python
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]
```

这两个 scope 不能访问 Gmail。现有 workspace 里能发送邮件，是因为另有 `send_email` skill 通过 Gmail SMTP app password 发信；它和 GDocs OAuth token 没有关系。

如果把 Gmail 放进 GDocs skill，目标不是做一个完整邮件客户端，而是延续 Outlook skill 的 AI-first pipeline：下载邮件到本地、查询和读取、导出 Markdown、发送、回复、archive 和 label 操作。

## 目标功能

第一期应覆盖这些命令：

```bash
python -m gdocs gmail download --days 7 --limit 200 --label INBOX
python -m gdocs gmail search "from:alice@example.com newer_than:7d"
python -m gdocs gmail list-local --limit 50
python -m gdocs gmail read --gmail-id MSG_ID --full
python -m gdocs gmail export-md --days 14 --label INBOX
python -m gdocs gmail send --to alice@example.com --subject "Subject" --body-file body.md --dry-run
python -m gdocs gmail reply --gmail-id MSG_ID --body-file reply.md --dry-run
python -m gdocs gmail archive MSG_ID
python -m gdocs gmail trash MSG_ID
python -m gdocs gmail label list
python -m gdocs gmail label apply MSG_ID --label "Important"
python -m gdocs gmail mark-read MSG_ID
python -m gdocs gmail mark-unread MSG_ID
```

Gmail 和 Outlook 的核心差异在于 Gmail 使用 label，而不是 folder。Archive 也不是移动到一个 Archive folder，而是移除 `INBOX` label。实现里应把这些语义暴露出来，不要照搬 Outlook 的 folder 模型。

## OAuth Scope

最小可用 scope 取决于功能范围：

| 功能 | Scope |
|---|---|
| 只读下载和查询 | `https://www.googleapis.com/auth/gmail.readonly` |
| 只发送 | `https://www.googleapis.com/auth/gmail.send` |
| 下载、发送、archive、trash、label、读未读状态 | `https://www.googleapis.com/auth/gmail.modify` |

第一期如果包含 archive、trash 和 label 操作，应直接使用 `gmail.modify`。它覆盖读写邮件和 label 修改，不需要再叠加 `gmail.readonly` 或 `gmail.send`。

加入新 scope 后，已有 `secrets/token.json` 的授权范围不够。首次执行 Gmail 命令时，需要删除旧 token 或让授权流程重新弹出浏览器，让用户同意新的 Gmail 权限。

## 架构

新增文件建议如下：

```text
gdocs/
├── gmail_client.py     # Gmail API wrapper
├── mail_store.py       # SQLite + .eml metadata store
└── __main__.py         # 增加 gmail subcommand group

data/mail/
├── messages/           # raw .eml
├── markdown/           # YAML frontmatter Markdown
└── mail.db             # SQLite metadata
```

`gmail_client.py` 负责 Google API 调用，职责类似现在的 `client.py`，但不要和 `GoogleDocsClient` 混在一个类里。`mail_store.py` 负责本地缓存，职责参考 Outlook skill 的 `MailStore`，但 schema 按 Gmail 的 `gmail_id`、`thread_id`、`labels_json` 设计。

建议 SQLite schema：

```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    gmail_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL,
    subject TEXT,
    from_addr TEXT,
    to_addr TEXT,
    cc_addr TEXT,
    date TEXT,
    snippet TEXT,
    size INTEGER,
    labels_json TEXT NOT NULL,
    mime_path TEXT NOT NULL,
    downloaded_at TEXT NOT NULL,
    sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS labels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    message_list_visibility TEXT,
    label_list_visibility TEXT
);
```

下载时调用 `users.messages.list` 找 message id，再用 `users.messages.get(format="raw")` 拉取 raw MIME，base64url decode 后保存为 `.eml`。发送和回复使用 Python stdlib `email` 组装 MIME，再用 `users.messages.send`。回复时必须设置 `threadId`，并尽量保留 `In-Reply-To` / `References` header，避免 Gmail 创建新 conversation。

## CLI 行为

所有 Gmail 命令放在 `python -m gdocs gmail ...` 下，保持现有入口不变。这样不会破坏已有 agent skill，也避免现在就把 repo 改名为 `google_workspace_skill`。

命令输出继续使用 JSON。涉及外部写操作的命令必须支持 `--dry-run`，至少包括 `send` 和 `reply`。`archive`、`trash`、`label apply/remove` 也可以支持 `--dry-run`，但它们的 payload 简单，优先级低于发信 dry-run。

本地读取优先走 SQLite + `.eml` 缓存。服务端 Gmail 查询单独作为 `gmail search`，直接暴露 Gmail 原生 query 语法，如 `from:`, `subject:`, `label:`, `newer_than:`, `is:unread`。不要自己发明一套查询 DSL。

## Public OAuth Client Feasibility

当前 GDocs repo 是一个 GitHub public repo：`https://github.com/grapeot/gdocs-skill.git`。现在没有 private/public split，也没有单独的 public slice。

Google OAuth 的分发模式和 Outlook skill 不完全一样。Outlook skill 可以共享一个 Microsoft public client id；Google 也可以做共享 desktop OAuth client，但 Gmail scope 会让验证成本显著上升。

Testing mode 下必须添加 test users。External app 在 Testing 状态时，只有 OAuth consent screen 里列出的 test users 能授权。跳过这一步会遇到 `Error 403: access_denied`。Testing mode 还有限制：最多 100 个 test users；请求 offline access 得到的 refresh token 通常会在 7 天后过期。

把 app 发布到 Production 后，普通用户不再需要被加入 test users。不过只要请求 sensitive 或 restricted scopes，Google 会显示 unverified app warning，且未验证 app 有 100 个新用户的 lifetime cap。要消除 warning 和 cap，需要完成 OAuth verification。

Scope 分类对可行性影响很大：

| Scope 类型 | 例子 | 发布成本 |
|---|---|---|
| Sensitive | Google Docs `documents` 通常属于这一类 | 需要品牌和 scope verification，通常不需要安全评估 |
| Restricted | Gmail scopes、很多 Drive scopes | 需要更严格 verification，通常还需要年度安全评估 |

Gmail API scopes 属于 restricted scopes，包括 `gmail.readonly`、`gmail.send`、`gmail.modify` 等。面向公众分发一个预验证的 Gmail OAuth client，通常需要 verified domain、homepage、privacy policy、功能演示视频、scope justification，以及 Google 要求的 restricted scope 安全评估和后续复审。对个人维护的 OSS 项目，这个成本通常高于实现 Gmail 功能本身。

Desktop OAuth client 还涉及 client secret。Google policy 不建议把 OAuth client credentials 提交到公开 repo。Desktop app 的 secret 实际上不能被当作真正的服务端 secret 保护，但公开提交 `credentials.json` 仍然是风险点。更合理的做法是：repo 不包含真实 `credentials.json`；如果决定提供共享 client，只在文档里解释如何获取，或者发布只含 client id 的模板，并说明用户可以替换成自己的 Google Cloud project。

## 推荐路线

短期路线：保留现有 BYO OAuth client 流程，先实现 Gmail 功能。这样最安全，也不需要立刻处理 public verification。用户仍然需要自己建 Google Cloud project、启用 Docs/Drive/Gmail API、添加 test user。

中期路线：为 Docs-only 使用场景做一个 shared OAuth client。Docs scope 的验证成本相对可控，能显著降低新用户使用 GDocs skill 的门槛。这个 client 不应默认包含 Gmail scope。

长期路线：如果 Gmail 功能真的有公共分发需求，再单独评估 Gmail restricted scope verification。这里要把它当成产品发布工作，而不是工程小改动：需要隐私政策、域名、演示视频、数据处理说明、安全评估和维护成本。

因此，Gmail 功能本身可以放进这个 repo；共享 OAuth client 应该分层推进。Docs-only shared client 可以先做，Gmail shared client 暂时不作为默认目标。

## Open Questions

第一，是否接受 `gmail.modify` 作为第一期 scope。如果只做发送，`gmail.send` 足够；如果要 archive 和 label，`gmail.modify` 更直接。

第二，邮件缓存是否和 Outlook skill 保持完全一致的目录结构。为了 agent 复用搜索习惯，建议保持 `data/mail/messages/` 和 `data/mail/markdown/`。

第三，是否要把项目对外定位从 Google Docs Skill 扩成 Google Workspace Skill。建议暂时不改名，只在 README 里注明 Gmail 是新增能力。等 Gmail、Calendar、Sheets 都进入后，再考虑改名。

## References

- Google Auth Platform publishing status and test users: https://support.google.com/cloud/answer/15549945
- Google OAuth verification requirements: https://support.google.com/cloud/answer/13464321
- Google restricted scopes list: https://support.google.com/cloud/answer/13464325
- Google OAuth 2.0 policies: https://developers.google.com/identity/protocols/oauth2/policies
- Gmail API policy: https://developers.google.com/gmail/api/policy
- OAuth 2.0 for desktop apps: https://developers.google.com/identity/protocols/oauth2/native-app
