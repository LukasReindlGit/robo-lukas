"""
Browser session management for the Jira module.

Login flow:
  1. Navigate to base_url (e.g. https://c-hafner.atlassian.net).
  2. Atlassian redirects to id.atlassian.com/login → user picks SSO provider.
  3. If Microsoft SSO: auto-advance safe steps (KMSI, consent, account picker).
  4. Once back on base_url without auth-path signals → session is active.
  5. Extract cookies and hand them to JiraClient for REST API calls.
"""

from __future__ import annotations

import sys
import time
from urllib.parse import urlparse
from typing import TYPE_CHECKING

from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

from robo_lukas.microsoft_sso import drain_microsoft_sso_interstitials, wait_document_ready
from robo_lukas.jira.models import JiraConfig
from robo_lukas.jira.safety import (
    is_atlassian_login_url,
    is_jira_app_url,
    is_microsoft_login_url,
)

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver


def wait_for_jira_login(
    driver: "WebDriver",
    cfg: JiraConfig,
    *,
    timeout_s: float,
    out_stream=sys.stderr,
) -> None:
    """
    Navigate to the Jira instance and block until the user is logged in.

    - Microsoft SSO pages: safe steps are auto-advanced (KMSI, account picker, consent).
    - Atlassian login page: user must click their SSO provider manually.
    - Password / MFA screens: always manual.

    Raises TimeoutError if login is not completed within ``timeout_s`` seconds.
    """
    deadline = time.monotonic() + timeout_s
    base_host = urlparse(cfg.base_url).netloc.lower()

    driver.get(cfg.base_url)
    time.sleep(cfg.post_nav_sleep_s)
    wait_document_ready(driver, timeout_s=min(20.0, max(5.0, timeout_s * 0.1)))

    pause = max(float(cfg.post_nav_sleep_s), 0.95)
    last_logged_url = ""
    stall_count = 0

    while time.monotonic() < deadline:
        try:
            url = driver.current_url or ""
        except (InvalidSessionIdException, WebDriverException) as exc:
            raise TimeoutError(
                "Browser session ended while waiting for Jira login. "
                "Keep the login window open and re-run the command."
            ) from exc

        wait_document_ready(driver, timeout_s=12.0)

        # ── Done: on the Jira app, not in an auth flow ────────────────────────
        if is_jira_app_url(url, base_host):
            time.sleep(min(0.5, pause * 0.3))
            return

        # ── Microsoft SSO (login.microsoftonline.com / login.live.com) ────────
        if is_microsoft_login_url(url):
            advanced = drain_microsoft_sso_interstitials(driver, pause_after_s=pause, max_clicks=10)
            if advanced > 0:
                stall_count = 0
                continue
            stall_count += 1
            if url != last_logged_url:
                last_logged_url = url
                print(
                    "Jira: Microsoft SSO page — auto-advancing safe steps; "
                    "complete password / MFA in the browser if needed.\n"
                    f"  URL: {url}\n"
                    f"  Waiting up to {timeout_s:.0f}s…",
                    file=out_stream,
                )
            sleep = min(float(cfg.login_poll_s) + min(stall_count * 0.12, 2.5), 4.0)
            time.sleep(sleep)
            continue

        # ── Atlassian login page (id.atlassian.com) ───────────────────────────
        if is_atlassian_login_url(url):
            stall_count += 1
            if url != last_logged_url:
                last_logged_url = url
                print(
                    "Jira: Atlassian login page — please sign in in the browser window.\n"
                    "  Tip: if your org uses Microsoft / Google SSO, click that button.\n"
                    f"  URL: {url}\n"
                    f"  Waiting up to {timeout_s:.0f}s…",
                    file=out_stream,
                )
            time.sleep(float(cfg.login_poll_s))
            continue

        # ── Unknown / intermediate page — keep waiting ────────────────────────
        time.sleep(float(cfg.login_poll_s))

    raise TimeoutError(
        f"Timed out after {timeout_s:.0f}s waiting for Jira login at {cfg.base_url!r}. "
        f"Last URL: {driver.current_url!r}"
    )


def extract_cookies_for_requests(driver: "WebDriver") -> dict[str, str]:
    """
    Return all current browser cookies as a ``{name: value}`` dict.

    Suitable for injecting into a ``requests.Session`` to authenticate REST API calls
    without a separate API token.
    """
    cookies: dict[str, str] = {}
    try:
        for cookie in driver.get_cookies():
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            if name:
                cookies[name] = value
    except Exception:
        pass
    return cookies
