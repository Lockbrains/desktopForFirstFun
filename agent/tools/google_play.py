"""
Google Play 发布模块。
使用 Google Play Developer API v3 (androidpublisher) 管理应用发布。

主要流程:
  1. gplay upload   - 上传 .aab 到指定 track
  2. gplay promote  - 将已上传的版本从库中分配到另一个 track
  3. gplay submit   - 提交变更供 Google 审核
  4. gplay status   - 查看各 track 状态

参考文档: https://developers.google.com/android-publisher/api-ref/rest
"""

import json
import os
from pathlib import Path
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .config import get_android_package_name, get_google_play_service_account_json, get_app_name


SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]


def _get_service(service_account_json: Optional[str] = None):
    """创建 Google Play Developer API 服务实例。"""
    json_path = service_account_json or get_google_play_service_account_json()
    if not json_path or not Path(json_path).exists():
        raise FileNotFoundError(
            f"Google Play Service Account JSON 不存在: {json_path}\n"
            "请在 config.yaml 的 app.android.service_account_json 中设置正确路径。"
        )
    credentials = service_account.Credentials.from_service_account_file(
        json_path, scopes=SCOPES
    )
    return build("androidpublisher", "v3", credentials=credentials)


def _begin_edit(service, package_name: str) -> str:
    """开始一个新的 edit。返回 editId。"""
    result = service.edits().insert(
        packageName=package_name,
        body={},
    ).execute()
    return result["id"]


def _commit_edit(service, package_name: str, edit_id: str) -> dict:
    """提交 edit（使变更生效）。"""
    return service.edits().commit(
        packageName=package_name,
        editId=edit_id,
    ).execute()


def upload_bundle(
    aab_path: str,
    track: str = "beta",  # beta = open testing
    release_name: Optional[str] = None,
    release_notes: Optional[str] = None,
    rollout_percentage: float = 100.0,
    version: Optional[str] = None,
    package_name: Optional[str] = None,
    service_account_json: Optional[str] = None,
    draft: bool = False,
) -> dict:
    """
    上传 AAB 文件到 Google Play 指定 track。

    Args:
        aab_path: .aab 文件路径
        track: 发布轨道 ('internal', 'alpha', 'beta', 'production')
                beta = Open testing, internal = Internal testing
        release_name: 发布名称，如 "Wingstrike (1.2.3)"
        release_notes: 发布说明（Google Play 限 500 字符）
        rollout_percentage: 灰度比例 (0-100)
        version: 版本号，用于自动生成 release_name
        package_name: 包名，默认从 config 读取
        service_account_json: 服务账号 JSON 路径，默认从 config 读取
        draft: 是否作为草稿（不立即发布）

    Returns:
        dict with 'success', 'message', 'version_code', 'edit_id'
    """
    aab = Path(aab_path)
    if not aab.exists():
        return {"success": False, "message": f"AAB 文件不存在: {aab_path}"}

    pkg = package_name or get_android_package_name()
    if not pkg:
        return {"success": False, "message": "未配置 Android 包名 (package_name)。"}

    try:
        service = _get_service(service_account_json)
    except FileNotFoundError as e:
        return {"success": False, "message": str(e)}

    # 自动生成 release name
    app_name = get_app_name()
    if not release_name and version:
        release_name = f"{app_name} ({version})"

    # 截断 release notes 到 500 字符
    if release_notes and len(release_notes) > 500:
        release_notes = release_notes[:497] + "..."

    try:
        # 1. 创建 edit
        edit_id = _begin_edit(service, pkg)

        # 2. 上传 AAB
        media = MediaFileUpload(str(aab), mimetype="application/octet-stream")
        upload_result = service.edits().bundles().upload(
            packageName=pkg,
            editId=edit_id,
            media_body=media,
        ).execute()

        version_code = upload_result.get("versionCode")

        # 3. 设置 track
        release_body: dict = {
            "versionCodes": [str(version_code)],
        }
        if release_name:
            release_body["name"] = release_name
        if release_notes:
            release_body["releaseNotes"] = [
                {"language": "en-US", "text": release_notes}
            ]
        if draft:
            release_body["status"] = "draft"
        else:
            release_body["status"] = "completed" if rollout_percentage >= 100 else "inProgress"
            if rollout_percentage < 100:
                release_body["userFraction"] = rollout_percentage / 100.0

        track_body = {
            "track": track,
            "releases": [release_body],
        }

        service.edits().tracks().update(
            packageName=pkg,
            editId=edit_id,
            track=track,
            body=track_body,
        ).execute()

        # 4. 提交 edit
        _commit_edit(service, pkg, edit_id)

        return {
            "success": True,
            "message": f"AAB 已上传到 {track} track",
            "version_code": version_code,
            "track": track,
            "release_name": release_name,
            "edit_id": edit_id,
        }

    except Exception as e:
        return {"success": False, "message": f"上传失败: {e}"}


