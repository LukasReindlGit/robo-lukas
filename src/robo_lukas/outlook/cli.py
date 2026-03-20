from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from robo_lukas.outlook.browser import (
    _discover_chrome_binary,
    _is_windows_chrome_binary,
    _running_in_wsl,
    build_chrome_options,
    create_chrome_driver,
    resolve_effective_chrome_binary,
)
from robo_lukas.outlook.models import MailMessage, OutlookReaderConfig
from robo_lukas.outlook.reader import OutlookReader, _parse_list_item_to_message
from robo_lukas.outlook.safety import normalize_robo_mail_folder
from robo_lukas.outlook.session import wait_for_manual_sso

_WITH_BRIDGE_HELP = """usage:
  python -m robo_lukas.outlook with-bridge SUBCOMMAND [args...]
  robo-outlook with-bridge SUBCOMMAND [args...]

Starts (or reuses) Windows ChromeDriver, then runs SUBCOMMAND — one step from WSL.

Examples:
  python -m robo_lukas.outlook with-bridge wait-login --login-timeout 600 --keep-browser
  python -m robo_lukas.outlook with-bridge list --folder inbox --limit 10 --format text

Requires CHROMEDRIVER_WINDOWS_EXE in .env (WSL path to chromedriver.exe) unless a driver
is already reachable (e.g. you left scripts/chromedriver-for-wsl.ps1 running).

See modules/outlook/README.md.
"""


def _load_config(args: argparse.Namespace) -> OutlookReaderConfig:
    base = args.mail_url or os.environ.get("OUTLOOK_WEB_URL") or "https://outlook.office.com/mail/"
    if getattr(args, "explicit_wait", None) is not None:
        explicit = float(args.explicit_wait)
    else:
        explicit = float(os.environ.get("OUTLOOK_EXPLICIT_WAIT", "25"))
    post_nav = float(os.environ.get("OUTLOOK_POST_NAV_SLEEP", "0.55"))
    login_poll = float(os.environ.get("OUTLOOK_LOGIN_POLL", "0.75"))
    list_row_poll = float(os.environ.get("OUTLOOK_LIST_ROW_POLL", "0.12"))
    scroll_key = float(os.environ.get("OUTLOOK_SCROLL_KEY_SLEEP", "0.22"))
    search_extra = float(os.environ.get("OUTLOOK_SEARCH_EXTRA_SLEEP", "0.35"))
    implicit = float(os.environ.get("OUTLOOK_IMPLICIT_WAIT", "1"))
    return OutlookReaderConfig(
        mail_base_url=base,
        implicit_wait_s=implicit,
        explicit_wait_s=explicit,
        login_poll_s=login_poll,
        post_nav_sleep_s=post_nav,
        list_row_poll_s=list_row_poll,
        scroll_key_sleep_s=scroll_key,
        search_extra_sleep_s=search_extra,
    )


def _mail_folder_type(value: str) -> str:
    """Argparse ``type=`` for ``--folder`` (only ``inbox`` and ``jira``)."""
    return normalize_robo_mail_folder(value)


def _driver_from_args(args: argparse.Namespace):
    profile = Path(args.browser_profile or os.environ.get("M365_BROWSER_USER_DATA_DIR") or "")
    if not str(profile):
        print(
            "ERROR: Set --browser-profile or M365_BROWSER_USER_DATA_DIR to a dedicated Chrome user-data directory.",
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
                "ERROR: Windows Chrome from WSL needs one of:\n"
                "  • CHROMEDRIVER_REMOTE_URL=http://<windows-host>:<port> "
                "(start ChromeDriver on Windows — scripts/chromedriver-for-wsl.ps1), or\n"
                "  • CHROMEDRIVER_PATH=/mnt/c/.../chromedriver.exe (often broken; prefer remote URL).\n"
                "  See modules/outlook/README.md — “WSL + Windows Chrome (remote ChromeDriver)”.",
                file=sys.stderr,
            )
            sys.exit(2)
    elif effective_bin is None and _discover_chrome_binary() is None:
        print(
            "robo-outlook: No Chrome/Chromium found.\n"
            "  • Linux in WSL: sudo apt install chromium-browser  OR\n"
            "  • Windows Chrome from WSL: CHROMEDRIVER_REMOTE_URL + scripts/chromedriver-for-wsl.ps1, "
            "or ROBO_OUTLOOK_USE_WINDOWS_CHROME=1 with CHROMEDRIVER_PATH / remote URL",
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


def cmd_status(args: argparse.Namespace) -> int:
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args)
    try:
        reader = OutlookReader(driver, cfg)
        reader.navigate_readonly(cfg.mail_base_url)
        snap = reader.status_snapshot()
        if args.format == "json":
            _print_json(snap)
        else:
            print("URL:  ", snap["url"])
            print("Title:", snap["title"])
        return 0
    finally:
        if not args.keep_browser:
            driver.quit()


