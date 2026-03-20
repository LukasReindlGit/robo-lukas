from __future__ import annotations

import time
from typing import TYPE_CHECKING

from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from robo_lukas.ms_todo.investigation import InvestigationReporter
from robo_lukas.ms_todo.models import TodoReaderConfig, TodoTask
from robo_lukas.ms_todo.safety import assert_readonly_todo_url, normalize_tasks_base_url
from robo_lukas.ms_todo.selectors import (
    LIST_NAV_CANDIDATES,
    ONBOARDING_CLICK_XPATHS,
    TASK_ROW_CANDIDATES,
    Sel,
)

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement


def _by(sel: Sel) -> tuple[str, str]:
    return sel.as_selenium()


def _find_elements(driver: WebDriver, sel: Sel):
    by, val = _by(sel)
    return driver.find_elements(by, val)


def _visible_task_rows(driver: WebDriver) -> list[WebElement]:
    for sel in TASK_ROW_CANDIDATES:
        try:
            els = _find_elements(driver, sel)
            visible = [e for e in els if e.is_displayed()]
            if len(visible) >= 1:
                return visible
        except Exception:
            continue
    return []


def _main_has_task_placeholder(driver: WebDriver) -> bool:
    """True when the main pane shows an empty-list / “add task” surface (no row elements yet)."""
    try:
        m = driver.find_element(By.CSS_SELECTOR, '[role="main"]')
        if not m.is_displayed():
            return False
        t = (m.text or "").lower()
        phrases = (
            "add a task",
            "add task",
            "new task",
            "neue aufgabe",
            "aufgabe hinzufügen",
            "eine aufgabe hinzufügen",
            "keine aufgaben",
        )
        return any(p in t for p in phrases)
    except Exception:
        return False


def _main_has_task_checkboxes(driver: WebDriver) -> bool:
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, '[role="main"] input[type="checkbox"]'):
            if el.is_displayed():
                return True
    except Exception:
        pass
    return False


def url_matches_sidebar_list(list_name: str, current_url: str) -> bool:
    """True when ``current_url`` already shows the named list (skip redundant nav click)."""
    name = list_name.strip().lower()
    u = (current_url or "").lower()
    if not u or "/tasks" not in u:
        return False
    if name == "tasks":
        return "/inbox" in u or "/lists/inbox" in u
    if name == "my day":
        return "/today" in u or "/myday" in u
    return False


def _wait_for_task_rows(driver: WebDriver, timeout_s: float, poll_s: float) -> list[WebElement]:
    end = time.monotonic() + timeout_s
    poll = max(0.04, min(poll_s, 0.14))
    poll_cap = max(poll, 0.28)
    while time.monotonic() < end:
        rows = _visible_task_rows(driver)
        if rows:
            return rows
        if _main_has_task_checkboxes(driver):
            rows = _visible_task_rows(driver)
            if rows:
                return rows
        time.sleep(poll)
        poll = min(poll * 1.12, poll_cap)
    return _visible_task_rows(driver)


def _scroll_page(driver: WebDriver, rounds: int, sleep_s: float) -> None:
    for _ in range(max(0, rounds)):
        try:
            ActionChains(driver).send_keys(Keys.PAGE_DOWN).perform()
        except Exception:
            driver.execute_script("window.scrollBy(0, 500);")
        time.sleep(max(0.06, sleep_s))


def _sidebar_label_from_element(el: WebElement) -> str:
    """
    Stable list name for sidebar rows.

    Office To Do uses ``aria-label`` like ``My Day, 2 tasks, Selected`` or ``Tasks, 7 tasks``.
    """
    try:
        aria = (el.get_attribute("aria-label") or "").strip()
    except StaleElementReferenceException:
        aria = ""
    if aria:
        # Strip trailing ", N tasks" / ", Selected" by taking first comma segment when it looks like nav.
        head = aria.split(",")[0].strip()
        if head and len(head) <= 120:
            return head
        return aria.split(",")[0].strip() or aria
    try:
        text = (el.text or "").strip()
        if text:
            return text.splitlines()[0].strip()
    except StaleElementReferenceException:
        pass
    return ""


def _nav_candidates(driver: WebDriver) -> list[WebElement]:
    seen: list[WebElement] = []
    seen_id: set[int] = set()
    for sel in LIST_NAV_CANDIDATES:
        try:
            for el in _find_elements(driver, sel):
                if not el.is_displayed():
                    continue
                eid = id(el)
                if eid in seen_id:
                    continue
                seen_id.add(eid)
                seen.append(el)
        except Exception:
            continue
    return seen