def promote(
    version_code: int,
    from_track: str = "beta",
    to_track: str = "internal",
    release_name: Optional[str] = None,
    release_notes: Optional[str] = None,
    rollout_percentage: float = 100.0,
    version: Optional[str] = None,
    package_name: Optional[str] = None,
    service_account_json: Optional[str] = None,
    draft: bool = False,
) -> dict:
    """
    将已上传的版本从一个 track 推广到另一个 track（"Add from library" 操作）。

    Args:
        version_code: 要推广的版本 code
        from_track: 来源 track（仅作记录）
        to_track: 目标 track
        release_name: 发布名称
        release_notes: 发布说明
        rollout_percentage: 灰度比例
        version: 版本号，用于自动生成 release_name
        package_name: 包名
        service_account_json: 服务账号 JSON 路径
        draft: 是否作为草稿

    Returns:
        dict with 'success', 'message'
    """
    pkg = package_name or get_android_package_name()
    if not pkg:
        return {"success": False, "message": "未配置 Android 包名 (package_name)。"}

    try:
        service = _get_service(service_account_json)
    except FileNotFoundError as e:
        return {"success": False, "message": str(e)}

    app_name = get_app_name()
    if not release_name and version:
        release_name = f"{app_name} ({version})"

    if release_notes and len(release_notes) > 500:
        release_notes = release_notes[:497] + "..."

    try:
        edit_id = _begin_edit(service, pkg)

        release_body: dict = {
            "versionCodes": [str(version_code)],
        }
        if release_name:
            release_body["name"] = release_name
        if release_notes:
            release_body["releaseNotes"] = [
                {"language": "en-US", "text": release_notes}
            ]
        if draft:
            release_body["status"] = "draft"
        else:
            release_body["status"] = "completed" if rollout_percentage >= 100 else "inProgress"
            if rollout_percentage < 100:
                release_body["userFraction"] = rollout_percentage / 100.0

        track_body = {
            "track": to_track,
            "releases": [release_body],
        }

        service.edits().tracks().update(
            packageName=pkg,
            editId=edit_id,
            track=to_track,
            body=track_body,
        ).execute()

        _commit_edit(service, pkg, edit_id)

        return {
            "success": True,
            "message": f"版本 {version_code} 已从 {from_track} 推广到 {to_track}",
            "version_code": version_code,
            "to_track": to_track,
            "release_name": release_name,
            "edit_id": edit_id,
        }

    except Exception as e:
        return {"success": False, "message": f"推广失败: {e}"}


def get_track_status(
    track: Optional[str] = None,
    package_name: Optional[str] = None,
    service_account_json: Optional[str] = None,
) -> dict:
    """
    查询指定 track（或所有 track）的状态。

    Args:
        track: 指定 track 名称，None 则查询全部
        package_name: 包名
        service_account_json: 服务账号 JSON 路径

    Returns:
        dict with 'success', 'tracks'
    """
    pkg = package_name or get_android_package_name()
    if not pkg:
        return {"success": False, "message": "未配置 Android 包名 (package_name)。"}

    try:
        service = _get_service(service_account_json)
    except FileNotFoundError as e:
        return {"success": False, "message": str(e)}

    try:
        edit_id = _begin_edit(service, pkg)

        if track:
            result = service.edits().tracks().get(
                packageName=pkg,
                editId=edit_id,
                track=track,
            ).execute()
            tracks_data = [result]
        else:
            result = service.edits().tracks().list(
                packageName=pkg,
                editId=edit_id,
            ).execute()
            tracks_data = result.get("tracks", [])

        # 格式化输出
        tracks_info = []
        for t in tracks_data:
            track_info = {
                "track": t.get("track"),
                "releases": [],
            }
            for r in t.get("releases", []):
                track_info["releases"].append({
                    "name": r.get("name", ""),
                    "status": r.get("status", ""),
                    "version_codes": r.get("versionCodes", []),
                    "user_fraction": r.get("userFraction"),
                })
            tracks_info.append(track_info)

        return {
            "success": True,
            "package_name": pkg,
            "tracks": tracks_info,
        }

    except Exception as e:
        return {"success": False, "message": f"查询失败: {e}"}


def list_bundles(
    package_name: Optional[str] = None,
    service_account_json: Optional[str] = None,
) -> dict:
    """列出所有已上传的 bundle。"""
    pkg = package_name or get_android_package_name()
    if not pkg:
        return {"success": False, "message": "未配置 Android 包名 (package_name)。"}

    try:
        service = _get_service(service_account_json)
    except FileNotFoundError as e:
        return {"success": False, "message": str(e)}

    try:
        edit_id = _begin_edit(service, pkg)
        result = service.edits().bundles().list(
            packageName=pkg,
            editId=edit_id,
        ).execute()

        bundles = []
        for b in result.get("bundles", []):
            bundles.append({
                "version_code": b.get("versionCode"),
                "sha256": b.get("sha256"),
            })

        return {
            "success": True,
            "bundles": bundles,
        }

    except Exception as e:
        return {"success": False, "message": f"查询失败: {e}"}

