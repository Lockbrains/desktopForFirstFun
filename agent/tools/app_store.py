"""
App Store Connect 发布模块。

使用两种方式：
  1. App Store Connect API (REST) - 管理版本、提审等
  2. xcrun altool / Transporter CLI - 上传 IPA 文件

注意：altool 和 Transporter 只能在 macOS 上运行。
"""

import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt
import requests

from .config import (
    get_appstore_api_key_id,
    get_appstore_api_key_path,
    get_appstore_api_issuer_id,
    get_ios_bundle_id,
)


ASC_API_BASE = "https://api.appstoreconnect.apple.com/v1"


# ── JWT Token 生成 ─────────────────────────────────────────────────

def _generate_asc_token() -> str:
    """生成 App Store Connect API 的 JWT token（有效期 20 分钟）。"""
    key_id = get_appstore_api_key_id()
    issuer_id = get_appstore_api_issuer_id()
    key_path = get_appstore_api_key_path()

    if not key_id or not issuer_id or not key_path:
        raise ValueError(
            "App Store Connect API 凭证未配置。\n"
            "请在 config.yaml 中设置 app.ios.api_key_id, api_issuer_id, api_key_path。"
        )

    with open(key_path, "r") as f:
        private_key = f.read()

    now = datetime.now(timezone.utc)
    payload = {
        "iss": issuer_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=20)).timestamp()),
        "aud": "appstoreconnect-v1",
    }

    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": key_id})


def _asc_headers() -> dict:
    """构建 App Store Connect API 请求头。"""
    token = _generate_asc_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# ── IPA 上传 ──────────────────────────────────────────────────────

def upload_ipa(
    ipa_path: str,
    method: str = "altool",
    api_key_id: Optional[str] = None,
    api_issuer_id: Optional[str] = None,
) -> dict:
    """
    上传 IPA 到 App Store Connect。

    Args:
        ipa_path: .ipa 文件路径
        method: 'altool' 或 'transporter'
        api_key_id: API Key ID，默认从 config 读取
        api_issuer_id: Issuer ID，默认从 config 读取

    Returns:
        dict with 'success', 'message'
    """
    ipa = Path(ipa_path)
    if not ipa.exists():
        return {"success": False, "message": f"IPA 文件不存在: {ipa_path}"}

    kid = api_key_id or get_appstore_api_key_id()
    issuer = api_issuer_id or get_appstore_api_issuer_id()

    if not kid or not issuer:
        return {
            "success": False,
            "message": "App Store Connect API 凭证未配置。",
        }

    if method == "altool":
        return _upload_via_altool(str(ipa), kid, issuer)
    elif method == "transporter":
        return _upload_via_transporter(str(ipa), kid, issuer)
    else:
        return {"success": False, "message": f"不支持的上传方式: {method}"}


def _upload_via_altool(ipa_path: str, api_key_id: str, api_issuer_id: str) -> dict:
    """
    使用 xcrun altool 上传 IPA（与 Xcode 使用相同链路，Apple 侧会出现 PROCESSING 记录）。
    p8 key 需位于 ~/.appstoreconnect/private_keys/AuthKey_<KEY_ID>.p8。
    """
    cmd = [
        "xcrun", "altool",
        "--upload-app",
        "-f", ipa_path,
        "-t", "ios",
        "--apiKey", api_key_id,
        "--apiIssuer", api_issuer_id,
    ]

    print(f"  altool 上传中: {ipa_path}（超时 30 分钟）...", flush=True)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode == 0:
            return {
                "success": True,
                "message": "IPA 上传成功 (altool)，请用 appstore builds 确认 Apple 侧是否出现 PROCESSING 记录",
                "stdout": result.stdout,
            }
        else:
            stderr = (result.stderr or "")[-2000:]
            stdout = (result.stdout or "")[-1000:]
            return {
                "success": False,
                "message": f"altool 上传失败 (exit {result.returncode}): {stderr}",
                "stderr": stderr,
                "stdout": stdout,
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "altool 上传超时（30 分钟）"}
    except FileNotFoundError:
        return {
            "success": False,
            "message": "xcrun altool 未找到。请确保在 macOS 上运行且已安装 Xcode CLI Tools。",
        }


