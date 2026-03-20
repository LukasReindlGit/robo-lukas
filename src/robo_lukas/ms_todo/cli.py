from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from robo_lukas.ms_todo.investigation import InvestigationReporter
from robo_lukas.ms_todo.models import TodoReaderConfig
from robo_lukas.ms_todo.reader import (
    TodoReader,
    task_list_resolved_for_export,
    url_matches_sidebar_list,
)
from robo_lukas.ms_todo.session import wait_for_todo_session
from robo_lukas.outlook.browser import (
    _discover_chrome_binary,
    _is_windows_chrome_binary,
    _running_in_wsl,
    build_chrome_options,
    create_chrome_driver,
    quit_chrome_driver_best_effort,
    resolve_effective_chrome_binary,
)

# Opens the **Tasks** list on the commercial host; cookies + less redirect than to-do.live.com for many M365 tenants.
_DEFAULT_MS_TODO_ENTRY = "https://to-do.office.com/tasks/inbox"


_WITH_BRIDGE_HELP = """usage:
  python -m robo_lukas.ms_todo with-bridge SUBCOMMAND [args...]
  robo-todo with-bridge SUBCOMMAND [args...]

Starts (or reuses) Windows ChromeDriver from WSL, then runs SUBCOMMAND.

Requires CHROMEDRIVER_WINDOWS_EXE (or reachable CHROMEDRIVER_REMOTE_URL).
See modules/ms-todo/README.md and modules/outlook/README.md (WSL bridge).
"""


def _env_float(name: str, fallback: str) -> float:
    raw = (os.environ.get(name) or "").strip()
    return float(raw or fallback)


def _investigation_from_args(args: argparse.Namespace) -> InvestigationReporter | None:
    raw = getattr(args, "investigate", None)
    if not (raw or "").strip():
        return None
    hb = float(getattr(args, "investigate_interval", 16.0))
    return InvestigationReporter(
        Path(raw.strip()).expanduser().resolve(),
        heartbeat_interval_s=max(2.0, hb),
    )


def _load_config(args: argparse.Namespace) -> TodoReaderConfig:
    base = (args.tasks_url or os.environ.get("MS_TODO_WEB_URL") or "").strip() or _DEFAULT_MS_TODO_ENTRY
    explicit = (
        float(args.explicit_wait)
        if getattr(args, "explicit_wait", None) is not None
        else _env_float("MS_TODO_EXPLICIT_WAIT", os.environ.get("OUTLOOK_EXPLICIT_WAIT") or "8")
    )
    post_nav = _env_float(
        "MS_TODO_POST_NAV_SLEEP", os.environ.get("OUTLOOK_POST_NAV_SLEEP") or "0.22"
    )
    login_poll = _env_float("MS_TODO_LOGIN_POLL", os.environ.get("OUTLOOK_LOGIN_POLL") or "0.45")
    list_row_poll = _env_float(
        "MS_TODO_LIST_ROW_POLL", os.environ.get("OUTLOOK_LIST_ROW_POLL") or "0.05"
    )
    scroll_key = _env_float(
        "MS_TODO_SCROLL_KEY_SLEEP", os.environ.get("OUTLOOK_SCROLL_KEY_SLEEP") or "0.1"
    )
    implicit = _env_float("MS_TODO_IMPLICIT_WAIT", os.environ.get("OUTLOOK_IMPLICIT_WAIT") or "1")
    shell_settle = _env_float("MS_TODO_SHELL_SETTLE", "0.45")
    shell_poll = _env_float("MS_TODO_SHELL_POLL", "0.32")
    shell_burst = _env_float("MS_TODO_SHELL_BURST", "9")
    page_max = _env_float("MS_TODO_PAGE_WAIT_MAX", "4")
    return TodoReaderConfig(
        tasks_base_url=base,
        implicit_wait_s=implicit,
        explicit_wait_s=explicit,
        login_poll_s=login_poll,
        post_nav_sleep_s=post_nav,
        list_row_poll_s=list_row_poll,
        scroll_key_sleep_s=scroll_key,
        shell_settle_sleep_s=shell_settle,
        shell_wait_poll_s=shell_poll,
        shell_burst_wait_s=shell_burst,
        max_page_wait_s=max(0.5, page_max),
    )


