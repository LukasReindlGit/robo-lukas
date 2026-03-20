"""Microsoft To Do (web) — selector fallbacks; tune when the UI changes."""

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


LIST_NAV_CANDIDATES: list[Sel] = [
    # to-do.office.com / M365 shell — sidebar rows are role=option (not treeitem)
    Sel(BySel.CSS, 'li.todayToolbar-item[role="option"]'),
    Sel(BySel.CSS, 'li.listItem-container[role="option"]'),
    Sel(BySel.CSS, '[role="navigation"] [role="treeitem"]'),
    Sel(BySel.CSS, '[role="tree"] [role="treeitem"]'),
    Sel(BySel.CSS, '[role="navigation"] button'),
    Sel(BySel.XPATH, '//div[@role="treeitem"]'),
    Sel(BySel.CSS, 'a[href*="/tasks/"]'),
]

# First-run / welcome — text varies by locale; extend for non-English tenants.
ONBOARDING_CLICK_XPATHS: tuple[str, ...] = (
    '//button[contains(., "Get started")]',
    '//button[contains(., "Get Started")]',
    '//a[contains(., "Get started")]',
    '//button[contains(., "Skip")]',
    '//a[contains(., "Skip")]',
    '//button[contains(., "Continue")]',
    '//button[contains(., "Next")]',
    '//button[contains(., "No thanks")]',
    '//button[contains(., "Maybe later")]',
    '//span[contains(., "Get started")]/ancestor::button[1]',
    '//span[contains(., "Skip")]/ancestor::button[1]',
    '//*[@role="dialog"]//button[contains(., "Continue")]',
    '//button[contains(., "Weiter")]',
    '//button[contains(., "Überspringen")]',
    '//button[contains(., "Los geht")]',
    '//button[contains(., "Jetzt starten")]',
)

TASK_ROW_CANDIDATES: list[Sel] = [
    # Grid view (default for many tenants): virtualized table — data rows are .grid-row, not listitem.
    # Exclude .row-group (e.g. "Completed" section header — not a task row).
    Sel(
        BySel.CSS,
        '[role="main"] [role="grid"] div.grid-row[role="row"]:not(.row-group)',
    ),
    Sel(
        BySel.XPATH,
        '//div[@role="main"]//div[@role="grid"]//div[@role="row" and contains(@class, "grid-row") '
        'and not(contains(@class, "row-group"))]',
    ),
    # Must stay under **main** — the sidebar uses ul[role=listbox] > li[role=option] too.
    Sel(BySel.CSS, '[role="main"] [role="listitem"]'),
    Sel(BySel.CSS, '[role="main"] [role="list"] [role="listitem"]'),
    Sel(BySel.CSS, '[role="main"] [role="listbox"] [role="option"]'),
    Sel(BySel.CSS, '[role="main"] [data-testid*="task"]'),
    Sel(BySel.XPATH, '//div[@role="main"]//div[@role="listitem"]'),
    # Fluent / To Do often renders task rows with a row checkbox inside main.
    Sel(BySel.CSS, '[role="main"] [role="list"] [role="checkbox"]'),
    Sel(BySel.XPATH, '//div[@role="main"]//*[@role="checkbox"][ancestor::*[@role="list" or @role="listbox"]]'),
]
