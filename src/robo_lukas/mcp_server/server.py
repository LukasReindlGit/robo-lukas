from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

_DEFAULT_TIMEOUT_S = 240

mcp = FastMCP(
    name="robo-lukas",
    instructions=(
        "Read-only access to local git/Jira/Outlook/Microsoft To Do workflows. "
        "This server wraps the existing robo-* CLIs and returns parsed JSON."
    ),
)


def _tool_timeout_s() -> int:
    raw = (os.environ.get("ROBO_MCP_TOOL_TIMEOUT_S") or "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT_S
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT_S
    return max(30, value)


def _run_robo_cli(module: str, args: list[str], *, timeout_s: int | None = None) -> Any:
    """
    Run one robo_lukas module command and parse JSON from stdout.

    Parameters:
    - module: Python module path, e.g. ``robo_lukas.git_local``.
    - args: CLI args passed to ``python -m <module>``.
    """
    cmd = [sys.executable, "-m", module, *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s or _tool_timeout_s(),
    )
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"{module} failed: {detail}")

    if not stdout:
        return {"ok": True}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        # Keep raw output for text-only commands.
        return {"raw_output": stdout, "stderr": stderr}


@mcp.tool(
    name="git_status",
    description="Read-only git status for a local repository.",
)
def git_status(repo_path: str | None = None) -> dict[str, Any]:
    args = ["status", "--format", "json"]
    if repo_path:
        args.extend(["--repo", repo_path])
    data = _run_robo_cli("robo_lukas.git_local", args)
    return {"ok": True, "data": data}


@mcp.tool(
    name="git_log",
    description="Read-only branch log compared to a base ref.",
)
def git_log(
    repo_path: str | None = None,
    base_ref: str | None = None,
    limit: int = 15,
) -> dict[str, Any]:
    args = ["log", "--format", "json", "--limit", str(max(1, limit))]
    if repo_path:
        args.extend(["--repo", repo_path])
    if base_ref:
        args.extend(["--base", base_ref])
    data = _run_robo_cli("robo_lukas.git_local", args)
    return {"ok": True, "data": data}


@mcp.tool(
    name="git_diff",
    description="Read-only git diff summary against a base ref.",
)
def git_diff(
    repo_path: str | None = None,
    base_ref: str = "main",
    stat_only: bool = False,
) -> dict[str, Any]:
    args = ["diff", "--format", "json", "--base", base_ref]
    if repo_path:
        args.extend(["--repo", repo_path])
    if stat_only:
        args.append("--stat-only")
    data = _run_robo_cli("robo_lukas.git_local", args)
    return {"ok": True, "data": data}


@mcp.tool(
    name="git_summary",
    description="Read-only combined git status/log/diff summary.",
)
def git_summary(
    repo_path: str | None = None,
    base_ref: str = "main",
    limit: int = 15,
    no_diff: bool = False,
) -> dict[str, Any]:
    args = [
        "summary",
        "--format",
        "json",
        "--base",
        base_ref,
        "--limit",
        str(max(1, limit)),
    ]
    if repo_path:
        args.extend(["--repo", repo_path])
    if no_diff:
        args.append("--no-diff")
    data = _run_robo_cli("robo_lukas.git_local", args)
    return {"ok": True, "data": data}


@mcp.tool(
    name="jira_status",
    description="Check Jira browser-session connection status (read-only).",
)
def jira_status(
    jira_url: str | None = None,
    browser_profile: str | None = None,
    login_timeout: float = 600.0,
) -> dict[str, Any]:
    args = ["status", "--format", "json", "--login-timeout", str(login_timeout)]
    if jira_url:
        args.extend(["--jira-url", jira_url])
    if browser_profile:
        args.extend(["--browser-profile", browser_profile])
    data = _run_robo_cli("robo_lukas.jira", args)
    return {"ok": True, "data": data}


@mcp.tool(
    name="jira_list_mine",
    description="List Jira issues assigned to the current user.",
)
def jira_list_mine(
    jira_url: str | None = None,
    browser_profile: str | None = None,
    limit: int = 25,
    include_done: bool = False,
    extra_jql: str = "",
) -> dict[str, Any]:
    args = ["list-mine", "--format", "json", "--limit", str(max(1, limit))]
    if jira_url:
        args.extend(["--jira-url", jira_url])
    if browser_profile:
        args.extend(["--browser-profile", browser_profile])
    if include_done:
        args.append("--include-done")
    if extra_jql.strip():
        args.extend(["--jql", extra_jql.strip()])
    data = _run_robo_cli("robo_lukas.jira", args)
    return {"ok": True, "data": data}