def is_todo_shell_ready(driver: WebDriver) -> bool:
    """True when sidebar and/or task list canvas looks loaded (not only URL)."""
    if _visible_task_rows(driver):
        return True
    if _main_has_task_checkboxes(driver):
        return True
    if _main_has_task_placeholder(driver):
        return True
    if len(_nav_candidates(driver)) >= 1:
        return True
    try:
        for sel in ('[role="main"]', '[data-testid*="TaskList"]', '[data-testid*="taskList"]', '[class*="taskList"]'):
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if not el.is_displayed():
                    continue
                sz = el.size or {}
                if int(sz.get("height", 0) or 0) > 64:
                    return True
    except Exception:
        pass
    return False


def is_todo_task_pane_ready(driver: WebDriver) -> bool:
    """
    True when the **main** task area looks usable — rows, empty state, checkboxes,
    or a list/grid inside ``role=main``. Sidebar-only does **not** count (avoids false “ready”).
    """
    if _visible_task_rows(driver):
        return True
    if _main_has_task_checkboxes(driver):
        return True
    if _main_has_task_placeholder(driver):
        return True
    try:
        main = driver.find_element(By.CSS_SELECTOR, '[role="main"]')
        if not main.is_displayed():
            return False
        for sel in (
            '[role="main"] [role="list"]',
            '[role="main"] [role="listbox"]',
            '[role="main"] [role="grid"]',
            '[role="main"] [data-testid*="task"]',
            # Virtualized / Fluent surfaces often omit role=list on the scroll container
            '[role="main"] [data-list-index]',
            '[role="main"] [class*="itemsList"]',
            '[role="main"] [class*="TasksPane"]',
            '[role="main"] [class*="taskList"]',
        ):
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed():
                    return True
        # Quick-add row / title field (common on empty inbox)
        for xp in (
            '//*[@role="main"]//input[contains(@placeholder, "task") or contains(@placeholder, "Task")]',
            '//*[@role="main"]//input[contains(@placeholder, "Aufgabe")]',
            '//*[@role="main"]//textarea',
        ):
            try:
                for el in driver.find_elements(By.XPATH, xp):
                    if el.is_displayed():
                        return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def task_list_resolved_for_export(driver: WebDriver) -> bool:
    """Enough UI to scrape or confirm an empty Tasks list (aligned with task pane detection)."""
    return is_todo_task_pane_ready(driver)


def wait_until_todo_ready(
    driver: WebDriver,
    cfg: TodoReaderConfig,
    *,
    deadline_monotonic: float,
    investigate: InvestigationReporter | None = None,
) -> bool:
    """
    Poll until the task list or shell is clearly visible, then return.

    Uses **adaptive** spacing: quick polls first, backs off toward ``shell_wait_poll_s``
    cap to reduce CPU while still exiting **immediately** once tasks or a stable shell appear.
    """
    poll = max(0.03, min(float(cfg.list_row_poll_s), 0.12))
    poll_cap = max(poll, float(getattr(cfg, "shell_wait_poll_s", 0.32)))
    consecutive = 0
    last_hb = time.monotonic()
    hb_every = max(4.0, float(investigate.heartbeat_interval_s)) if investigate else 0.0
    hb_snap = 0
    while time.monotonic() < deadline_monotonic:
        rows = _visible_task_rows(driver)
        if rows:
            return True
        if _main_has_task_checkboxes(driver):
            return True
        ok = is_todo_task_pane_ready(driver)
        if ok:
            consecutive += 1
            # One stable “main task area” poll is enough when we hard-fail after max_page_wait_s.
            if consecutive >= 1:
                return True
        else:
            consecutive = 0
        if investigate and hb_every > 0:
            now = time.monotonic()
            if now - last_hb >= hb_every:
                last_hb = now
                hb_snap += 1
                investigate.heartbeat(
                    driver,
                    "wait_until_todo_ready",
                    snapshot=(hb_snap % 2 == 0),
                )
        time.sleep(poll)
        poll = min(poll * 1.15, poll_cap)
    return (
        bool(_visible_task_rows(driver))
        or bool(_main_has_task_checkboxes(driver))
        or is_todo_task_pane_ready(driver)
    )


