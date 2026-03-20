"""
Guards to keep Outlook automation read-oriented.

Navigation is restricted to mail-reading surfaces. This does not prove absence of
server side-effects (opening a message in OWA may still mark it read).
"""

from __future__ import annotations

from urllib.parse import urlparse

# Paths/fragments that often correspond to compose, send, or account mutation flows.
_FORBIDDEN_PATH_FRAGMENTS: tuple[str, ...] = (
    "compose",
    "newemail",
    "deeplink/compose",
    "/options/",
    "/settings/",
    "messagecompose",
    "popout/compose",
)

# If ``/mail/search`` appears, still reading.


def assert_readonly_navigation_url(url: str) -> None:
    """
    Raise ValueError if ``url`` looks like a compose/settings surface we refuse to open.

    Call this before ``driver.get(url)`` for every navigation this tool performs.
    """
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    full_lower = url.lower()

    for frag in _FORBIDDEN_PATH_FRAGMENTS:
        if frag in full_lower:
            raise ValueError(
                f"Read-only tool: refusing URL containing blocked fragment {frag!r}: {url}"
            )

    if "/mail/" in path or path.rstrip("/").endswith("/mail"):
        return
    if "/owa/" in path or path.startswith("/owa"):
        return

    raise ValueError(
        "Read-only tool: URL path must look like Outlook mail or OWA reading UI "
        f"(expected /mail/ or /owa/): {url}"
    )


def normalize_mail_base_url(base: str) -> str:
    """Trim trailing slash for consistent joins."""
    return base.rstrip("/")


def join_mail_path(base: str, *segments: str) -> str:
    base_n = normalize_mail_base_url(base)
    rest = "/".join(s.strip("/") for s in segments if s)
    return f"{base_n}/{rest}" if rest else base_n


_WELL_KNOWN_FOLDER_SLUGS: dict[str, str] = {
    "inbox": "inbox",
    "jira": "jira",
    "sent": "sentitems",
    "sentitems": "sentitems",
    "drafts": "drafts",
    "deleted": "deleteditems",
    "deleteditems": "deleteditems",
    "trash": "deleteditems",
    "archive": "archive",
    "junk": "junkemail",
    "junkemail": "junkemail",
    "outbox": "outbox",
}


def well_known_folder_slug(name: str) -> str | None:
    """Return OWA path segment for a friendly folder name, or None if unknown."""
    key = name.strip().lower().replace(" ", "")
    return _WELL_KNOWN_FOLDER_SLUGS.get(key)


def build_folder_url(mail_base_url: str, folder: str) -> str:
    """
    Build a mail folder URL from a friendly name or raw OWA segment.

    Examples: ``inbox`` -> ``.../mail/inbox``, ``sent`` -> ``.../mail/sentitems``.
    If ``folder`` is a full http(s) URL, it is validated and returned as-is.
    """
    base = normalize_mail_base_url(mail_base_url)
    folder = folder.strip()
    if folder.lower().startswith("http://") or folder.lower().startswith("https://"):
        assert_readonly_navigation_url(folder)
        return folder
    if folder.startswith("/"):
        parsed_base = urlparse(base)
        url = f"{parsed_base.scheme}://{parsed_base.netloc}{folder}"
        assert_readonly_navigation_url(url)
        return url

    slug = well_known_folder_slug(folder)
    segment = slug if slug is not None else folder.strip("/")
    url = f"{base}/mail/{segment}"
    assert_readonly_navigation_url(url)
    return url


# Folders this toolchain supports when using ``--folder`` (extend here as needed).
ROBO_MAIL_FOLDERS: frozenset[str] = frozenset(("inbox", "jira"))


def normalize_robo_mail_folder(name: str) -> str:
    """
    Validate and normalize ``--folder`` to an OWA segment (e.g. ``inbox``, ``jira``).

    Raises:
        ValueError: if the folder is not one of the supported names.
    """
    key = name.strip().lower().replace(" ", "")
    if key not in ROBO_MAIL_FOLDERS:
        allowed = ", ".join(sorted(ROBO_MAIL_FOLDERS))
        raise ValueError(f"Unsupported folder {name!r}. Use one of: {allowed}.")
    slug = well_known_folder_slug(key)
    return slug if slug is not None else key


def is_likely_login_url(url: str) -> bool:
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
