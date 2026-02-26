#!/usr/bin/env python3
"""
Wingstrike Release Agent CLI

由 OpenClaw AI Agent 或人工直接调用的命令行工具。
所有发布流程（打包、测试、发版）统一入口。

使用方法：
  python cli.py --help
  python cli.py <command> <subcommand> [options]

详细使用手册参见 RELEASE_CLI_MANUAL.md
"""

import json
import os
import shutil
import sys

import click
import yaml

# 确保 tools/ 可以被导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.config import load_config, get_config


# ── CLI 入口 ───────────────────────────────────────────────────────

@click.group()
@click.option("--config", "-c", default="./config.yaml", help="配置文件路径")
@click.option("--json-output", "-j", is_flag=True, default=False, help="以 JSON 格式输出结果")
@click.pass_context
def cli(ctx, config, json_output):
    """Wingstrike Release Agent CLI - 自动化发布管理工具"""
    ctx.ensure_object(dict)
    ctx.obj["json_output"] = json_output
    load_config(config)


def _output(ctx, data: dict):
    """统一输出。json_output 模式输出 JSON，否则友好文本。无 success 键时视为失败。"""
    if ctx.obj.get("json_output"):
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        success = data.get("success", False) if "success" in data else False
        icon = "✅" if success else "❌"
        msg = data.get("message", "") or ("无返回信息" if not success else "")
        click.echo(f"{icon} {msg}")
        for k, v in data.items():
            if k in ("success", "message"):
                continue
            if isinstance(v, dict):
                click.echo(f"  {k}:")
                for kk, vv in v.items():
                    click.echo(f"    {kk}: {vv}")
            elif isinstance(v, list):
                click.echo(f"  {k}:")
                for item in v:
                    if isinstance(item, dict):
                        click.echo(f"    - {json.dumps(item, ensure_ascii=False)}")
                    else:
                        click.echo(f"    - {item}")
            else:
                click.echo(f"  {k}: {v}")


# ═══════════════════════════════════════════════════════════════════
# config - 配置管理
# ═══════════════════════════════════════════════════════════════════

@cli.group()
def config():
    """配置管理"""
    pass


@config.command("init")
@click.option("--output", "-o", default="./config.yaml", help="配置文件输出路径")
@click.pass_context
def config_init(ctx, output):
    """生成配置文件模板"""
    template_path = os.path.join(os.path.dirname(__file__), "config.yaml.example")
    if os.path.exists(output):
        click.echo(f"⚠️  {output} 已存在，跳过。使用 --output 指定其他路径。")
        return
    if os.path.exists(template_path):
        shutil.copy(template_path, output)
    else:
        # 生成最小模板
        template = {
            "app": {
                "name": "Wingstrike",
                "android": {"package_name": "", "service_account_json": ""},
                "ios": {"bundle_id": "", "api_key_path": "", "api_key_id": "", "api_issuer_id": ""},
            },
            "jenkins": {
                "base_url": "http://192.168.50.249:8080",
                "user": "",
                "token": "",
                "build_output_dir": "",
                "pipelines": {
                    "android-debug": "StarFire-Android-Debug-Pipeline",
                    "android-release": "StarFire-Android-Release",
                    "ios-debug": "StarFire-iOS-Debug-Pipeline",
                    "ios-release": "StarFire-iOS-Release-Pipeline",
                },
            },
            "gemini": {"api_key": "", "model": "gemini-2.0-flash"},
        }
        with open(output, "w", encoding="utf-8") as f:
            yaml.dump(template, f, default_flow_style=False, allow_unicode=True)
    click.echo(f"✅ 配置文件已生成: {output}")
    click.echo("   请填入实际凭证信息后使用。")


@config.command("validate")
@click.pass_context
def config_validate(ctx):
    """验证当前配置是否完整"""
    cfg = get_config()
    issues = []

    # 检查必要字段
    checks = [
        (("app", "android", "package_name"), "Android 包名"),
        (("app", "android", "service_account_json"), "Google Play Service Account JSON"),
        (("app", "ios", "bundle_id"), "iOS Bundle ID"),
        (("app", "ios", "api_key_path"), "App Store API Key 路径"),
        (("app", "ios", "api_key_id"), "App Store API Key ID"),
        (("app", "ios", "api_issuer_id"), "App Store API Issuer ID"),
        (("jenkins", "base_url"), "Jenkins URL"),
    ]

    for keys, label in checks:
        val = cfg
        for k in keys:
            val = val.get(k, {}) if isinstance(val, dict) else ""
        if not val:
            # 检查环境变量备选
            env_map = {
                "Google Play Service Account JSON": "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON",
                "App Store API Key 路径": "APP_STORE_API_KEY_PATH",
                "App Store API Key ID": "APP_STORE_API_KEY_ID",
                "App Store API Issuer ID": "APP_STORE_API_ISSUER_ID",
            }
            env_key = env_map.get(label)
            if env_key and os.environ.get(env_key):
                continue
            issues.append(f"  ⚠️  缺少: {label}")

    # Gemini
    gemini_key = cfg.get("gemini", {}).get("api_key") or os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        issues.append("  ⚠️  缺少: Gemini API Key")

    # Jenkins 凭证
    jenkins_user = cfg.get("jenkins", {}).get("user") or os.environ.get("JENKINS_USER")
    jenkins_token = cfg.get("jenkins", {}).get("token") or os.environ.get("JENKINS_TOKEN")
    if not jenkins_user or not jenkins_token:
        issues.append("  ⚠️  缺少: Jenkins 用户名/Token")

    if issues:
        click.echo("❌ 配置验证发现问题：")
        for issue in issues:
            click.echo(issue)
    else:
        click.echo("✅ 配置验证通过，所有必要字段已设置。")


