"""Data models for the Jira module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class JiraConfig:
    """Runtime configuration for the Jira module."""

    base_url: str  # e.g. https://c-hafner.atlassian.net (no trailing slash)
    browser_user_data_dir: str  # same Chrome profile used by Outlook / To Do is fine
    login_timeout_s: float = 600.0
    post_nav_sleep_s: float = 0.55
    login_poll_s: float = 0.75
    max_results: int = 25
    explicit_wait_s: float = 25.0


@dataclass
class JiraUser:
    """Minimal representation of the authenticated Jira user."""

    account_id: str
    display_name: str
    email: str | None = None


@dataclass
class JiraComment:
    """One comment on a Jira issue."""

    author: str
    created: str
    updated: str
    body_text: str

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JiraAttachment:
    """One attachment on a Jira issue."""

    attachment_id: str
    filename: str
    mime_type: str | None
    size_bytes: int | None
    created: str
    author: str | None
    content_url: str

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JiraIssue:
    """Full representation of a Jira issue, suitable for downstream LLM consumption."""

    key: str
    summary: str
    status: str
    issue_type: str
    created: str
    updated: str
    url: str
    assignee: str | None = None
    reporter: str | None = None
    priority: str | None = None
    description_text: str | None = None
    comments: list[JiraComment] = field(default_factory=list)
    attachments: list[JiraAttachment] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    sprint: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)