def _driver_from_args(args: argparse.Namespace):
    profile = Path(args.browser_profile or os.environ.get("M365_BROWSER_USER_DATA_DIR") or "")
    if not str(profile):
        print(
            "ERROR: Set --browser-profile or M365_BROWSER_USER_DATA_DIR (same as Outlook).",
            file=sys.stderr,
        )
        sys.exit(2)
    effective_bin = resolve_effective_chrome_binary(args.chrome_binary or os.environ.get("CHROME_BINARY"))
    remote_url = (
        getattr(args, "remote_url", None)
        or os.environ.get("CHROMEDRIVER_REMOTE_URL")
        or os.environ.get("SELENIUM_REMOTE_URL")
        or ""
    ).strip()
    if _is_windows_chrome_binary(effective_bin) and _running_in_wsl():
        if not remote_url and not os.environ.get("CHROMEDRIVER_PATH", "").strip():
            print(
                "ERROR: Windows Chrome from WSL needs CHROMEDRIVER_REMOTE_URL or CHROMEDRIVER_PATH.\n"
                "  See modules/outlook/README.md (WSL + Windows Chrome).",
                file=sys.stderr,
            )
            sys.exit(2)
    elif effective_bin is None and _discover_chrome_binary() is None:
        print(
            "robo-todo: No Chrome/Chromium on PATH. Install Chrome or set CHROME_BINARY.",
            file=sys.stderr,
        )
    opts = build_chrome_options(
        user_data_dir=profile,
        profile_directory=args.chrome_profile_directory or os.environ.get("CHROME_PROFILE_DIRECTORY"),
        headless=bool(args.headless),
        binary_location=args.chrome_binary or os.environ.get("CHROME_BINARY"),
    )
    return create_chrome_driver(
        opts,
        profile_dir=profile,
        remote_command_executor=remote_url or None,
    )


def _print_json(obj) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")


def _attach_shared_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--browser-profile", help="Chrome user-data-dir. Env: M365_BROWSER_USER_DATA_DIR")
    sp.add_argument(
        "--chrome-profile-directory",
        help="Profile folder inside user-data-dir. Env: CHROME_PROFILE_DIRECTORY",
    )
    sp.add_argument("--chrome-binary", help="Chrome binary. Env: CHROME_BINARY")
    sp.add_argument(
        "--tasks-url",
        help=(
            "First URL to open (cookies apply per host). Env: MS_TODO_WEB_URL. "
            f"Default: {_DEFAULT_MS_TODO_ENTRY}. "
            "Personal Microsoft accounts: often use https://to-do.live.com/tasks/ instead."
        ),
    )
    sp.add_argument("--headless", action="store_true", help="Headless (often breaks SSO).")
    sp.add_argument("--keep-browser", action="store_true", help="Leave browser open.")
    sp.add_argument("--explicit-wait", type=float, help="Max wait for task rows (see MS_TODO_EXPLICIT_WAIT).")
    sp.add_argument(
        "--remote-url",
        metavar="URL",
        help="ChromeDriver URL (WSL). Env: CHROMEDRIVER_REMOTE_URL",
    )
    sp.add_argument(
        "--investigate",
        nargs="?",
        const=".robo-todo-investigate",
        default=None,
        metavar="DIR",
        help=(
            "Investigation mode: write investigation.log + numbered HTML/PNG/JSON snapshots "
            "under DIR (default: .robo-todo-investigate). Use for debugging stuck flows."
        ),
    )
    sp.add_argument(
        "--investigate-interval",
        type=float,
        default=16.0,
        metavar="SEC",
        help="With --investigate: heartbeat interval during long waits (default 16).",
    )


def cmd_status(args: argparse.Namespace) -> int:
    load_dotenv()
    cfg = _load_config(args)
    inv = _investigation_from_args(args)
    driver = _driver_from_args(args)
    try:
        reader = TodoReader(driver, cfg, investigate=inv)
        reader.navigate_tasks_home()
        snap = reader.status_snapshot()
        if args.format == "json":
            _print_json(snap)
        else:
            print("URL:  ", snap["url"])
            print("Title:", snap["title"])
        return 0
    finally:
        if not args.keep_browser:
            quit_chrome_driver_best_effort(driver)


