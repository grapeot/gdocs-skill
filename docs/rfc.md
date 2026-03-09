# Google Docs Skill — 技术方案 RFC

## 1. 概述

本文档记录了 Google Docs Skill 的技术选型过程、关键调研发现和最终架构决策。

## 2. 技术选型：三条路线的比较

我们评估了三种实现路径：

### 路线 A：纯 MCP 服务器

使用现有的第三方 MCP 服务器（如 `taylorwilsdon/google_workspace_mcp`）作为中间层，skill 层直接调用 MCP 暴露的工具。

调研发现，`taylorwilsdon/google_workspace_mcp` 是目前最成熟的选项（1731 stars，Python，19 个 Docs 工具 + 14 个 Drive 工具，今日仍在活跃维护）。它基于 FastMCP 3.0+ 构建，支持 OAuth 2.1、多用户、Docker 部署。

优势在于开发速度极快（代码量减少约 90%），认证、重试、错误处理全部由 MCP 层封装。劣势是引入了额外的依赖链：`fastmcp`（社区较小）、MCP 服务器本身 3000+ 行自定义代码、多一层网络抽象增加攻击面。

### 路线 B：Skill + MCP 混合

skill 文件描述业务逻辑和工作流，底层调用 MCP 服务器的工具完成实际 API 操作。这种方式在易用性和灵活性之间取得平衡，但依然继承了 MCP 层的所有依赖风险。

### 路线 C：直接调用 Google 官方 SDK（最终选择）

使用 `google-api-python-client` 直接调用 Google Docs API 和 Drive API，所有认证和业务逻辑在 skill 内部完成。

### 决策理由

最终选择**路线 C**，核心考量如下：

**安全性**是首要因素。MCP 方案引入了 `fastmcp` 等第三方依赖，社区规模小（173 stars），供应链攻击面不可忽视。第三方 MCP 服务器可能缓存凭证、注入非预期逻辑。直接使用 SDK 则只依赖 Google 官方维护的三个包（`google-api-python-client`、`google-auth`、`google-auth-oauthlib`），攻击面最小。

**可控性**是第二个因素。200-300 行自己写的代码，远比 3000+ 行别人的代码更容易理解、调试和维护。出现问题时可以直接查看 API 响应，无需追踪 MCP 中间层。

**工作量**是可接受的代价。SDK 方案确实需要约 16-32 小时（vs MCP 的 3.5-6.5 小时），但这是一次性投入，换来的是长期的安全性和控制力。考虑到这个 skill 会长期使用，这个交换是值得的。

## 3. 关键调研发现

### 3.1 Google Docs API 原生支持 Tabs

这是调研过程中最重要的发现。Google Docs API（约 2024 年 10 月起）已经原生支持文档内的 Tab 操作，包括创建、删除、更新、嵌套。

Tab 对象结构如下：

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

支持的 batchUpdate 操作：

- `addDocumentTab` — 创建新 tab
- `deleteTab` — 删除 tab
- `updateDocumentTabProperties` — 更新 tab 标题、图标等属性

向特定 tab 写入内容时，在 `insertText` 的 `location` 中指定 `tabId` 即可。读取时需在 `documents.get()` 中传入 `includeTabsContent=True`。

这意味着我们不需要用 Heading 模拟 tab 结构，可以使用原生的、用户在 Google Docs UI 中可直接看到和切换的 tab。

### 3.2 搜索能力

Drive API 的 `files().list()` 支持丰富的查询语法：

- `fullText contains '关键词'` — 搜索文档内容（包括正文、标题、描述）
- `name contains '文档名'` — 按标题搜索（仅匹配前缀）
- `modifiedTime > '2024-01-01T00:00:00'` — 按修改时间筛选
- `mimeType = 'application/vnd.google-apps.document'` — 限定文档类型
- `'folder_id' in parents` — 限定文件夹

