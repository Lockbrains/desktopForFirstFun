"""
Jenkins 构建触发模块。
从 agent-tools.ts 移植的 Jenkins HTTP 交互逻辑。
"""

import base64
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

from .config import (
    get_jenkins_base_url,
    get_jenkins_pipeline,
    get_jenkins_user,
    get_jenkins_token,
    get_jenkins_build_output_dir,
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
    install_type: Optional[str] = None,
) -> dict:
    """
    触发 Jenkins 构建。表格环境固定为 dev，不可改。

    Args:
        platform: 'ios' 或 'android'
        mode: 'debug' 或 'release'
        branch: 构建分支
        build_type: Android='APK'/'HotUpdate', iOS='App'/'HotUpdate'
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
    raw_build_type = build_type or ("App" if is_ios else "APK")
    # Android Jenkins 只接受 APK/HotUpdate；传 App 会触发 HTTP 500，此处做平台归一化
    if platform == "android" and raw_build_type == "App":
        final_build_type = "APK"
    elif platform == "ios" and raw_build_type == "APK":
        final_build_type = "App"
    else:
        final_build_type = raw_build_type

    # Android 仅允许 APK / HotUpdate，否则 Jenkins 可能 500
    if platform == "android" and final_build_type not in ("APK", "HotUpdate"):
        return {
            "success": False,
            "message": f"Android 仅支持 build_type: APK 或 HotUpdate，当前为: {final_build_type}。"
            "（iOS 使用 App/HotUpdate）",
        }

    # 表格环境固定为 dev，不提供修改入口
    final_table_env = "dev"
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
            "message": "构建已触发（TABLE_ENV=dev）",
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


def get_latest_build_number(platform: str, mode: str) -> Optional[int]:
    """获取最近一次构建的 number，无构建时返回 None。"""
    r = get_build_status(platform=platform, mode=mode, count=1)
    if not r.get("success") or not r.get("builds"):
        return None
    return r["builds"][0].get("number")


def wait_for_build(
    platform: str,
    mode: str,
    after_build_number: Optional[int] = None,
    poll_interval: int = 60,
    timeout_seconds: int = 7200,
) -> dict:
    """
    轮询直到在 after_build_number 之后出现一次新构建并完成。
    Returns: {"success": bool, "message": str, "build_number": int|None, "result": str}
    """
    if after_build_number is None:
        after_build_number = get_latest_build_number(platform, mode) or 0
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        r = get_build_status(platform=platform, mode=mode, count=5)
        if not r.get("success"):
            time.sleep(poll_interval)
            continue
        for b in r.get("builds", []):
            num = b.get("number")
            if num is None or num <= after_build_number:
                continue
            result = b.get("result") or "RUNNING"
            if result in ("SUCCESS", "FAILURE", "UNSTABLE", "ABORTED"):
                return {
                    "success": result == "SUCCESS",
                    "message": f"构建 #{num} 完成: {result}",
                    "build_number": num,
                    "result": result,
                }
        time.sleep(poll_interval)
    return {
        "success": False,
        "message": f"等待构建超时（{timeout_seconds}s）",
        "build_number": None,
        "result": None,
    }


def resolve_android_aab_path(build_number: int) -> Optional[str]:
    """根据 Jenkins 构建号解析 Android Release AAB 路径（约定：build_output_dir/PipelineName/build_number/*.aab）。"""
    pipeline_name = get_jenkins_pipeline("android-release") or PIPELINE_MAP.get("android-release", "")
    if not pipeline_name:
        return None
    base = get_jenkins_build_output_dir()
    dir_path = Path(base) / pipeline_name / str(build_number)
    if not dir_path.exists():
        return None
    aabs = list(dir_path.glob("*.aab"))
    return str(aabs[0].resolve()) if aabs else None