def cmd_wait_login(args: argparse.Namespace) -> int:
    load_dotenv()
    cfg = _load_config(args)
    inv = _investigation_from_args(args)
    driver = _driver_from_args(args)
    try:
        wait_for_todo_session(
            driver,
            cfg,
            timeout_s=float(args.login_timeout),
            investigate=inv,
        )
        snap = TodoReader(driver, cfg, investigate=inv).status_snapshot()
        print("Signed in; To Do UI reached.", file=sys.stderr)
        if args.format == "json":
            _print_json(snap)
        else:
            print("URL:  ", snap["url"])
        return 0
    finally:
        if not args.keep_browser:
            quit_chrome_driver_best_effort(driver)


def cmd_lists(args: argparse.Namespace) -> int:
    load_dotenv()
    cfg = _load_config(args)
    inv = _investigation_from_args(args)
    driver = _driver_from_args(args)
    try:
        wait_for_todo_session(
            driver,
            cfg,
            timeout_s=float(args.login_timeout),
            investigate=inv,
        )
        reader = TodoReader(driver, cfg, investigate=inv)
        names = reader.list_sidebar_labels(max_items=args.max_items)
        if args.format == "json":
            _print_json([{"name": n} for n in names])
        else:
            for n in names:
                print(n)
        return 0
    finally:
        if not args.keep_browser:
            quit_chrome_driver_best_effort(driver)


def cmd_list(args: argparse.Namespace) -> int:
    load_dotenv()
    cfg = _load_config(args)
    inv = _investigation_from_args(args)
    driver = _driver_from_args(args)
    try:
        wait_for_todo_session(
            driver,
            cfg,
            timeout_s=float(args.login_timeout),
            investigate=inv,
        )
        reader = TodoReader(driver, cfg, investigate=inv)
        ln = args.list_name.strip().lower()
        if not (
            ln == "tasks"
            and url_matches_sidebar_list(args.list_name, driver.current_url or "")
            and task_list_resolved_for_export(driver)
        ):
            reader.open_list_by_name(args.list_name)
        tasks = reader.list_tasks(
            args.list_name,
            limit=args.limit,
            scroll_rounds=args.scroll_rounds,
        )
        if args.format == "json":
            _print_json([t.to_json_dict() for t in tasks])
        else:
            for t in tasks:
                title = (t.title or "").replace("\n", " ")[:100]
                due = (t.due_hint or "").replace("\n", " ")[:40]
                print(f"[{t.index}] {title}  |  {due}")
        return 0
    finally:
        if not args.keep_browser:
            quit_chrome_driver_best_effort(driver)