def cmd_wait_login(args: argparse.Namespace) -> int:
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args)
    try:
        wait_for_manual_sso(driver, cfg, timeout_s=float(args.login_timeout))
        snap = OutlookReader(driver, cfg).status_snapshot()
        print("Signed in; mail UI reached.", file=sys.stderr)
        if args.format == "json":
            _print_json(snap)
        else:
            print("URL:  ", snap["url"])
        return 0
    finally:
        if not args.keep_browser:
            driver.quit()


def cmd_folders(args: argparse.Namespace) -> int:
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args)
    try:
        wait_for_manual_sso(driver, cfg, timeout_s=float(args.login_timeout))
        reader = OutlookReader(driver, cfg)
        reader.open_folder(args.folder)
        folders = reader.list_nav_folders(max_items=args.max_items)
        data = [{"name": f.name, "url": f.url} for f in folders]
        if args.format == "json":
            _print_json(data)
        else:
            for f in folders:
                print(f.name)
        return 0
    finally:
        if not args.keep_browser:
            driver.quit()


def _filter_messages(msgs: list[MailMessage], subject_contains: str | None) -> list[MailMessage]:
    if not subject_contains:
        return msgs
    s = subject_contains.lower()
    return [m for m in msgs if s in (m.subject or "").lower() or s in (m.list_row_text or "").lower()]


def cmd_list(args: argparse.Namespace) -> int:
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args)
    try:
        wait_for_manual_sso(driver, cfg, timeout_s=float(args.login_timeout))
        reader = OutlookReader(driver, cfg)
        items = reader.list_messages(
            args.folder,
            limit=args.limit,
            scroll_rounds=args.scroll_rounds,
            unread_filter=bool(args.filter_unread),
        )
        msgs = [_parse_list_item_to_message(args.folder, it) for it in items]
        msgs = _filter_messages(msgs, args.subject_contains)
        msgs = [m for m in msgs[: args.limit]]
        if args.format == "json":
            _print_json([m.to_json_dict() for m in msgs])
        else:
            for m in msgs:
                subj = (m.subject or "").replace("\n", " ")[:120]
                sender = (m.from_ or "").replace("\n", " ")[:80]
                print(f"[{m.index_in_list}] {sender} | {subj}")
        return 0
    finally:
        if not args.keep_browser:
            driver.quit()


def cmd_export(args: argparse.Namespace) -> int:
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args)
    try:
        wait_for_manual_sso(driver, cfg, timeout_s=float(args.login_timeout))
        reader = OutlookReader(driver, cfg)
        items = reader.list_messages(
            args.folder,
            limit=args.limit,
            scroll_rounds=args.scroll_rounds,
            unread_filter=bool(args.filter_unread),
        )
        msgs: list[MailMessage] = []
        if args.with_bodies:
            for it in items:
                idx = it.index
                try:
                    m = reader.get_message(
                        args.folder,
                        idx,
                        include_body=True,
                        max_scroll_rounds=args.scroll_rounds,
                        skip_folder_open=True,
                    )
                    msgs.append(m)
                except Exception as exc:  # noqa: BLE001
                    m = _parse_list_item_to_message(args.folder, it)
                    m.body_text = f"(failed to load body: {exc})"
                    msgs.append(m)
                time.sleep(float(args.body_delay))
        else:
            msgs = [_parse_list_item_to_message(args.folder, it) for it in items]
        msgs = _filter_messages(msgs, args.subject_contains)
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [m.to_json_dict() for m in msgs]
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(str(out_path.resolve()))
        return 0
    finally:
        if not args.keep_browser:
            driver.quit()


def cmd_show(args: argparse.Namespace) -> int:
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args)
    try:
        wait_for_manual_sso(driver, cfg, timeout_s=float(args.login_timeout))
        reader = OutlookReader(driver, cfg)
        msg = reader.get_message(
            args.folder,
            args.index,
            include_body=not args.no_body,
            max_scroll_rounds=args.scroll_rounds,
            unread_filter=bool(args.filter_unread),
        )
        if args.format == "json":
            _print_json(msg.to_json_dict())
        else:
            print(f"Subject: {msg.subject}")
            print(f"From:    {msg.from_}")
            print(f"Preview: {msg.preview}")
            if msg.body_text:
                print()
                print(msg.body_text)
        return 0
    finally:
        if not args.keep_browser:
            driver.quit()


