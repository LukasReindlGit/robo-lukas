from __future__ import annotations

import time
from typing import TYPE_CHECKING

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from robo_lukas.outlook.models import MailFolder, MailListItem, MailMessage, OutlookReaderConfig
from robo_lukas.outlook.safety import assert_readonly_navigation_url, build_folder_url
from robo_lukas.outlook.selectors import (
    BODY_TEXT_CANDIDATES,
    FOLDER_TREE_CANDIDATES,
    MAIL_LIST_FILTER_MENU_CANDIDATES,
    MESSAGE_IFRAME_CANDIDATES,
    MESSAGE_ROW_CANDIDATES,
    READING_PANE_ROOT_CANDIDATES,
    SEARCH_INPUT_CANDIDATES,
    UNREAD_MENU_RADIO_CANDIDATES,
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


def _first_non_empty_rows(driver: WebDriver) -> list[WebElement]:
    for sel in MESSAGE_ROW_CANDIDATES:
        try:
            els = _find_elements(driver, sel)
            visible = [e for e in els if e.is_displayed()]
            if visible:
                return visible
        except Exception:
            continue
    return []


def _wait_for_message_rows(driver: WebDriver, timeout_s: float, poll_s: float) -> list[WebElement]:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        rows = _first_non_empty_rows(driver)
        if rows:
            return rows
        time.sleep(max(0.05, poll_s))
    return _first_non_empty_rows(driver)


def _scroll_for_more_rows(driver: WebDriver, rounds: int, key_sleep_s: float) -> None:
    for _ in range(max(0, rounds)):
        try:
            ActionChains(driver).send_keys(Keys.PAGE_DOWN).perform()
        except Exception:
            driver.execute_script("window.scrollBy(0, 600);")
        time.sleep(max(0.08, key_sleep_s))


def _row_to_list_item(idx: int, el: WebElement) -> MailListItem:
    aria = None
    conv = None
    try:
        aria = el.get_attribute("aria-label")
    except StaleElementReferenceException:
        pass
    try:
        conv = el.get_attribute("data-convid")
    except StaleElementReferenceException:
        pass
    text = ""
    try:
        text = (el.text or "").strip()
    except StaleElementReferenceException:
        text = ""
    if not text and aria:
        text = aria.strip()
    return MailListItem(index=idx, raw_aria_label=aria, text=text, conversation_id=conv)


def _parse_list_item_to_message(folder: str, item: MailListItem) -> MailMessage:
    lines = [ln.strip() for ln in (item.text or "").splitlines() if ln.strip()]
    subject = lines[0] if lines else (item.raw_aria_label or "(no subject)")
    from_ = lines[1] if len(lines) > 1 else ""
    preview = "\n".join(lines[2:]) if len(lines) > 2 else ""
    if not from_ and item.raw_aria_label:
        from_ = ""
    return MailMessage(
        folder=folder,
        index_in_list=item.index,
        subject=subject,
        from_=from_,
        received="",
        preview=preview,
        body_text=None,
        body_html=None,
        list_row_text=item.text,
        conversation_id=item.conversation_id,
        source_url="",
    )


class OutlookReader:
    """
    Read-only navigation and scraping for Outlook on the web.

    Does not expose compose/send/delete. Opening a thread may still cause the
    server to mark messages as read — see module README.
    """

    def __init__(self, driver: WebDriver, cfg: OutlookReaderConfig) -> None:
        self.driver = driver
        self.cfg = cfg
        driver.implicitly_wait(int(cfg.implicit_wait_s))

    def navigate_readonly(self, url: str) -> None:
        assert_readonly_navigation_url(url)
        self.driver.get(url)
        time.sleep(self.cfg.post_nav_sleep_s)

    def open_folder(self, folder_spec: str) -> str:
        url = build_folder_url(self.cfg.mail_base_url, folder_spec)
        self.navigate_readonly(url)
        return url

    def status_snapshot(self) -> dict[str, str]:
        return {
            "url": self.driver.current_url or "",
            "title": self.driver.title or "",
        }

    def list_nav_folders(self, max_items: int = 200) -> list[MailFolder]:
        """
        Best-effort scrape of folder names from the left navigation tree.

        May miss folders or pick up non-folder controls depending on OWA variant.
        """
        folders: list[MailFolder] = []
        seen: set[str] = set()
        for sel in FOLDER_TREE_CANDIDATES:
            try:
                els = _find_elements(self.driver, sel)
            except Exception:
                continue
            for el in els:
                if not el.is_displayed():
                    continue
                name = (el.text or "").strip() or (el.get_attribute("name") or "").strip()
                if not name or len(name) > 200:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                folders.append(MailFolder(name=name, url=None))
                if len(folders) >= max_items:
                    return folders
        return folders

    def apply_unread_list_filter(self) -> None:
        """
        Open the mail list filter menu (#mailListFilterMenu) and choose Unread.

        Matches OWA “Filter → Unread” (menu item radio, title Unread). DOM varies by tenant;
        see ``UNREAD_MENU_RADIO_CANDIDATES``.
        """
        filter_btn = None
        for sel in MAIL_LIST_FILTER_MENU_CANDIDATES:
            try:
                for el in _find_elements(self.driver, sel):
                    if el.is_displayed():
                        filter_btn = el
                        break
            except Exception:
                continue
            if filter_btn is not None:
                break
        if filter_btn is None:
            raise RuntimeError("Could not find mail list filter control (#mailListFilterMenu).")
        try:
            filter_btn.click()
        except ElementClickInterceptedException:
            self.driver.execute_script("arguments[0].click();", filter_btn)
        time.sleep(self.cfg.post_nav_sleep_s)
        time.sleep(0.12)

        def _is_unread_choice(el: WebElement) -> bool:
            title = (el.get_attribute("title") or "").strip()
            label = (el.get_attribute("aria-label") or "").strip()
            if title == "Unread" or label == "Unread":
                return True
            try:
                return "Unread" in (el.text or "")
            except StaleElementReferenceException:
                return False

        unread_el = None
        for sel in UNREAD_MENU_RADIO_CANDIDATES:
            try:
                for el in _find_elements(self.driver, sel):
                    if el.is_displayed() and _is_unread_choice(el):
                        unread_el = el
                        break
            except Exception:
                continue
            if unread_el is not None:
                break
        if unread_el is None:
            try:
                unread_el = self.driver.find_element(
                    By.XPATH,
                    "//*[@role='menuitemradio' or @role='menuitem'][.//text()[normalize-space()='Unread'] or @title='Unread' or @aria-label='Unread']",
                )
                if not unread_el.is_displayed():
                    unread_el = None
            except NoSuchElementException:
                unread_el = None

        if unread_el is None:
            raise RuntimeError("Could not find Unread in the filter menu (UI may differ).")

        try:
            unread_el.click()
        except ElementClickInterceptedException:
            self.driver.execute_script("arguments[0].click();", unread_el)
        time.sleep(self.cfg.post_nav_sleep_s)
        time.sleep(0.12)

    def list_messages(
        self,
        folder_spec: str,
        *,
        limit: int = 50,
        scroll_rounds: int = 3,
        skip_navigation: bool = False,
        unread_filter: bool = False,
    ) -> list[MailListItem]:
        if not skip_navigation:
            self.open_folder(folder_spec)
            if unread_filter:
                self.apply_unread_list_filter()
        _wait_for_message_rows(self.driver, self.cfg.explicit_wait_s, self.cfg.list_row_poll_s)
        collected: list[MailListItem] = []
        seen_conv: set[str] = set()

        for round_i in range(max(1, scroll_rounds + 1)):
            rows = _first_non_empty_rows(self.driver)
            for i, el in enumerate(rows):
                try:
                    item = _row_to_list_item(len(collected), el)
                except StaleElementReferenceException:
                    continue
                key = item.conversation_id or f"{item.text}:{item.raw_aria_label}"
                if key in seen_conv:
                    continue
                seen_conv.add(key)
                collected.append(item)
                if len(collected) >= limit:
                    return collected
            if len(collected) >= limit:
                break
            if round_i < scroll_rounds:
                _scroll_for_more_rows(self.driver, 1, self.cfg.scroll_key_sleep_s)

        return collected[:limit]

    def search(self, query: str) -> None:
        """Run an in-app search (read-only intent: only loads result list)."""
        inp = None
        for sel in SEARCH_INPUT_CANDIDATES:
            try:
                els = _find_elements(self.driver, sel)
                for el in els:
                    if el.is_displayed():
                        inp = el
                        break
            except Exception:
                continue
            if inp is not None:
                break
        if inp is None:
            raise RuntimeError("Could not find Outlook search input; UI may have changed.")
        inp.click()
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
        inp.send_keys(Keys.BACKSPACE)
        inp.send_keys(query)
        inp.send_keys(Keys.ENTER)
        time.sleep(self.cfg.post_nav_sleep_s)
        time.sleep(self.cfg.search_extra_sleep_s)

    def open_list_item(self, index: int) -> None:
        rows = _wait_for_message_rows(self.driver, self.cfg.explicit_wait_s, self.cfg.list_row_poll_s)
        if index < 0 or index >= len(rows):
            raise IndexError(f"Message index {index} out of range (0..{len(rows)-1}).")
        el = rows[index]
        try:
            el.click()
        except ElementClickInterceptedException:
            self.driver.execute_script("arguments[0].click();", el)
        time.sleep(self.cfg.post_nav_sleep_s)
        time.sleep(0.22)

    def read_reading_pane(self) -> tuple[str | None, str | None]:
        """
        Return ``(body_text, body_html)`` from the reading pane if found.
        """
        text: str | None = None
        html: str | None = None

        for sel in MESSAGE_IFRAME_CANDIDATES:
            try:
                frames = _find_elements(self.driver, sel)
                for fr in frames:
                    if not fr.is_displayed():
                        continue
                    self.driver.switch_to.frame(fr)
                    try:
                        body = self.driver.find_element(By.TAG_NAME, "body")
                        t = (body.text or "").strip()
                        h = body.get_attribute("innerHTML")
                        if t:
                            self.driver.switch_to.default_content()
                            return t, h
                    finally:
                        self.driver.switch_to.default_content()
            except Exception:
                self.driver.switch_to.default_content()

        root = None
        for sel in READING_PANE_ROOT_CANDIDATES:
            try:
                els = _find_elements(self.driver, sel)
                for e in els:
                    if e.is_displayed():
                        root = e
                        break
            except Exception:
                continue
            if root is not None:
                break

        search_roots: list[WebElement] = []
        if root is not None:
            search_roots.append(root)
        try:
            search_roots.append(self.driver.find_element(By.TAG_NAME, "body"))
        except NoSuchElementException:
            pass

        for r in search_roots:
            for sel in BODY_TEXT_CANDIDATES:
                try:
                    by, val = _by(sel)
                    els = r.find_elements(by, val)
                    for e in els:
                        if not e.is_displayed():
                            continue
                        t = (e.text or "").strip()
                        if len(t) > 12:
                            text = t
                            html = e.get_attribute("innerHTML")
                            return text, html
                except Exception:
                    continue

        return text, html

    def get_message(
        self,
        folder_spec: str,
        index: int,
        *,
        include_body: bool = True,
        max_scroll_rounds: int = 8,
        skip_folder_open: bool = False,
        unread_filter: bool = False,
    ) -> MailMessage:
        """
        If ``skip_folder_open`` is True, assume the list pane already shows the desired
        messages (e.g. after ``search``). Do not call ``open_folder`` — avoids clearing
        the active search / filter.
        """
        if not skip_folder_open:
            self.open_folder(folder_spec)
            if unread_filter:
                self.apply_unread_list_filter()
        _wait_for_message_rows(self.driver, self.cfg.explicit_wait_s, self.cfg.list_row_poll_s)
        rows: list[WebElement] = []
        for _ in range(max(1, max_scroll_rounds)):
            rows = _first_non_empty_rows(self.driver)
            if len(rows) > index:
                break
            _scroll_for_more_rows(self.driver, 1, self.cfg.scroll_key_sleep_s)
        rows = _first_non_empty_rows(self.driver)
        if index < 0 or index >= len(rows):
            raise IndexError(
                f"Message index {index} not found in folder {folder_spec!r} "
                f"(only {len(rows)} row(s) visible in DOM; try increasing scroll rounds)."
            )
        item = _row_to_list_item(index, rows[index])
        msg = _parse_list_item_to_message(folder_spec, item)
        msg.source_url = self.driver.current_url

        if include_body:
            clicked = False
            for _ in range(4):
                try:
                    r = _first_non_empty_rows(self.driver)
                    if index >= len(r):
                        raise IndexError(
                            f"Row index {index} disappeared after navigation "
                            f"(visible rows: {len(r)})."
                        )
                    el = r[index]
                    try:
                        el.click()
                    except ElementClickInterceptedException:
                        self.driver.execute_script("arguments[0].click();", el)
                    clicked = True
                    break
                except StaleElementReferenceException:
                    time.sleep(0.18)
            if not clicked:
                raise RuntimeError("Could not open message row (stale DOM); retry the command.")

            time.sleep(self.cfg.post_nav_sleep_s)
            time.sleep(0.22)
            msg.source_url = self.driver.current_url
            btxt, bhtml = self.read_reading_pane()
            msg.body_text = btxt
            msg.body_html = bhtml
        return msg
