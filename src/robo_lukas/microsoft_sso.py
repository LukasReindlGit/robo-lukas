"""
Auto-advance Microsoft login / SSO pages where it is safe (no password entry).

Handles **Pick an account** (saved tiles), “Stay signed in?” (KMSI), app consent **Accept**,
and **Next** when an email/UPN field is already filled.

Does **not** submit empty password forms or solve MFA. For several accounts, set
:envvar:`MICROSOFT_ACCOUNT_HINT` (substring of the tile text, usually the email).
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.by import By

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver


def wait_document_ready(
    driver: "WebDriver", timeout_s: float = 30.0, poll_s: float = 0.08
) -> bool:
    """Wait until ``document.readyState == 'complete'`` (best effort)."""
    deadline = time.monotonic() + max(0.5, timeout_s)
    while time.monotonic() < deadline:
        try:
            state = driver.execute_script("return document.readyState")
            if state == "complete":
                return True
        except Exception:
            pass
        time.sleep(poll_s)
    return False


def wait_document_interactive(driver: "WebDriver", timeout_s: float = 0.5, poll_s: float = 0.03) -> bool:
    """
    Return as soon as ``readyState`` is ``interactive`` **or** ``complete``.

    OWA / To Do SPAs often sit on ``interactive`` for a long time; waiting only for
    ``complete`` burns seconds per poll cycle for no benefit.
    """
    deadline = time.monotonic() + max(0.06, timeout_s)
    while time.monotonic() < deadline:
        try:
            state = driver.execute_script("return document.readyState")
            if state in ("interactive", "complete"):
                return True
        except Exception:
            pass
        time.sleep(poll_s)
    return False


def _safe_body_text(driver: "WebDriver") -> str:
    try:
        return (driver.find_element(By.TAG_NAME, "body").text or "").lower()
    except Exception:
        return ""


def _password_field_visible(driver: "WebDriver") -> bool:
    try:
        for sel in ('input[type="password"]', "input[name=passwd]", "#password"):
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    if el.is_displayed():
                        return True
                except StaleElementReferenceException:
                    continue
    except Exception:
        pass
    return False


_SKIP_ACCOUNT_TILE_PHRASES: tuple[str, ...] = (
    "use another account",
    "another account",
    "sign in with a different",
    "different account",
    "add account",
    "guest",
    "andere konto verwenden",
    "anderes konto",
    "compte d’invité",
)

# Hints: env `MICROSOFT_ACCOUNT_HINT` or `M365_ACCOUNT_TILE_SUBSTRING` — substring of email/name on the tile.


def _account_hint_from_env() -> str:
    return (
        (os.environ.get("MICROSOFT_ACCOUNT_HINT") or os.environ.get("M365_ACCOUNT_TILE_SUBSTRING") or "").strip().lower()
    )


def _url_suggests_account_picker(url: str) -> bool:
    u = (url or "").lower()
    if "select_account" in u:
        return True
    try:
        qs = parse_qs(urlparse(url).query)
        for p in qs.get("prompt", ()):
            if p.lower() == "select_account":
                return True
    except Exception:
        pass
    return False


def _body_suggests_account_picker(body: str) -> bool:
    return any(
        x in body
        for x in (
            "pick an account",
            "choose an account",
            "select an account",
            "which account do you want",
            "wählen sie ein konto",
            "konto auswählen",
            "choisir un compte",
        )
    )


def _is_login_host(url: str) -> bool:
    h = (urlparse(url).hostname or "").lower()
    return any(
        x in h
        for x in (
            "login.microsoftonline.com",
            "login.microsoft.com",
            "login.live.com",
        )
    )


def _tile_visible_text(el) -> str:
    try:
        return (el.text or "").strip().lower()
    except StaleElementReferenceException:
        return ""


def _is_skippable_account_tile(text: str) -> bool:
    t = text.strip().lower()
    if len(t) < 3:
        return True
    return any(p in t for p in _SKIP_ACCOUNT_TILE_PHRASES)


def _gather_account_tiles(driver: "WebDriver") -> list:
    """Visible clickable tiles that look like saved accounts (not “Use another account”)."""
    candidates: list[tuple[object, str]] = []
    seen_ids: set[int] = set()

    css_groups = (
        '[role="listbox"] [role="option"]',
        '[role="list"] [role="listitem"]',
        "div[role=button][data-test-id]",
    )
    for css in css_groups:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, css):
                try:
                    if not el.is_displayed():
                        continue
                except StaleElementReferenceException:
                    continue
                txt = _tile_visible_text(el)
                if _is_skippable_account_tile(txt):
                    continue
                eid = id(el)
                if eid in seen_ids:
                    continue
                if "@" not in txt and len(txt) < 6:
                    continue
                seen_ids.add(eid)
                candidates.append((el, txt))
        except Exception:
            continue

    xpaths = (
        '//div[@role="listbox"]//div[@role="option"]',
        '//div[@role="button"][.//text()[contains(.,"@")]]',
        '//button[.//text()[contains(.,"@")]]',
        '//a[.//text()[contains(.,"@")]]',
    )
    for xp in xpaths:
        try:
            for el in driver.find_elements(By.XPATH, xp):
                try:
                    if not el.is_displayed():
                        continue
                except StaleElementReferenceException:
                    continue
                txt = _tile_visible_text(el)
                if _is_skippable_account_tile(txt):
                    continue
                eid = id(el)
                if eid in seen_ids:
                    continue
                if "@" not in txt and len(txt) < 6:
                    continue
                seen_ids.add(eid)
                candidates.append((el, txt))
        except Exception:
            continue

    return candidates


def try_pick_microsoft_account(driver: "WebDriver", *, pause_after_s: float) -> int:
    """
    On “Pick an account”, click one saved account tile.

    Prefer a tile matching :envvar:`MICROSOFT_ACCOUNT_HINT` / :envvar:`M365_ACCOUNT_TILE_SUBSTRING`
    (substring of visible email or label), else the first plausible tile.
    """
    pause_after_s = max(0.35, pause_after_s)
    url = driver.current_url or ""
    if not _is_login_host(url):
        return 0
    if _password_field_visible(driver):
        return 0

    body = _safe_body_text(driver)
    url_pick = _url_suggests_account_picker(url)
    body_pick = _body_suggests_account_picker(body)
    tiles = _gather_account_tiles(driver)
    if not tiles:
        return 0

    heuristic_pick = False
    if not url_pick and not body_pick:
        if "login.microsoftonline.com" not in url.lower():
            return 0
        if len(tiles) < 1:
            return 0
        heuristic_pick = True

    hint = _account_hint_from_env()
    chosen: object | None = None
    if hint:
        for el, txt in tiles:
            if hint in txt:
                chosen = el
                break
        if chosen is None:
            return 0
    else:
        chosen = tiles[0][0]

    cid = id(chosen)
    chosen_txt = ""
    for el, txt in tiles:
        if id(el) == cid:
            chosen_txt = txt
            break

    if heuristic_pick and "@" not in chosen_txt and not hint:
        return 0

    if _click_element(driver, chosen):
        time.sleep(pause_after_s)
        return 1
    return 0


def _click_element(driver: "WebDriver", el) -> bool:
    try:
        el.click()
        return True
    except ElementClickInterceptedException:
        try:
            driver.execute_script("arguments[0].click();", el)
            return True
        except Exception:
            return False
    except StaleElementReferenceException:
        return False


def try_advance_microsoft_sso_interstitials(driver: "WebDriver", *, pause_after_s: float = 1.0) -> int:
    """
    Perform at most **one** safe UI action (one click) and return ``1`` if so, else ``0``.

    Call in a loop: the page may transition through several hops (KMSI, consent, …).
    """
    pause_after_s = max(0.35, pause_after_s)
    src = ""
    try:
        src = (driver.page_source or "").lower()
    except Exception:
        pass
    body = _safe_body_text(driver)

    # --- Pick an account (saved account tiles) ---
    if try_pick_microsoft_account(driver, pause_after_s=pause_after_s):
        return 1

    # --- Keep me signed in / KMSI ---
    kmsi_hint = (
        "stay signed in" in body
        or "angemeldet bleiben" in body
        or "reduce the number of times you are asked to sign in" in body
        or "reis de aanmeldingen" in body  # nl hint
        or "formkmsi" in src
        or "kmsiinter" in src
    )
    if kmsi_hint:
        for sel in ("#idSIButton9", 'input[type="submit"]#idSIButton9'):
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed() and el.is_enabled():
                    if _click_element(driver, el):
                        time.sleep(pause_after_s)
                        return 1
            except (NoSuchElementException, StaleElementReferenceException):
                continue

    # --- OAuth / consent Accept ---
    if not _password_field_visible(driver):
        for xp in (
            '//button[contains(., "Accept")]',
            '//span[contains(., "Accept")]/ancestor::button[1]',
            '//input[@type="submit" and (@value="Accept" or @value="accept")]',
            '//button[contains(., "Zustimmen")]',
            '//button[contains(., "Accepter")]',
            '//input[@type="submit" and contains(@value,"Accept")]',
        ):
            try:
                for el in driver.find_elements(By.XPATH, xp):
                    if not el.is_displayed() or not el.is_enabled():
                        continue
                    if _click_element(driver, el):
                        time.sleep(pause_after_s)
                        return 1
            except Exception:
                continue

    # --- Next when email / login name is already filled (no password field yet) ---
    if not _password_field_visible(driver):
        email_val = ""
        try:
            for sel in ('input[name="loginfmt"]', "input[type=email]", "#i0116"):
                for inp in driver.find_elements(By.CSS_SELECTOR, sel):
                    if not inp.is_displayed():
                        continue
                    email_val = (inp.get_attribute("value") or "").strip()
                    if email_val:
                        break
                if email_val:
                    break
        except Exception:
            pass
        if email_val:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, "#idSIButton9")
                if btn.is_displayed() and btn.is_enabled():
                    label = (btn.get_attribute("value") or btn.text or "").strip().lower()
                    aria = (btn.get_attribute("aria-label") or "").strip().lower()
                    combined = f"{label} {aria}"
                    if "sign in" in combined or "anmelden" in combined or "einloggen" in combined:
                        return 0
                    if "next" in combined or "weiter" in combined or "siguiente" in combined:
                        if _click_element(driver, btn):
                            time.sleep(pause_after_s)
                            return 1
            except (NoSuchElementException, StaleElementReferenceException):
                pass

    return 0


def drain_microsoft_sso_interstitials(driver: "WebDriver", *, pause_after_s: float, max_clicks: int = 8) -> int:
    """Apply :func:`try_advance_microsoft_sso_interstitials` until it stops advancing or cap reached."""
    total = 0
    for _ in range(max(1, max_clicks)):
        n = try_advance_microsoft_sso_interstitials(driver, pause_after_s=pause_after_s)
        if n == 0:
            break
        total += n
    return total