def dismiss_onboarding_if_present(driver: WebDriver, cfg: TodoReaderConfig) -> int:
    """
    Close first-run / \"Get started\" overlays (best effort; wording varies by locale).

    Returns how many control activations ran (clicks); 0 if nothing matched.
    """
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.05)
    except Exception:
        pass

    total = 0
    for _ in range(4):
        clicked = False
        for xp in ONBOARDING_CLICK_XPATHS:
            try:
                els = driver.find_elements(By.XPATH, xp)
                for el in els:
                    try:
                        if not el.is_displayed():
                            continue
                    except StaleElementReferenceException:
                        continue
                    try:
                        if not el.is_enabled():
                            continue
                    except StaleElementReferenceException:
                        continue
                    try:
                        el.click()
                    except ElementClickInterceptedException:
                        driver.execute_script("arguments[0].click();", el)
                    except StaleElementReferenceException:
                        continue
                    clicked = True
                    total += 1
                    time.sleep(min(0.38, cfg.post_nav_sleep_s * 0.55 + 0.06))
                    break
                if clicked:
                    break
            except Exception:
                continue
        if not clicked:
            break
    return total


def _row_to_task(idx: int, list_name: str, el: WebElement, source_url: str) -> TodoTask:
    text = ""
    try:
        text = (el.text or "").strip()
    except StaleElementReferenceException:
        text = ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()] if text else []
    title = lines[0] if lines else "(no title)"
    due_hint = ""
    status_hint = ""
    note_preview = ""
    if len(lines) > 1:
        for ln in lines[1:]:
            low = ln.lower()
            if "due" in low or "today" in low or "tomorrow" in low or any(
                x in low for x in ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
            ):
                due_hint = due_hint or ln
            elif "completed" in low or ln in ("Done",):
                status_hint = ln
            else:
                note_preview = note_preview or ln
    aria = None
    try:
        aria = el.get_attribute("aria-label")
    except StaleElementReferenceException:
        pass
    if not text and aria:
        title = aria.strip()
    try:
        completed = el.get_attribute("aria-checked")
        if completed == "true":
            status_hint = status_hint or "completed"
    except StaleElementReferenceException:
        pass
    return TodoTask(
        index=idx,
        list_name=list_name,
        title=title,
        due_hint=due_hint,
        status_hint=status_hint,
        note_preview=note_preview,
        row_text=text,
        source_url=source_url,
    )


