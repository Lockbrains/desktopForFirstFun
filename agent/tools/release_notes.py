"""
Release Notes 生成模块。
使用 Gemini AI 从 git log 生成 release notes。
Prompt 与 GitHub Desktop release-dropdown.tsx 保持一致。
"""

import json
import os
from pathlib import Path

import requests

from .config import get_gemini_api_key, get_gemini_model, get_app_name
from .git_ops import git_log_detailed


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# ── Prompt 模板（与 release-dropdown.tsx 完全一致）──────────────────────

RELEASE_NOTES_PROMPT = '''You are a release note generator for a game project called "{app_name}" (a mobile aerial combat game). Based on the following git commit logs from the main branch, generate TWO sections of release notes following our project's changelog instructions.

## Commit Logs (last {commit_count} commits, --first-parent only):
{commit_messages}

---

## Instructions:

### SECTION 1: Technical Changelog
Generate a technical changelog using these categories:
- **Added** - New features, systems, components, or capabilities
- **Changed** - Modifications to existing functionality
- **Fixed** - Bug fixes and issue resolutions
- **Performance** - Optimizations and performance improvements
- **Assets** - Art, UI, sprites, models, animations
- **Technical** - Backend changes, refactoring, architecture
- **Removed** - Deleted features or deprecated code

Format each entry as: - [Component/System] Description of change
Include ALL code changes comprehensively. Include specific class/component names, technical details, and PR numbers if visible in commit messages.

### SECTION 2: Public Release Notes (User-Facing)
Transform technical changes into user-facing benefits using these categories:
- **New Features** - Exciting new content
- **Improvements** - Better experience
- **Bug Fixes** - Stability improvements
- **Balance Changes** - Gameplay adjustments

Translation rules (System → Feature mapping):
- Combat Systems → "Aerial combat mechanics"
- Movement Systems → "Flight controls"
- UI Systems → "Interface improvements"
- Inventory/Item Systems → "Aircraft and pilot collection"
- AI Systems → "Enemy squadron behavior"
- Network Systems → "Online features"
- Audio Systems → "Sound and music"
- Visual Systems → "Graphics and effects"
- Weapon Systems → "Aircraft armaments"
- Buff Systems → "Upgrade stacking"
- Power-up Systems → "In-flight bonuses"
- Wingman Systems → "Squadron support"
- Hangar Systems → "Aircraft collection"
- Gacha Systems → "Pilot and plane unlocks"

Common fixes translation:
- Null reference exceptions → "Stability improvements"
- Memory leaks → "Performance optimization"
- Shader issues → "Visual improvements"
- Input handling → "Control responsiveness"
- Save/load bugs → "Progress saving fixes"
- Collision detection → "Gameplay fixes"

EXCLUDE from public notes:
- Technical implementation details, class/component/system names
- PR numbers or commit hashes
- Internal tool changes (Excel Merge Tool, Level Visualizer, Editor scripts, build tools)
- Developer tools and workflows
- Documentation files
- Features not in playable content or disabled features

Public tone should be exciting, positive, and use simple non-technical language.

### SECTION 3: Google Play Release Notes (≤500 characters)
Based on SECTION 2, write a very concise version suitable for Google Play (max 500 characters).
Focus on the most impactful changes only.

### OUTPUT FORMAT:
Output the three sections clearly separated with headers:

## Technical Changelog

[entries here]

## Public Release Notes

[entries here]

## Google Play Release Notes

[concise version here, max 500 characters]
'''


def generate_release_notes(
    version: str,
    repo_path: str = ".",
    branch: str = "main",
    commits: int = 30,
    output_dir: str = "./release_notes",
) -> dict:
    """
    使用 Gemini AI 生成 release notes。

    Returns:
        dict with 'success', 'message', 'files' keys
    """
    api_key = get_gemini_api_key()
    if not api_key:
        return {
            "success": False,
            "message": "Gemini API Key 未配置。请在 config.yaml 或环境变量 GEMINI_API_KEY 中设置。",
        }

    # 获取 commit 历史
    commit_messages = git_log_detailed(repo_path=repo_path, count=commits, branch=branch)
    if not commit_messages or commit_messages == "No commits found":
        return {"success": False, "message": "未找到 commit 记录。"}

    app_name = get_app_name()
    model = get_gemini_model()

    prompt = RELEASE_NOTES_PROMPT.format(
        app_name=app_name,
        commit_count=commits,
        commit_messages=commit_messages,
    )

    # 调用 Gemini API
    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 1.0,
            "topP": 0.95,
            "maxOutputTokens": 8192,
        },
    }

    try:
        resp = requests.post(url, json=body, timeout=120)
    except requests.RequestException as e:
        return {"success": False, "message": f"网络错误: {e}"}

    if not resp.ok:
        return {"success": False, "message": f"API 返回 {resp.status_code}: {resp.text[:500]}"}

    data = resp.json()
    full_text = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )

    if not full_text:
        return {"success": False, "message": "Gemini 未生成内容。"}

    # 解析三个部分
    technical = _extract_section(full_text, "Technical Changelog")
    public = _extract_section(full_text, "Public Release Notes")
    google_play = _extract_section(full_text, "Google Play Release Notes")

    # 确保 Google Play 版本 ≤ 500 字符
    if google_play and len(google_play) > 500:
        google_play = google_play[:497] + "..."

    # 写入文件
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    files = {}

    if technical:
        p = out / f"{version}_technical.md"
        p.write_text(f"# Technical Changelog - v{version}\n\n{technical}", encoding="utf-8")
        files["technical"] = str(p)

    if public:
        p = out / f"{version}_public.md"
        p.write_text(f"# Public Release Notes - v{version}\n\n{public}", encoding="utf-8")
        files["public"] = str(p)

    if google_play:
        p = out / f"{version}_google_play.txt"
        p.write_text(google_play, encoding="utf-8")
        files["google_play"] = str(p)
        files["google_play_chars"] = len(google_play)

    # App Store 版本（与 public 相同）
    if public:
        p = out / f"{version}_appstore.txt"
        p.write_text(public, encoding="utf-8")
        files["appstore"] = str(p)

    # 完整原始输出
    p = out / f"{version}_full.md"
    p.write_text(full_text, encoding="utf-8")
    files["full"] = str(p)

    return {
        "success": True,
        "message": "Release notes 已生成",
        "version": version,
        "files": files,
    }


def _extract_section(text: str, header: str) -> str:
    """从 Markdown 文本中提取指定 ## 标题下的内容。"""
    marker = f"## {header}"
    idx = text.find(marker)
    if idx == -1:
        return ""
    start = idx + len(marker)
    # 找下一个 ## 或文末
    next_section = text.find("\n## ", start)
    if next_section == -1:
        content = text[start:]
    else:
        content = text[start:next_section]
    return content.strip()

