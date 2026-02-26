"""
Git 操作模块。
封装常用 git 命令，通过 subprocess 调用。
"""

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional


def _run_git(args: list[str], repo_path: str = ".", check: bool = True) -> subprocess.CompletedProcess:
    """执行 git 命令并返回结果。"""
    cmd = ["git", "-C", repo_path] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=check,
    )


def git_status(repo_path: str = ".") -> str:
    """获取 git status 输出。"""
    r = _run_git(["status"], repo_path, check=False)
    return r.stdout or r.stderr or "No output"


def git_log(
    repo_path: str = ".",
    count: int = 10,
    branch: Optional[str] = None,
    first_parent: bool = False,
    format_str: Optional[str] = None,
) -> str:
    """获取 git log。"""
    args = ["log"]
    if format_str:
        args.append(f"--format={format_str}")
    else:
        args.append("--oneline")
    if first_parent:
        args.append("--first-parent")
    args.append(f"-{count}")
    if branch:
        args.append(branch)
    r = _run_git(args, repo_path, check=False)
    return r.stdout or "No commits found"


def git_log_detailed(
    repo_path: str = ".",
    count: int = 30,
    branch: str = "main",
) -> str:
    """获取详细的 git log，包含 commit body（与 release-dropdown.tsx 一致）。"""
    args = [
        "log",
        "--first-parent",
        f"-{count}",
        "--format=%h %s%n%b%n---",
        branch,
    ]
    r = _run_git(args, repo_path, check=False)
    return r.stdout or "No commits found"


def get_current_branch(repo_path: str = ".") -> str:
    """获取当前分支名。"""
    r = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path, check=False)
    return r.stdout.strip() or "main"


def create_release_branch(
    repo_path: str = ".",
    name: Optional[str] = None,
    base: str = "main",
    checkout: bool = True,
) -> str:
    """创建 release 分支。默认命名: releaseMMDDYY。"""
    if not name:
        now = datetime.now()
        name = f"release{now.strftime('%m%d%y')}"

    _run_git(["branch", name, base], repo_path)
    if checkout:
        _run_git(["checkout", name], repo_path)
    return name


def git_branch_list(repo_path: str = ".") -> str:
    """列出所有本地分支。"""
    r = _run_git(["branch", "-a"], repo_path, check=False)
    return r.stdout or "No branches found"


def branch_exists(branch_name: str, repo_path: str = ".", remote: bool = True) -> bool:
    """检查分支是否存在（默认检查远端 origin/branch）。"""
    ref = f"origin/{branch_name}" if remote else branch_name
    r = _run_git(["rev-parse", "--verify", ref], repo_path, check=False)
    return r.returncode == 0


def ensure_release_branch(
    branch_name: str,
    base: str = "main",
    repo_path: str = ".",
    push: bool = True,
) -> dict:
    """
    确保 release 分支存在：不存在则从 base 创建并可选 push。
    Returns: {"success": bool, "message": str, "branch": str, "created": bool}
    """
    if branch_exists(branch_name, repo_path, remote=True):
        return {"success": True, "message": f"分支已存在: {branch_name}", "branch": branch_name, "created": False}
    # 本地是否存在
    if branch_exists(branch_name, repo_path, remote=False):
        if push:
            _run_git(["push", "-u", "origin", branch_name], repo_path, check=False)
        return {"success": True, "message": f"本地分支已存在: {branch_name}", "branch": branch_name, "created": False}
    # 先 fetch，再基于 origin/base 创建
    _run_git(["fetch", "origin"], repo_path, check=False)
    base_ref = f"origin/{base}" if not base.startswith("origin/") else base
    _run_git(["branch", branch_name, base_ref], repo_path)
    _run_git(["checkout", branch_name], repo_path)
    if push:
        r = _run_git(["push", "-u", "origin", branch_name], repo_path, check=False)
        if r.returncode != 0:
            return {"success": False, "message": f"推送失败: {r.stderr or r.stdout}", "branch": branch_name, "created": True}
    return {"success": True, "message": f"已创建并检出: {branch_name}", "branch": branch_name, "created": True}


def git_checkout(repo_path: str = ".", branch: str = "main") -> str:
    """切换分支。"""
    r = _run_git(["checkout", branch], repo_path)
    return r.stdout or f"Switched to branch: {branch}"


def git_diff(repo_path: str = ".") -> str:
    """显示当前变更。"""
    r = _run_git(["diff"], repo_path, check=False)
    if not r.stdout:
        r = _run_git(["diff", "--staged"], repo_path, check=False)
    return r.stdout or "No changes detected"


def git_add(repo_path: str = ".", files: Optional[list[str]] = None) -> str:
    """暂存文件。"""
    targets = files or ["."]
    _run_git(["add", "--"] + targets, repo_path)
    return f"Staged: {', '.join(targets)}"


def git_commit(repo_path: str = ".", message: str = "") -> str:
    """创建 commit。"""
    if not message:
        return "Error: commit message is required"
    r = _run_git(["commit", "-m", message], repo_path)
    return r.stdout or "Commit created"


def git_push(repo_path: str = ".") -> str:
    """推送到远端。"""
    r = _run_git(["push"], repo_path, check=False)
    return r.stdout or r.stderr or "Push completed"


def git_pull(repo_path: str = ".") -> str:
    """拉取远端变更。"""
    r = _run_git(["pull"], repo_path, check=False)
    return r.stdout or r.stderr or "Pull completed"