class TodoReader:
    """Read-only navigation and scraping for Microsoft To Do on the web."""

    def __init__(
        self,
        driver: WebDriver,
        cfg: TodoReaderConfig,
        *,
        investigate: InvestigationReporter | None = None,
    ) -> None:
        self.driver = driver
        self.cfg = cfg
        self._investigate = investigate
        # **Critical:** implicit wait applies to find_elements too — with many selectors per poll,
        # even 1s multiplies into multi‑minute “freezes” on To Do. Use explicit waits only (our loops).
        driver.implicitly_wait(0)
        try:
            driver.set_page_load_timeout(75)
            driver.set_script_timeout(60)
        except Exception:
            pass

    def navigate_tasks_home(self) -> None:
        base = normalize_tasks_base_url(self.cfg.tasks_base_url)
        assert_readonly_todo_url(base)
        inv = self._investigate
        if inv:
            inv.phase("navigate_tasks_home_before_get", self.driver, snapshot=True)
        self.driver.get(base)
        time.sleep(self.cfg.post_nav_sleep_s)
        if inv:
            inv.phase("navigate_tasks_home_after_sleep", self.driver, snapshot=True)

    def status_snapshot(self) -> dict[str, str]:
        return {
            "url": self.driver.current_url or "",
            "title": self.driver.title or "",
        }

    def list_sidebar_labels(self, max_items: int = 120) -> list[str]:
        """Best-effort labels from the left list nav (for discovery)."""
        labels: list[str] = []
        seen: set[str] = set()
        for el in _nav_candidates(self.driver):
            try:
                name = _sidebar_label_from_element(el)
                if not name or len(name) > 120:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                labels.append(name)
                if len(labels) >= max_items:
                    break
            except StaleElementReferenceException:
                continue
        return labels

    def open_list_by_name(self, list_name: str) -> None:
        """Click a sidebar entry whose visible text matches ``list_name`` (case-insensitive)."""
        target = list_name.strip()
        if not target:
            raise ValueError("list name must be non-empty")
        target_l = target.lower()

        cur = self.driver.current_url or ""
        nav_budget = min(float(self.cfg.explicit_wait_s), float(self.cfg.max_page_wait_s))
        if url_matches_sidebar_list(target, cur):
            if _visible_task_rows(self.driver):
                time.sleep(min(0.06, float(self.cfg.post_nav_sleep_s) * 0.12))
                return
            t0 = time.monotonic()
            wait_until_todo_ready(
                self.driver,
                self.cfg,
                deadline_monotonic=t0 + nav_budget,
                investigate=self._investigate,
            )
            if task_list_resolved_for_export(self.driver):
                return

        for el in _nav_candidates(self.driver):
            try:
                label = _sidebar_label_from_element(el)
                if label.strip().lower() == target_l:
                    try:
                        el.click()
                    except ElementClickInterceptedException:
                        self.driver.execute_script("arguments[0].click();", el)
                    time.sleep(min(float(self.cfg.post_nav_sleep_s), 0.28))
                    t_click = time.monotonic()
                    nav_deadline = t_click + min(
                        float(self.cfg.explicit_wait_s),
                        float(self.cfg.max_page_wait_s),
                    )
                    if self._investigate:
                        self._investigate.phase(
                            "open_list_by_name_after_click",
                            self.driver,
                            snapshot=True,
                        )
                    wait_until_todo_ready(
                        self.driver,
                        self.cfg,
                        deadline_monotonic=nav_deadline,
                        investigate=self._investigate,
                    )
                    if not task_list_resolved_for_export(self.driver):
                        raise RuntimeError(
                            f"List {list_name!r}: task pane not ready within "
                            f"{self.cfg.max_page_wait_s:.0f}s after click. URL: "
                            f"{self.driver.current_url!r}. Try --investigate."
                        )
                    return
            except StaleElementReferenceException:
                continue

        if self._investigate:
            self._investigate.phase(
                "open_list_by_name_not_found",
                self.driver,
                snapshot=True,
            )
        raise RuntimeError(
            f"Could not find list {list_name!r} in the sidebar. "
            "Try `lists` to see detected names, or open the list manually once."
        )

    def list_tasks(
        self,
        list_name: str,
        *,
        limit: int = 50,
        scroll_rounds: int = 4,
    ) -> list[TodoTask]:
        """Collect visible task rows after the current list is open."""
        t0 = time.monotonic()
        cap = float(self.cfg.max_page_wait_s)
        abs_deadline = t0 + cap
        if not task_list_resolved_for_export(self.driver):
            dismiss_onboarding_if_present(self.driver, self.cfg)
        if self._investigate:
            self._investigate.phase("list_tasks_after_dismiss", self.driver, snapshot=True)
        url = self.driver.current_url or ""
        if _visible_task_rows(self.driver):
            list_deadline = min(
                abs_deadline,
                time.monotonic() + min(0.75, cap * 0.2),
            )
        else:
            list_deadline = abs_deadline
        wait_until_todo_ready(
            self.driver,
            self.cfg,
            deadline_monotonic=list_deadline,
            investigate=self._investigate,
        )
        remain = max(0.0, abs_deadline - time.monotonic())
        if not _visible_task_rows(self.driver) and remain > 0.03:
            _wait_for_task_rows(self.driver, remain, self.cfg.list_row_poll_s)
        if not task_list_resolved_for_export(self.driver):
            raise RuntimeError(
                f"No task list UI within {cap:.0f}s (MS_TODO_PAGE_WAIT_MAX) for {list_name!r}. "
                f"URL: {self.driver.current_url!r}. Use --investigate."
            )
        if self._investigate:
            self._investigate.phase(
                "list_tasks_rows_ready",
                self.driver,
                snapshot=True,
            )
        collected: list[TodoTask] = []
        seen_text: set[str] = set()

        for round_i in range(max(1, scroll_rounds + 1)):
            rows = _visible_task_rows(self.driver)
            src = self.driver.current_url or url
            for el in rows:
                try:
                    t = _row_to_task(len(collected), list_name, el, src)
                except StaleElementReferenceException:
                    continue
                key = (t.title, t.row_text[:200] if t.row_text else "")
                if key in seen_text:
                    continue
                seen_text.add(key)
                collected.append(t)
                if len(collected) >= limit:
                    return collected[:limit]
            if len(collected) >= limit:
                break
            if round_i < scroll_rounds:
                _scroll_page(self.driver, 1, self.cfg.scroll_key_sleep_s)

        return collected[:limit]
