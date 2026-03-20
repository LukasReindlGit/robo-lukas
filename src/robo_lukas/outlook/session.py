from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from robo_lukas.microsoft_sso import (
    drain_microsoft_sso_interstitials,
    wait_document_ready,
)
from robo_lukas.outlook.models import OutlookReaderConfig
from robo_lukas.outlook.safety import is_likely_login_url, normalize_mail_base_url

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver


def wait_for_manual_sso(
    driver: WebDriver,
    cfg: OutlookReaderConfig,
    *,
    timeout_s: float,
    out_stream=sys.stderr,
) -> None:
    """
    Block until the session reaches Outlook mail (URL contains ``/mail/``) or timeout.

    While on Microsoft login / SSO hosts, tries safe auto-advance (KMSI **Yes**, consent
    **Accept**, **Next** when email is pre-filled). Password entry and MFA still require you.
    """
    deadline = time.monotonic() + timeout_s
    base = normalize_mail_base_url(cfg.mail_base_url)
    driver.get(base)
    time.sleep(cfg.post_nav_sleep_s)
    wait_document_ready(driver, timeout_s=min(20.0, max(5.0, timeout_s * 0.1)))

    pause = max(float(cfg.post_nav_sleep_s), 0.95)
    last_login_log_url = ""
    stall_login = 0
    while time.monotonic() < deadline:
        url = driver.current_url or ""
        path = ""
        try:
            path = urlparse(url).path or ""
        except Exception:
            pass

        wait_document_ready(driver, timeout_s=12.0)

        if "/mail/" in path or path.rstrip("/").endswith("/mail"):
            time.sleep(min(0.5, pause * 0.3))
            return

        if is_likely_login_url(url):
            advanced = drain_microsoft_sso_interstitials(
                driver, pause_after_s=pause, max_clicks=10
            )
            if advanced > 0:
                stall_login = 0
                continue
            stall_login += 1
            if url != last_login_log_url:
                last_login_log_url = url
                print(
                    "Outlook reader: SSO / login page — advancing what we can; "
                    "complete password / MFA in the browser if needed.\n"
                    f"  Current URL: {url}\n"
                    f"  Waiting up to {timeout_s:.0f}s…",
                    file=out_stream,
                )
            # Back off slightly when nothing to auto-click (user typing, MFA, …)
            sleep = min(
                float(cfg.login_poll_s) + min(stall_login * 0.12, 2.5),
                4.0,
            )
            time.sleep(sleep)
            continue

        time.sleep(float(cfg.login_poll_s))

    raise TimeoutError(
        f"Timed out after {timeout_s:.0f}s waiting for Outlook mail UI "
        f"(expected URL path to contain /mail/). Last URL: {driver.current_url!r}"
    )
