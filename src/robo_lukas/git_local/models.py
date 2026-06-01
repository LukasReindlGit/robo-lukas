"""Data models for the git-local module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class GitFileChange:
    """One changed file in the working tree or index."""

    path: str
    status: str  # 'modified' | 'added' | 'deleted' | 'renamed' | 'untracked' | 'staged'
    staged: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GitStatus:
    """Output of ``git status`` — branch info and file change summary."""

    repo_path: str
    branch: str
    upstream: str | None           # e.g. origin/main
    ahead: int = 0                 # commits ahead of upstream
    behind: int = 0                # commits behind upstream
    staged: list[GitFileChange] = field(default_factory=list)
    unstaged: list[GitFileChange] = field(default_factory=list)
    untracked: list[GitFileChange] = field(default_factory=list)
    is_clean: bool = False         # True when nothing to commit, nothing staged
    detached_head: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GitCommit:
    """One entry from ``git log``."""

    sha: str          # full 40-char hash
    short_sha: str    # 7-char abbreviation
    author: str
    author_email: str
    date: str         # ISO-8601
    subject: str      # first line of commit message
    body: str = ""    # rest of commit message (may be empty)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GitDiff:
    """Output of ``git diff`` against a base ref."""

    repo_path: str
    base_ref: str           # e.g. 'main' or 'origin/main'
    head_ref: str           # usually 'HEAD'
    files_changed: int
    insertions: int
    deletions: int
    file_patches: list[FilePatch] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FilePatch:
    """Diff for one file."""

    path: str
    old_path: str | None   # only set for renames
    insertions: int
    deletions: int
    patch: str             # unified diff text (may be truncated)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GitSummary:
    """Combined output for the morning briefing / end-of-day summary."""

    repo_path: str
    repo_name: str           # basename of repo_path
    status: GitStatus
    recent_commits: list[GitCommit] = field(default_factory=list)
    diff: GitDiff | None = None  # diff vs base ref; None if on main / clean

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d
