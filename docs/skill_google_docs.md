# Skill: Google Docs 操作

通过 CLI 命令操控 Google Docs：同步 Markdown 文件、创建文档、搜索、修改、分享、Tab 管理。

## When to Use

用户说出以下意图时触发：
- "帮我创建一个 Google Doc"
- "把这个 Markdown 发到 Google Docs"
- "这份 MD 改了，更新到 Google Docs" / "重新同步一下" → 优先用 `sync`
- "搜索我的 Google Docs"
- "把这个文档分享给 xxx"
- "修改那个文档的标题 / 内容"
- "这个文档上有什么 comments"、"看看评论"
- 任何涉及 Google Docs 创建、搜索、修改、分享、评论的需求

## Prerequisites

- 项目位置：`adhoc_jobs/gdocs_skill/`
- Python venv：`adhoc_jobs/gdocs_skill/.venv/`（用 `uv` 创建）
- OAuth 凭证：`adhoc_jobs/gdocs_skill/secrets/credentials.json` 必须存在
- 首次使用需完成 OAuth 授权（浏览器弹窗），详见项目 `README.md`

## 调用方式

所有命令在项目目录下通过 `python -m gdocs` 调用，输出均为 JSON。

```bash
cd /path/to/knowledge_working/adhoc_jobs/gdocs_skill && source .venv/bin/activate
```

## 常见场景

### 场景 0：幂等同步 Markdown（最常见，优先用）

**当 MD 文件会被反复修改、需要持续更新到同一个 Google Doc 时，用 `sync` 而不是 `publish`。**

`sync` 基于 MD 文件开头的 YAML front matter 记录 doc 绑定：

```yaml
---
gdoc_id: 1CLveZUmbU22YT_i5TGjhysSsxxFOM9h_r_b2-tvjMQ8
gdoc_tab_id: t.t6qmc76tli6j   # 可选，没有就写默认 tab t.0
gdoc_last_synced: 2026-04-23T21:31:38Z
---

# 正文从这里开始
```

三种用法：

```bash
# 1) 首次 sync（还没有 doc）— 创建新 doc，把 doc_id 写回 front matter
python -m gdocs sync report.md --title "报告"

# 2) 已有 front matter — 自动 tab replace，更新 gdoc_last_synced
python -m gdocs sync report.md

# 3) 绑定到已有 doc 的特定 tab — 把两个 id 写进 front matter，同时更新 tab 内容
python -m gdocs sync report.md --gdoc-id DOC_ID --tab-id t.xxx
```

`--dry-run` 打印将要执行的动作（action: create / replace + doc_id + tab_id），不调 API、不写文件。面对已绑定的 MD 时先 dry-run 确认目标是对的，再执行。

**sync 的好处**：
- 幂等——MD 文件持有自己的 doc 映射，AI agent 不需要翻历史找 ID
- source of truth 跟着 MD 走——移动/改名文件不会丢映射
- 不会产生重复 doc

**何时用 publish 而不是 sync**：
- 一次性 throwaway 文档（不打算后续更新）
- 不想在 MD 里出现 front matter

### 场景 1：把一个 Markdown 文件一次性发布到 Google Docs（不回写 front matter）

```bash
python -m gdocs publish path/to/report.md --title "AI 前线 2026-03-08"
```

发布后立刻分享给某人：

```bash
python -m gdocs publish path/to/report.md --title "报告" --share someone@example.com --role writer
```

### 场景 2：Tab 管理

列出文档所有 Tab：

```bash
python -m gdocs tab list DOC_ID
```

给文档添加新 Tab：

```bash
python -m gdocs tab add DOC_ID "Tab标题"
python -m gdocs tab add DOC_ID "Tab标题" path/to/content.md --format markdown
```

更新已有 Tab 的内容（清空后重写）：

```bash
python -m gdocs tab replace DOC_ID TAB_ID path/to/updated.md
```

默认使用 markdown 格式。如需纯文本：

```bash
python -m gdocs tab replace DOC_ID TAB_ID file.txt --format plain
```

重命名 Tab：

```bash
python -m gdocs tab rename DOC_ID TAB_ID "新标题"
```

### 场景 3：创建空文档

```bash
python -m gdocs create --title "新文档"
```

### 场景 4：搜索文档

```bash
python -m gdocs search "关键词"
python -m gdocs search "关键词" --max-results 20
```

### 场景 5：分享文档

```bash
python -m gdocs share DOC_ID --email user@example.com --role writer
python -m gdocs share DOC_ID --email user@example.com --role reader --message "请查看"
```

### 场景 6.5：删除文档（清理 test / 废 docs）

```bash
python -m gdocs delete DOC_ID                # 移到回收站（默认，30 天可恢复）
python -m gdocs delete DOC_ID --permanent    # 立即永久删除（不可恢复）
```

**何时用**：
- 调试 publish / create 失败留下的 test docs
- 一次操作产生多份重复 doc（参见 §故障排查）
- Sub-agent 跑测试自动产生的 scaffold doc

**纪律**：每次 create / publish 之前，先想清楚是否会留下不需要的 doc。如果是 debug 用 doc，**用完立即 delete**，不要留在用户的 Drive 里污染。Default trash 模式让你后悔有 30 天反悔窗口。

### 场景 6：修改标题 / 获取链接

```bash
python -m gdocs title DOC_ID "新标题"
python -m gdocs link DOC_ID
python -m gdocs link DOC_ID --public
```

## 支持的 Markdown 格式