多条件用 `and` / `or` / `not` 组合。分页通过 `nextPageToken` 实现，每页最多 100 条。性能建议：避免 `corpora='allDrives'`（可能返回不完整结果），优先使用 `modifiedTime` 排序（比 `createdTime` 更快）。

### 3.3 分享与权限

Drive API 的 Permissions 体系：

| 角色 | 对应 UI | 说明 |
|------|---------|------|
| `reader` | 查看者 | 只读 |
| `commenter` | 评论者 | 可查看和评论 |
| `writer` | 编辑者 | 可编辑内容 |
| `owner` | 所有者 | 完全控制，转让需 `transferOwnership=true` |

权限类型：`user`（指定邮箱）、`group`（Google Group）、`domain`（整个域）、`anyone`（公开链接）。

关键注意事项：

- 同一文件的并发权限操作可能冲突，应使用 batch request
- "Anyone with link" 需设置 `allowFileDiscovery=False` 避免文件被搜索引擎索引
- 转让所有权必须先添加为 writer 再升级为 owner
- `sendNotificationEmail=False` 可抑制通知邮件

### 3.4 文档标题修改

标题不属于 Docs API 管辖，而是 Drive API 的文件元数据。通过 `files().update(fileId, body={"name": "新标题"})` 实现。

## 4. 架构设计

### 4.1 整体结构

```
adhoc_jobs/gdocs_skill/
├── docs/
│   ├── prd.md                  # 产品需求
│   ├── rfc.md                  # 本文档
│   ├── skill_google_docs.md    # AI agent 可读的 skill 文件
│   └── working.md              # Changelog + Lessons Learned
├── secrets/                    # OAuth 凭证（.gitignore 排除）
│   ├── credentials.json        # OAuth 客户端凭证
│   └── token.json              # 授权后的 token（自动生成）
├── gdocs/                      # Python 包（可通过 python -m gdocs 调用）
│   ├── __init__.py
│   ├── __main__.py             # CLI 入口（argparse）
│   ├── auth.py                 # OAuth 认证模块
│   ├── client.py               # GoogleDocsClient（SDK 封装）
│   └── markdown.py             # Markdown → Google Docs API 转换
├── tests/
│   ├── unit/                   # 单元测试
│   └── integration/            # 集成测试（真实 API）
├── .gitignore
├── pyproject.toml
└── README.md
```

### 4.2 核心类设计

```python
class GoogleDocsClient:
    """单一入口，封装 Docs + Drive 两个 service"""
    
    def __init__(self):
        self.creds = self._authenticate()
        self.docs_service = build("docs", "v1", credentials=self.creds)
        self.drive_service = build("drive", "v3", credentials=self.creds)
    
    # 认证
    def _authenticate(self) -> Credentials: ...
    
    # 文档操作
    def create_document(self, title, tabs=None) -> dict: ...
    def modify_document(self, doc_id, tab_id, text) -> dict: ...
    
    # Tab 操作
    def _insert_text_to_tab(self, doc_id, tab_id, text) -> None: ...
    
    # 搜索
    def search_documents(self, query, folder_id=None) -> list: ...
    
    # 分享
    def share_document(self, doc_id, email, role) -> dict: ...
    def get_share_link(self, doc_id, public=False) -> str: ...
    
    # 元数据
    def update_title(self, doc_id, new_title) -> dict: ...
```

### 4.3 认证流程

```
首次运行:
  credentials.json → InstalledAppFlow → 浏览器授权 → token.json

后续运行:
  token.json → Credentials → 检查有效性
    → 有效：直接使用
    → 过期：自动 refresh
    → 无法刷新：重新走浏览器授权
```

凭证存储位置：项目目录下的 `secrets/`（已通过 `.gitignore` 排除），权限设为 `600`。

### 4.4 依赖清单

