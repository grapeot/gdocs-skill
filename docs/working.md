# Working Log

## Changelog

### 2026-03-09

- 新增 `tab list DOC_ID` CLI 命令：列出文档所有 tab 的 ID 和标题
- 新增 `tab add DOC_ID "标题" [文件] [--format]` CLI 命令：给现有文档添加新 tab，可选填充内容（支持 Markdown）
- 新增 `list_tabs()` 和 `add_tab()` 方法到 GoogleDocsClient
- 新增 8 个单元测试覆盖新功能（client + CLI）
- **新增 Markdown 表格支持**（`feat/table-support` 分支）：
  - Markdown 中的 `| col1 | col2 |` 表格语法现在渲染为 Google Docs 原生表格
  - 表头行自动加粗
  - 空单元格正确跳过（不插入空文本）
  - 单元格文本按反序插入，避免索引偏移
  - 支持表格与普通文本混排（文本→表格→文本→表格...）
  - `markdown.py` 重构为分段架构：`_split_at_tables()` 将内容分为 text/table 段，各段独立生成请求
  - 不支持合并单元格、列宽控制、对齐方式（设计决策：只支持简单表格）
  - `markdown_to_requests()` 返回类型不变（`tuple[list[dict], int]`），无需修改调用方
  - 新增 10 个表格专用单元测试，总测试数 84 个，全部通过
  - 已在"测试"文档中验证：新建 "Table 测试" tab 含 3x3 表格 + 前后文本，渲染正确
  - 已重新渲染 "AI 周报 2026-03-07" tab，表格从纯文本升级为原生 Google Docs 表格

### 2026-03-08

- 完成 Google Docs Skill 技术调研：评估了纯 MCP、Skill+MCP 混合、直接 SDK 三种路线
- 调研发现 Google Docs API 原生支持 Tab 操作（addDocumentTab / deleteTab / updateDocumentTabProperties），无需用 Heading 模拟
- 调研 Google Drive API 搜索语法（fullText contains）、分享权限（permissions.create）、标题修改（files.update）
- 评估 taylorwilsdon/google_workspace_mcp（1731 stars）作为 MCP 候选方案，最终因安全性考虑放弃
- 对比 SDK vs MCP 工作量：SDK 约 200-300 行 / 16-32h，MCP 约 15-30 行 / 3.5-6.5h
- 最终决策：直接使用 google-api-python-client，零第三方运行时依赖
- 完成 OAuth 2.0 配置（Google Cloud Console 创建项目、启用 API、配置 consent screen、创建 Desktop app 凭证）
- 撰写 prd.md（产品需求）和 rfc.md（技术方案 RFC）
- 建立项目目录结构，凭证存储在项目内 secrets/ 目录
- 通过两个并行 sub-agent 完成 src/auth.py（63 行）和 src/client.py（191 行）实现
- 通过 sub-agent 完成 tests/unit/test_auth.py（5 个测试）和 tests/unit/test_client.py（15 个测试）
- 修复 6 个因并行 agent 间接口不匹配导致的单元测试失败：
  - auth.py 中的 isinstance 防御性检查导致 MagicMock 无法通过 → 移除 isinstance 守卫，改用 cast
  - test_client.py 中 get() 断言缺少 fields 参数 → 补全
  - test_client.py 中 email_message 参数名与实际 message 不一致 → 修正
  - test_auth.py 中 PropertyMock 对 MagicMock 类不生效 → 改用 MagicMock(valid=True)
  - test_auth.py 中 creds.to_json() 返回 MagicMock 而非字符串 → 设置 return_value
- 单元测试 20/20 全部通过
- 完成集成测试 tests/integration/test_integration.py（9 个测试），覆盖完整流程：创建文档 → 创建带 Tab 文档 → 修改内容 → 重命名 → 搜索 → 分享 → 获取链接 → 清理
- 集成测试全部通过（8 passed, 1 skipped — share_document 因未设 GDOCS_TEST_EMAIL 跳过）
- 手动测试创建带格式的文档成功（标题、加粗、斜体、列表），确认 Google Docs API 格式化请求正常工作
- 实现 src/markdown.py（289 行）— Markdown → Google Docs API 请求转换器，三阶段架构（解析→纯文本→请求生成）
  - 支持：H1/H2/H3 标题、加粗、斜体、加粗斜体、行内代码、超链接、无序列表、有序列表
  - 纯 Python 实现，无第三方 Markdown 解析库依赖