@config.command("show")
@click.pass_context
def config_show(ctx):
    """显示当前配置（隐藏敏感信息）"""
    cfg = get_config()

    def _mask(d, depth=0):
        masked = {}
        sensitive_keys = {"api_key", "token", "service_account_json", "api_key_path"}
        for k, v in d.items():
            if isinstance(v, dict):
                masked[k] = _mask(v, depth + 1)
            elif k in sensitive_keys and v:
                masked[k] = "***" + str(v)[-4:] if len(str(v)) > 4 else "****"
            else:
                masked[k] = v
        return masked

    masked = _mask(cfg)
    click.echo(yaml.dump(masked, default_flow_style=False, allow_unicode=True))


# ═══════════════════════════════════════════════════════════════════
# build - Jenkins 构建
# ═══════════════════════════════════════════════════════════════════

@cli.group()
def build():
    """Jenkins 构建管理"""
    pass


@build.command("trigger")
@click.option("--platform", "-p", required=True, type=click.Choice(["ios", "android"]))
@click.option("--mode", "-m", required=True, type=click.Choice(["debug", "release"]))
@click.option("--branch", "-b", default=None, help="构建分支（默认当前分支）")
@click.option(
    "--build-type",
    default=None,
    help="构建类型: Android 仅支持 APK/HotUpdate；iOS 支持 App/HotUpdate（传 App 时 Android 会自动用 APK）",
)
@click.option("--install-type", default=None, help="iOS 安装类型: Adhoc/TestFlight")
@click.pass_context
def build_trigger(ctx, platform, mode, branch, build_type, install_type):
    """触发 Jenkins 构建（表格环境固定为 dev）"""
    from tools.jenkins import trigger_build
    from tools.git_ops import get_current_branch

    if not branch:
        try:
            branch = get_current_branch()
        except Exception:
            branch = "main"

    result = trigger_build(
        platform=platform,
        mode=mode,
        branch=branch,
        build_type=build_type,
        install_type=install_type,
    )
    _output(ctx, result)


@build.command("status")
@click.option("--platform", "-p", required=True, type=click.Choice(["ios", "android"]))
@click.option("--mode", "-m", required=True, type=click.Choice(["debug", "release"]))
@click.option("--count", "-n", default=3, help="显示最近几次构建")
@click.pass_context
def build_status(ctx, platform, mode, count):
    """查询构建状态"""
    from tools.jenkins import get_build_status

    result = get_build_status(platform=platform, mode=mode, count=count)
    _output(ctx, result)


# ═══════════════════════════════════════════════════════════════════
# release-notes - Release Notes 管理
# ═══════════════════════════════════════════════════════════════════

@cli.group("release-notes")
def release_notes():
    """Release Notes 生成与管理"""
    pass


@release_notes.command("generate")
@click.option("--version", "-v", required=True, help="版本号")
@click.option("--commits", "-n", default=30, help="读取最近 N 条 commit")
@click.option("--repo-path", default=".", help="Git 仓库路径")
@click.option("--branch", "-b", default="main", help="读取 commit 的分支")
@click.option("--output", "-o", default="./release_notes", help="输出目录")
@click.pass_context
def release_notes_generate(ctx, version, commits, repo_path, branch, output):
    """使用 Gemini AI 生成 Release Notes"""
    from tools.release_notes import generate_release_notes

    result = generate_release_notes(
        version=version,
        repo_path=repo_path,
        branch=branch,
        commits=commits,
        output_dir=output,
    )
    _output(ctx, result)


# ═══════════════════════════════════════════════════════════════════
# gplay - Google Play 发布
# ═══════════════════════════════════════════════════════════════════

@cli.group()
def gplay():
    """Google Play 发布管理"""
    pass


@gplay.command("upload")
@click.option("--aab", required=True, help=".aab 文件路径")
@click.option("--track", "-t", default="beta", type=click.Choice(["internal", "alpha", "beta", "production"]),
              help="发布轨道 (beta=Open Testing)")
