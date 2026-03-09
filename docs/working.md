# Working Log

## Changelog

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

## Lessons Learned

- Google Docs API 的 Tab 功能是较新的（约 2024 年 10 月），很多 Stack Overflow 答案和旧文档仍说"不支持创建 Tab"，需要以官方 API Reference 为准
- 文档标题修改不在 Docs API 中，而是通过 Drive API 的 files().update() 完成——Docs API 管内容，Drive API 管元数据
- OAuth scope 选 `drive.file` 而非 `drive`，前者是最小权限原则（只能访问本应用创建或用户主动打开的文件），但这也意味着搜索范围受限于此
- MCP 服务器（如 google_workspace_mcp）虽然大幅减少代码量，但引入了 fastmcp 等社区规模较小的依赖，增加供应链攻击面。对于长期使用的 skill，直接 SDK 更安全可控
- Google Cloud Console 创建 OAuth 凭证时，Application type 要选 "Desktop app"，这决定了授权流程使用 localhost 回调，适合本地 CLI 场景
- 并行开发 src 和 test 时，接口细节（参数名、额外参数）容易出现不一致。应先固定接口签名再分发任务，或由一个 agent 先写完 src 再写 test
- auth.py 中的 isinstance(mock, Credentials) 在单元测试中永远返回 False（MagicMock 不是 Credentials 的实例）。对于类型安全来说，用 typing.cast 替代运行时 isinstance 检查更适合可测试性
- Google Drive 搜索索引有延迟，集成测试中搜索新创建/重命名的文档需要加重试逻辑（每次 2s，最多 6 次）
