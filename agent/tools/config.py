"""
配置加载模块。
从 config.yaml 和环境变量读取配置。
"""

import os
import sys
from pathlib import Path
from typing import Any, Optional

import yaml


_config: Optional[dict] = None
_config_path: Optional[Path] = None


def load_config(config_path: str = "./config.yaml") -> dict:
    """加载配置文件，环境变量优先级高于文件。"""
    global _config, _config_path
    p = Path(config_path)
    if not p.exists():
        print(f"⚠️  配置文件不存在: {p.absolute()}", file=sys.stderr)
        print("   运行 'python cli.py config init' 创建配置文件", file=sys.stderr)
        _config = {}
        return _config

    with open(p, "r", encoding="utf-8") as f:
        _config = yaml.safe_load(f) or {}
    _config_path = p
    return _config


def get_config() -> dict:
    """获取已加载的配置。未加载则自动加载默认路径。"""
    if _config is None:
        load_config()
    return _config  # type: ignore


def _deep_get(d: dict, *keys: str, default: Any = None) -> Any:
    """从嵌套字典中安全取值。"""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)  # type: ignore
    return d


# ── 便捷取值函数 ──────────────────────────────────────────────────────

def get_app_name() -> str:
    return _deep_get(get_config(), "app", "name", default="Wingstrike")


# -- Android / Google Play --

def get_android_package_name() -> str:
    return _deep_get(get_config(), "app", "android", "package_name", default="")


def get_google_play_service_account_json() -> str:
    return (
        os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON")
        or _deep_get(get_config(), "app", "android", "service_account_json", default="")
    )


# -- iOS / App Store Connect --

def get_ios_bundle_id() -> str:
    return _deep_get(get_config(), "app", "ios", "bundle_id", default="")


def get_appstore_api_key_path() -> str:
    return (
        os.environ.get("APP_STORE_API_KEY_PATH")
        or _deep_get(get_config(), "app", "ios", "api_key_path", default="")
    )


def get_appstore_api_key_id() -> str:
    return (
        os.environ.get("APP_STORE_API_KEY_ID")
        or _deep_get(get_config(), "app", "ios", "api_key_id", default="")
    )


def get_appstore_api_issuer_id() -> str:
    return (
        os.environ.get("APP_STORE_API_ISSUER_ID")
        or _deep_get(get_config(), "app", "ios", "api_issuer_id", default="")
    )


# -- Jenkins --

def get_jenkins_base_url() -> str:
    return _deep_get(get_config(), "jenkins", "base_url", default="http://192.168.50.249:8080")


def get_jenkins_user() -> str:
    return (
        os.environ.get("JENKINS_USER")
        or _deep_get(get_config(), "jenkins", "user", default="")
    )


def get_jenkins_token() -> str:
    return (
        os.environ.get("JENKINS_TOKEN")
        or _deep_get(get_config(), "jenkins", "token", default="")
    )


def get_jenkins_build_output_dir() -> str:
    return _deep_get(get_config(), "jenkins", "build_output_dir", default="/Users/jenkins/workspace/builds")


def get_jenkins_pipeline(key: str) -> str:
    """获取 pipeline 名称。key 格式: 'android-debug', 'ios-release' 等。"""
    default_pipelines = {
        "android-debug": "StarFire-Android-Debug-Pipeline",
        "android-release": "StarFire-Android-Release",
        "ios-debug": "StarFire-iOS-Debug-Pipeline",
        "ios-release": "StarFire-iOS-Release-Pipeline",
    }
    pipelines = _deep_get(get_config(), "jenkins", "pipelines", default=default_pipelines)
    return pipelines.get(key, default_pipelines.get(key, ""))


# -- Gemini --

def get_gemini_api_key() -> str:
    return (
        os.environ.get("GEMINI_API_KEY")
        or _deep_get(get_config(), "gemini", "api_key", default="")
    )


def get_gemini_model() -> str:
    return _deep_get(get_config(), "gemini", "model", default="gemini-2.0-flash")

