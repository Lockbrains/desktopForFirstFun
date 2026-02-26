"""
Xcode 工程 → IPA 命令行导出。

在已有 .xcworkspace 的机器上执行：
  1. xcodebuild archive → .xcarchive
  2. xcodebuild -exportArchive -exportOptionsPlist → .ipa

供本机或 Jenkins 调用，不依赖 Xcode UI。
"""

import subprocess
from pathlib import Path
from typing import Optional


def build_ipa(
    workspace_path: str,
    scheme: str,
    configuration: str = "Release",
    export_options_plist: str = "",
    archive_path: Optional[str] = None,
    export_path: Optional[str] = None,
    derived_data_path: Optional[str] = None,
) -> dict:
    """
    从 Xcode 工程打出 IPA。

    Args:
        workspace_path: .xcworkspace 的绝对路径（或含 .xcworkspace 的目录）
        scheme: Scheme 名称
        configuration: 一般为 Release
        export_options_plist: ExportOptions.plist 的绝对路径（Ad Hoc / App Store 等）
        archive_path: 生成的 .xcarchive 路径，不填则用临时目录
        export_path: 导出目录，IPA 会在此目录下，不填则用 archive_path 同级的 export
        derived_data_path: 可选，DerivedData 路径

    Returns:
        dict: success, message, ipa_path, archive_path
    """
    workspace = Path(workspace_path).resolve()
    if not workspace.exists():
        return {"success": False, "message": f"Workspace 不存在: {workspace}"}
    if workspace.suffix != ".xcworkspace":
        # 可能是目录，找里面的 xcworkspace
        candidates = list(workspace.glob("*.xcworkspace"))
        if not candidates:
            return {"success": False, "message": f"目录下未找到 .xcworkspace: {workspace}"}
        workspace = candidates[0]

    if not export_options_plist or not Path(export_options_plist).exists():
        return {
            "success": False,
            "message": f"ExportOptions.plist 不存在或未配置: {export_options_plist}",
        }

    base_dir = workspace.parent
    if not archive_path:
        archive_path = str(base_dir / "build" / "Wingstrike.xcarchive")
    if not export_path:
        export_path = str(Path(archive_path).parent / "ipa_export")

    Path(archive_path).parent.mkdir(parents=True, exist_ok=True)
    Path(export_path).mkdir(parents=True, exist_ok=True)

    # 1. Archive
    archive_cmd = [
        "xcodebuild",
        "-workspace", str(workspace),
        "-scheme", scheme,
        "-configuration", configuration,
        "-archivePath", archive_path,
    ]
    if derived_data_path:
        archive_cmd.extend(["-derivedDataPath", derived_data_path])

    try:
        out = subprocess.run(
            archive_cmd,
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "xcodebuild archive 超时（60 分钟）"}
    except FileNotFoundError:
        return {"success": False, "message": "未找到 xcodebuild，请确保在 macOS 上且已安装 Xcode"}

    if out.returncode != 0:
        stderr = (out.stderr or "")[-2000:]
        return {
            "success": False,
            "message": f"xcodebuild archive 失败 (exit {out.returncode})",
            "detail": stderr,
        }

    # 2. Export IPA
    export_cmd = [
        "xcodebuild", "-exportArchive",
        "-archivePath", archive_path,
        "-exportPath", export_path,
        "-exportOptionsPlist", export_options_plist,
    ]
    try:
        out2 = subprocess.run(
            export_cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "xcodebuild -exportArchive 超时（10 分钟）"}

    if out2.returncode != 0:
        stderr = (out2.stderr or "")[-2000:]
        return {
            "success": False,
            "message": f"xcodebuild -exportArchive 失败 (exit {out2.returncode})",
            "detail": stderr,
        }

    # IPA 通常在 export_path 下，名称多为 <AppName>.ipa
    export_dir = Path(export_path)
    ipa_files = list(export_dir.glob("*.ipa"))
    if not ipa_files:
        return {
            "success": False,
            "message": f"导出目录下未找到 .ipa: {export_path}",
            "export_path": export_path,
        }
    ipa_path = str(ipa_files[0].resolve())

    return {
        "success": True,
        "message": "IPA 已导出",
        "ipa_path": ipa_path,
        "archive_path": archive_path,
        "export_path": export_path,
    }
