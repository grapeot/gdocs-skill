# Skill: Google Docs 操作

通过 CLI 命令操控 Google Docs：发布 Markdown 文件、创建文档、搜索、修改、分享、Tab 管理。

## When to Use

用户说出以下意图时触发：
- "帮我创建一个 Google Doc"
- "把这个 Markdown 发到 Google Docs"
- "搜索我的 Google Docs"
- "把这个文档分享给 xxx"
- "修改那个文档的标题 / 内容"
- 任何涉及 Google Docs 创建、搜索、修改、分享的需求

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

### 场景 1：把一个 Markdown 文件发布到 Google Docs

这是最常见的需求。

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

## 注意事项

- OAuth scope 为 `drive.file`，只能访问本应用创建或用户主动打开的文件
- 搜索只能找到上述范围内的文档，无法搜索整个 Google Drive
- 不支持删除文档（安全考虑）
- 所有输出为 JSON，错误输出到 stderr
- 凭证存储在项目内 `secrets/` 目录，已 gitignore
- Token 自动刷新，过期后会自动重新授权