@click.option("--version", "-v", default=None, help="版本号（用于 release name）")
@click.option("--release-name", default=None, help="自定义发布名称")
@click.option("--release-notes", default=None, help="发布说明文本（≤500字符）")
@click.option("--release-notes-file", default=None, help="从文件读取发布说明")
@click.option("--rollout", default=100.0, type=float, help="灰度比例 0-100")
@click.option("--draft", is_flag=True, default=False, help="作为草稿上传")
@click.option("--debug", is_flag=True, default=False, envvar="GPLAY_DEBUG",
              help="打印 HTTP 请求/响应详情，便于排查重定向等问题；可设环境变量 GPLAY_DEBUG=1")
@click.pass_context
def gplay_upload(ctx, aab, track, version, release_name, release_notes, release_notes_file, rollout, draft, debug):
    """上传 AAB 到 Google Play"""
    from tools.google_play import upload_bundle

    # 从文件读取 release notes
    if release_notes_file and not release_notes:
        try:
            with open(release_notes_file, "r", encoding="utf-8") as f:
                release_notes = f.read().strip()
        except Exception as e:
            _output(ctx, {"success": False, "message": f"读取 release notes 文件失败: {e}"})
            return

    if debug:
        click.echo("HTTP 调试已开启，请求/响应会打印到终端；建议用 2>&1 | tee upload.log 保存完整输出以便排查。")

    result = upload_bundle(
        aab_path=aab,
        track=track,
        release_name=release_name,
        release_notes=release_notes,
        rollout_percentage=rollout,
        version=version,
        draft=draft,
        debug=debug,
    )
    _output(ctx, result)
    if result.get("success"):
        click.echo("建议执行: python cli.py gplay status  以确认 Play Console 上是否出现新版本。")
    elif not result.get("success") and result.get("message"):
        click.echo("若为超时，可稍后重试；结果以 gplay status 或 Play Console 为准。")


@gplay.command("promote")
@click.option("--version-code", required=True, type=int, help="要推广的 version code")
@click.option("--from-track", default="beta", help="来源 track")
@click.option("--to-track", required=True, type=click.Choice(["internal", "alpha", "beta", "production"]),
              help="目标 track")
@click.option("--version", "-v", default=None, help="版本号（用于 release name）")
@click.option("--release-name", default=None, help="自定义发布名称")
@click.option("--release-notes", default=None, help="发布说明文本")
@click.option("--release-notes-file", default=None, help="从文件读取发布说明")
@click.option("--rollout", default=100.0, type=float, help="灰度比例 0-100")
@click.option("--draft", is_flag=True, default=False, help="作为草稿")
@click.pass_context
def gplay_promote(ctx, version_code, from_track, to_track, version, release_name, release_notes,
                  release_notes_file, rollout, draft):
    """将已上传版本推广到另一个 track（Add from library）"""
    from tools.google_play import promote

    if release_notes_file and not release_notes:
        try:
            with open(release_notes_file, "r", encoding="utf-8") as f:
                release_notes = f.read().strip()
        except Exception as e:
            _output(ctx, {"success": False, "message": f"读取 release notes 文件失败: {e}"})
            return

    result = promote(
        version_code=version_code,
        from_track=from_track,
        to_track=to_track,
        release_name=release_name,
        release_notes=release_notes,
        rollout_percentage=rollout,
        version=version,
        draft=draft,
    )
    _output(ctx, result)


@gplay.command("status")
@click.option("--track", "-t", default=None, help="指定 track（不指定则查询全部）")
@click.pass_context
def gplay_status(ctx, track):
    """查询 Google Play 各 track 状态"""
    from tools.google_play import get_track_status

    result = get_track_status(track=track)
    _output(ctx, result)


@gplay.command("bundles")
@click.pass_context
def gplay_bundles(ctx):
    """列出已上传的 bundle"""
    from tools.google_play import list_bundles

    result = list_bundles()
    _output(ctx, result)


# ═══════════════════════════════════════════════════════════════════
# appstore - App Store Connect 发布
# ═══════════════════════════════════════════════════════════════════

@cli.group()
def appstore():
    """App Store Connect 发布管理"""
    pass


@appstore.command("build-ipa")
@click.option("--workspace", "-w", default=None, help=".xcworkspace 路径（默认从 config app.ios.workspace_path 读取）")
@click.option("--scheme", "-s", default=None, help="Scheme 名称（默认从 config app.ios.scheme 读取）")
@click.option("--configuration", "-c", default="Release", help="Configuration，默认 Release")
@click.option("--export-options", "-e", default=None, help="ExportOptions.plist 路径（默认从 config app.ios.export_options_plist 读取）")
@click.option("--output-dir", "-o", default=None, help="IPA 导出目录（不填则用 workspace 同级的 build/ipa_export）")
@click.pass_context
def appstore_build_ipa(ctx, workspace, scheme, configuration, export_options, output_dir):
    """从 Xcode 工程打出 IPA（archive + exportArchive），供本机或 Jenkins 调用"""
    from tools.xcode_export import build_ipa
    from tools.config import (
        get_ios_workspace_path,
        get_ios_scheme,
        get_ios_export_options_plist,
    )

    workspace = workspace or get_ios_workspace_path()
    scheme = scheme or get_ios_scheme()
    export_options = export_options or get_ios_export_options_plist()

    if not workspace:
        _output(ctx, {"success": False, "message": "未配置 workspace_path，请设置 config app.ios.workspace_path 或传 --workspace"})
        return
    if not export_options:
        _output(ctx, {"success": False, "message": "未配置 export_options_plist，请设置 config app.ios.export_options_plist 或传 --export-options"})
        return

    result = build_ipa(
        workspace_path=workspace,
        scheme=scheme,
        configuration=configuration,
        export_options_plist=export_options,
        export_path=output_dir,
    )
    _output(ctx, result)


