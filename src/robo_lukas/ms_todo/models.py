from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class TodoTask:
    """One row in the task list (best-effort scrape)."""

    index: int
    list_name: str
    title: str
    due_hint: str
    status_hint: str
    note_preview: str
    row_text: str
    source_url: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TodoReaderConfig:
    tasks_base_url: str
    implicit_wait_s: float = 1.0
    explicit_wait_s: float = 8.0
    login_poll_s: float = 0.45
    post_nav_sleep_s: float = 0.22
    list_row_poll_s: float = 0.05
    scroll_key_sleep_s: float = 0.1
    # After URL + shell look ready, tiny pause (tunable via MS_TODO_SHELL_SETTLE).
    shell_settle_sleep_s: float = 0.45
    # Poll backoff cap inside ``wait_until_todo_ready`` / stall retries.
    shell_wait_poll_s: float = 0.32
    # Max time per loop iteration in ``wait_until_todo_ready`` before SSO/shell retry.
    shell_burst_wait_s: float = 9.0
    # Hard cap: max seconds waiting on one To Do **task** URL for rows / empty-list UI (then error).
    max_page_wait_s: float = 4.0
