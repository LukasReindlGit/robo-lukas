"""URL safety guards for the Jira module."""

from __future__ import annotations

from urllib.parse import urlparse

# Paths that indicate we are still in an Atlassian or third-party auth flow
# (not yet on the main Jira app).
_AUTH_PATH_SIGNALS: tuple[str, ...] = (
    "/login",
    "/signin",
    "/sign-in",
    "/auth",
    "/oauth",
    "/sso",
    "/saml",
)


def is_atlassian_login_url(url: str) -> bool:
    """Return True if the URL is Atlassian's own login / auth page."""
    host = (urlparse(url).hostname or "").lower()
    return any(
        x in host
        for x in (
            "id.atlassian.com",
            "auth.atlassian.com",
        )
    )


def is_microsoft_login_url(url: str) -> bool:
    """Return True if the URL is a Microsoft login / SSO interstitial."""
    host = (urlparse(url).hostname or "").lower()
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


def is_likely_login_url(url: str) -> bool:
    """Return True if the URL is any known login/SSO interstitial."""
    return is_atlassian_login_url(url) or is_microsoft_login_url(url)


def is_jira_app_url(url: str, base_host: str) -> bool:
    """
    Return True if the URL looks like the user is logged into the Jira application.

    We check:
    - The netloc matches the configured Jira base host.
    - The path does not suggest we're still in an auth flow.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        current_host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()

        # Must be on the configured Jira host (exact or subdomain match)
        base = base_host.lower().lstrip(".")
        if current_host != base and not current_host.endswith("." + base):
            return False

        # Reject if path contains known auth segments
        for signal in _AUTH_PATH_SIGNALS:
            if signal in path:
                return False

        return True
    except Exception:
        return False


def normalize_jira_base_url(base: str) -> str:
    """Strip trailing slash for consistent URL joining."""
    return base.rstrip("/")