@appstore.command("upload")
@click.option("--ipa", required=True, help=".ipa 文件路径")
@click.option("--method", default="altool", type=click.Choice(["altool", "transporter"]),
              help="上传方式（默认 altool，与 Xcode 同链路；transporter 存在假成功问题）")
@click.option("--verify/--no-verify", default=True,
              help="上传后自动查询 ASC builds 验证是否出现 PROCESSING 记录（默认开启）")
@click.pass_context
def appstore_upload(ctx, ipa, method, verify):
    """上传 IPA 到 App Store Connect"""
    from tools.app_store import upload_ipa, list_builds
    import time

    result = upload_ipa(ipa_path=ipa, method=method)
    _output(ctx, result)

    if result.get("success") and verify:
        click.echo("\n--- 自动验证：查询 App Store Connect builds ---")
        click.echo("等待 15 秒让 Apple 处理...")
        time.sleep(15)
        builds_result = list_builds(limit=5)
        if builds_result.get("success"):
            builds = builds_result.get("builds", [])
            if builds:
                click.echo(f"最新 {len(builds)} 条 builds:")
                for b in builds:
                    state = b.get("processing_state", "?")
                    ver = b.get("version", "?")
                    date = b.get("uploaded_date", "?")
                    marker = " ← 新上传?" if state == "PROCESSING" else ""
                    click.echo(f"  Build {ver} | {state} | {date}{marker}")
                processing = [b for b in builds if b.get("processing_state") == "PROCESSING"]
                if processing:
                    click.echo(f"\n✅ 发现 {len(processing)} 个 PROCESSING 状态的 build，Apple 侧已收到。")
                else:
                    click.echo("\n⚠️ 未发现 PROCESSING 状态的 build。可能 Apple 还在处理，"
                               "建议 1-2 分钟后再执行: python3 cli.py appstore builds")
            else:
                click.echo("  未返回任何 build 记录。")
        else:
            click.echo(f"  验证查询失败: {builds_result.get('message')}")


@appstore.command("create-version")
@click.option("--version", "-v", required=True, help="版本号")
@click.option("--platform", default="IOS", type=click.Choice(["IOS", "MAC_OS"]))
@click.option("--release-type", default="MANUAL", type=click.Choice(["MANUAL", "AFTER_APPROVAL"]))
@click.pass_context
def appstore_create_version(ctx, version, platform, release_type):
    """在 App Store Connect 创建新版本"""
    from tools.app_store import create_version

    result = create_version(
        version_string=version,
        platform=platform,
        release_type=release_type,
    )
    _output(ctx, result)


@appstore.command("set-notes")
@click.option("--version-id", required=True, help="App Store 版本 ID")
@click.option("--release-notes", default=None, help="发布说明文本")
@click.option("--release-notes-file", default=None, help="从文件读取发布说明")
@click.option("--locale", default="en-US", help="语言区域")
@click.pass_context
def appstore_set_notes(ctx, version_id, release_notes, release_notes_file, locale):
    """更新 App Store 版本的 Release Notes"""
    from tools.app_store import update_release_notes

    if release_notes_file and not release_notes:
        try:
            with open(release_notes_file, "r", encoding="utf-8") as f:
                release_notes = f.read().strip()
        except Exception as e:
            _output(ctx, {"success": False, "message": f"读取文件失败: {e}"})
            return

    if not release_notes:
        _output(ctx, {"success": False, "message": "请提供 --release-notes 或 --release-notes-file"})
        return

    result = update_release_notes(
        version_id=version_id,
        release_notes=release_notes,
        locale=locale,
    )
    _output(ctx, result)


@appstore.command("submit")
@click.option("--version-id", required=True, help="App Store 版本 ID")
@click.pass_context
def appstore_submit(ctx, version_id):
    """提交版本送审"""
    from tools.app_store import submit_for_review

    result = submit_for_review(version_id=version_id)
    _output(ctx, result)


@appstore.command("status")
@click.pass_context
def appstore_status(ctx):
    """查询 App Store 应用状态"""
    from tools.app_store import get_app_status

    result = get_app_status()
    _output(ctx, result)


