# Google Docs Skill

通过 Google 官方 Python SDK 直接操控 Google Docs，支持创建带 Tab 结构的文档、搜索、修改、分享。

## 项目结构

```
gdocs_skill/
├── docs/
│   ├── prd.md          # 产品需求文档
│   ├── rfc.md          # 技术方案 RFC（含调研过程和决策记录）
│   └── working.md      # Changelog + Lessons Learned
├── secrets/            # OAuth 凭证（已 gitignore）
│   ├── credentials.json
│   └── token.json
├── src/                # 核心实现
│   └── google_docs_client.py
├── .gitignore
└── README.md
```

## 功能概览

- 创建文档（支持原生 Tab 结构）
- 搜索文档（Drive API 全文搜索）
- 修改文档内容（batchUpdate）
- 修改文档标题
- 分享文档（添加用户权限、获取分享链接）

## 技术选型

直接使用 Google 官方 SDK（`google-api-python-client`），不依赖任何第三方 MCP 服务器。选型理由详见 `docs/rfc.md`。

依赖仅三个 Google 官方包：
- `google-api-python-client`
- `google-auth`
- `google-auth-oauthlib`

---

## 初始化配置指南（面向 AI agent）

以下是引导用户完成首次配置的完整流程。AI agent 应按顺序引导用户完成每一步，在每一步确认用户完成后再进入下一步。

### 前置检查

在开始之前，先确认：

1. 用户是否有 Google 账号（Gmail 或 Google Workspace）
2. `secrets/` 目录下是否已存在 `credentials.json` —— 如果已存在，跳到「Step 6: 验证」

### Step 1: 创建 Google Cloud 项目

引导用户访问 https://console.cloud.google.com/

操作：
1. 点击页面顶部的项目选择器（通常显示 "Select a project" 或已有项目名）
2. 在弹出的对话框中点击右上角的 "NEW PROJECT"
3. 填写 Project name（建议填 `google-docs-skill`）
4. Organization 可以留空
5. 点击 "CREATE"
6. 等待项目创建完成（通常几秒钟），确认顶部项目选择器显示新项目名

### Step 2: 启用 API

在刚创建的项目中，需要启用两个 API。

操作：
1. 在 Console 顶部搜索栏搜索 "Google Docs API"，点击搜索结果进入
2. 点击 "ENABLE"（启用）按钮
3. 返回搜索栏，搜索 "Google Drive API"
4. 同样点击 "ENABLE"

验证：在 https://console.cloud.google.com/apis/dashboard 页面的 "Enabled APIs" 列表中，应能看到 Google Docs API 和 Google Drive API。

### Step 3: 配置 OAuth Consent Screen

操作：
1. 在左侧导航栏找到 "OAuth consent screen"（或通过搜索栏搜索）
2. 选择 User Type 为 "External"（除非用户有 Google Workspace 且只需内部使用，则选 "Internal"）
3. 点击 "CREATE"
4. 填写必填信息：
   - App name: `Google Docs Skill`
   - User support email: 用户自己的邮箱
   - Developer contact information: 用户自己的邮箱
5. 点击 "SAVE AND CONTINUE"
6. 在 Scopes 页面，点击 "ADD OR REMOVE SCOPES"，搜索并勾选：
   - `https://www.googleapis.com/auth/documents`（Google Docs API - 查看和管理文档）
   - `https://www.googleapis.com/auth/drive.file`（Google Drive API - 查看和管理文件）
7. 点击 "UPDATE"，然后 "SAVE AND CONTINUE"
8. **（关键步骤）** 在 Test users 页面，点击 "ADD USERS"，添加用户自己的 Gmail 地址。**如果跳过此步，授权时会遇到 `Error 403: access_denied`（"has not completed the Google verification process"），而不是授权确认页面。** 应用处于测试模式（External + 未发布）时，只有被添加到 Test users 列表中的账号才能授权。
9. 点击 "SAVE AND CONTINUE"，最后点击 "BACK TO DASHBOARD"

### Step 4: 创建 OAuth 2.0 凭证

操作：
1. 在左侧导航栏点击 "Credentials"（凭据），或直接访问 https://console.cloud.google.com/apis/credentials
2. 点击页面顶部的 "+ CREATE CREDENTIALS" 按钮
3. 在下拉菜单中选择 "OAuth client ID"
4. Application type 选择 "Desktop app"（这表示应用跑在用户本地电脑上，授权时会通过 localhost 回调）
5. Name 填写 `gdocs-skill-desktop`（仅用于辨识，随意填写）
6. 点击 "CREATE"

### Step 5: 下载凭证 JSON

操作：
1. 创建成功后会弹出对话框，显示 Client ID 和 Client Secret
2. 点击对话框中的 "DOWNLOAD JSON" 按钮（或下载图标）
3. 浏览器会下载一个文件，文件名类似 `client_secret_123456789-xxx.apps.googleusercontent.com.json`
4. 将该文件移动到本项目的 `secrets/` 目录，并重命名为 `credentials.json`

如果不小心关掉了对话框：回到 Credentials 页面，在 "OAuth 2.0 Client IDs" 列表中找到刚创建的条目，点击最右边的下载图标即可重新下载。

终端命令（AI agent 帮用户执行）：
```bash
mv ~/Downloads/client_secret_*.json <项目路径>/secrets/credentials.json
chmod 600 <项目路径>/secrets/credentials.json
```

### Step 6: 验证

确认配置完成：
```bash
ls -la secrets/credentials.json
# 应显示文件存在，权限为 -rw-------
```

首次运行 Python 脚本时，会自动弹出浏览器窗口要求登录 Google 账号并授权。授权完成后，`secrets/token.json` 会自动生成，后续运行无需重复授权。

### 常见问题

**Q: 授权时提示 "Access blocked" / `Error 403: access_denied`**
A: 说明当前登录的 Google 账号不在 OAuth consent screen 的 Test users 列表中。前往 [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent) → Test users → ADD USERS，把自己的 Gmail 地址加进去，然后重新运行授权流程。

**Q: 授权时提示 "This app isn't verified"**
A: 这是正常的。因为应用处于测试模式，点击 "Continue"（继续）即可。只有发布到生产环境才需要 Google 审核。注意：只有先被加入 Test users 列表，才会看到这个页面；如果没加，直接看到的是 403 错误（见上一条）。

**Q: token.json 过期了怎么办？**
A: SDK 会自动刷新 token。如果刷新失败（比如 refresh token 也过期了），删除 `secrets/token.json` 重新运行即可，会再次弹出浏览器授权。

**Q: 换了电脑怎么办？**
A: 把 `secrets/credentials.json` 拷过去就行，`token.json` 会在首次运行时重新生成。

**Q: 需要更换 Google 账号？**
A: 删除 `secrets/token.json`，重新运行时会弹出授权页面，选择新账号即可。
