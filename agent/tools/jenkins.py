"""
Jenkins 构建触发模块。
从 agent-tools.ts 移植的 Jenkins HTTP 交互逻辑。
"""

import base64
from typing import Optional
from urllib.parse import urlencode

import requests

from .config import (
    get_jenkins_base_url,
    get_jenkins_pipeline,
    get_jenkins_user,
    get_jenkins_token,
)


PIPELINE_MAP = {
    "android-debug": "StarFire-Android-Debug-Pipeline",
    "android-release": "StarFire-Android-Release",
    "ios-debug": "StarFire-iOS-Debug-Pipeline",
    "ios-release": "StarFire-iOS-Release-Pipeline",
}


def _get_auth_headers() -> dict:
    """构建 Jenkins Basic Auth 头。"""
    user = get_jenkins_user()
    token = get_jenkins_token()
    if user and token:
        encoded = base64.b64encode(f"{user}:{token}".encode()).decode()
        return {"Authorization": f"Basic {encoded}"}
    return {}


def _fetch_crumb(base_url: str, auth_headers: dict) -> tuple[dict, Optional[str]]:
    """获取 Jenkins CSRF crumb 和 cookie。"""
    crumb_header: dict = {}
    cookie_str: Optional[str] = None
    try:
        resp = requests.get(
            f"{base_url}/crumbIssuer/api/json",
            headers=auth_headers,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("crumb") and data.get("crumbRequestField"):
                crumb_header[data["crumbRequestField"]] = data["crumb"]
            if resp.cookies:
                cookie_str = "; ".join(f"{k}={v}" for k, v in resp.cookies.items())
    except Exception:
        pass  # Continue without crumb
    return crumb_header, cookie_str


def trigger_build(
    platform: str,
    mode: str,
    branch: str = "main",
    build_type: Optional[str] = None,
    table_env: Optional[str] = None,
    install_type: Optional[str] = None,
) -> dict:
    """
    触发 Jenkins 构建。

    Args:
        platform: 'ios' 或 'android'
        mode: 'debug' 或 'release'
        branch: 构建分支
        build_type: Android='APK'/'HotUpdate', iOS='App'/'HotUpdate'
        table_env: 'dev'/'test'/'production'
        install_type: iOS 专用 'Adhoc'/'Xcode'/'TestFlight'

    Returns:
        dict with 'success', 'message', 'pipeline', 'url' keys
    """
    pipeline_key = f"{platform}-{mode}"
    pipeline_name = get_jenkins_pipeline(pipeline_key)
    if not pipeline_name:
        pipeline_name = PIPELINE_MAP.get(pipeline_key, "")
    if not pipeline_name:
        return {
            "success": False,
            "message": f"无效的 platform/mode 组合: {platform}/{mode}",
        }

    is_ios = platform == "ios"
    is_debug = mode == "debug"

    # 默认值
    final_build_type = build_type or ("App" if is_ios else "APK")
    final_table_env = table_env or ("dev" if is_debug else "test")
    final_install_type = install_type or "Adhoc"

    base_url = get_jenkins_base_url()
    auth_headers = _get_auth_headers()

    # 获取 crumb
    crumb_header, cookie_str = _fetch_crumb(base_url, auth_headers)

    # 构建参数
    params = {
        "BuildType": final_build_type,
        "BRANCH": branch,
        "TABLE_ENV": final_table_env,
        "SIMULATE_ONLINE": "false",
        "PACK_ALL": "false",
        "CLEAR_CACHE": "false",
        "USE_DEBUG_HOT_UPDATE": "true" if is_debug else "false",
    }
    if is_ios:
        params["InstallType"] = final_install_type

    build_url = f"{base_url}/job/{pipeline_name}/buildWithParameters?{urlencode(params)}"

    headers = {**auth_headers, **crumb_header}
    if cookie_str:
        headers["Cookie"] = cookie_str

    try:
        resp = requests.post(build_url, headers=headers, timeout=30)
    except requests.RequestException as e:
        return {"success": False, "message": f"网络错误: {e}"}

    if 200 <= resp.status_code < 300:
        return {
            "success": True,
            "message": "构建已触发",
            "pipeline": pipeline_name,
            "branch": branch,
            "build_type": final_build_type,
            "table_env": final_table_env,
            "install_type": final_install_type if is_ios else None,
            "url": f"{base_url}/job/{pipeline_name}/",
        }
    else:
        return {
            "success": False,
            "message": f"HTTP {resp.status_code}: {resp.text[:500]}",
        }


def get_build_status(platform: str, mode: str, count: int = 3) -> dict:
    """查询最近几次构建状态。"""
    pipeline_key = f"{platform}-{mode}"
    pipeline_name = get_jenkins_pipeline(pipeline_key)
    if not pipeline_name:
        pipeline_name = PIPELINE_MAP.get(pipeline_key, "")
    if not pipeline_name:
        return {"success": False, "message": f"无效的 pipeline: {pipeline_key}"}

    base_url = get_jenkins_base_url()
    auth_headers = _get_auth_headers()

    try:
        resp = requests.get(
            f"{base_url}/job/{pipeline_name}/api/json?tree=builds[number,result,timestamp,duration]{{0,{count}}}",
            headers=auth_headers,
            timeout=10,
        )
        if resp.status_code != 200:
            return {"success": False, "message": f"HTTP {resp.status_code}"}

        data = resp.json()
        builds = []
        for b in data.get("builds", []):
            builds.append({
                "number": b.get("number"),
                "result": b.get("result", "RUNNING"),
                "timestamp": b.get("timestamp"),
                "duration_ms": b.get("duration"),
            })
        return {
            "success": True,
            "pipeline": pipeline_name,
            "builds": builds,
        }
    except requests.RequestException as e:
        return {"success": False, "message": f"网络错误: {e}"}