@appstore.command("builds")
@click.option("--limit", "-n", default=20, help="最多列出多少条 build，默认 20")
@click.pass_context
def appstore_builds(ctx, limit):
    """列出所有构建及 processing 状态（PROCESSING/VALID/INVALID/FAILED），用于确认上传后的 build 是否已就绪"""
    from tools.app_store import list_builds

    result = list_builds(limit=limit)
    _output(ctx, result)


# ═══════════════════════════════════════════════════════════════════
# git - Git 操作
# ═══════════════════════════════════════════════════════════════════

@cli.group()
def git():
    """Git 操作"""
    pass


@git.command("status")
@click.option("--repo-path", default=".", help="仓库路径")
@click.pass_context
def git_status_cmd(ctx, repo_path):
    """查看 Git 状态"""
    from tools.git_ops import git_status
    output = git_status(repo_path)
    click.echo(output)


@git.command("log")
@click.option("--repo-path", default=".", help="仓库路径")
@click.option("--count", "-n", default=10, help="显示条数")
@click.option("--branch", "-b", default=None, help="指定分支")
@click.pass_context
def git_log_cmd(ctx, repo_path, count, branch):
    """查看 Git 日志"""
    from tools.git_ops import git_log
    output = git_log(repo_path, count=count, branch=branch)
    click.echo(output)


@git.command("branch")
@click.option("--repo-path", default=".", help="仓库路径")
@click.pass_context
def git_branch_cmd(ctx, repo_path):
    """列出所有分支"""
    from tools.git_ops import git_branch_list
    output = git_branch_list(repo_path)
    click.echo(output)


@git.command("checkout")
@click.option("--repo-path", default=".", help="仓库路径")
@click.argument("branch_name")
@click.pass_context
def git_checkout_cmd(ctx, repo_path, branch_name):
    """切换分支"""
    from tools.git_ops import git_checkout
    output = git_checkout(repo_path, branch=branch_name)
    click.echo(output)


@git.command("create-release-branch")
@click.option("--repo-path", default=".", help="仓库路径")
@click.option("--name", default=None, help="分支名称（默认 releaseMMDDYY）")
@click.option("--base", default="main", help="基于哪个分支创建")
@click.pass_context
def git_create_release_branch_cmd(ctx, repo_path, name, base):
    """创建 Release 分支"""
    from tools.git_ops import create_release_branch
    branch = create_release_branch(repo_path, name=name, base=base)
    click.echo(f"✅ Release 分支已创建: {branch}")


# ═══════════════════════════════════════════════════════════════════
# release - 完整发布流程（编排命令）
# ═══════════════════════════════════════════════════════════════════

@cli.group()
def release():
    """完整发布流程编排"""
    pass


