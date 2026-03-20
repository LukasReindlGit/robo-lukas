"""
Outlook on the web — selector fallbacks.

Microsoft changes the DOM frequently. Order matters: first match wins per strategy.
Tune these in one place when OWA updates break scraping.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from selenium.webdriver.common.by import By


class BySel(Enum):
    CSS = "css"
    XPATH = "xpath"


@dataclass(frozen=True)
class Sel:
    by: BySel
    value: str

    def as_selenium(self) -> tuple[str, str]:
        if self.by == BySel.CSS:
            return By.CSS_SELECTOR, self.value
        return By.XPATH, self.value


# --- Message list rows (conversation list) ---
MESSAGE_ROW_CANDIDATES: list[Sel] = [
    Sel(BySel.CSS, '[role="listbox"] [role="option"]'),
    Sel(BySel.CSS, '[data-convid]'),
    Sel(BySel.CSS, 'div[role="list"] [role="listitem"]'),
    Sel(BySel.CSS, '[data-item-type="conversation"]'),
    Sel(BySel.XPATH, '//div[@role="listbox"]//div[@role="option"]'),
]

# --- Folder / navigation tree ---
FOLDER_TREE_CANDIDATES: list[Sel] = [
    Sel(BySel.CSS, '[role="navigation"] [role="tree"] [role="treeitem"]'),
    Sel(BySel.CSS, '[role="tree"] [role="treeitem"]'),
    Sel(BySel.CSS, 'button[name]'),
    Sel(BySel.XPATH, '//div[@role="treeitem"]'),
]

# --- Reading pane body ---
READING_PANE_ROOT_CANDIDATES: list[Sel] = [
    Sel(BySel.CSS, '[role="region"][aria-label*="Read" i]'),
    Sel(BySel.CSS, '[data-app-section="ReadingPane"]'),
    Sel(BySel.CSS, "div[data-min-width-reading-pane]"),
    Sel(BySel.XPATH, '//div[contains(@aria-label,"Reading")]'),
]

BODY_TEXT_CANDIDATES: list[Sel] = [
    Sel(BySel.CSS, '[role="document"]'),
    Sel(BySel.CSS, "div[dir='auto']"),
    Sel(BySel.CSS, ".allowTextSelection"),
]

# --- Mail list filter (Filter -> Unread) ---
MAIL_LIST_FILTER_MENU_CANDIDATES: list[Sel] = [
    Sel(BySel.CSS, "#mailListFilterMenu"),
    Sel(BySel.CSS, '[id="mailListFilterMenu"]'),
]

UNREAD_MENU_RADIO_CANDIDATES: list[Sel] = [
    Sel(BySel.CSS, '[role="menuitemradio"][title="Unread"]'),
    Sel(BySel.CSS, 'input[type="radio"][title="Unread"]'),
    Sel(
        BySel.XPATH,
        '//*[@role="menuitemradio" and (@title="Unread" or @aria-label="Unread" or normalize-space()="Unread")]',
    ),
    Sel(
        BySel.XPATH,
        '//span[normalize-space()="Unread"]/ancestor::*[@role="menuitemradio" or @role="menuitem"][1]',
    ),
]

# --- Search box (optional read-only search) ---
SEARCH_INPUT_CANDIDATES: list[Sel] = [
    Sel(BySel.CSS, 'input[aria-label*="Search" i]'),
    Sel(BySel.CSS, 'input[placeholder*="Search" i]'),
    Sel(BySel.CSS, 'input[type="search"]'),
]

# --- If OWA embeds message HTML in an iframe ---
MESSAGE_IFRAME_CANDIDATES: list[Sel] = [
    Sel(BySel.CSS, "iframe[title*='Message' i]"),
    Sel(BySel.CSS, "iframe[src*='message']"),
    Sel(BySel.CSS, "div[role='document'] iframe"),
]