def cmd_search(args: argparse.Namespace) -> int:
    load_dotenv()
    cfg = _load_config(args)
    driver = _driver_from_args(args)
    try:
        if not (args.query or "").strip() and not args.filter_unread:
            print("Provide a search query and/or --filter-unread.", file=sys.stderr)
            return 2
        wait_for_manual_sso(driver, cfg, timeout_s=float(args.login_timeout))
        reader = OutlookReader(driver, cfg)
        reader.open_folder(args.folder)
        if args.filter_unread:
            reader.apply_unread_list_filter()
        q = (args.query or "").strip()
        if q:
            reader.search(q)
        items = reader.list_messages(
            args.folder,
            limit=args.limit,
            scroll_rounds=args.scroll_rounds,
            skip_navigation=True,
        )
        msgs = [_parse_list_item_to_message(args.folder, it) for it in items]
        msgs = _filter_messages(msgs, args.subject_contains)
        if getattr(args, "show_index", None) is not None:
            if not msgs:
                print("No messages matched; cannot open --show-index.", file=sys.stderr)
                return 1
            idx = int(args.show_index)
            msg = reader.get_message(
                args.folder,
                idx,
                include_body=not args.no_body,
                max_scroll_rounds=args.scroll_rounds,
                skip_folder_open=True,
            )
            if args.format == "json":
                _print_json(msg.to_json_dict())
            else:
                print(f"Subject: {msg.subject}")
                print(f"From:    {msg.from_}")
                print(f"Preview: {msg.preview}")
                if msg.body_text:
                    print()
                    print(msg.body_text)
            return 0
        if args.format == "json":
            _print_json([m.to_json_dict() for m in msgs])
        else:
            for m in msgs:
                subj = (m.subject or "").replace("\n", " ")[:120]
                sender = (m.from_ or "").replace("\n", " ")[:80]
                print(f"[{m.index_in_list}] {sender} | {subj}")
        return 0
    finally:
        if not args.keep_browser:
            driver.quit()