@release.command("run")
@click.option("--platform", "-p", required=True, type=click.Choice(["android", "ios"]), help="android 或 ios")
@click.option("--version", "-v", required=True, help="版本号，如 2.0.6")
@click.option("--branch", "-b", default=None, help="Release 分支名，不填则用 release_MMDD（如 release_0225）")
@click.option("--repo-path", default=".", help="Git 仓库路径")
@click.option("--skip-notes", is_flag=True, default=False, help="跳过 Release Notes 生成")
@click.option("--skip-upload", is_flag=True, default=False, help="仅打包不上传")
@click.option("--poll-interval", default=60, help="轮询 Jenkins 状态间隔（秒）")
@click.option("--build-timeout", default=7200, help="等待构建完成超时（秒），默认 2 小时")
@click.option("--dry-run", is_flag=True, default=False, help="仅打印计划不执行")
@click.pass_context
def release_run(
    ctx, platform, version, branch, repo_path, skip_notes, skip_upload,
    poll_interval, build_timeout, dry_run,
):
    """一键发布：检查/创建 release 分支 → 触发 Jenkins → 等待产物 → 上传（Agent 调用此命令即可，避免多步超时）"""
    if branch is None:
        from datetime import datetime
        branch = f"release_{datetime.now().strftime('%m%d')}"
    click.echo(f"📋 一键发布计划: {platform} v{version}")
    click.echo(f"   分支: {branch} | Release Notes: {'跳过' if skip_notes else '生成'} | 上传: {'否' if skip_upload else '是'}")
    click.echo("")

    if dry_run:
        click.echo("🔍 Dry run，不执行。")
        return

    # 1. 确保 release 分支存在
    click.echo("🔀 Step 1: 检查/创建 release 分支...")
    from tools.git_ops import ensure_release_branch
    r = ensure_release_branch(branch_name=branch, base="main", repo_path=repo_path, push=True)
    _output(ctx, r)
    if not r.get("success"):
        return

    # 2. Release Notes（可选）
    gplay_notes_file = None
    appstore_notes_file = None
    if not skip_notes:
        click.echo("\n📝 Step 2: 生成 Release Notes...")
        from tools.release_notes import generate_release_notes
        result = generate_release_notes(version=version, repo_path=repo_path, branch=branch, commits=30, output_dir="./release_notes")
        _output(ctx, result)
        if not result.get("success"):
            return
        files = result.get("files", {})
        gplay_notes_file = files.get("google_play")
        appstore_notes_file = files.get("appstore")
    else:
        click.echo("\n📝 Step 2: 跳过 Release Notes")

    # 3. 触发 Jenkins 并等待完成
    click.echo("\n🔨 Step 3: 触发 Jenkins 构建...")
    from tools.jenkins import trigger_build, get_latest_build_number, wait_for_build
    t = trigger_build(platform=platform, mode="release", branch=branch)
    _output(ctx, t)
    if not t.get("success"):
        return
    after = get_latest_build_number(platform, "release")
    click.echo(f"\n⏳ Step 4: 等待构建完成（每 {poll_interval}s 轮询，超时 {build_timeout}s）...")
    w = wait_for_build(platform, "release", after_build_number=after, poll_interval=poll_interval, timeout_seconds=build_timeout)
    _output(ctx, w)
    if not w.get("success"):
        click.echo("❌ 构建未成功，终止。")
        return

    build_number = w.get("build_number")
    if skip_upload:
        click.echo(f"\n✅ 构建完成 #{build_number}，已跳过上传。")
        if platform == "android":
            from tools.jenkins import resolve_android_aab_path
            aab = resolve_android_aab_path(build_number) if build_number else None
            if aab:
                click.echo(f"   AAB: {aab}")
        return

    # 5. 上传
    if platform == "android":
        from tools.jenkins import resolve_android_aab_path
        from tools.google_play import upload_bundle, promote
        aab = resolve_android_aab_path(build_number) if build_number else None
        if not aab or not os.path.isfile(aab):
            click.echo(f"\n❌ 未找到 AAB（构建号 {build_number}），请检查 jenkins.build_output_dir 与产物路径约定。")
            return
        click.echo(f"\n📤 Step 5: 上传 AAB 到 Google Play...")
        gplay_notes = None
        if gplay_notes_file and os.path.isfile(gplay_notes_file):
            with open(gplay_notes_file, "r", encoding="utf-8") as f:
                gplay_notes = f.read().strip()
        result = upload_bundle(aab_path=aab, track="beta", version=version, release_notes=gplay_notes, rollout_percentage=100.0)
        _output(ctx, result)
        if not result.get("success"):
            return
        vc = result.get("version_code")
        if vc:
            click.echo("📤 推广到 Internal...")
            _output(ctx, promote(version_code=vc, from_track="beta", to_track="internal", version=version, release_notes=gplay_notes))
        click.echo("\n🎉 Android 一键发布完成。")
    else:
        from tools.config import get_jenkins_ios_ipa_output_path
        from tools.app_store import upload_ipa, create_version, update_release_notes
        ipa = get_jenkins_ios_ipa_output_path()
        if not ipa or not os.path.isfile(ipa):
            click.echo(f"\n❌ 未找到 IPA: {ipa}，请确认 Jenkins 已将产物放到约定路径。")
            return
        click.echo("\n📤 Step 5: 上传 IPA 到 App Store Connect...")
        result = upload_ipa(ipa_path=ipa)
        _output(ctx, result)
        if not result.get("success"):
            return
        click.echo(f"\n📋 创建版本 v{version}...")
        cv = create_version(version_string=version)
        _output(ctx, cv)
        if cv.get("success") and cv.get("version_id") and appstore_notes_file and os.path.isfile(appstore_notes_file):
            with open(appstore_notes_file, "r", encoding="utf-8") as f:
                notes = f.read().strip()
            _output(ctx, update_release_notes(version_id=cv["version_id"], release_notes=notes))
        click.echo("\n🎉 iOS 一键发布完成。")


