"""
Git introspection via subprocess calls to the system ``git`` binary.

All operations are read-only (no checkout, commit, push, or fetch).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from robo_lukas.git_local.models import (
    FilePatch,
    GitCommit,
    GitDiff,
    GitFileChange,
    GitStatus,
    GitSummary,
)

# Max bytes of unified diff to capture per file (keeps LLM context sane).
_MAX_PATCH_BYTES = 8_000
# Max total diff bytes across all files.
_MAX_TOTAL_DIFF_BYTES = 60_000


class GitReader:
    """Read-only access to one local git repository."""

    def __init__(self, repo_path: str | Path) -> None:
        self.repo_path = Path(repo_path).expanduser().resolve()
        if not (self.repo_path / ".git").exists():
            # Walk up to find the git root (handles subdirectories)
            found = _find_git_root(self.repo_path)
            if found is None:
                raise ValueError(
                    f"No git repository found at or above: {self.repo_path}"
                )
            self.repo_path = found

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def status(self) -> GitStatus:
        """Return branch info and working-tree changes."""
        return _parse_status(self._run(["git", "status", "--porcelain=v2", "--branch"]))

    def log(self, limit: int = 20, base_ref: str | None = None) -> list[GitCommit]:
        """
        Return the last ``limit`` commits on HEAD.

        If ``base_ref`` is given (e.g. ``main``), return commits on HEAD that
        are NOT in ``base_ref`` (i.e. commits on the current branch only).
        """
        rev_range = f"{base_ref}..HEAD" if base_ref else "HEAD"
        raw = self._run(
            [
                "git", "log",
                rev_range,
                f"--max-count={limit}",
                "--format=%x00%H%x01%h%x01%an%x01%ae%x01%aI%x01%s%x01%b%x02",
            ]
        )
        return _parse_log(raw)

    def diff(
        self,
        base_ref: str = "main",
        *,
        max_files: int = 30,
        include_patches: bool = True,
    ) -> GitDiff:
        """
        Diff HEAD against ``base_ref``.

        Falls back to ``origin/main`` → ``origin/master`` → ``master`` if
        ``base_ref`` is not found as a local ref.
        """
        resolved_base = self._resolve_base_ref(base_ref)

        # --stat summary
        stat_raw = self._run(["git", "diff", "--stat", f"{resolved_base}...HEAD"])
        files_changed, insertions, deletions = _parse_diff_stat(stat_raw)

        file_patches: list[FilePatch] = []
        if include_patches and files_changed > 0:
            # Name-status to know which files changed
            name_status = self._run(
                ["git", "diff", "--name-status", f"{resolved_base}...HEAD"]
            )
            changed_files = _parse_name_status(name_status)[:max_files]

            total_bytes = 0
            for fp in changed_files:
                if total_bytes >= _MAX_TOTAL_DIFF_BYTES:
                    break
                patch_text = self._file_patch(fp.path, resolved_base)
                if len(patch_text) > _MAX_PATCH_BYTES:
                    patch_text = patch_text[:_MAX_PATCH_BYTES] + "\n… [truncated]"
                total_bytes += len(patch_text)
                file_patches.append(
                    FilePatch(
                        path=fp.path,
                        old_path=fp.old_path,
                        insertions=fp.insertions,
                        deletions=fp.deletions,
                        patch=patch_text,
                    )
                )

        return GitDiff(
            repo_path=str(self.repo_path),
            base_ref=resolved_base,
            head_ref="HEAD",
            files_changed=files_changed,
            insertions=insertions,
            deletions=deletions,
            file_patches=file_patches,
        )

    def summary(
        self,
        base_ref: str = "main",
        log_limit: int = 10,
        include_diff: bool = True,
    ) -> GitSummary:
        """
        Combined status + recent commits + optional diff — for morning briefing.

        Skips the diff if HEAD is already on ``base_ref`` (nothing to compare).
        """
        git_status = self.status()
        recent = self.log(limit=log_limit, base_ref=base_ref if self._ref_exists(base_ref) else None)

        diff: GitDiff | None = None
        if include_diff and self._ref_exists(base_ref):
            # Only diff if there are commits ahead of base_ref
            ahead_commits = self.log(limit=1, base_ref=base_ref)
            if ahead_commits:
                try:
                    diff = self.diff(base_ref=base_ref, include_patches=True)
                except Exception:
                    diff = None

        return GitSummary(
            repo_path=str(self.repo_path),
            repo_name=self.repo_path.name,
            status=git_status,
            recent_commits=recent,
            diff=diff,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, cmd: list[str], *, check: bool = True) -> str:
        """Run a git command in the repo directory and return stdout."""
        result = subprocess.run(
            cmd,
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if check and result.returncode != 0:
            raise GitCommandError(
                f"git command failed (exit {result.returncode}): {' '.join(cmd)}\n"
                f"stderr: {result.stderr.strip()}"
            )
        return result.stdout

    def _resolve_base_ref(self, base_ref: str) -> str:
        """Return the first existing ref from a fallback list."""
        candidates = [base_ref]
        if base_ref == "main":
            candidates += ["origin/main", "master", "origin/master"]
        elif base_ref == "master":
            candidates += ["origin/master", "main", "origin/main"]
        for ref in candidates:
            if self._ref_exists(ref):
                return ref
        # Return the original even if not found; git will error with a clear message
        return base_ref

    def _ref_exists(self, ref: str) -> bool:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", ref],
            cwd=str(self.repo_path),
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0

    def _file_patch(self, path: str, base_ref: str) -> str:
        try:
            return self._run(["git", "diff", f"{base_ref}...HEAD", "--", path])
        except GitCommandError:
            return ""


# ------------------------------------------------------------------
# Multi-repo convenience
# ------------------------------------------------------------------


def repos_from_env() -> list[Path]:
    """
    Read repo paths from env vars.

    - ``GIT_REPO_PATHS`` — comma-separated list of absolute paths.
    - ``GIT_REPO_PATH``  — single path (legacy / simple case).
    """
    paths: list[Path] = []
    multi = os.environ.get("GIT_REPO_PATHS", "").strip()
    if multi:
        for p in multi.split(","):
            p = p.strip()
            if p:
                paths.append(Path(p))
    single = os.environ.get("GIT_REPO_PATH", "").strip()
    if single and Path(single) not in paths:
        paths.append(Path(single))
    return paths


# ------------------------------------------------------------------
# Parsing helpers
# ------------------------------------------------------------------


def _find_git_root(path: Path) -> Path | None:
    """Walk up from ``path`` until we find a ``.git`` directory."""
    current = path
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _parse_status(raw: str) -> GitStatus:
    """
    Parse ``git status --porcelain=v2 --branch`` output into a GitStatus.

    Porcelain v2 format is stable and machine-readable.
    """
    branch = "unknown"
    upstream: str | None = None
    ahead = 0
    behind = 0
    staged: list[GitFileChange] = []
    unstaged: list[GitFileChange] = []
    untracked: list[GitFileChange] = []
    detached = False

    for line in raw.splitlines():
        if line.startswith("# branch.head"):
            val = line.split(maxsplit=2)[2] if len(line.split()) >= 3 else ""
            if val == "(detached)":
                detached = True
                branch = "HEAD (detached)"
            else:
                branch = val
        elif line.startswith("# branch.upstream"):
            parts = line.split(maxsplit=2)
            upstream = parts[2] if len(parts) >= 3 else None
        elif line.startswith("# branch.ab"):
            m = re.search(r"\+(\d+)\s+-(\d+)", line)
            if m:
                ahead = int(m.group(1))
                behind = int(m.group(2))
        elif line.startswith("1 "):
            # Changed tracked entry: "1 XY sub mH mI mW hH hI path"
            parts = line.split(" ")
            if len(parts) >= 9:
                xy = parts[1]
                path = " ".join(parts[8:])
                x, y = xy[0], xy[1]
                if x != "." and x != "?":
                    staged.append(GitFileChange(path=path, status=_xy_to_status(x), staged=True))
                if y != "." and y != "?":
                    unstaged.append(GitFileChange(path=path, status=_xy_to_status(y), staged=False))
        elif line.startswith("2 "):
            # Renamed/copied entry
            parts = line.split(" ")
            if len(parts) >= 10:
                xy = parts[1]
                paths = " ".join(parts[9:])
                x, y = xy[0], xy[1]
                if x != ".":
                    staged.append(GitFileChange(path=paths, status="renamed", staged=True))
                if y != ".":
                    unstaged.append(GitFileChange(path=paths, status="renamed", staged=False))
        elif line.startswith("? "):
            path = line[2:]
            untracked.append(GitFileChange(path=path, status="untracked", staged=False))

    is_clean = not staged and not unstaged and not untracked
    return GitStatus(
        repo_path="",  # filled in by caller
        branch=branch,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
        is_clean=is_clean,
        detached_head=detached,
    )


def _xy_to_status(code: str) -> str:
    return {
        "M": "modified",
        "A": "added",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "U": "unmerged",
    }.get(code.upper(), code)


# Record separator \x00, field separator \x01, end \x02
_LOG_SEP = re.compile(r"\x00(.*?)\x02", re.DOTALL)
_FIELD_SEP = "\x01"


def _parse_log(raw: str) -> list[GitCommit]:
    commits = []
    for m in _LOG_SEP.finditer(raw):
        fields = m.group(1).split(_FIELD_SEP)
        if len(fields) < 6:
            continue
        sha, short_sha, author, email, date, subject = fields[:6]
        body = fields[6].strip() if len(fields) > 6 else ""
        commits.append(
            GitCommit(
                sha=sha.strip(),
                short_sha=short_sha.strip(),
                author=author.strip(),
                author_email=email.strip(),
                date=date.strip(),
                subject=subject.strip(),
                body=body,
            )
        )
    return commits


def _parse_diff_stat(stat_raw: str) -> tuple[int, int, int]:
    """Parse the summary line from ``git diff --stat``: '3 files changed, 10 insertions(+), 2 deletions(-)'."""
    files = insertions = deletions = 0
    for line in reversed(stat_raw.splitlines()):
        line = line.strip()
        if "changed" in line:
            m = re.search(r"(\d+) files? changed", line)
            if m:
                files = int(m.group(1))
            m = re.search(r"(\d+) insertion", line)
            if m:
                insertions = int(m.group(1))
            m = re.search(r"(\d+) deletion", line)
            if m:
                deletions = int(m.group(1))
            break
    return files, insertions, deletions


def _parse_name_status(raw: str) -> list[FilePatch]:
    """Parse ``git diff --name-status`` output into minimal FilePatch stubs."""
    patches: list[FilePatch] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        code = parts[0]
        if code.startswith("R") and len(parts) >= 3:
            patches.append(FilePatch(path=parts[2], old_path=parts[1], insertions=0, deletions=0, patch=""))
        elif len(parts) >= 2:
            patches.append(FilePatch(path=parts[1], old_path=None, insertions=0, deletions=0, patch=""))
    return patches


class GitCommandError(RuntimeError):
    pass