def _attach_shared_outlook_args(sp: argparse.ArgumentParser) -> None:
    """
    Browser / URL flags on each subparser so they work *after* the subcommand
    (e.g. ``wait-login --keep-browser``). Putting the same options on the root
    parser breaks that pattern and duplicates ``dest`` in a way that resets flags.
    """
    sp.add_argument(
        "--browser-profile",
        help="Chrome user-data-dir (persistent SSO). Env: M365_BROWSER_USER_DATA_DIR",
    )
    sp.add_argument(
        "--chrome-profile-directory",
        help="Chrome profile name inside user-data-dir, e.g. Default. Env: CHROME_PROFILE_DIRECTORY",
    )
    sp.add_argument(
        "--chrome-binary",
        help="Path to Chrome/Chromium binary. Env: CHROME_BINARY",
    )
    sp.add_argument(
        "--mail-url",
        help="Outlook mail base URL. Env: OUTLOOK_WEB_URL (default https://outlook.office.com/mail/)",
    )
    sp.add_argument(
        "--headless",
        action="store_true",
        help="Headless Chrome (often breaks SSO/MFA; default off).",
    )
    sp.add_argument(
        "--keep-browser",
        action="store_true",
        help="Leave the browser open when the command finishes.",
    )
    sp.add_argument(
        "--explicit-wait",
        type=float,
        help="Max seconds to wait for list/reading-pane elements (default OUTLOOK_EXPLICIT_WAIT or 25).",
    )
    sp.add_argument(
        "--remote-url",
        metavar="URL",
        help="ChromeDriver base URL when driver runs on Windows (WSL). Env: CHROMEDRIVER_REMOTE_URL",
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="robo-outlook",
        description="Read-only Outlook on the web automation (Selenium). No send/compose/delete.",
        epilog="One-shot from WSL (starts Windows ChromeDriver if needed): "
        "python -m robo_lukas.outlook with-bridge wait-login …  (see with-bridge --help). "
        "Otherwise shared options go after the subcommand, "
        "e.g. robo-outlook wait-login --login-timeout 600 --keep-browser",
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="Open mail base URL and print current URL/title.")
    _attach_shared_outlook_args(s)
    s.add_argument("--format", choices=("text", "json"), default="text")
    s.set_defaults(func=cmd_status)

    w = sub.add_parser("wait-login", help="Open Outlook and wait until /mail/ is reachable (complete SSO in browser).")
    _attach_shared_outlook_args(w)
    w.add_argument("--login-timeout", type=float, default=600.0, help="Seconds to wait for login (default 600).")
    w.add_argument("--format", choices=("text", "json"), default="text")
    w.set_defaults(func=cmd_wait_login)

    f = sub.add_parser("folders", help="Best-effort list of folder names from the left nav (after opening a folder).")
    _attach_shared_outlook_args(f)
    f.add_argument(
        "--folder",
        default="inbox",
        type=_mail_folder_type,
        metavar="inbox|jira",
        help="Supported folder: inbox or jira.",
    )
    f.add_argument("--max-items", type=int, default=200)
    f.add_argument("--login-timeout", type=float, default=600.0)
    f.add_argument("--format", choices=("text", "json"), default="text")
    f.set_defaults(func=cmd_folders)

    l = sub.add_parser("list", help="List messages in a folder (list pane only; does not open threads).")
    _attach_shared_outlook_args(l)
    l.add_argument(
        "--folder",
        default="inbox",
        type=_mail_folder_type,
        metavar="inbox|jira",
        help="inbox or jira.",
    )
    l.add_argument("--limit", type=int, default=30)
    l.add_argument("--scroll-rounds", type=int, default=4, help="Extra PageDown rounds to virtualize long lists.")
    l.add_argument("--login-timeout", type=float, default=600.0)
    l.add_argument(
        "--filter-unread",
        action="store_true",
        help="Apply OWA list filter: #mailListFilterMenu → Unread.",
    )
    l.add_argument("--subject-contains", help="Case-insensitive filter on subject / row text (client-side).")
    l.add_argument("--format", choices=("text", "json"), default="text")
    l.set_defaults(func=cmd_list)

    e = sub.add_parser("export", help="Export folder messages to JSON for local processing.")
    _attach_shared_outlook_args(e)
    e.add_argument(
        "--folder",
        default="inbox",
        type=_mail_folder_type,
        metavar="inbox|jira",
        help="inbox or jira.",
    )
    e.add_argument("--limit", type=int, default=50)
    e.add_argument("--scroll-rounds", type=int, default=6)
    e.add_argument("--output", "-o", required=True, help="Output .json path")
    e.add_argument(
        "--with-bodies",
        action="store_true",
        help="Open each row to capture body (slow; may mark messages read on server).",
    )
    e.add_argument("--body-delay", type=float, default=0.45, help="Pause between body fetches.")
    e.add_argument("--login-timeout", type=float, default=600.0)
    e.add_argument(
        "--filter-unread",
        action="store_true",
        help="Apply OWA list filter: #mailListFilterMenu → Unread.",
    )
    e.add_argument("--subject-contains", help="Case-insensitive filter (client-side).")
    e.set_defaults(func=cmd_export)

    sh = sub.add_parser("show", help="Open one message by list index and print preview/body.")
    _attach_shared_outlook_args(sh)
    sh.add_argument(
        "--folder",
        default="inbox",
        type=_mail_folder_type,
        metavar="inbox|jira",
        help="inbox or jira.",
    )
    sh.add_argument("--index", type=int, required=True, help="0-based index in the current list order.")
    sh.add_argument(
        "--no-body",
        action="store_true",
        help="Only use list row text (does not open reading pane).",
    )
    sh.add_argument("--scroll-rounds", type=int, default=8)
    sh.add_argument("--login-timeout", type=float, default=600.0)
    sh.add_argument(
        "--filter-unread",
        action="store_true",
        help="Open folder then apply OWA list filter Unread before opening the row.",
    )
    sh.add_argument("--format", choices=("text", "json"), default="text")
    sh.set_defaults(func=cmd_show)

    se = sub.add_parser("search", help="Use Outlook search box, then list result rows (read-only intent).")
    _attach_shared_outlook_args(se)
    se.add_argument(
        "query",
        nargs="?",
        default="",
        help="Search string (optional if --filter-unread). e.g. read:no",
    )
    se.add_argument(
        "--folder",
        default="inbox",
        type=_mail_folder_type,
        metavar="inbox|jira",
        help="Folder to open before search/filter.",
    )
    se.add_argument("--limit", type=int, default=30)
    se.add_argument("--scroll-rounds", type=int, default=4)
    se.add_argument("--login-timeout", type=float, default=600.0)
    se.add_argument("--subject-contains", help="Extra client-side filter after search.")
    se.add_argument(
        "--filter-unread",
        action="store_true",
        help="After opening folder, use #mailListFilterMenu → Unread (then optional query).",
    )
    se.add_argument(
        "--show-index",
        type=int,
        metavar="N",
        help="After search, open list row N (0-based) and print message (may mark read on server).",
    )
    se.add_argument(
        "--no-body",
        action="store_true",
        help="With --show-index: only list row fields (do not open reading pane).",
    )
    se.add_argument("--format", choices=("text", "json"), default="text")
    se.set_defaults(func=cmd_search)

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
        from robo_lukas.outlook.bridge import run_under_windows_chromedriver_bridge

        return run_under_windows_chromedriver_bridge(argv_list[1:])
    parser = _build_parser()
    args = parser.parse_args(argv_list)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