@release.command("android")
@click.option("--version", "-v", required=True, help="版本号")
@click.option("--aab", default=None, help=".aab 文件路径（不指定则从 Jenkins 输出目录查找）")
@click.option("--repo-path", default=".", help="Git 仓库路径")
@click.option("--branch", "-b", default="main", help="Release 分支")
@click.option("--commits", "-n", default=30, help="Release Notes 读取 commit 数")
@click.option("--skip-notes", is_flag=True, default=False, help="跳过 Release Notes 生成")
@click.option("--skip-build", is_flag=True, default=False, help="跳过 Jenkins 构建")
@click.option("--skip-upload", is_flag=True, default=False, help="跳过 Google Play 上传")
@click.option("--dry-run", is_flag=True, default=False, help="仅打印计划，不执行")
@click.pass_context
def release_android(ctx, version, aab, repo_path, branch, commits, skip_notes, skip_build, skip_upload, dry_run):
    """Android 完整发布流程"""
    from tools.config import get_jenkins_build_output_dir

    steps = []

    # Step 1: Release Notes
    if not skip_notes:
        steps.append(("生成 Release Notes", "release_notes"))
    else:
        steps.append(("跳过 Release Notes", "skip"))

    # Step 2: Jenkins Build
    if not skip_build:
        steps.append(("触发 Jenkins Android Release 构建", "build"))
    else:
        steps.append(("跳过 Jenkins 构建", "skip"))

    # Step 3: Upload to Google Play (Open Testing)
    if not skip_upload:
        steps.append(("上传 AAB 到 Google Play Open Testing", "upload_beta"))
        steps.append(("推广到 Internal Testing", "promote_internal"))
    else:
        steps.append(("跳过 Google Play 上传", "skip"))

    click.echo(f"\n📋 Android 发布计划 - v{version}")
    click.echo("=" * 50)
    for i, (desc, _) in enumerate(steps, 1):
        click.echo(f"  {i}. {desc}")
    click.echo("")

    if dry_run:
        click.echo("🔍 Dry run 模式，不执行实际操作。")
        return

    # 执行
    notes_dir = f"./release_notes"
    gplay_notes_file = None

    # Step 1: Release Notes
    if not skip_notes:
        click.echo("\n📝 Step 1: 生成 Release Notes...")
        from tools.release_notes import generate_release_notes

        result = generate_release_notes(
            version=version,
            repo_path=repo_path,
            branch=branch,
            commits=commits,
            output_dir=notes_dir,
        )
        _output(ctx, result)
        if not result.get("success"):
            click.echo("❌ Release Notes 生成失败，终止流程。")
            return
        gplay_notes_file = result.get("files", {}).get("google_play")

    # Step 2: Jenkins Build
    if not skip_build:
        click.echo("\n🔨 Step 2: 触发 Jenkins 构建...")
        from tools.jenkins import trigger_build

        result = trigger_build(
            platform="android",
            mode="release",
            branch=branch,
        )
        _output(ctx, result)
        if not result.get("success"):
            click.echo("❌ Jenkins 构建触发失败，终止流程。")
            return
        click.echo("\n⏳ Jenkins 正在构建，请等待构建完成后继续。")
        click.echo(f"   构建页面: {result.get('url', '')}")
        if not aab:
            click.echo(f"   构建完成后，请使用以下命令继续上传：")
            click.echo(f"   python cli.py gplay upload --aab <path-to-aab> --track beta --version {version}")
            return

    # Step 3: Upload
    if not skip_upload:
        if not aab:
            # 尝试从 Jenkins 输出目录查找
            build_dir = get_jenkins_build_output_dir()
            click.echo(f"\n⚠️  未指定 AAB 路径，请提供 --aab 参数。")
            click.echo(f"   Jenkins 输出目录: {build_dir}")
            return

        click.echo(f"\n📤 Step 3: 上传到 Google Play Open Testing...")
        from tools.google_play import upload_bundle

        gplay_notes = None
        if gplay_notes_file:
            try:
                with open(gplay_notes_file, "r", encoding="utf-8") as f:
                    gplay_notes = f.read().strip()
            except Exception:
                pass

        result = upload_bundle(
            aab_path=aab,
            track="beta",
            version=version,
            release_notes=gplay_notes,
            rollout_percentage=100.0,
        )
        _output(ctx, result)
        if not result.get("success"):
            click.echo("❌ 上传失败，终止流程。")
            return

        version_code = result.get("version_code")

        # Step 4: Promote to Internal
        if version_code:
            click.echo(f"\n📤 Step 4: 推广到 Internal Testing...")
            from tools.google_play import promote

            result = promote(
                version_code=version_code,
                from_track="beta",
                to_track="internal",
                version=version,
                release_notes=gplay_notes,
            )
            _output(ctx, result)

    click.echo(f"\n🎉 Android v{version} 发布流程完成！")
    click.echo("   请前往 Google Play Console 的 Publishing overview 页面提交审核。")


