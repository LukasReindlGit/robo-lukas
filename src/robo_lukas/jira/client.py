"""
Jira REST API client using browser session cookies.

Targets Jira Cloud REST API v3 (https://developer.atlassian.com/cloud/jira/platform/rest/v3/).
All endpoints are GET-only; no writes are performed.

Session cookies (extracted from the browser after login) are forwarded via a
``requests.Session``. No API token is required.
"""

from __future__ import annotations

from typing import Any

import requests

from robo_lukas.jira.models import JiraComment, JiraIssue, JiraUser


# Default fields fetched for search / list operations (omitting heavy fields like comments).
_LIST_FIELDS: list[str] = [
    "summary",
    "status",
    "assignee",
    "reporter",
    "priority",
    "issuetype",
    "created",
    "updated",
    "labels",
    "customfield_10020",  # Sprint (Jira Cloud)
]

# Full fields including description and comments, for single-issue fetch.
_DETAIL_FIELDS: list[str] = _LIST_FIELDS + ["description", "comment"]


class JiraClient:
    """
    Read-only Jira REST API client.

    Accepts a dict of browser session cookies; no separate token needed.
    """

    def __init__(self, base_url: str, cookies: dict[str, str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        for name, value in cookies.items():
            self.session.cookies.set(name, value)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                # Prevents some Jira endpoints from rejecting cookie-authenticated requests.
                "X-Atlassian-Token": "no-check",
            }
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> Any:
        """Issue a GET request; raise for non-2xx status."""
        url = f"{self.base_url}{path}"
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def myself(self) -> JiraUser:
        """Return the currently authenticated user."""
        data = self._get("/rest/api/3/myself")
        return JiraUser(
            account_id=data.get("accountId", ""),
            display_name=data.get("displayName", ""),
            email=data.get("emailAddress"),
        )

    def search(
        self,
        jql: str,
        max_results: int = 25,
        fields: list[str] | None = None,
        start_at: int = 0,
    ) -> list[JiraIssue]:
        """
        Search issues using JQL.

        ``fields`` defaults to :data:`_LIST_FIELDS`; pass a custom list to override.
        """
        params: dict[str, Any] = {
            "jql": jql,
            "maxResults": max_results,
            "startAt": start_at,
            "fields": ",".join(fields if fields is not None else _LIST_FIELDS),
        }
        try:
            data = self._get("/rest/api/3/search", params=params)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code != 410:
                raise
            # Some Jira Cloud tenants no longer support GET /search.
            data = self._get("/rest/api/3/search/jql", params=params)
        return [self._parse_issue(item) for item in (data.get("issues") or [])]

    def get_issue(self, issue_key: str, *, include_comments: bool = True) -> JiraIssue:
        """Fetch a single issue by key with description and optionally comments."""
        use_fields = _DETAIL_FIELDS if include_comments else _LIST_FIELDS + ["description"]
        params = {"fields": ",".join(use_fields)}
        data = self._get(f"/rest/api/3/issue/{issue_key}", params=params)
        return self._parse_issue(data)

    def list_my_issues(
        self,
        max_results: int = 25,
        exclude_done: bool = True,
        extra_jql: str = "",
    ) -> list[JiraIssue]:
        """
        List open issues assigned to the current user, newest first.

        Pass ``exclude_done=False`` to include Closed/Done/Resolved issues.
        ``extra_jql`` is appended to the JQL with AND (e.g. ``'project = ECOM'``).
        """
        jql = "assignee = currentUser()"

        if exclude_done:
            jql += (
                ' AND status not in ("Done", "Closed", "Resolved", "Won\'t Do", "Cancelled")'
            )

        if extra_jql.strip():
            jql += f" AND ({extra_jql.strip()})"

        jql += " ORDER BY updated DESC"
        return self.search(jql, max_results=max_results)

    def list_sprint_issues(self, max_results: int = 50, extra_jql: str = "") -> list[JiraIssue]:
        """
        List issues in any open sprint that are assigned to the current user.

        Requires the Jira Agile (Software) feature and appropriate permissions.
        Raises ``requests.HTTPError`` with a 400 if JQL uses ``openSprints()`` but
        no Agile configuration exists — caller should handle this gracefully.
        """
        jql = "sprint in openSprints() AND assignee = currentUser()"
        if extra_jql.strip():
            jql += f" AND ({extra_jql.strip()})"
        jql += " ORDER BY rank ASC"
        return self.search(jql, max_results=max_results)

    def list_recent_issues(self, max_results: int = 25, extra_jql: str = "") -> list[JiraIssue]:
        """All issues assigned to current user (including done), newest first."""
        return self.list_my_issues(
            max_results=max_results,
            exclude_done=False,
            extra_jql=extra_jql,
        )

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_issue(self, data: dict) -> JiraIssue:
        key = data.get("key", "")
        fields = data.get("fields") or {}

        desc_text = _adf_to_text(fields.get("description"))

        comments: list[JiraComment] = []
        comment_block = fields.get("comment") or {}
        for c in comment_block.get("comments") or []:
            author = ((c.get("author") or {}).get("displayName") or "Unknown")
            body_text = _adf_to_text(c.get("body"))
            comments.append(
                JiraComment(
                    author=author,
                    created=c.get("created", ""),
                    updated=c.get("updated", ""),
                    body_text=body_text,
                )
            )

        sprint_name = _extract_sprint_name(fields.get("customfield_10020"))

        return JiraIssue(
            key=key,
            summary=fields.get("summary") or "",
            status=((fields.get("status") or {}).get("name") or "Unknown"),
            issue_type=((fields.get("issuetype") or {}).get("name") or "Unknown"),
            created=fields.get("created") or "",
            updated=fields.get("updated") or "",
            url=f"{self.base_url}/browse/{key}",
            assignee=((fields.get("assignee") or {}).get("displayName")) if fields.get("assignee") else None,
            reporter=((fields.get("reporter") or {}).get("displayName")) if fields.get("reporter") else None,
            priority=((fields.get("priority") or {}).get("name")) if fields.get("priority") else None,
            description_text=desc_text or None,
            comments=comments,
            labels=list(fields.get("labels") or []),
            sprint=sprint_name,
        )


# ------------------------------------------------------------------
# ADF (Atlassian Document Format) → plain text
# ------------------------------------------------------------------


def _extract_sprint_name(sprint_field: Any) -> str | None:
    """
    Extract sprint name from ``customfield_10020``.

    The field can be ``None``, a single sprint dict, or a list of sprint dicts
    (Jira can include historical sprints). We take the last (most recent) entry.
    """
    if sprint_field is None:
        return None
    if isinstance(sprint_field, dict):
        return sprint_field.get("name")
    if isinstance(sprint_field, list) and sprint_field:
        last = sprint_field[-1]
        if isinstance(last, dict):
            return last.get("name")
    return None


def _adf_to_text(node: Any) -> str:
    """
    Convert an Atlassian Document Format (ADF) JSON tree to plain text.

    Falls back gracefully:
    - Plain strings (Jira Server / DC) are returned as-is.
    - ``None`` → empty string.
    - Unknown node types → recurse into children.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return str(node)

    node_type = node.get("type", "")
    content = node.get("content") or []

    if node_type == "text":
        return node.get("text", "")

    if node_type == "hardBreak":
        return "\n"

    if node_type in ("paragraph", "heading"):
        inner = "".join(_adf_to_text(c) for c in content)
        return inner + "\n" if inner.strip() else ""

    if node_type == "bulletList":
        lines = []
        for item in content:
            t = _collect_children(item).strip()
            if t:
                lines.append(f"• {t}")
        return "\n".join(lines) + "\n" if lines else ""

    if node_type == "orderedList":
        lines = []
        for i, item in enumerate(content, start=1):
            t = _collect_children(item).strip()
            if t:
                lines.append(f"{i}. {t}")
        return "\n".join(lines) + "\n" if lines else ""

    if node_type == "codeBlock":
        inner = "".join(_adf_to_text(c) for c in content)
        return f"```\n{inner}\n```\n" if inner.strip() else ""

    if node_type == "blockquote":
        inner = _collect_children(node).strip()
        return f"> {inner}\n" if inner else ""

    if node_type == "rule":
        return "\n---\n"

    if node_type == "mention":
        return node.get("attrs", {}).get("text", "") or ""

    if node_type == "emoji":
        return node.get("attrs", {}).get("text", "") or ""

    if node_type == "inlineCard":
        return node.get("attrs", {}).get("url", "") or ""

    # Table: flatten cells with tab/newline separation
    if node_type == "table":
        rows = []
        for row in content:
            cells = []
            for cell in (row.get("content") or []):
                cells.append(_collect_children(cell).strip())
            rows.append("\t".join(cells))
        return "\n".join(rows) + "\n" if rows else ""

    # Generic fallback: recurse into children
    return _collect_children(node)


def _collect_children(node: dict) -> str:
    """Concatenate the text of all children of *node*."""
    return "".join(_adf_to_text(c) for c in (node.get("content") or []))
