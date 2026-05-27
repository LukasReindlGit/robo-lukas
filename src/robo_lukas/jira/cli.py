"""
Command-line interface for the Jira module.

All operations are read-only.  No issues are created, updated, or deleted.

Quick start:
    robo-jira wait-login --jira-url https://your-org.atlassian.net
    robo-jira list-mine --format json
    robo-jira show PROJ-123 --format json
    robo-jira search "project = ECOM AND status = 'In Progress'" --format json

Environment variables (override with CLI flags):
    JIRA_BASE_URL            — Jira instance URL (e.g. https://your-org.atlassian.net)
    M365_BROWSER_USER_DATA_DIR — shared Chrome profile dir (same as Outlook / To Do)
    JIRA_LOGIN_TIMEOUT       — seconds to wait for login (default 600)
    JIRA_MAX_RESULTS         — default page size (default 25)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Reuse the shared browser infrastructure from the Outlook module.
from robo_lukas.outlook.browser import (
    _discover_chrome_binary,
    _is_windows_chrome_binary,
    _running_in_wsl,
    build_chrome_options,
    create_chrome_driver,
    quit_chrome_driver_best_effort,
    resolve_effective_chrome_binary,
)
from robo_lukas.jira.client import JiraClient
from robo_lukas.jira.models import JiraConfig
from robo_lukas.jira.safety import normalize_jira_base_url
from robo_lukas.jira.session import extract_cookies_for_requests, wait_for_jira_login


# ---------------------------------------------------------------------------
# Config / driver helpers
# ---------------------------------------------------------------------------


def _load_config(args: argparse.Namespace) -> JiraConfig:
    """Build JiraConfig from CLI args and env vars."""
    base_url = (
        getattr(args, "jira_url", None)
        or os.environ.get("JIRA_BASE_URL")
        or ""
    ).strip()
    if not base_url:
        print(
            "ERROR: Provide --jira-url or set JIRA_BASE_URL "
            "(e.g. https://your-org.atlassian.net).",
            file=sys.stderr,
        )
        sys.exit(2)

    user_data_dir = (
        getattr(args, "browser_profile", None)
        or os.environ.get("M365_BROWSER_USER_DATA_DIR")
        or ""
    ).strip()
    if not user_data_dir:
        print(
            "ERROR: Provide --browser-profile or set M365_BROWSER_USER_DATA_DIR "
            "to a Chrome user-data directory.",
            file=sys.stderr,
        )
        sys.exit(2)

    return JiraConfig(
        base_url=normalize_jira_base_url(base_url),
        browser_user_data_dir=user_data_dir,
        login_timeout_s=float(
            getattr(args, "login_timeout", None)
            or os.environ.get("JIRA_LOGIN_TIMEOUT", "600")
        ),
        post_nav_sleep_s=float(os.environ.get("JIRA_POST_NAV_SLEEP", "0.55")),
        login_poll_s=float(os.environ.get("JIRA_LOGIN_POLL", "0.75")),
        max_results=int(os.environ.get("JIRA_MAX_RESULTS", "25")),
    )


def _driver_from_args(args: argparse.Namespace, cfg: JiraConfig):
    """Create a Selenium Chrome driver using the same profile as Outlook / To Do."""
    profile = Path(cfg.browser_user_data_dir)
    effective_bin = resolve_effective_chrome_binary(
        getattr(args, "chrome_binary", None) or os.environ.get("CHROME_BINARY")
    )
    remote_url = (
        getattr(args, "remote_url", None)
        or os.environ.get("CHROMEDRIVER_REMOTE_URL")
        or os.environ.get("SELENIUM_REMOTE_URL")
        or ""
    ).strip()

    if _is_windows_chrome_binary(effective_bin) and _running_in_wsl():
        if not remote_url and not os.environ.get("CHROMEDRIVER_PATH", "").strip():
            print(
                "ERROR: Windows Chrome from WSL needs one of:\n"
                "  • CHROMEDRIVER_REMOTE_URL=http://<windows-host>:<port>\n"
                "  • CHROMEDRIVER_PATH=/mnt/c/.../chromedriver.exe",
                file=sys.stderr,
            )
            sys.exit(2)
    elif effective_bin is None and _discover_chrome_binary() is None:
        print("robo-jira: No Chrome/Chromium found in PATH.", file=sys.stderr)

    opts = build_chrome_options(
        user_data_dir=profile,
        profile_directory=(
            getattr(args, "chrome_profile_directory", None)
            or os.environ.get("CHROME_PROFILE_DIRECTORY")
        ),
        headless=bool(getattr(args, "headless", False)),
        binary_location=(
            getattr(args, "chrome_binary", None)
            or os.environ.get("CHROME_BINARY")
        ),
    )
    return create_chrome_driver(opts, profile_dir=profile, remote_command_executor=remote_url or None)


def _print_json(obj) -> None:
    """Print obj as indented UTF-8 JSON to stdout."""
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")


def _make_client(args: argparse.Namespace, cfg: JiraConfig, driver) -> JiraClient:
    """Wait for login and return a ready JiraClient."""
    wait_for_jira_login(driver, cfg, timeout_s=cfg.login_timeout_s)
    cookies = extract_cookies_for_requests(driver)
    return JiraClient(cfg.base_url, cookies)


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def cmd_wait_login(args: argparse.Namespace) -> int:
    """Open Jira, wait for login, verify REST API with /myself."""
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args, cfg)
    try:
        client = _make_client(args, cfg, driver)
        try:
            user = client.myself()
            print(
                f"Signed in: {user.display_name} ({user.email or user.account_id})",
                file=sys.stderr,
            )
            if args.format == "json":
                _print_json(
                    {
                        "status": "ok",
                        "user": user.display_name,
                        "email": user.email,
                        "account_id": user.account_id,
                        "base_url": cfg.base_url,
                    }
                )
            else:
                print(f"Jira OK — {cfg.base_url}")
                print(f"User:  {user.display_name} ({user.email or user.account_id})")
        except Exception as exc:
            print(
                f"Browser login OK, but REST API check failed: {exc}",
                file=sys.stderr,
            )
            if args.format == "json":
                _print_json({"status": "browser_ok", "rest_error": str(exc)})
            else:
                print(f"Browser login OK; REST check error: {exc}")
        return 0
    finally:
        if not args.keep_browser:
            quit_chrome_driver_best_effort(driver)


def cmd_status(args: argparse.Namespace) -> int:
    """Check the Jira connection and print the current user."""
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args, cfg)
    try:
        client = _make_client(args, cfg, driver)
        user = client.myself()
        if args.format == "json":
            _print_json(
                {
                    "status": "ok",
                    "user": user.display_name,
                    "email": user.email,
                    "base_url": cfg.base_url,
                }
            )
        else:
            print(f"Connected: {cfg.base_url}")
            print(f"User:      {user.display_name} ({user.email or user.account_id})")
        return 0
    finally:
        if not args.keep_browser:
            quit_chrome_driver_best_effort(driver)


def cmd_list_mine(args: argparse.Namespace) -> int:
    """List open issues assigned to the current user."""
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args, cfg)
    try:
        client = _make_client(args, cfg, driver)
        issues = client.list_my_issues(
            max_results=args.limit or cfg.max_results,
            exclude_done=not args.include_done,
            extra_jql=args.jql or "",
        )
        if args.format == "json":
            _print_json([i.to_json_dict() for i in issues])
        else:
            print(f"Assigned to me ({len(issues)} issues):")
            for issue in issues:
                sprint = f" [{issue.sprint}]" if issue.sprint else ""
                prio = f" ({issue.priority})" if issue.priority else ""
                print(f"  [{issue.key}]{sprint}{prio} [{issue.status}] {issue.summary}")
        return 0
    finally:
        if not args.keep_browser:
            quit_chrome_driver_best_effort(driver)


def cmd_list_sprint(args: argparse.Namespace) -> int:
    """List issues in the current open sprint assigned to the user."""
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args, cfg)
    try:
        client = _make_client(args, cfg, driver)
        try:
            issues = client.list_sprint_issues(
                max_results=args.limit or 50,
                extra_jql=args.jql or "",
            )
        except Exception as exc:
            # Jira returns HTTP 400 for openSprints() when no Agile board exists.
            print(
                f"robo-jira: list-sprint failed: {exc}\n"
                "  Hint: your Jira project may not use sprints, "
                "or you may need a Jira Software licence.",
                file=sys.stderr,
            )
            return 1
        if args.format == "json":
            _print_json([i.to_json_dict() for i in issues])
        else:
            sprint_label = issues[0].sprint if issues else "open sprint"
            print(f"Sprint issues — {sprint_label} ({len(issues)}):")
            for issue in issues:
                prio = f" ({issue.priority})" if issue.priority else ""
                print(f"  [{issue.key}]{prio} [{issue.status}] {issue.summary}")
        return 0
    finally:
        if not args.keep_browser:
            quit_chrome_driver_best_effort(driver)


def cmd_show(args: argparse.Namespace) -> int:
    """Show a single Jira issue with description and comments."""
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args, cfg)
    try:
        client = _make_client(args, cfg, driver)
        issue = client.get_issue(args.issue_key, include_comments=not args.no_comments)
        if args.format == "json":
            _print_json(issue.to_json_dict())
        else:
            print(f"[{issue.key}] {issue.summary}")
            print(f"  Type:     {issue.issue_type}")
            print(f"  Status:   {issue.status}")
            print(f"  Priority: {issue.priority or 'N/A'}")
            print(f"  Assignee: {issue.assignee or 'Unassigned'}")
            print(f"  Reporter: {issue.reporter or 'N/A'}")
            print(f"  Sprint:   {issue.sprint or 'N/A'}")
            print(f"  Labels:   {', '.join(issue.labels) or 'none'}")
            print(f"  Updated:  {issue.updated[:10]}")
            print(f"  URL:      {issue.url}")
            if issue.description_text:
                print()
                print("Description:")
                print(issue.description_text[:3000])
            if issue.comments:
                print()
                print(f"Comments ({len(issue.comments)}):")
                for c in issue.comments:
                    print(f"  [{c.created[:10]}] {c.author}:")
                    for line in c.body_text[:800].splitlines():
                        print(f"    {line}")
        return 0
    finally:
        if not args.keep_browser:
            quit_chrome_driver_best_effort(driver)


def cmd_search(args: argparse.Namespace) -> int:
    """Search issues with a JQL query."""
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args, cfg)
    try:
        jql = args.jql
        client = _make_client(args, cfg, driver)
        issues = client.search(jql, max_results=args.limit or cfg.max_results)
        if args.format == "json":
            _print_json([i.to_json_dict() for i in issues])
        else:
            print(f"JQL: {jql}")
            print(f"Found {len(issues)} issue(s):")
            for issue in issues:
                sprint = f" [{issue.sprint}]" if issue.sprint else ""
                prio = f" ({issue.priority})" if issue.priority else ""
                print(f"  [{issue.key}]{sprint}{prio} [{issue.status}] {issue.summary}")
        return 0
    finally:
        if not args.keep_browser:
            quit_chrome_driver_best_effort(driver)


# ---------------------------------------------------------------------------
# Shared argument attachment
# ---------------------------------------------------------------------------


def _attach_shared_jira_args(sp: argparse.ArgumentParser) -> None:
    """Add browser / URL flags common to every subcommand."""
    sp.add_argument(
        "--jira-url",
        metavar="URL",
        help="Jira base URL (e.g. https://org.atlassian.net). Env: JIRA_BASE_URL",
    )
    sp.add_argument(
        "--browser-profile",
        metavar="DIR",
        help="Chrome user-data-dir for persistent SSO. Env: M365_BROWSER_USER_DATA_DIR",
    )
    sp.add_argument(
        "--chrome-profile-directory",
        metavar="NAME",
        help="Profile folder inside user-data-dir (e.g. Default). Env: CHROME_PROFILE_DIRECTORY",
    )
    sp.add_argument(
        "--chrome-binary",
        metavar="PATH",
        help="Path to Chrome/Chromium binary. Env: CHROME_BINARY",
    )
    sp.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome headless (usually breaks SSO; avoid for login steps).",
    )
    sp.add_argument(
        "--keep-browser",
        action="store_true",
        help="Leave the browser open when the command finishes.",
    )
    sp.add_argument(
        "--remote-url",
        metavar="URL",
        help="ChromeDriver base URL for WSL→Windows bridge. Env: CHROMEDRIVER_REMOTE_URL",
    )
    sp.add_argument(
        "--login-timeout",
        type=float,
        default=600.0,
        metavar="SECS",
        help="Seconds to wait for SSO login to complete (default 600).",
    )


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="robo-jira",
        description=(
            "Read-only Jira access via browser session + REST API. "
            "No API token required; uses the same Chrome profile as robo-outlook."
        ),
        epilog=(
            "Examples:\n"
            "  robo-jira wait-login --jira-url https://org.atlassian.net\n"
            "  robo-jira list-mine --format json\n"
            "  robo-jira show PROJ-123\n"
            "  robo-jira search \"assignee = currentUser() AND project = ECOM\"\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ── wait-login ────────────────────────────────────────────────────────────
    w = sub.add_parser("wait-login", help="Open Jira and wait until SSO login is complete.")
    _attach_shared_jira_args(w)
    w.add_argument("--format", choices=("text", "json"), default="text")
    w.set_defaults(func=cmd_wait_login)

    # ── status ────────────────────────────────────────────────────────────────
    s = sub.add_parser("status", help="Check Jira connection and print current user.")
    _attach_shared_jira_args(s)
    s.add_argument("--format", choices=("text", "json"), default="text")
    s.set_defaults(func=cmd_status)

    # ── list-mine ─────────────────────────────────────────────────────────────
    lm = sub.add_parser(
        "list-mine",
        help="List open issues assigned to the current user.",
    )
    _attach_shared_jira_args(lm)
    lm.add_argument("--limit", type=int, default=25, metavar="N", help="Max issues (default 25).")
    lm.add_argument(
        "--include-done",
        action="store_true",
        help="Include closed/done/resolved issues.",
    )
    lm.add_argument(
        "--jql",
        default="",
        metavar="CLAUSE",
        help="Extra JQL clause appended with AND (e.g. 'project = ECOM').",
    )
    lm.add_argument("--format", choices=("text", "json"), default="text")
    lm.set_defaults(func=cmd_list_mine)

    # ── list-sprint ───────────────────────────────────────────────────────────
    ls = sub.add_parser(
        "list-sprint",
        help="List current sprint issues assigned to the current user.",
    )
    _attach_shared_jira_args(ls)
    ls.add_argument("--limit", type=int, default=50, metavar="N", help="Max issues (default 50).")
    ls.add_argument(
        "--jql",
        default="",
        metavar="CLAUSE",
        help="Extra JQL clause appended with AND.",
    )
    ls.add_argument("--format", choices=("text", "json"), default="text")
    ls.set_defaults(func=cmd_list_sprint)

    # ── show ──────────────────────────────────────────────────────────────────
    sh = sub.add_parser(
        "show",
        help="Show a Jira issue with description and comments.",
    )
    _attach_shared_jira_args(sh)
    sh.add_argument("issue_key", help="Issue key (e.g. PROJ-123 or ECOM-808).")
    sh.add_argument("--no-comments", action="store_true", help="Skip loading comments.")
    sh.add_argument("--format", choices=("text", "json"), default="text")
    sh.set_defaults(func=cmd_show)

    # ── search ────────────────────────────────────────────────────────────────
    se = sub.add_parser(
        "search",
        help="Search issues with a JQL query.",
    )
    _attach_shared_jira_args(se)
    se.add_argument(
        "jql",
        help='JQL query string (e.g. \'project = ECOM AND status = "In Progress"\').',
    )
    se.add_argument("--limit", type=int, default=25, metavar="N", help="Max results (default 25).")
    se.add_argument("--format", choices=("text", "json"), default="text")
    se.set_defaults(func=cmd_search)

    return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