@release.command("ios")
@click.option("--version", "-v", required=True, help="版本号")
@click.option("--ipa", default=None, help=".ipa 文件路径")
@click.option("--repo-path", default=".", help="Git 仓库路径")
@click.option("--branch", "-b", default="main", help="Release 分支")
@click.option("--commits", "-n", default=30, help="Release Notes 读取 commit 数")
@click.option("--skip-notes", is_flag=True, default=False, help="跳过 Release Notes 生成")
@click.option("--skip-build", is_flag=True, default=False, help="跳过 Jenkins 构建")
@click.option("--skip-upload", is_flag=True, default=False, help="跳过上传")
@click.option("--dry-run", is_flag=True, default=False, help="仅打印计划，不执行")
@click.pass_context
def release_ios(ctx, version, ipa, repo_path, branch, commits, skip_notes, skip_build, skip_upload, dry_run):
    """iOS 完整发布流程"""

    steps = []
    if not skip_notes:
        steps.append("生成 Release Notes")
    if not skip_build:
        steps.append("触发 Jenkins iOS Release 构建")
    if not skip_upload:
        steps.append("上传 IPA 到 App Store Connect")
        steps.append("创建 App Store 版本")
        steps.append("设置 Release Notes")

    click.echo(f"\n📋 iOS 发布计划 - v{version}")
    click.echo("=" * 50)
    for i, desc in enumerate(steps, 1):
        click.echo(f"  {i}. {desc}")
    click.echo("")

    if dry_run:
        click.echo("🔍 Dry run 模式，不执行实际操作。")
        return

    notes_dir = "./release_notes"

    # Step 1: Release Notes
    if not skip_notes:
        click.echo("\n📝 Step 1: 生成 Release Notes...")
        from tools.release_notes import generate_release_notes

        result = generate_release_notes(
            version=version,
            repo_path=repo_path,
            branch=branch,
            commits=commits,
            output_dir=notes_dir,
        )
        _output(ctx, result)
        if not result.get("success"):
            click.echo("❌ Release Notes 生成失败，终止流程。")
            return

    # Step 2: Jenkins Build
    if not skip_build:
        click.echo("\n🔨 Step 2: 触发 Jenkins iOS Release 构建...")
        from tools.jenkins import trigger_build

        result = trigger_build(
            platform="ios",
            mode="release",
            branch=branch,
        )
        _output(ctx, result)
        if not result.get("success"):
            click.echo("❌ Jenkins 构建触发失败。")
            return
        click.echo("\n⏳ Jenkins 正在构建，请等待完成。")

    # Step 3: Upload IPA（未指定 --ipa 时使用 config 中的 jenkins.ios_ipa_output_path）
    if not skip_upload:
        if not ipa:
            from tools.config import get_jenkins_ios_ipa_output_path
            ipa = get_jenkins_ios_ipa_output_path()
        if not ipa:
            click.echo("\n⚠️  未指定 IPA 路径且未配置 jenkins.ios_ipa_output_path，请提供 --ipa 或配置约定路径。")
            return
        if not os.path.isfile(ipa):
            click.echo(f"\n⚠️  IPA 文件不存在: {ipa}")
            click.echo("   请确认 Jenkins 已构建完成并将产物放到约定路径，或使用 --ipa 指定路径。")
            return

        click.echo(f"\n📤 Step 3: 上传 IPA...")
        from tools.app_store import upload_ipa

        result = upload_ipa(ipa_path=ipa)
        _output(ctx, result)
        if not result.get("success"):
            click.echo("❌ 上传失败。")
            return

        # Step 4: Create version
        click.echo(f"\n📋 Step 4: 创建 App Store 版本 v{version}...")
        from tools.app_store import create_version

        result = create_version(version_string=version)
        _output(ctx, result)

        # Step 5: Set release notes
        if result.get("success"):
            version_id = result.get("version_id")
            appstore_notes_file = f"{notes_dir}/{version}_appstore.txt"
            if os.path.exists(appstore_notes_file):
                click.echo(f"\n📝 Step 5: 设置 Release Notes...")
                from tools.app_store import update_release_notes
                with open(appstore_notes_file, "r", encoding="utf-8") as f:
                    notes_text = f.read().strip()
                result = update_release_notes(version_id=version_id, release_notes=notes_text)
                _output(ctx, result)

    click.echo(f"\n🎉 iOS v{version} 发布流程完成！")
    click.echo("   请在 App Store Connect 中确认并提审。")


# ═══════════════════════════════════════════════════════════════════
# status - 全局状态查询
# ═══════════════════════════════════════════════════════════════════

@cli.command("status")
@click.option("--repo-path", default=".", help="仓库路径")
@click.pass_context
def status_cmd(ctx, repo_path):
    """查看当前项目发布状态概览"""
    from tools.git_ops import get_current_branch, git_status

    click.echo("📊 Wingstrike Release Status Overview")
    click.echo("=" * 50)

    # Git
    try:
        branch = get_current_branch(repo_path)
        click.echo(f"\n🔀 Git Branch: {branch}")
    except Exception:
        click.echo("\n🔀 Git: 无法获取分支信息")

    # Google Play
    click.echo("\n📱 Google Play:")
    try:
        from tools.google_play import get_track_status
        result = get_track_status()
        if result.get("success"):
            for t in result.get("tracks", []):
                track_name = t.get("track", "unknown")
                releases = t.get("releases", [])
                if releases:
                    latest = releases[0]
                    click.echo(f"  {track_name}: {latest.get('status', 'N/A')} "
                               f"(codes: {latest.get('version_codes', [])})")
                else:
                    click.echo(f"  {track_name}: 无 release")
        else:
            click.echo(f"  ⚠️  {result.get('message', '无法查询')}")
    except Exception as e:
        click.echo(f"  ⚠️  查询失败: {e}")

    # App Store
    click.echo("\n🍎 App Store:")
    try:
        from tools.app_store import get_app_status
        result = get_app_status()
        if result.get("success"):
            for v in result.get("versions", [])[:3]:
                click.echo(f"  v{v.get('version_string', '?')}: {v.get('state', 'N/A')}")
        else:
            click.echo(f"  ⚠️  {result.get('message', '无法查询')}")
    except Exception as e:
        click.echo(f"  ⚠️  查询失败: {e}")


# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cli()