def cmd_all_tasks(args: argparse.Namespace) -> int:
    """Scrape the **Tasks** list by default, or every sidebar list with ``--all-lists``."""
    load_dotenv()
    cfg = _load_config(args)
    inv = _investigation_from_args(args)
    driver = _driver_from_args(args)
    try:
        wait_for_todo_session(
            driver,
            cfg,
            timeout_s=float(args.login_timeout),
            investigate=inv,
        )
        reader = TodoReader(driver, cfg, investigate=inv)
        if getattr(args, "all_lists", False):
            names = reader.list_sidebar_labels(max_items=args.max_items)
            if not names:
                print(
                    "robo-todo: no sidebar list names detected — try wait-login, or --investigate.",
                    file=sys.stderr,
                )
        else:
            names = [args.tasks_sidebar_name]
        payload: list[dict] = []
        for name in names:
            block: dict = {"list_name": name, "tasks": []}
            try:
                if not (
                    name.strip().lower() == "tasks"
                    and url_matches_sidebar_list(name, driver.current_url or "")
                    and task_list_resolved_for_export(driver)
                ):
                    reader.open_list_by_name(name)
                tasks = reader.list_tasks(
                    name,
                    limit=args.limit,
                    scroll_rounds=args.scroll_rounds,
                )
                block["tasks"] = [t.to_json_dict() for t in tasks]
            except Exception as e:
                block["error"] = str(e)
                print(f"robo-todo: list {name!r}: {e}", file=sys.stderr)
            payload.append(block)
        if args.format == "json":
            _print_json(payload)
        else:
            for block in payload:
                print(f"=== {block['list_name']} ===")
                if block.get("error"):
                    print(f"  (error: {block['error']})")
                for row in block["tasks"]:
                    title = (row.get("title") or "").replace("\n", " ")[:100]
                    due = (row.get("due_hint") or "").replace("\n", " ")[:40]
                    print(f"  [{row.get('index', 0)}] {title}  |  {due}")
        try:
            sys.stdout.flush()
        except OSError:
            pass
        return 0
    finally:
        if not args.keep_browser:
            quit_chrome_driver_best_effort(driver)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="robo-todo",
        description="Read-only Microsoft To Do (web) automation. No create/edit/complete/delete.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    st = sub.add_parser("status", help="Open To Do URL; print URL and title.")
    _attach_shared_args(st)
    st.add_argument("--format", choices=("text", "json"), default="text")
    st.set_defaults(func=cmd_status)

    w = sub.add_parser("wait-login", help="Wait until To Do is reachable (sign in in browser).")
    _attach_shared_args(w)
    w.add_argument("--login-timeout", type=float, default=600.0)
    w.add_argument("--format", choices=("text", "json"), default="text")
    w.set_defaults(func=cmd_wait_login)

    ls = sub.add_parser("lists", help="Best-effort scrape of sidebar list names.")
    _attach_shared_args(ls)
    ls.add_argument("--max-items", type=int, default=120)
    ls.add_argument("--login-timeout", type=float, default=600.0)
    ls.add_argument("--format", choices=("text", "json"), default="text")
    ls.set_defaults(func=cmd_lists)

    li = sub.add_parser("list", help="Open a list by name and print tasks from the task pane.")
    _attach_shared_args(li)
    li.add_argument("--list", "-l", dest="list_name", required=True, metavar="NAME", help="List name (sidebar).")
    li.add_argument("--limit", type=int, default=50)
    li.add_argument("--scroll-rounds", type=int, default=4)
    li.add_argument("--login-timeout", type=float, default=600.0)
    li.add_argument("--format", choices=("text", "json"), default="text")
    li.set_defaults(func=cmd_list)

    at = sub.add_parser(
        "all-tasks",
        help='Scrape the default **Tasks** sidebar list (use --all-lists for My Day, Important, …).',
    )
    _attach_shared_args(at)
    at.add_argument(
        "--list",
        "-l",
        dest="tasks_sidebar_name",
        default="Tasks",
        metavar="NAME",
        help='Sidebar label for the task list (default: "Tasks").',
    )
    at.add_argument(
        "--all-lists",
        action="store_true",
        help="Scrape every detected sidebar list (slower; includes My Day, Important, …).",
    )
    at.add_argument("--max-items", type=int, default=120, help="With --all-lists: max sidebar lists to iterate.")
    at.add_argument("--limit", type=int, default=200, help="Max tasks per list.")
    at.add_argument("--scroll-rounds", type=int, default=4)
    at.add_argument("--login-timeout", type=float, default=600.0)
    at.add_argument("--format", choices=("text", "json"), default="json")
    at.set_defaults(func=cmd_all_tasks)

    return p


def main(argv: list[str] | None = None, *, _skip_bridge: bool = False) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    load_dotenv()
    argv_list = list(sys.argv[1:] if argv is None else argv)
    if not _skip_bridge and argv_list and argv_list[0] == "with-bridge":
        if len(argv_list) == 1 or argv_list[1] in ("-h", "--help"):
            print(_WITH_BRIDGE_HELP, end="")
            return 0
        from robo_lukas.outlook.bridge import managed_windows_chromedriver

        with managed_windows_chromedriver():
            return main(argv_list[1:], _skip_bridge=True)
    parser = _build_parser()
    args = parser.parse_args(argv_list)
    rc = int(args.func(args))
    inv_path = getattr(args, "investigate", None)
    if inv_path:
        print(
            f"robo-todo: investigation artifacts → {Path(str(inv_path)).expanduser().resolve()}",
            file=sys.stderr,
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