| 语法 | 效果 |
|------|------|
| `# 标题` | Heading 1 |
| `## 标题` | Heading 2 |
| `### 标题` | Heading 3 |
| `**加粗**` | 加粗 |
| `*斜体*` | 斜体 |
| `***加粗斜体***` | 加粗+斜体 |
| `` `代码` `` | 等宽字体 (Courier New) |
| `[文本](url)` | 超链接 |
| `- 项目` | 无序列表 |
| `1. 项目` | 有序列表 |
| `---` | 分割线（灰色居中线） |
| `> 引用文本` | 引用块（左缩进 + 左边框） |
| `\| col \| col \|` | 原生表格（表头自动加粗） |

### 场景 7：查看文档上的评论

列出所有 comments（包括已解决的）：

```bash
python -m gdocs comment list DOC_ID
```

只看未解决的 comments：

```bash
python -m gdocs comment list DOC_ID --unresolved-only
```

输出 JSON 数组，每个 comment 包含 `id`、`author`、`content`、`quoted_text`（引用的原文片段）、`created_time`、`resolved`、`replies`。

回复评论：

```bash
python -m gdocs comment reply DOC_ID COMMENT_ID "回复内容"
```

解决评论（标记为已解决）：

```bash
python -m gdocs comment resolve DOC_ID COMMENT_ID
```

### 场景 8：在文档中插入本地图片

```bash
python -m gdocs image DOC_ID path/to/image.png --width 468
```

默认插入到文档末尾。指定位置插入（需要知道字符 index）：

```bash
python -m gdocs image DOC_ID image.png --index 2050 --width 468
```

`--width 468` 是全宽。图片会先上传到 Google Drive 再插入文档。

**带图片的 Markdown 发布流程**：Markdown 中的 `![alt](local_path.png)` 不会自动变成图片，publish 后 alt text 会保留为纯文本（如 `!Monthly Revenue by Course`）。正确做法：

1. 先 publish markdown（图片占位符变成 alt text）
2. 用 Google Docs API 扫描文档找到 alt text 的 index
3. 从文档底部往顶部逐个 `gdocs image --index` 插入（从底部开始是为了避免 index 偏移）

批量插入示例（Python，从底往顶）：

```python
from gdocs.auth import get_credentials
from googleapiclient.discovery import build

creds = get_credentials(Path("secrets"))
docs = build("docs", "v1", credentials=creds)
doc = docs.documents().get(documentId=DOC_ID).execute()

# 找到 "!alt text" 占位段落的 startIndex
# 按 index 降序排列
# 逐个调用: gdocs image DOC_ID path --index {start} --width 468
```

注意：插入图片后文档所有后续 index 会偏移，所以必须从后往前插。如果需要删除已插入的图片，用 batchUpdate 的 `deleteContentRange`。

## 注意事项

- OAuth scope 为 `drive.file`，只能访问本应用创建或用户主动打开的文件
- 搜索只能找到上述范围内的文档，无法搜索整个 Google Drive
- 不支持删除文档（安全考虑）
- 所有输出为 JSON，错误输出到 stderr
- 凭证存储在项目内 `secrets/` 目录，已 gitignore
- Token 自动刷新，过期后会自动重新授权

## 故障排查

### CLI publish 失败时怎么办

**正常错误信息**（2026-04-08 之后）: `{"error": "Failed to create document '...': HTTP 503 — <body>"}` —— 现在 RuntimeError 包含了 status code 和 response body，可以直接看出原因。

**Status code 速查**:
- **429 / 5xx**：transient 错误，client.py 已经自动 retry 3 次（exponential backoff），如果仍失败说明 Google API 真的挂了。**直接重试整个命令**，不要 fallback 到 workaround。
- **400**：request 格式错（title 含特殊 char、content 太大、参数错误等）。看 response body 找 specific 字段。
- **401 / 403**：OAuth 失效。删 `secrets/token.json` 重新授权。
- **404**：doc_id 不存在或没权限。

**反 pattern：fallback 到 workaround chain**

如果 CLI publish 失败，**不要**这样做：
1. 跑 `gdocs create` 试 auth ← 留下 test doc 污染
2. 用 Python 直接 call `client.create_document()` ← 绕过 CLI 后续步骤
3. 用 `gdocs tab replace` 修复
4. 重新 share

**正确做法**：先看 error 的 status code 和 body。Transient 就直接 retry CLI publish 命令；permanent 就根据 body 的具体字段诊断。如果不得不创建 debug doc 来验证 auth，**用完立即 `gdocs delete DOC_ID` 清理掉**。

**已知触发场景**:
- 大文件（>15,000 字）publish 偶尔触发 5xx — 已经 auto-retry，若 4 次都失败考虑拆 tab
- Google API 偶发 503 — auto-retry 通常能 cover

### CLI publish 排版不对（markdown 没渲染成 headings / tables）

**症状**: doc 创建成功但所有内容是纯文本，没有 heading 样式。

**原因**: `client.create_document()` 直接 call 不走 `content_format="markdown"` 路径。CLI publish 路径正确（line 90-98 of `__main__.py` 用 `content_format="markdown"`）。

**修复**: 用 `gdocs tab replace DOC_ID t.0 file.md --format markdown` 重新写入同一份 doc。Tab id 可以用 `gdocs tab list DOC_ID` 查到（默认是 `t.0`）。**不要重新 create 一份新 doc** —— 那样会留下原 doc 在用户 Drive 里。

### OAuth 重新授权

### OAuth 重新授权

如果遇到 OAuth 相关错误（403 access_denied、token invalid 等）：
1. 删除 `secrets/token.json`
2. 重新运行命令，浏览器会弹出授权页面
3. 确认当前 Google 账号在 OAuth consent screen 的 Test users 列表中