def _upload_via_transporter(ipa_path: str, api_key_id: str, api_issuer_id: str) -> dict:
    """
    使用 Transporter CLI 上传 IPA。
    ⚠️ 已知问题：Transporter 返回成功但 Apple 侧不出现 PROCESSING 记录，
    上传实际未生效。建议优先使用 altool。
    """
    print("  ⚠️ Transporter 已知存在"假成功"问题，建议改用 altool（--method altool）", flush=True)
    cmd = [
        "xcrun", "iTMSTransporter",
        "-m", "upload",
        "-f", ipa_path,
        "-apiKey", api_key_id,
        "-apiIssuer", api_issuer_id,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode == 0:
            return {
                "success": True,
                "message": "Transporter 返回成功，但请务必用 appstore builds 验证 Apple 侧是否真正出现 PROCESSING 记录（此路径存在假成功问题）",
                "stdout": result.stdout,
            }
        else:
            return {
                "success": False,
                "message": f"Transporter 上传失败 (exit {result.returncode})",
                "stderr": (result.stderr or "")[-2000:],
            }
    except FileNotFoundError:
        return {
            "success": False,
            "message": "iTMSTransporter 未找到。请安装 Transporter。",
        }


# ── App Store Connect API 操作 ──────────────────────────────────

def get_app_id(bundle_id: Optional[str] = None) -> dict:
    """通过 bundle ID 获取 App Store 中的 app ID。"""
    bid = bundle_id or get_ios_bundle_id()
    if not bid:
        return {"success": False, "message": "未配置 bundle_id。"}

    try:
        headers = _asc_headers()
        resp = requests.get(
            f"{ASC_API_BASE}/apps",
            headers=headers,
            params={"filter[bundleId]": bid},
            timeout=30,
        )
        if not resp.ok:
            return {"success": False, "message": f"API 错误 {resp.status_code}: {resp.text[:500]}"}

        data = resp.json()
        apps = data.get("data", [])
        if not apps:
            return {"success": False, "message": f"未找到 bundle ID 为 {bid} 的 app。"}

        app = apps[0]
        return {
            "success": True,
            "app_id": app["id"],
            "name": app["attributes"]["name"],
            "bundle_id": app["attributes"]["bundleId"],
        }
    except Exception as e:
        return {"success": False, "message": f"查询失败: {e}"}


def create_version(
    version_string: str,
    platform: str = "IOS",
    release_type: str = "MANUAL",
    bundle_id: Optional[str] = None,
) -> dict:
    """
    创建新版本。

    Args:
        version_string: 版本号，如 "1.2.3"
        platform: 'IOS' 或 'MAC_OS'
        release_type: 'MANUAL' 或 'AFTER_APPROVAL'
        bundle_id: bundle ID

    Returns:
        dict with 'success', 'version_id'
    """
    app_result = get_app_id(bundle_id)
    if not app_result.get("success"):
        return app_result

    app_id = app_result["app_id"]

    try:
        headers = _asc_headers()
        body = {
            "data": {
                "type": "appStoreVersions",
                "attributes": {
                    "versionString": version_string,
                    "platform": platform,
                    "releaseType": release_type,
                },
                "relationships": {
                    "app": {
                        "data": {
                            "type": "apps",
                            "id": app_id,
                        }
                    }
                },
            }
        }

        resp = requests.post(
            f"{ASC_API_BASE}/appStoreVersions",
            headers=headers,
            json=body,
            timeout=30,
        )

        if not resp.ok:
            return {"success": False, "message": f"API 错误 {resp.status_code}: {resp.text[:500]}"}

        data = resp.json()
        return {
            "success": True,
            "message": f"版本 {version_string} 已创建",
            "version_id": data["data"]["id"],
            "state": data["data"]["attributes"]["appStoreState"],
        }
    except Exception as e:
        return {"success": False, "message": f"创建版本失败: {e}"}


def update_release_notes(
    version_id: str,
    release_notes: str,
    locale: str = "en-US",
) -> dict:
    """更新指定版本的 release notes。"""
    try:
        headers = _asc_headers()

        # 先获取已有的 localization
        resp = requests.get(
            f"{ASC_API_BASE}/appStoreVersions/{version_id}/appStoreVersionLocalizations",
            headers=headers,
            timeout=30,
        )
        if not resp.ok:
            return {"success": False, "message": f"获取 localization 失败: {resp.status_code}"}

        localizations = resp.json().get("data", [])
        target_loc = None
        for loc in localizations:
            if loc["attributes"]["locale"] == locale:
                target_loc = loc
                break

        if target_loc:
            # 更新已有的
            loc_id = target_loc["id"]
            resp = requests.patch(
                f"{ASC_API_BASE}/appStoreVersionLocalizations/{loc_id}",
                headers=headers,
                json={
                    "data": {
                        "type": "appStoreVersionLocalizations",
                        "id": loc_id,
                        "attributes": {
                            "whatsNew": release_notes,
                        },
                    }
                },
                timeout=30,
            )
        else:
            # 创建新的
            resp = requests.post(
                f"{ASC_API_BASE}/appStoreVersionLocalizations",
                headers=headers,
                json={
                    "data": {
                        "type": "appStoreVersionLocalizations",
                        "attributes": {
                            "locale": locale,
                            "whatsNew": release_notes,
                        },
                        "relationships": {
                            "appStoreVersion": {
                                "data": {
                                    "type": "appStoreVersions",
                                    "id": version_id,
                                }
                            }
                        },
                    }
                },
                timeout=30,
            )

        if not resp.ok:
            return {"success": False, "message": f"更新 release notes 失败: {resp.status_code}: {resp.text[:300]}"}

        return {"success": True, "message": f"Release notes 已更新 ({locale})"}

    except Exception as e:
        return {"success": False, "message": f"更新失败: {e}"}


def submit_for_review(
    version_id: str,
) -> dict:
    """提交版本送审。"""
    try:
        headers = _asc_headers()
        body = {
            "data": {
                "type": "appStoreVersionSubmissions",
                "relationships": {
                    "appStoreVersion": {
                        "data": {
                            "type": "appStoreVersions",
                            "id": version_id,
                        }
                    }
                },
            }
        }

        resp = requests.post(
            f"{ASC_API_BASE}/appStoreVersionSubmissions",
            headers=headers,
            json=body,
            timeout=30,
        )

        if not resp.ok:
            return {"success": False, "message": f"提审失败: {resp.status_code}: {resp.text[:500]}"}

        return {
            "success": True,
            "message": "版本已提交审核",
            "version_id": version_id,
        }
    except Exception as e:
        return {"success": False, "message": f"提审失败: {e}"}


def get_app_status(
    bundle_id: Optional[str] = None,
) -> dict:
    """查询应用当前状态。"""
    app_result = get_app_id(bundle_id)
    if not app_result.get("success"):
        return app_result

    app_id = app_result["app_id"]

    try:
        headers = _asc_headers()
        resp = requests.get(
            f"{ASC_API_BASE}/apps/{app_id}/appStoreVersions",
            headers=headers,
            params={"limit": 5},
            timeout=30,
        )

        if not resp.ok:
            return {"success": False, "message": f"查询失败: {resp.status_code}"}

        versions = []
        for v in resp.json().get("data", []):
            attrs = v.get("attributes", {})
            versions.append({
                "version_id": v["id"],
                "version_string": attrs.get("versionString"),
                "state": attrs.get("appStoreState"),
                "platform": attrs.get("platform"),
                "created_date": attrs.get("createdDate"),
            })

        return {
            "success": True,
            "app_name": app_result.get("name"),
            "versions": versions,
        }
    except Exception as e:
        return {"success": False, "message": f"查询失败: {e}"}


def list_builds(
    bundle_id: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """
    列出 App 的构建（builds）及 processing 状态。
    用于确认「刚上传的 IPA 是否已出现在 App Store Connect、当前是 PROCESSING 还是 VALID」。

    Returns:
        success, message, builds: [{ build_id, version, processing_state, uploaded_date }]
    """
    app_result = get_app_id(bundle_id)
    if not app_result.get("success"):
        return app_result

    app_id = app_result["app_id"]

    try:
        headers = _asc_headers()
        resp = requests.get(
            f"{ASC_API_BASE}/builds",
            headers=headers,
            params={
                "filter[app]": app_id,
                "limit": min(limit, 50),
                "sort": "-uploadedDate",
            },
            timeout=30,
        )

        if not resp.ok:
            return {"success": False, "message": f"API 错误: {resp.status_code} - {resp.text[:300]}"}

        data = resp.json()
        builds = []
        for b in data.get("data", []):
            attrs = b.get("attributes", {})
            builds.append({
                "build_id": b["id"],
                "version": attrs.get("version"),
                "processing_state": attrs.get("processingState", "UNKNOWN"),
                "uploaded_date": attrs.get("uploadedDate"),
                "expiration_date": attrs.get("expirationDate"),
            })

        return {
            "success": True,
            "app_name": app_result.get("name"),
            "builds": builds,
        }
    except Exception as e:
        return {"success": False, "message": f"查询失败: {e}"}

