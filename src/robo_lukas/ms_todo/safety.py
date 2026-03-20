"""
Read-only navigation guards for Microsoft To Do (web).
"""

from __future__ import annotations

from urllib.parse import urlparse

_FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    "signout",
    "sign-out",
    "/logout",
    "/settings",
    "/account",
    "deleteservice",
)


def assert_readonly_todo_url(url: str) -> None:
    """Refuse URLs that look like sign-out, settings, or account deletion."""
    lower = url.lower()
    for frag in _FORBIDDEN_FRAGMENTS:
        if frag in lower:
            raise ValueError(f"Read-only tool: blocked URL fragment {frag!r}: {url}")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Expected http(s) URL: {url}")
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()

    if host.endswith("to-do.live.com") and "/tasks" in path:
        return
    if host.endswith("to-do.live.com"):
        return
    if "to-do.live.com" in host:
        return
    if host.endswith("to-do.office.com") and "/tasks" in path:
        return
    if host.endswith("to-do.office.com"):
        return
    if "to-do.office.com" in host:
        return
    if "tasks.office.com" in host or "office.com" in host and "todo" in path:
        return
    if "microsoft365.com" in host and "todo" in path:
        return

    raise ValueError(
        "Read-only tool: URL must look like Microsoft To Do (e.g. to-do.live.com/tasks). "
        f"Got host={host!r} path={path!r}"
    )


def normalize_tasks_base_url(base: str) -> str:
    return base.rstrip("/")