- 更新 client.py — create_document 和 modify_document 新增 content_format 参数（"plain" / "markdown"）
- 更新 PRD：新增 Markdown 格式支持（P0）和用户场景
- 更新 RFC：新增 Markdown → Google Docs 格式转换设计章节
- Security check 通过：git 历史中无敏感信息，.gitignore 正确覆盖所有凭证文件
- 创建 docs/skill_google_docs.md（AI agent 可读的 skill 文件）
- 在 rules/skills/ 创建 symlink 并更新 INDEX.md
- GitHub 创建 private repo：https://github.com/grapeot/gdocs-skill（未 push）
- 新增 `rename_tab(doc_id, tab_id, new_title)` 方法，通过 `updateDocumentTabProperties` API 实现 tab 重命名
- 新增 `replace_tab_content(doc_id, tab_id, text, content_format)` 方法，先删除旧内容再写入新内容，支持 Markdown 格式
- 手动测试：将 ai_frontline_20260307.md 的内容替换到 Tab 1，重命名为 "AI 前线 2026-03-07"
- 新增 Markdown 分割线（`---`）支持：由于 Google Docs 没有原生 HR，实现为 ━×30 灰色居中文字（6pt），视觉效果接近分割线
- 新增 Markdown 引用块（`> text`）支持：通过 `indentStart` 36pt + `borderLeft` 灰色实线实现
- 手动测试分享功能：成功分享文档给 grapeot@outlook.com 作为 editor
- 删除空 Tab 1（`deleteTab` API）
- 单元测试扩展至 54 个（新增 rename_tab、replace_tab_content、HR/blockquote 测试）
- 重命名 `src/` → `gdocs/` 包，支持 `python -m gdocs` CLI 调用方式
- 更新所有 import 路径（测试文件、内部引用）从 `src.` → `gdocs.`
- 新增 CLI 入口 `gdocs/__main__.py`（argparse），所有功能可通过 `python -m gdocs <subcommand>` 调用
- CLI 子命令：publish、create、search、share、title、link、tab rename、tab replace
- 所有 CLI 输出为 JSON 格式，便于 AI agent 程序化处理
- 重写 skill 文件（`docs/skill_google_docs.md`），从 Python 代码示例改为 CLI 命令示例
- 更新 PRD 新增 CLI 场景和功能、RFC 新增 CLI 设计章节和目录结构

## Lessons Learned

- Google Docs API 的 Tab 功能是较新的（约 2024 年 10 月），很多 Stack Overflow 答案和旧文档仍说"不支持创建 Tab"，需要以官方 API Reference 为准
- 文档标题修改不在 Docs API 中，而是通过 Drive API 的 files().update() 完成——Docs API 管内容，Drive API 管元数据
- OAuth scope 选 `drive.file` 而非 `drive`，前者是最小权限原则（只能访问本应用创建或用户主动打开的文件），但这也意味着搜索范围受限于此
- MCP 服务器（如 google_workspace_mcp）虽然大幅减少代码量，但引入了 fastmcp 等社区规模较小的依赖，增加供应链攻击面。对于长期使用的 skill，直接 SDK 更安全可控
- Google Cloud Console 创建 OAuth 凭证时，Application type 要选 "Desktop app"，这决定了授权流程使用 localhost 回调，适合本地 CLI 场景
- 并行开发 src 和 test 时，接口细节（参数名、额外参数）容易出现不一致。应先固定接口签名再分发任务，或由一个 agent 先写完 src 再写 test
- auth.py 中的 isinstance(mock, Credentials) 在单元测试中永远返回 False（MagicMock 不是 Credentials 的实例）。对于类型安全来说，用 typing.cast 替代运行时 isinstance 检查更适合可测试性
- Google Drive 搜索索引有延迟，集成测试中搜索新创建/重命名的文档需要加重试逻辑（每次 2s，最多 6 次）
- OAuth consent screen 配置为 External + 未发布状态时，**必须**将用户 Gmail 加入 Test users 列表，否则授权会直接返回 `Error 403: access_denied`（而非显示 "This app isn't verified" 的 Continue 页面）。这一步容易被忽略
- Tab 重命名的 API 格式：`tabId` 要放在 `tabProperties` 内部（`{"updateDocumentTabProperties": {"tabProperties": {"tabId": "...", "title": "..."}, "fields": "title"}}`），不是作为 `tabProperties` 的兄弟字段。通过 Google Docs Discovery API schema 确认
- Google Docs 没有原生的水平分割线插入 API，需要用替代方案模拟。最终选择 ━（U+2501 BOX DRAWINGS HEAVY HORIZONTAL）×30 + 灰色 6pt 居中对齐
- 引用块通过 `updateParagraphStyle` 设置左缩进 + 左边框实现，`borderLeft` 需要包含 `color`、`width`、`dashStyle`、`padding` 四个子字段
- CLI 比现场写 Python 更适合 AI agent 调用：减少 import/venv/path 出错机会，一行命令完成操作，JSON 输出便于程序化处理
- 包从 `src/` 重命名为 `gdocs/` 后，`python -m gdocs` 自动寻找 `gdocs/__main__.py`，无需额外安装步骤
- Google Docs `insertTable` API 的索引行为：在 index N 调用 insertTable 后，表格元素实际从 N+1 开始（不是 N）。这意味着 cell(r,c) 的空位置公式是 `insertion_index + r*(2*C+1) + 2*c + 4`（不是 +3），空表格占用大小是 `R*(2*C+1) + 3`（不是 +2）。这个 +1 偏移在 Google 官方文档中没有明确说明，只能通过实际 API 调用后读取文档结构来验证
- 表格单元格文本必须按反序插入（最后一个 cell 先插入），否则前面的插入会改变后面 cell 的索引位置。这与普通文本的顺序插入逻辑不同
- 混合内容（文本+表格+文本）的渲染需要先将 markdown 按表格边界分段，每段独立计算索引。段间共享 end_index 作为下一段的 start_index，确保索引连续