@mcp.tool(
    name="jira_show_issue",
    description="Show one Jira issue with fields and comments.",
)
def jira_show_issue(
    issue_key: str,
    jira_url: str | None = None,
    browser_profile: str | None = None,
    include_comments: bool = True,
) -> dict[str, Any]:
    args = ["show", issue_key, "--format", "json"]
    if jira_url:
        args.extend(["--jira-url", jira_url])
    if browser_profile:
        args.extend(["--browser-profile", browser_profile])
    if not include_comments:
        args.append("--no-comments")
    data = _run_robo_cli("robo_lukas.jira", args)
    return {"ok": True, "data": data}


@mcp.tool(
    name="todo_lists",
    description="List Microsoft To Do sidebar lists (read-only).",
)
def todo_lists(
    browser_profile: str | None = None,
    login_timeout: float = 600.0,
    max_items: int = 120,
) -> dict[str, Any]:
    args = [
        "lists",
        "--format",
        "json",
        "--login-timeout",
        str(login_timeout),
        "--max-items",
        str(max(1, max_items)),
    ]
    if browser_profile:
        args.extend(["--browser-profile", browser_profile])
    data = _run_robo_cli("robo_lukas.ms_todo", args)
    return {"ok": True, "data": data}


@mcp.tool(
    name="todo_list_tasks",
    description="List tasks from one Microsoft To Do list.",
)
def todo_list_tasks(
    list_name: str,
    browser_profile: str | None = None,
    login_timeout: float = 600.0,
    limit: int = 50,
    scroll_rounds: int = 4,
) -> dict[str, Any]:
    args = [
        "list",
        "--format",
        "json",
        "--list",
        list_name,
        "--login-timeout",
        str(login_timeout),
        "--limit",
        str(max(1, limit)),
        "--scroll-rounds",
        str(max(0, scroll_rounds)),
    ]
    if browser_profile:
        args.extend(["--browser-profile", browser_profile])
    data = _run_robo_cli("robo_lukas.ms_todo", args)
    return {"ok": True, "data": data}


@mcp.tool(
    name="todo_all_tasks",
    description="Scrape Tasks list or all To Do lists.",
)
def todo_all_tasks(
    browser_profile: str | None = None,
    login_timeout: float = 600.0,
    all_lists: bool = False,
    tasks_sidebar_name: str = "Tasks",
    limit: int = 200,
    max_items: int = 120,
    scroll_rounds: int = 4,
) -> dict[str, Any]:
    args = [
        "all-tasks",
        "--format",
        "json",
        "--login-timeout",
        str(login_timeout),
        "--list",
        tasks_sidebar_name,
        "--limit",
        str(max(1, limit)),
        "--max-items",
        str(max(1, max_items)),
        "--scroll-rounds",
        str(max(0, scroll_rounds)),
    ]
    if browser_profile:
        args.extend(["--browser-profile", browser_profile])
    if all_lists:
        args.append("--all-lists")
    data = _run_robo_cli("robo_lukas.ms_todo", args)
    return {"ok": True, "data": data}


@mcp.tool(
    name="outlook_list_messages",
    description="List Outlook messages from inbox/jira folder (read-only).",
)
def outlook_list_messages(
    folder: str = "inbox",
    browser_profile: str | None = None,
    login_timeout: float = 600.0,
    limit: int = 30,
    scroll_rounds: int = 4,
    filter_unread: bool = False,
    subject_contains: str | None = None,
) -> dict[str, Any]:
    args = [
        "list",
        "--format",
        "json",
        "--folder",
        folder,
        "--login-timeout",
        str(login_timeout),
        "--limit",
        str(max(1, limit)),
        "--scroll-rounds",
        str(max(0, scroll_rounds)),
    ]
    if browser_profile:
        args.extend(["--browser-profile", browser_profile])
    if filter_unread:
        args.append("--filter-unread")
    if subject_contains and subject_contains.strip():
        args.extend(["--subject-contains", subject_contains.strip()])
    data = _run_robo_cli("robo_lukas.outlook", args)
    return {"ok": True, "data": data}


def main() -> None:
    load_dotenv()
    mcp.run()

