"""
Command-line interface for the git-local module.

All operations are read-only. No checkout, commit, push, fetch, or pull.

Quick start:
    robo-git status                          # current repo (cwd)
    robo-git log --repo /path/to/repo
    robo-git diff --base main --format json
    robo-git summary --format json           # status + log + diff combined

Multi-repo (for morning briefing):
    robo-git all-summary --format json
    # reads GIT_REPO_PATHS=path1,path2,... from env / .env

Environment variables:
    GIT_REPO_PATH    — default single repo path (can be overridden with --repo)
    GIT_REPO_PATHS   — comma-separated repo paths for all-summary
    GIT_BASE_REF     — default base ref for diff/summary (default: main)
    GIT_LOG_LIMIT    — default commit count for log/summary (default: 15)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from robo_lukas.git_local.reader import GitCommandError, GitReader, repos_from_env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_json(obj) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")


def _resolve_repo(args: argparse.Namespace) -> Path:
    """Return the repo path from --repo flag, env var, or cwd."""
    p = getattr(args, "repo", None) or os.environ.get("GIT_REPO_PATH", "").strip()
    return Path(p) if p else Path.cwd()


def _default_base_ref() -> str:
    return os.environ.get("GIT_BASE_REF", "main").strip() or "main"


def _default_log_limit() -> int:
    try:
        return int(os.environ.get("GIT_LOG_LIMIT", "15"))
    except ValueError:
        return 15


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    repo_path = _resolve_repo(args)
    try:
        reader = GitReader(repo_path)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        status = reader.status()
        status.repo_path = str(reader.repo_path)
    except GitCommandError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(status.to_json_dict())
    else:
        _print_status_text(status)
    return 0


def _print_status_text(status) -> None:
    sync = ""
    if status.ahead and status.behind:
        sync = f" (↑{status.ahead} ↓{status.behind})"
    elif status.ahead:
        sync = f" (↑{status.ahead} ahead)"
    elif status.behind:
        sync = f" (↓{status.behind} behind)"

    upstream = f" → {status.upstream}" if status.upstream else ""
    print(f"Branch: {status.branch}{upstream}{sync}")
    print(f"Repo:   {status.repo_path}")

    if status.is_clean:
        print("Status: clean ✓")
        return

    if status.staged:
        print(f"\nStaged ({len(status.staged)}):")
        for f in status.staged:
            print(f"  {f.status[:3]:3s}  {f.path}")
    if status.unstaged:
        print(f"\nUnstaged ({len(status.unstaged)}):")
        for f in status.unstaged:
            print(f"  {f.status[:3]:3s}  {f.path}")
    if status.untracked:
        print(f"\nUntracked ({len(status.untracked)}):")
        for f in status.untracked[:10]:
            print(f"  ???  {f.path}")
        if len(status.untracked) > 10:
            print(f"  … and {len(status.untracked) - 10} more")


def cmd_log(args: argparse.Namespace) -> int:
    repo_path = _resolve_repo(args)
    try:
        reader = GitReader(repo_path)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    base = args.base or _default_base_ref()
    limit = args.limit or _default_log_limit()

    try:
        # Show commits on this branch that aren't in base_ref (branch-only log)
        base_ref = base if reader._ref_exists(base) else None
        commits = reader.log(limit=limit, base_ref=base_ref)
    except GitCommandError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json([c.to_json_dict() for c in commits])
    else:
        if not commits:
            print(f"No commits on this branch beyond {base}.")
            return 0
        for c in commits:
            print(f"{c.short_sha}  {c.date[:10]}  {c.author}  {c.subject}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    repo_path = _resolve_repo(args)
    try:
        reader = GitReader(repo_path)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    base = args.base or _default_base_ref()
    include_patches = not args.stat_only

    try:
        diff = reader.diff(base_ref=base, include_patches=include_patches)
    except GitCommandError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(diff.to_json_dict())
    else:
        print(f"Diff: {diff.base_ref}...HEAD  ({diff.files_changed} files, +{diff.insertions}/-{diff.deletions})")
        for fp in diff.file_patches:
            old = f"{fp.old_path} → " if fp.old_path else ""
            print(f"\n{'─'*60}")
            print(f"  {old}{fp.path}")
            if fp.patch:
                for line in fp.patch.splitlines()[:40]:
                    print(f"    {line}")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    repo_path = _resolve_repo(args)
    try:
        reader = GitReader(repo_path)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    base = args.base or _default_base_ref()
    limit = args.limit or _default_log_limit()
    no_diff = getattr(args, "no_diff", False)

    try:
        summary = reader.summary(base_ref=base, log_limit=limit, include_diff=not no_diff)
    except GitCommandError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.format == "json":
        _print_json(summary.to_json_dict())
    else:
        print(f"=== {summary.repo_name} ({summary.repo_path}) ===")
        _print_status_text(summary.status)
        if summary.recent_commits:
            print(f"\nRecent commits ({len(summary.recent_commits)}):")
            for c in summary.recent_commits:
                print(f"  {c.short_sha}  {c.date[:10]}  {c.subject}")
        if summary.diff and summary.diff.files_changed > 0:
            d = summary.diff
            print(f"\nDiff vs {d.base_ref}: {d.files_changed} files changed, +{d.insertions}/-{d.deletions}")
            for fp in d.file_patches[:5]:
                print(f"  {fp.path}")
            if len(d.file_patches) > 5:
                print(f"  … and {len(d.file_patches) - 5} more")
    return 0


def cmd_all_summary(args: argparse.Namespace) -> int:
    """Run summary across all repos configured in GIT_REPO_PATHS / GIT_REPO_PATH."""
    paths = repos_from_env()

    # Also accept --repo for a single override
    single = getattr(args, "repo", None)
    if single:
        paths = [Path(single)]

    if not paths:
        print(
            "ERROR: No repos configured. Set GIT_REPO_PATHS (comma-separated) "
            "or GIT_REPO_PATH in .env or environment.",
            file=sys.stderr,
        )
        return 1

    base = args.base or _default_base_ref()
    limit = args.limit or _default_log_limit()
    no_diff = getattr(args, "no_diff", False)

    summaries = []
    errors = []
    for p in paths:
        try:
            reader = GitReader(p)
            s = reader.summary(base_ref=base, log_limit=limit, include_diff=not no_diff)
            summaries.append(s)
        except Exception as exc:
            errors.append({"repo": str(p), "error": str(exc)})

    if args.format == "json":
        out: dict = {"summaries": [s.to_json_dict() for s in summaries]}
        if errors:
            out["errors"] = errors
        _print_json(out)
    else:
        for s in summaries:
            print()
            print(f"=== {s.repo_name} ===")
            _print_status_text(s.status)
            if s.recent_commits:
                print(f"\n  Recent commits ({len(s.recent_commits)}):")
                for c in s.recent_commits[:5]:
                    print(f"    {c.short_sha}  {c.date[:10]}  {c.subject}")
            if s.diff and s.diff.files_changed > 0:
                d = s.diff
                print(f"\n  Diff vs {d.base_ref}: {d.files_changed} files, +{d.insertions}/-{d.deletions}")
        if errors:
            print("\nErrors:")
            for e in errors:
                print(f"  {e['repo']}: {e['error']}")
    return 0


# ---------------------------------------------------------------------------
# Shared args / parser
# ---------------------------------------------------------------------------


def _attach_repo_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument(
        "--repo",
        metavar="PATH",
        help="Path to the git repository root. Env: GIT_REPO_PATH (default: cwd)",
    )
    sp.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="robo-git",
        description=(
            "Read-only git repository introspection. "
            "No commits, no push, no fetch."
        ),
        epilog=(
            "Examples:\n"
            "  robo-git status\n"
            "  robo-git log --base main --limit 10\n"
            "  robo-git diff --base main --format json\n"
            "  robo-git summary --format json\n"
            "  robo-git all-summary --format json   # all repos from GIT_REPO_PATHS\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ── status ───────────────────────────────────────────────────────────────
    s = sub.add_parser("status", help="Show branch, staged, unstaged, and untracked files.")
    _attach_repo_args(s)
    s.set_defaults(func=cmd_status)

    # ── log ──────────────────────────────────────────────────────────────────
    l = sub.add_parser("log", help="Show recent commits (branch-only by default).")
    _attach_repo_args(l)
    l.add_argument(
        "--base",
        metavar="REF",
        help="Base ref to compare against (shows commits on current branch beyond this ref). "
             "Env: GIT_BASE_REF (default: main)",
    )
    l.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Max commits to show. Env: GIT_LOG_LIMIT (default: 15)",
    )
    l.add_argument(
        "--all",
        action="store_true",
        help="Show all commits on HEAD (not just branch-only).",
    )
    l.set_defaults(func=cmd_log)

    # ── diff ─────────────────────────────────────────────────────────────────
    d = sub.add_parser("diff", help="Show diff vs a base ref.")
    _attach_repo_args(d)
    d.add_argument(
        "--base",
        metavar="REF",
        help="Base ref to diff against. Env: GIT_BASE_REF (default: main)",
    )
    d.add_argument(
        "--stat-only",
        action="store_true",
        help="Only show changed file names and counts (no patch text).",
    )
    d.set_defaults(func=cmd_diff)

    # ── summary ──────────────────────────────────────────────────────────────
    su = sub.add_parser(
        "summary",
        help="Combined status + log + diff — ideal for morning briefing or end-of-day.",
    )
    _attach_repo_args(su)
    su.add_argument(
        "--base",
        metavar="REF",
        help="Base ref for log and diff. Env: GIT_BASE_REF (default: main)",
    )
    su.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Max commits in log section. Env: GIT_LOG_LIMIT (default: 15)",
    )
    su.add_argument(
        "--no-diff",
        action="store_true",
        help="Skip the diff section (faster).",
    )
    su.set_defaults(func=cmd_summary)

    # ── all-summary ───────────────────────────────────────────────────────────
    a = sub.add_parser(
        "all-summary",
        help="Run summary across all repos in GIT_REPO_PATHS / GIT_REPO_PATH.",
    )
    _attach_repo_args(a)
    a.add_argument(
        "--base",
        metavar="REF",
        help="Base ref for all repos. Env: GIT_BASE_REF (default: main)",
    )
    a.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Max commits per repo. Env: GIT_LOG_LIMIT (default: 15)",
    )
    a.add_argument(
        "--no-diff",
        action="store_true",
        help="Skip diff for all repos (faster).",
    )
    a.set_defaults(func=cmd_all_summary)

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
