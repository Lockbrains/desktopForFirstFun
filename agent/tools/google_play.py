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
import time
from pathlib import Path
from typing import Optional

import httplib2
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .config import get_android_package_name, get_google_play_service_account_json, get_app_name


SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]

# 每块上传的单次请求超时（秒）。设短一点便于“卡住”时尽快超时并触发断点续传重试，否则会一直干等
UPLOAD_HTTP_TIMEOUT = 60  # 60 秒/块；最后一块需等 Google 校验完再回 200，太短会一直超时


def _get_service(
    service_account_json: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
):
    """创建 Google Play Developer API 服务实例。timeout_seconds 用于上传等长耗时请求。"""
    json_path = service_account_json or get_google_play_service_account_json()
    if not json_path or not Path(json_path).exists():
        raise FileNotFoundError(
            f"Google Play Service Account JSON 不存在: {json_path}\n"
            "请在 config.yaml 的 app.android.service_account_json 中设置正确路径。"
        )
    credentials = service_account.Credentials.from_service_account_file(
        json_path, scopes=SCOPES
    )
    if timeout_seconds is not None and timeout_seconds > 0:
        http = httplib2.Http(timeout=timeout_seconds)
        # 308 Resume Incomplete 是分片上传的中间响应，不应被当作“重定向”跟随（否则会报 RedirectMissingLocation）。
        # 从 redirect_codes 中排除 308，让 308 原样返回给 googleapiclient 的 resumable upload 逻辑继续发下一块。
        if hasattr(http, "redirect_codes"):
            codes = getattr(http, "redirect_codes", set())
            if isinstance(codes, set):
                http.redirect_codes = codes - {308}
            else:
                http.redirect_codes = set(codes) - {308}
        auth_http = AuthorizedHttp(credentials, http=http)
        return build("androidpublisher", "v3", http=auth_http)
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
    debug: bool = False,
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
        debug: 为 True 时开启 httplib2 详细输出（请求/响应），便于排查重定向等问题

    Returns:
        dict with 'success', 'message', 'version_code', 'edit_id'
    """
    aab = Path(aab_path)
    if not aab.exists():
        return {"success": False, "message": f"AAB 文件不存在: {aab_path}"}

    pkg = package_name or get_android_package_name()
    if not pkg:
        return {"success": False, "message": "未配置 Android 包名 (package_name)。"}

    if debug:
        httplib2.debuglevel = 1

    try:
        service = _get_service(service_account_json, timeout_seconds=UPLOAD_HTTP_TIMEOUT)
    except FileNotFoundError as e:
        return {"success": False, "message": str(e)}

    # 自动生成 release name
    app_name = get_app_name()
    if not release_name and version:
        release_name = f"{app_name} ({version})"

    # 截断 release notes 到 500 字符
    if release_notes and len(release_notes) > 500:
        release_notes = release_notes[:497] + "..."

    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            # 1. 创建 edit
            edit_id = _begin_edit(service, pkg)

            # 2. 上传 AAB（可恢复上传 + next_chunk 循环以便显示进度）
            # 使用 1MB 分块：每轮“发块+等 308”更短，不易单次读超时；进度更新更频繁（279MB 约 280 次）
            CHUNK_MB = 1
            media = MediaFileUpload(
                str(aab),
                mimetype="application/octet-stream",
                resumable=True,
                chunksize=CHUNK_MB * 1024 * 1024,
            )
            request = service.edits().bundles().upload(
                packageName=pkg,
                editId=edit_id,
                media_body=media,
            )
            upload_result = None
            file_size = aab.stat().st_size
            total_mb = file_size / (1024 * 1024)
            # 单块失败时重试次数（超时/5xx 后再次 next_chunk 会从断点续传，不丢进度）
            MAX_CHUNK_RETRIES = 10
            print(f"  分块上传中（每块 {CHUNK_MB} MB，共 {total_mb:.0f} MB），单块失败将自动重试最多 {MAX_CHUNK_RETRIES} 次", flush=True)
            while upload_result is None:
                status = None
                for chunk_attempt in range(MAX_CHUNK_RETRIES):
                    try:
                        status, upload_result = request.next_chunk()
                        break
                    except Exception as chunk_err:
                        err_str = str(chunk_err).lower()
                        is_timeout = "timed out" in err_str or "timeout" in err_str
                        is_5xx = isinstance(chunk_err, HttpError) and getattr(
                            getattr(chunk_err, "resp", None), "status", None
                        ) in (500, 502, 503, 504)
                        if (is_timeout or is_5xx) and chunk_attempt < MAX_CHUNK_RETRIES - 1:
                            delay = (2 ** chunk_attempt) * 5
                            print(
                                f"  本块超时/失败，{delay}s 后从断点续传 ({chunk_attempt + 1}/{MAX_CHUNK_RETRIES})...",
                                flush=True,
                            )
                            time.sleep(delay)
                        else:
                            raise chunk_err
                if status:
                    pct = int(status.progress() * 100)
                    done = getattr(status, "resumable_progress", None)
                    if done is None:
                        done = int(status.progress() * file_size)
                    done_mb = done / (1024 * 1024)
                    print(f"  上传进度: {pct}% ({done_mb:.1f} / {total_mb:.1f} MB)", flush=True)
            print("  上传完成，正在设置 track 并提交...", flush=True)

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
                "message": f"AAB 已上传到 {track} track，请用 gplay status 确认 Play Console 是否出现新版本",
                "version_code": version_code,
                "track": track,
                "release_name": release_name,
                "edit_id": edit_id,
            }

        except Exception as e:
            last_error = e
            err_msg = str(e).strip()
            is_timeout = "timed out" in err_msg.lower() or "timeout" in err_msg.lower()
            status = getattr(getattr(e, "resp", None), "status", None) if isinstance(e, HttpError) else None
            is_retryable = is_timeout or (status in (500, 502, 503, 504))
            if is_retryable and attempt < max_retries - 1:
                delay = (2 ** attempt) * 10
                time.sleep(delay)
                continue
            break

    msg = f"上传失败: {last_error}"
    if last_error and "timed out" in str(last_error).lower():
        msg += "（读/写超时，可检查网络或稍后重试；单块 60 秒超时并会自动重试）"
    err_str = str(last_error).lower() if last_error else ""
    if "redirect" in err_str or "location" in err_str:
        msg += " 建议使用 --debug 再次运行并保存完整输出（例如: 2>&1 | tee upload.log），或检查本机代理/防火墙。"
    return {
        "success": False,
        "message": msg,
        "error_type": type(last_error).__name__ if last_error else None,
    }


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

