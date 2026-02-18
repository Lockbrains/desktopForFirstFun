# Release Agent CLI 使用手册

> 本手册描述了 Release Agent 的所有命令行工具。  
> 运行环境：Mac 打包机（与 Jenkins 同机），Python 3.9+  
> 所有命令通过 `python cli.py <command> <subcommand> [options]` 调用。

---

## 目录

- [环境配置](#环境配置)
- [命令总览](#命令总览)
- [Google Play 发布](#google-play-发布)
- [App Store Connect 发布](#app-store-connect-发布)
- [Release Notes 生成](#release-notes-生成)
- [Jenkins 构建触发](#jenkins-构建触发)
- [Git 操作](#git-操作)
- [状态查询](#状态查询)
- [完整工作流示例](#完整工作流示例)
- [错误处理](#错误处理)

---

## 环境配置

### 首次使用初始化

```bash
python cli.py config init
```

交互式引导创建 `config.yaml`，包含：
- Google Play Service Account JSON 路径
- App Store Connect API Key 路径
- Jenkins 构建产物目录
- 应用包名 / Bundle ID

### config.yaml 格式

```yaml
app:
  name: "Wingstrike"
  android:
    package_name: "com.LCYD.StarFire"    # Google Play 包名
    service_account_json: "/path/to/google-play-service-account.json"
  ios:
    bundle_id: "com.LCYD.StarFire"       # App Store Bundle ID
    api_key_path: "/path/to/AuthKey_XXXXX.p8"
    api_key_id: "XXXXXXXXXX"
    api_issuer_id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

jenkins:
  base_url: "http://192.168.50.249:8080"
  user: ""          # 留空则从环境变量 JENKINS_USER 读取
  token: ""         # 留空则从环境变量 JENKINS_TOKEN 读取
  build_output_dir: "/Users/jenkins/workspace/builds"

gemini:
  api_key: ""       # 留空则从环境变量 GEMINI_API_KEY 读取
  model: "gemini-2.0-flash"
```

### 环境变量（可选，优先级高于 config.yaml）

```bash
export GOOGLE_PLAY_SERVICE_ACCOUNT_JSON="/path/to/service-account.json"
export APP_STORE_API_KEY_PATH="/path/to/AuthKey.p8"
export APP_STORE_API_KEY_ID="XXXXXXXXXX"
export APP_STORE_API_ISSUER_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
export JENKINS_USER="your-jenkins-user"
export JENKINS_TOKEN="your-jenkins-token"
export GEMINI_API_KEY="your-gemini-api-key"
```

---

## 命令总览

| 命令 | 说明 |
|------|------|
| `config init` | 初始化配置文件 |
| `config show` | 显示当前配置（隐藏密钥） |
| `gplay upload` | 上传 .aab 到 Google Play 指定轨道 |
| `gplay promote` | 将已上传的版本从一个轨道推广到另一个轨道 |
| `gplay submit` | 提交所有变更供 Google Play 审核 |
| `gplay status` | 查询 Google Play 各轨道版本状态 |
| `appstore upload` | 上传 .ipa 到 App Store Connect |
| `appstore submit` | 提交 App Store 审核 |
| `appstore status` | 查询 App Store Connect 审核状态 |
| `release-notes generate` | 用 AI 从 git log 生成 release notes |
| `jenkins trigger` | 触发 Jenkins 构建 |
| `jenkins status` | 查询 Jenkins 构建状态 |
| `git release-branch` | 创建 release 分支 |
| `git log` | 查看 commit 历史 |
| `status` | 查询所有平台发布状态 |

---

## Google Play 发布

### gplay upload

上传 .aab 文件到 Google Play 的指定轨道。

```bash
python cli.py gplay upload \
  --aab-path /path/to/app-release.aab \
  --track open-testing \
  --version "1.2.3" \
  --release-name "Wingstrike (1.2.3)" \
  --release-notes "修复了若干问题，优化了游戏性能" \
  --rollout 100
```

**参数说明：**

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--aab-path` | ✅ | - | .aab 文件的完整路径 |
| `--track` | ✅ | - | 目标轨道：`internal`、`alpha`（封闭测试）、`open-testing`、`production` |
| `--version` | ✅ | - | 版本号，如 `1.2.3` |
| `--release-name` | ❌ | `Wingstrike ({version})` | 发布名称。默认使用 `Wingstrike ({version})` 格式 |
| `--release-notes` | ❌ | - | 面向用户的发版说明（500 字符以内） |
| `--release-notes-file` | ❌ | - | 从文件读取 release notes。与 `--release-notes` 二选一 |
| `--rollout` | ❌ | `100` | 推出百分比（1-100）。仅 `production` 轨道支持灰度 |
| `--config` | ❌ | `./config.yaml` | 配置文件路径 |

**行为说明：**
- 自动从 config.yaml 读取 `package_name` 和 `service_account_json`
- 上传前自动验证 .aab 文件是否存在、大小是否合理
- 上传后返回 `version_code`，后续 `promote` 命令需要用到
- `--release-notes` 超过 500 字符会被截断并发出警告

**输出示例：**
```
📦 上传到 Google Play (open-testing)...
  文件: /path/to/app-release.aab (48.2 MB)
  包名: com.LCYD.StarFire
✅ 上传成功
  version_code: 145
  轨道: open-testing
  发布名称: Wingstrike (1.2.3)
  推出比例: 100%
```

---

### gplay promote

将已上传的版本推广到另一个轨道（对应 Google Play Console 的「Add from library」操作）。
**不会重新上传 .aab 文件**，只是引用已有的 version code。

```bash
python cli.py gplay promote \
  --version-code 145 \
  --to internal \
  --release-name "Wingstrike (1.2.3)" \
  --release-notes "内部测试版本"
```

**参数说明：**

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--version-code` | ✅ | - | 要推广的版本码（从 `gplay upload` 输出获取） |
| `--to` | ✅ | - | 目标轨道：`internal`、`alpha`、`open-testing`、`production` |
| `--release-name` | ❌ | 沿用上传时的名称 | 发布名称 |
| `--release-notes` | ❌ | 沿用上传时的内容 | release notes |
| `--rollout` | ❌ | `100` | 推出百分比 |

**行为说明：**
- 这个命令**不上传文件**，只是把已有 bundle 分配到新轨道
- 对应 Google Play Console 里「Create new release → Add from library」的操作
- 适用场景：先上传到 Open Testing，测试通过后推广到 Internal Testing 或 Production

**输出示例：**
```
🔄 推广 version_code=145 到 internal...
✅ 推广成功
  version_code: 145
  目标轨道: internal
  发布名称: Wingstrike (1.2.3)
```

---

### gplay submit

提交所有待审核的变更到 Google Play。对应 Google Play Console 的「Send changes for review」操作。

```bash
python cli.py gplay submit
```

**参数说明：**

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--config` | ❌ | `./config.yaml` | 配置文件路径 |

**行为说明：**
- 提交当前所有未提交的 edit（即 commit edit）
- 提交后 Google Play 会开始 common issues check
- 审核通常需要数小时到数天

**输出示例：**
```
📋 提交 Google Play 审核...
✅ 变更已提交
  状态: 待审核
  提交时间: 2026-02-17 10:30 UTC
```

---

### gplay status

查询 Google Play 各轨道的当前版本状态。

```bash
python cli.py gplay status
```

**输出示例：**
```
📊 Google Play 状态 (com.LCYD.StarFire)
  internal:     v1.2.3 (145) - 已发布
  open-testing: v1.2.3 (145) - 已发布
  production:   v1.2.2 (140) - 已发布
```

---

## App Store Connect 发布

### appstore upload

上传 .ipa 文件到 App Store Connect。使用 Mac 原生 `xcrun altool` 或 Apple Transporter。

```bash
python cli.py appstore upload \
  --ipa-path /path/to/App.ipa \
  --version "1.2.3"
```

**参数说明：**

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--ipa-path` | ✅ | - | .ipa 文件完整路径 |
| `--version` | ✅ | - | 版本号 |
| `--upload-method` | ❌ | `altool` | 上传方式：`altool`（xcrun）或 `transporter` |
| `--config` | ❌ | `./config.yaml` | 配置文件路径 |

**行为说明：**
- 自动从 config.yaml 读取 API Key 信息
- 上传前验证 .ipa 签名和 Bundle ID
- `altool` 模式使用 `xcrun altool --upload-app`
- `transporter` 模式使用 Apple Transporter CLI
- 上传成功后 App Store Connect 会自动开始处理（通常几分钟到1小时）

**输出示例：**
```
📦 上传到 App Store Connect...
  文件: /path/to/App.ipa (125.3 MB)
  Bundle ID: com.LCYD.StarFire
  版本: 1.2.3
✅ 上传成功
  状态: 处理中 (Processing)
  预计处理完成: 10-30 分钟
💡 处理完成后可以在 TestFlight 中看到此构建版本
```

---

### appstore submit

提交到 App Store 审核。可选择提交到 TestFlight 外部测试或正式 App Store。

```bash
# 提交到 TestFlight（外部测试组需要审核）
python cli.py appstore submit \
  --version "1.2.3" \
  --target testflight \
  --release-notes "修复了若干问题"

# 提交到 App Store 正式审核
python cli.py appstore submit \
  --version "1.2.3" \
  --target appstore \
  --release-notes-file ./release_notes/1.2.3_appstore.txt \
  --auto-release
```

**参数说明：**

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--version` | ✅ | - | 版本号 |
| `--target` | ✅ | - | 提交目标：`testflight` 或 `appstore` |
| `--release-notes` | ❌ | - | release notes 文本 |
| `--release-notes-file` | ❌ | - | 从文件读取 release notes |
| `--auto-release` | ❌ | `false` | 审核通过后是否自动发布（仅 appstore 目标） |
| `--phased-release` | ❌ | `false` | 是否启用分阶段发布（7天逐步推出，仅 appstore 目标） |

**输出示例：**
```
📋 提交 App Store 审核...
  版本: 1.2.3
  目标: App Store
  自动发布: 是
✅ 已提交审核
  预计审核时间: 1-2 天
```

---

### appstore status

查询 App Store Connect 当前版本状态。

```bash
python cli.py appstore status
```

**输出示例：**
```
📊 App Store Connect 状态 (com.LCYD.StarFire)
  TestFlight:
    最新构建: v1.2.3 (145) - 可测试
    内部测试: ✅ 可用
    外部测试: ✅ 已审核通过
  App Store:
    当前版本: v1.2.2 - 已发布
    待审核版本: v1.2.3 - 审核中 (提交于 2026-02-17)
```

---

## Release Notes 生成

> **已有实现**：GitHub Desktop 中已经有完整的 Release Notes 生成逻辑（`release-dropdown.tsx` 和 `agent-tools.ts`），使用 Gemini AI + `git log --first-parent` 实现。以下 CLI 命令复用相同的 Prompt 和术语映射规则。

### release-notes generate

从 git commit 历史自动生成 release notes。使用 Gemini AI 将技术 commit 转换为用户友好的说明。

```bash
python cli.py release-notes generate \
  --version "1.2.3" \
  --commits 30 \
  --repo-path /path/to/game-repo \
  --output ./release_notes/
```

**参数说明：**

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--version` | ✅ | - | 版本号 |
| `--commits` | ❌ | `30` | 读取最近 N 条 commit |
| `--repo-path` | ❌ | `.` | Git 仓库路径 |
| `--output` | ❌ | `./release_notes/` | 输出目录 |
| `--branch` | ❌ | `main` | 读取 commit 的分支 |

**行为说明：**
- 执行 `git log --first-parent -{commits} {branch}` 获取合入主线的 commit
- 调用 Gemini AI 生成内容，使用与 GitHub Desktop 相同的 Prompt，包含 Wingstrike 游戏术语映射规则：
  - Combat Systems → "Aerial combat mechanics"
  - Movement Systems → "Flight controls"
  - UI Systems → "Interface improvements"
  - Weapon Systems → "Aircraft armaments"
  - 等等（完整映射表见 `release-dropdown.tsx`）
- 输出两部分：
  1. **Technical Changelog**（技术人员用，包含组件名、PR 号）
  2. **Public Release Notes**（用户用，非技术语言，排除内部工具变更）
- 自动生成 Google Play 版本（≤500字符）
- 输出文件：
  - `release_notes/{version}_technical.md` — 完整技术日志
  - `release_notes/{version}_public.md` — 用户友好的 release notes
  - `release_notes/{version}_google_play.txt` — Google Play 版本（≤500字符）
  - `release_notes/{version}_appstore.txt` — App Store 版本

**输出示例：**
```
📝 生成 Release Notes (v1.2.3)...
  读取 main 分支最近 30 条 commit...
  调用 Gemini AI 生成...
✅ Release Notes 已生成
  技术日志: ./release_notes/1.2.3_technical.md
  公开说明: ./release_notes/1.2.3_public.md
  Google Play: ./release_notes/1.2.3_google_play.txt (387/500 字符)
  App Store: ./release_notes/1.2.3_appstore.txt
```

---

## Jenkins 构建触发

### jenkins trigger

触发 Jenkins 构建流水线。

```bash
python cli.py jenkins trigger \
  --platform android \
  --mode release \
  --branch release021726
```

**参数说明：**

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--platform` | ✅ | - | `ios` 或 `android` |
| `--mode` | ✅ | - | `debug` 或 `release` |
| `--branch` | ❌ | 当前分支 | 构建分支 |
| `--build-type` | ❌ | 平台默认值 | Android: `APK`/`HotUpdate`; iOS: `App`/`HotUpdate` |
| `--table-env` | ❌ | debug→`dev`, release→`test` | 表环境 |
| `--install-type` | ❌ | `Adhoc` | iOS 专用：`Adhoc`/`Xcode`/`TestFlight` |

**Pipeline 映射：**
| platform + mode | Jenkins Pipeline |
|----------------|------------------|
| android + debug | StarFire-Android-Debug-Pipeline |
| android + release | StarFire-Android-Release |
| ios + debug | StarFire-iOS-Debug-Pipeline |
| ios + release | StarFire-iOS-Release-Pipeline |

**输出示例：**
```
🔨 触发 Jenkins 构建...
  Pipeline: StarFire-Android-Release
  分支: release021726
  Build Type: APK
  Table Env: test
✅ 构建已触发
  构建 URL: http://192.168.50.249:8080/job/StarFire-Android-Release/42/
```

---

### jenkins status

查询最近的 Jenkins 构建状态。

```bash
python cli.py jenkins status --platform android --mode release
```

**输出示例：**
```
📊 Jenkins 构建状态 (StarFire-Android-Release)
  #42: ✅ 成功 (2026-02-17 09:30, 耗时 15分钟)
    产物: /Users/jenkins/workspace/builds/app-release.aab
  #41: ❌ 失败 (2026-02-16 16:00)
  #40: ✅ 成功 (2026-02-15 11:20)
```

---

## Git 操作

### git release-branch

创建 release 分支，命名格式 `releaseMMDDYY`。

```bash
# 自动命名（基于今天日期）
python cli.py git release-branch

# 自定义名称
python cli.py git release-branch --name release021726

# 指定仓库路径
python cli.py git release-branch --repo-path /path/to/game-repo
```

**参数说明：**

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--name` | ❌ | `releaseMMDDYY` | 分支名称，默认基于当日日期 |
| `--base` | ❌ | `main` | 基础分支 |
| `--repo-path` | ❌ | `.` | 仓库路径 |
| `--checkout` | ❌ | `true` | 创建后是否自动切换到该分支 |

**输出示例：**
```
🌿 创建 release 分支...
✅ 已创建并切换到: release021726 (基于 main)
```

---

### git log

查看 commit 历史。

```bash
python cli.py git log --count 20 --branch main --repo-path /path/to/repo
```

**参数说明：**

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--count` | ❌ | `10` | 显示条数 |
| `--branch` | ❌ | 当前分支 | 目标分支 |
| `--first-parent` | ❌ | `false` | 是否只显示合入主线的 commit |
| `--repo-path` | ❌ | `.` | 仓库路径 |

---

## 状态查询

### status

一次性查询所有平台的发布状态。

```bash
python cli.py status --version 1.2.3
```

**输出示例：**
```
═══════════════════════════════════════
  Wingstrike v1.2.3 发布状态总览
═══════════════════════════════════════

🤖 Google Play (Android)
  ├─ Internal Testing: v1.2.3 (145) ✅ 已发布
  ├─ Open Testing:     v1.2.3 (145) ✅ 已发布
  └─ Production:       v1.2.2 (140) — 当前线上版本

🍎 App Store (iOS)
  ├─ TestFlight:  v1.2.3 (145) ✅ 可测试
  └─ App Store:   v1.2.3       ⏳ 审核中

🔨 Jenkins 最近构建
  ├─ Android Release: #42 ✅ 成功
  └─ iOS Release:     #38 ✅ 成功
═══════════════════════════════════════
```

---

## 完整工作流示例

### 场景：发布 Wingstrike v1.2.3 到 Google Play

按照团队标准流程，完整的命令序列如下：

```bash
# ─── 第 1 步：创建 release 分支 ───
python cli.py git release-branch --name release021726 --repo-path /path/to/wingstrike

# ─── 第 2 步：生成 Release Notes ───
python cli.py release-notes generate \
  --version 1.2.3 \
  --commits 30 \
  --repo-path /path/to/wingstrike

# ─── 第 3 步：触发 Jenkins 打包 ───
python cli.py jenkins trigger \
  --platform android \
  --mode release \
  --branch release021726

# （等待 Jenkins 构建完成...）
# 可用 jenkins status 查询进度
python cli.py jenkins status --platform android --mode release

# ─── 第 4 步：上传到 Open Testing（公开测试） ───
python cli.py gplay upload \
  --aab-path /Users/jenkins/workspace/builds/app-release.aab \
  --track open-testing \
  --version "1.2.3" \
  --release-name "Wingstrike (1.2.3)" \
  --release-notes-file ./release_notes/1.2.3_google_play.txt \
  --rollout 100

# 记住输出的 version_code，下一步要用（例如 145）

# ─── 第 5 步：推广到 Internal Testing（内部测试） ───
# 注意：不需要重新上传，使用 promote 引用同一个 bundle
python cli.py gplay promote \
  --version-code 145 \
  --to internal \
  --release-name "Wingstrike (1.2.3)" \
  --release-notes "内部测试版本 1.2.3"

# ─── 第 6 步：提交审核 ───
python cli.py gplay submit

# ─── 第 7 步：查看状态 ───
python cli.py gplay status
```

### 场景：发布 Wingstrike v1.2.3 到 App Store

```bash
# ─── 第 1 步：触发 Jenkins iOS 打包 ───
python cli.py jenkins trigger \
  --platform ios \
  --mode release \
  --branch release021726 \
  --install-type TestFlight

# （等待构建完成...）

# ─── 第 2 步：上传 IPA 到 App Store Connect ───
python cli.py appstore upload \
  --ipa-path /Users/jenkins/workspace/builds/Wingstrike.ipa \
  --version "1.2.3"

# ─── 第 3 步：提交审核 ───
python cli.py appstore submit \
  --version "1.2.3" \
  --target appstore \
  --release-notes-file ./release_notes/1.2.3_appstore.txt \
  --auto-release

# ─── 第 4 步：查看状态 ───
python cli.py appstore status
```

### 场景：双平台同时发布

```bash
# 一键查看当前版本状态
python cli.py status --version 1.2.3
```

---

## 错误处理

所有命令的退出码遵循以下规则：

| 退出码 | 含义 |
|--------|------|
| `0` | 成功 |
| `1` | 一般错误（参数不正确、文件不存在等） |
| `2` | 认证失败（API Key 无效、Service Account 过期等） |
| `3` | 网络错误（上传超时、API 不可达等） |
| `4` | 版本冲突（version code 已存在、版本号未递增等） |

### 常见错误及解决方法

**`ERROR: .aab file not found`**
- 检查 `--aab-path` 路径是否正确
- 检查 Jenkins 构建是否已完成

**`ERROR: Google Play API authentication failed`**
- 检查 `service_account_json` 路径
- 确认 Service Account 在 Google Play Console 有 "Release manager" 权限

**`ERROR: Version code 145 already exists in track 'open-testing'`**
- 该版本码已经上传过了
- 需要重新打包以递增 version code，或直接使用 `gplay promote` 推广到其他轨道

**`ERROR: Release notes exceed 500 characters`**
- Google Play 对 release notes 有 500 字符限制
- 使用 `release-notes generate` 会自动生成符合限制的版本
- 或手动精简 `--release-notes` 内容

**`ERROR: xcrun altool upload failed - invalid credentials`**
- 检查 App Store Connect API Key 配置
- 或检查 Apple ID 的 App-Specific Password

### 自动重试

所有网络请求支持 `--retry` 参数（默认重试 3 次，间隔指数递增）：

```bash
python cli.py gplay upload --aab-path ... --retry 5
```

### 日志

所有命令支持 `--verbose` 参数输出详细日志：

```bash
python cli.py gplay upload --aab-path ... --verbose
```

日志自动保存到 `./logs/release_agent_{date}.log`。

---

## 注意事项

1. **Google Play release notes 限制**：每种语言最多 500 字符
2. **Google Play 发布顺序**：建议先 Open Testing → 再 Internal Testing（用 promote）→ 最后 Production
3. **App Store 处理时间**：上传 IPA 后 Apple 需要约 10-30 分钟处理，之后才能在 TestFlight 中看到
4. **App Store 审核时间**：通常 1-2 天，加急审核需要在 App Store Connect 手动申请
5. **所有密钥文件不应提交到 Git**：确保 `.gitignore` 包含 `*.p8`、`*service-account*.json`、`config.yaml`