| 包名 | 版本 | 来源 | 用途 |
|------|------|------|------|
| `google-api-python-client` | latest | Google 官方 | API 客户端 |
| `google-auth` | latest | Google 官方 | 凭证管理 |
| `google-auth-oauthlib` | latest | Google 官方 | OAuth 2.0 流程 |

无任何第三方运行时依赖。

### 4.5 OAuth Scope

```python
SCOPES = [
    "https://www.googleapis.com/auth/documents",    # Docs 读写
    "https://www.googleapis.com/auth/drive.file",    # Drive 文件级访问
]
```

选用 `drive.file` 而非 `drive`（完整访问）是遵循最小权限原则：只能访问由本应用创建或用户主动打开的文件。

## 5. Markdown → Google Docs 格式转换

### 5.1 设计动机

Google Docs API 的格式化操作（`updateTextStyle`、`updateParagraphStyle`、`createParagraphBullets`）需要精确的字符索引区间，手工拼装请求非常繁琐且容易出错。为了让 AI agent 能自然地用 Markdown 写入格式化内容，我们实现了一个 Markdown → Google Docs API 请求的转换层。

### 5.2 支持的 Markdown 语法

| Markdown 语法 | Google Docs 对应 | API 请求类型 |
|---------------|-----------------|-------------|
| `# 标题` | Heading 1 | `updateParagraphStyle` (HEADING_1) |
| `## 副标题` | Heading 2 | `updateParagraphStyle` (HEADING_2) |
| `### 小标题` | Heading 3 | `updateParagraphStyle` (HEADING_3) |
| `**加粗**` | 加粗 | `updateTextStyle` (bold) |
| `*斜体*` | 斜体 | `updateTextStyle` (italic) |
| `***加粗斜体***` | 加粗+斜体 | `updateTextStyle` (bold+italic) |
| `` `代码` `` | 等宽字体 | `updateTextStyle` (Courier New) |
| `[文本](url)` | 超链接 | `updateTextStyle` (link) |
| `- 项目` / `* 项目` | 无序列表 | `createParagraphBullets` |
| `1. 项目` | 有序列表 | `createParagraphBullets` |
| `---` / `***` / `___` | 分割线 | `updateParagraphStyle` (CENTER) + `updateTextStyle` (gray, 6pt) |
| `> 引用文本` | 引用块 | `updateParagraphStyle` (indentStart 36pt + borderLeft gray) |

不支持的语法（后续迭代）：代码块、表格、图片。

### 5.3 转换架构

转换分三个阶段：

**Phase 1: 解析（Parse）** — 将 Markdown 文本按行解析为中间表示（Block + TextSegment）。每行根据前缀判断块类型（标题、列表、段落），然后解析行内格式（加粗、斜体、代码、链接）为 TextSegment 列表。

**Phase 2: 生成纯文本（Flatten）** — 将所有 TextSegment 的纯文本拼接，剥掉 Markdown 语法符号，每个 Block 以 `\n` 结尾。

**Phase 3: 生成请求（Generate）** — 遍历 Block 和 Segment，基于累计字符索引生成 Google Docs API 请求。先生成一个 `insertText` 插入全部纯文本，再生成所有格式化请求。

这种"先插入再格式化"的策略避免了交叉插入导致的索引偏移问题。

### 5.4 索引计算

Google Docs 使用 1-based 索引。`insertText` 在 `start_index`（默认 1）处插入文本后，后续格式化请求的 `range.startIndex` 和 `range.endIndex` 基于插入后的文档状态计算。对于多 Tab 文档，所有 range 和 location 都需要包含 `tabId`。

## 6. CLI 设计

### 6.1 设计动机

原来 AI agent 使用此 skill 时需要现场写 Python 代码（导入模块、创建 client、调用方法）。这要求 agent 正确处理 venv 激活、import 路径、credentials 目录等细节，容易出错。CLI 将所有细节封装为子命令，agent 只需执行一行 bash 命令。

### 6.2 入口方式

选择 `python -m gdocs` 而非安装 console_scripts，原因：不需要全局安装，项目完全自包含，和现有 venv 结构一致。

