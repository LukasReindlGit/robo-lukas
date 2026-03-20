from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from robo_lukas.microsoft_sso import (
    drain_microsoft_sso_interstitials,
    wait_document_interactive,
    wait_document_ready,
)
from robo_lukas.ms_todo.investigation import InvestigationReporter
from robo_lukas.ms_todo.reader import (
    dismiss_onboarding_if_present,
    task_list_resolved_for_export,
    wait_until_todo_ready,
)
from robo_lukas.ms_todo.safety import normalize_tasks_base_url

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

    from robo_lukas.ms_todo.models import TodoReaderConfig


def _is_tasks_app_url(url: str) -> bool:
    u = (url or "").lower()
    if "to-do.live.com" in u and "/tasks" in u:
        return True
    if "to-do.live.com/tasks" in u:
        return True
    if "to-do.live.com" in u:
        return True
    # Work / M365 often redirects here instead of to-do.live.com
    if "to-do.office.com" in u and "/tasks" in u:
        return True
    if "to-do.office.com/tasks" in u:
        return True
    if "to-do.office.com" in u:
        return True
    if "tasks.office.com" in u:
        return True
    if "microsoft365.com" in u and "todo" in u:
        return True
    return False


def is_likely_login_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    host = host.lower()
    return any(
        x in host
        for x in (
            "login.microsoftonline.com",
            "login.microsoft.com",
            "login.live.com",
            "account.live.com",
            "account.microsoft.com",
        )
    )


def wait_for_todo_session(
    driver: "WebDriver",
    cfg: "TodoReaderConfig",
    *,
    timeout_s: float,
    investigate: InvestigationReporter | None = None,
    out_stream=sys.stderr,
) -> None:
    """
    Block until Microsoft To Do **UI** is usable. Waits for document load, advances SSO
    pages when safe, dismisses onboarding, then requires sidebar/task shell — not URL alone.
    """
    deadline = time.monotonic() + timeout_s
    base = normalize_tasks_base_url(cfg.tasks_base_url)
    if investigate:
        investigate.phase("todo_session_start", driver, snapshot=True)
    driver.get(base)
    time.sleep(min(0.12, max(0.05, float(cfg.post_nav_sleep_s) * 0.22)))
    wait_document_interactive(driver, timeout_s=0.55, poll_s=0.03)
    if investigate:
        investigate.phase("todo_session_after_initial_get", driver, snapshot=True)

    pause = max(float(cfg.post_nav_sleep_s), 0.35)
    last_login_log = ""
    page_cap = float(getattr(cfg, "max_page_wait_s", 4.0))
    loop_i = 0
    login_snap_counter = 0

    while time.monotonic() < deadline:
        loop_i += 1
        url = driver.current_url or ""
        if investigate:
            investigate.phase(
                f"todo_session_loop_{loop_i}",
                driver,
                snapshot=(loop_i == 1 or loop_i % 4 == 0),
            )

        if is_likely_login_url(url):
            wait_document_ready(driver, timeout_s=min(5.0, max(2.0, timeout_s * 0.02)))
        elif _is_tasks_app_url(url):
            wait_document_interactive(driver, timeout_s=0.38, poll_s=0.03)
        else:
            wait_document_interactive(driver, timeout_s=0.45, poll_s=0.03)

        if is_likely_login_url(url):
            login_snap_counter += 1
            if investigate:
                investigate.phase(
                    "todo_session_login_host",
                    driver,
                    snapshot=(login_snap_counter == 1 or login_snap_counter % 6 == 0),
                )
            advanced = drain_microsoft_sso_interstitials(
                driver, pause_after_s=pause, max_clicks=10
            )
            if advanced > 0 and investigate:
                investigate.phase(
                    "todo_session_sso_advanced",
                    driver,
                    snapshot=True,
                )
            if advanced > 0:
                continue
            if url != last_login_log:
                last_login_log = url
                print(
                    "To Do reader: Microsoft sign-in — auto-advancing KMSI/consent where "
                    "possible; complete password / MFA in the browser if needed.\n"
                    f"  URL: {url}\n"
                    f"  Waiting up to {timeout_s:.0f}s…",
                    file=out_stream,
                )
            time.sleep(min(float(cfg.login_poll_s) + 0.12, 1.8))
            continue

        if not _is_tasks_app_url(url):
            if investigate:
                investigate.phase("todo_session_not_tasks_app", driver, snapshot=(loop_i % 5 == 0))
            time.sleep(float(cfg.login_poll_s))
            continue

        login_snap_counter = 0
        # Hard cap per task URL: onboarding + wait for task pane, then succeed or error (no endless spin).
        t_page = time.monotonic()
        n_dismiss = dismiss_onboarding_if_present(driver, cfg)
        if investigate and n_dismiss:
            investigate.phase(
                "todo_session_onboarding_dismiss",
                driver,
                snapshot=True,
            )

        wait_deadline = min(deadline, t_page + page_cap)
        if investigate:
            investigate.phase("todo_session_before_wait_until_ready", driver, snapshot=True)
        wait_until_todo_ready(
            driver,
            cfg,
            deadline_monotonic=wait_deadline,
            investigate=investigate,
        )
        if not task_list_resolved_for_export(driver):
            msg = (
                f"To Do: task list UI not ready within {page_cap:.0f}s on this page "
                f"(max MS_TODO_PAGE_WAIT_MAX_S={page_cap:.0f}). "
                f"URL: {driver.current_url!r}. "
                "Use --investigate DIR for HTML/JSON, or dismiss overlays manually."
            )
            if investigate:
                investigate.phase("todo_session_page_clamp_fail", driver, snapshot=True)
            raise TimeoutError(msg)

        wait_document_interactive(driver, timeout_s=0.15, poll_s=0.02)
        time.sleep(min(0.03, float(cfg.shell_settle_sleep_s) * 0.04))
        if investigate:
            investigate.phase("todo_session_done", driver, snapshot=True)
        return

    if investigate:
        investigate.phase("todo_session_timeout", driver, snapshot=True)
    raise TimeoutError(
        f"Timed out after {timeout_s:.0f}s waiting for Microsoft To Do UI "
        f"(shell not ready). Last URL: {driver.current_url!r}"
    )
