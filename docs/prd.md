# Google Docs Skill — 产品需求文档

## 1. 背景与动机

我们的 AI 工作流（OhMyClaude Code / knowledge_working）中缺少直接操控 Google Docs 的能力。目前如果需要生成、修改或分享 Google Docs，只能手动完成。这个 skill 旨在让 AI agent 能够直接通过 Google 官方 API 完成文档的全生命周期操作。

## 2. 用户场景

### 场景 1：创建带 Tab 结构的文档

用户说："帮我创建一个项目报告，包含三个 tab：执行摘要、数据分析、下一步计划。"

AI agent 自动创建一个 Google Docs 文档，内含三个原生 tab（非 heading 模拟），每个 tab 有独立的标题和内容区域，并返回可访问的文档链接。

### 场景 2：搜索并修改文档

用户说："找到所有包含 'API 集成' 的文档，把状态更新为已完成。"

AI agent 通过 Drive API 全文搜索匹配的文档，展示搜索结果供用户确认，然后对选中的文档执行内容修改。

### 场景 3：分享文档

用户说："把这个文档分享给 alice@example.com，让她作为 editor。"

AI agent 调用 Drive Permissions API，将指定用户添加为编辑者，可选是否发送通知邮件，并返回分享链接。

### 场景 4：修改文档标题

用户说："把这个文档的标题改成 Q4 财报终稿。"

AI agent 通过 Drive API 更新文档元数据中的 name 字段。

### 场景 5：获取分享链接

用户说："把这个文档的分享链接给我。"

AI agent 获取文档的 `webViewLink`，如果需要还可以将文档设置为"任何拥有链接的人可查看"模式。

### 场景 6：用 Markdown 写入带格式的内容

用户说："帮我创建一个文档，标题叫'周报'，内容用 Markdown 写。"

AI agent 接收 Markdown 格式的文本，自动转换为 Google Docs 原生格式（标题、加粗、斜体、列表、超链接、行内代码等），写入文档。支持在创建文档和修改文档时使用。

### 场景 7：通过 CLI 一键发布 Markdown 到 Google Docs

用户说："把 `report.md` 发到 Google Docs。"

AI agent 执行 `python -m gdocs publish report.md --title "报告"`，一行命令完成 Markdown 文件到 Google Docs 的发布。所有输出为 JSON 格式，方便程序化处理。CLI 封装了认证、格式转换、API 调用的全部细节。

## 3. 功能范围

### 第一期（MVP）

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 创建文档 | P0 | 支持纯文本和带 Tab 结构的文档 |
| Tab 管理 | P0 | 创建多个 tab，指定标题、图标、内容 |
| Markdown 格式支持 | P0 | 内容支持 Markdown 语法，自动转换为 Google Docs 原生格式（标题、加粗、斜体、列表、链接、行内代码、分割线、引用块等） |
| Tab 管理（重命名/替换内容） | P0 | 重命名 Tab 标题、替换 Tab 内容（清空+写入，支持 Markdown） |
| CLI 入口 | P0 | `python -m gdocs` 子命令，所有功能可通过命令行调用，JSON 输出 |
| 搜索文档 | P0 | 按关键词全文搜索，支持按文件夹筛选 |
| 修改文档内容 | P0 | 向指定 tab 插入/替换文本 |
| 修改文档标题 | P1 | 通过 Drive API 更新 name 字段 |
| 分享文档 | P1 | 添加用户权限（reader/writer/commenter） |
| 获取分享链接 | P1 | 返回 webViewLink，可设置公开访问 |

### 不做（Out of Scope）

| 功能 | 原因 |
|------|------|
| 删除文档 | 风险太高，手动操作更安全 |
| 复杂格式排版 | 表格、图片等后续迭代（常见 Markdown 格式已支持，含分割线和引用） |
| Google Sheets / Slides | 不在本 skill 范围 |
| 多用户 session 管理 | MVP 只支持单用户 |

## 4. 非功能需求

### 安全性

- 所有凭证本地存储（`~/.google_docs_skill/`），不进入版本控制
- 只使用 Google 官方 SDK，零第三方运行时依赖
- OAuth token 自动刷新，过期自动重新认证
- 最小权限原则：仅申请 `documents` 和 `drive.file` 两个 scope

### 可靠性

- 所有 API 调用包含错误处理（`HttpError` 捕获）
- Token 过期自动刷新，无需用户干预
- 搜索结果支持分页，防止大量结果导致超时

### 易用性

- 首次使用自动触发 OAuth 授权流程（浏览器弹窗）
- 授权后 token 持久化，后续使用无感知
- Skill 文档提供完整的使用示例

## 5. 前置条件

用户需要完成以下一次性配置：

1. 在 Google Cloud Console 创建项目
2. 启用 Google Docs API 和 Google Drive API
3. 创建 OAuth 2.0 客户端凭证（Desktop app 类型）
4. 下载 `credentials.json` 到 `~/.google_docs_skill/`
5. 首次运行时在浏览器中完成授权

## 6. 成功指标

- AI agent 能在 30 秒内完成文档创建（含 tab）
- 搜索结果准确返回包含目标关键词的文档
- 分享操作成功后，目标用户能立即访问文档
- 整个 skill 核心代码量控制在 500 行以内（含 CLI 入口）