### 6.3 输出规范

所有输出为 JSON（`ensure_ascii=False, indent=2`），便于 AI agent 和脚本解析。错误输出到 stderr，格式为 `{"error": "message"}`，exit code 为 1。

### 6.4 子命令列表

| 子命令 | 用途 | 示例 |
|--------|------|------|
| `publish <file>` | 发布 Markdown 文件为 Google Doc | `python -m gdocs publish report.md --title "报告"` |
| `create` | 创建空文档 | `python -m gdocs create --title "新文档"` |
| `search <query>` | 搜索文档 | `python -m gdocs search "前线"` |
| `share <doc_id>` | 分享文档 | `python -m gdocs share DOC_ID --email user@example.com` |
| `title <doc_id> <title>` | 修改标题 | `python -m gdocs title DOC_ID "新标题"` |
| `link <doc_id>` | 获取链接 | `python -m gdocs link DOC_ID --public` |
| `tab rename` | 重命名 Tab | `python -m gdocs tab rename DOC_ID TAB_ID "新名"` |
| `tab replace` | 替换 Tab 内容 | `python -m gdocs tab replace DOC_ID TAB_ID file.md` |

## 7. API 调用模式

### 5.1 创建带 Tab 的文档

分三步完成：

1. `documents().create()` 创建空文档
2. `documents().batchUpdate()` 使用 `addDocumentTab` 添加 tab
3. `documents().get(includeTabsContent=True)` 获取 tab ID
4. `documents().batchUpdate()` 使用 `insertText` + `tabId` 填充内容

注意：新文档自带一个默认 tab，添加新 tab 后需要根据业务需求决定是否保留或删除默认 tab。

### 5.2 搜索文档

```python
query = "fullText contains '关键词' and mimeType='application/vnd.google-apps.document' and trashed=false"
drive_service.files().list(
    q=query,
    pageSize=10,
    fields="files(id, name, webViewLink, modifiedTime)"
).execute()
```

搜索词中的单引号需要转义：`text.replace("'", "\\'")`。

### 5.3 分享文档

```python
permission = {"type": "user", "role": "writer", "emailAddress": "user@example.com"}
drive_service.permissions().create(
    fileId=doc_id,
    body=permission,
    sendNotificationEmail=True
).execute()
```

获取分享链接：`drive_service.files().get(fileId=doc_id, fields="webViewLink").execute()`

## 6. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Google API 限流 | 请求被拒 | 指数退避重试，respect quota |
| Token 过期且无法刷新 | 功能中断 | 自动重走 OAuth 流程 |
| Tab API 行为变更 | 功能异常 | Tab 是较新功能，关注 changelog |
| 搜索结果不完整 | 遗漏文档 | 避免 `corpora='allDrives'`，检查 `incompleteSearch` 字段 |
| credentials.json 泄露 | 安全事故 | `.gitignore` 排除，文件权限 `600` |

## 8. 后续迭代方向

- 扩展 Markdown 支持（代码块、表格）
- 支持文档模板（从模板创建新文档）
- 支持 Google Sheets 基础操作
- 批量操作优化（一次 batchUpdate 完成多个操作）
- 嵌套 tab 支持（子 tab）

## 9. 参考资料

- [Google Docs API Reference](https://developers.google.com/workspace/docs/api/reference/rest)
- [Google Docs Tabs Guide](https://developers.google.com/workspace/docs/api/how-tos/tabs)
- [Google Drive API v3 Permissions](https://developers.google.com/workspace/drive/api/reference/rest/v3/permissions)
- [Google Drive Search Query Syntax](https://developers.google.com/workspace/drive/api/guides/search-files)
- [google-api-python-client](https://github.com/googleapis/google-api-python-client)
- [Google OAuth 2.0 Best Practices](https://developers.google.com/identity/protocols/oauth2/resources/best-practices)
