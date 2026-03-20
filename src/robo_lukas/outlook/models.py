from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class MailListItem:
    """One row in the conversation / message list (may be partial if list is virtualized)."""

    index: int
    raw_aria_label: str | None
    text: str
    conversation_id: str | None = None


@dataclass
class MailFolder:
    name: str
    url: str | None = None


@dataclass
class MailMessage:
    """Message payload for export / downstream processing."""

    folder: str
    index_in_list: int | None
    subject: str
    from_: str
    received: str
    preview: str
    body_text: str | None = None
    body_html: str | None = None
    list_row_text: str | None = None
    conversation_id: str | None = None
    source_url: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["from"] = d.pop("from_")
        return d


@dataclass
class OutlookReaderConfig:
    mail_base_url: str
    implicit_wait_s: float = 1.0
    explicit_wait_s: float = 25.0
    login_poll_s: float = 0.75
    # Extra pause after navigation for OWA shell (slow tenants).
    post_nav_sleep_s: float = 0.55
    # Poll interval while waiting for message rows to appear.
    list_row_poll_s: float = 0.12
    # Pause after each PageDown when virtualizing the list.
    scroll_key_sleep_s: float = 0.22
    # After typing a search query, wait for results (on top of post_nav_sleep_s).
    search_extra_sleep_s: float = 0.35
