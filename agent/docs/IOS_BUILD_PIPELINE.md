# iOS 打包流水线约定（Xcode → IPA → App Store）

本文档约定路径与角色，供 Jenkins 与 CLI 共用，**路径确定后不随意改动**；若需改动须同步更新本文档与 config。

---

## 1. 路径与名称约定（固定点）

| 项 | 约定值 | 说明 |
|----|--------|------|
| **Xcode Workspace** | `Wingstrike.xcworkspace` | 工程名，可置于任意目录，config 中填绝对路径 |
| **Scheme** | `Wingstrike` | Archive 使用的 scheme |
| **Configuration** | `Release` | 发版用 Release |
| **ExportOptions.plist** | 由你决定并写入 config | 从当前可成功导出的 build 手动导出一次，保存到固定路径，例如 `/Users/ffmac/workspace/ios_export/ExportOptions_adhoc.plist` 或 `ExportOptions_appstore.plist` |
| **Jenkins iOS Release Job 名称** | `StarFire-iOS-Release-Pipeline` | 已存在，不变 |
| **Jenkins IPA 输出路径** | `/Users/ffmac/.jenkins/workspace/StarFire-iOS-Release-Pipeline/build/ipa_output/Wingstrike.ipa` | Jenkins 承诺“iOS Release 产物总是出在此路径”；CLI 用此路径做自动上传 |

以上在 `config.yaml` 中对应：

- `app.ios.workspace_path`：.xcworkspace 的绝对路径
- `app.ios.scheme`：`Wingstrike`
- `app.ios.export_options_plist`：ExportOptions.plist 的绝对路径
- `jenkins.ios_ipa_output_path`：上述 Jenkins IPA 路径

---

## 2. Xcode 工程层面（一次性准备）

- **Release 配置 + Scheme**：在 Xcode 中用 `Wingstrike` scheme + `Release` 能正常 Archive 成功。
- **签名**：保持 Automatic signing，或构建机 Keychain 中已有所需 profiles，且 xcodebuild 能找到。
- **ExportOptions.plist**：在 Xcode 里用当前可上传的那套配置手动导出一次（Ad Hoc 或 App Store），将生成的 plist 放到固定路径并填入 config。

---

## 3. 从 Xcode 到 IPA 的命令行工具

CLI 已提供：

```bash
python cli.py appstore build-ipa
```

- 默认从 config 读取 `workspace_path`、`scheme`、`export_options_plist`。
- 也可显式传参：`--workspace`、`--scheme`、`--export-options`、`--output-dir`。

步骤：`xcodebuild archive` → `xcodebuild -exportArchive -exportOptionsPlist`，产出 IPA。

Jenkins 可在“源码拉取 + 编译”之后调用此命令（或等价 xcodebuild 两步），并将 IPA 输出到约定路径。

---

## 4. Jenkins Job 层面

- 在 iOS Release job 中，在现有步骤之后增加：Archive → 使用 ExportOptions.plist 导出 IPA → 将 IPA 放到约定路径。
- 保留控制台日志，便于查看 xcodebuild exit code 及证书/编译错误。

---

## 5. 上传与版本号

- 上传：本机已具备 App Store Connect API Key；`cli.py appstore upload --ipa <path>` 已打通；可选 xcrun altool / Transporter。
- 版本号：由发版流程决定（如 release branch + bump）；CFBundleShortVersionString / CFBundleVersion 在“生成 release branch + 版本号”步骤中更新；无特殊不可跳过的版本号规则时，以约定流程为准。

---

## 6. 角色与承诺

- **你方**：上述路径和 job 配好后，不随意改动工程结构 / job 名 / IPA 输出路径；若必须改，则同步更新本文档与 config，并通知对方。
- **FirstGit/我方**：从 Jenkins 触发 → 打包 → 上传 → 状态检查 → 错误上报，全程可脚本化；各步骤有明确超时与汇报，不“卡住不说话”。
