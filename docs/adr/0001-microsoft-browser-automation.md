# ADR 0001: Microsoft access without Graph API

## Status

Accepted

## Context

Microsoft 365 APIs (e.g. Microsoft Graph) are not usable in this environment (policy, consent, or tenant restrictions).

Outlook and Microsoft To Do still need automation.

## Decision

Implement **browser-based automation** (Selenium WebDriver or Playwright) against the official web clients:

- Outlook: `outlook.office.com` / org-specific OWA URLs as applicable.
- To Do: `to-do.live.com` (or the URL your tenant redirects to).

Use a **dedicated browser user-data directory** so interactive login + MFA can be done once per session or periodically, rather than embedding credentials in the repo.

## Consequences

- **Fragile UI**: DOM changes break selectors; plan for maintenance and small smoke tests.
- **MFA / CAPTCHA**: May require human-in-the-loop; headless mode may be blocked.
- **Compliance**: Same data-handling rules as reading mail/tasks manually; avoid storing full bodies in long-lived logs without need.
- **Performance**: Slower than APIs; add explicit waits and conservative rate behavior.

## Alternatives considered

- **IMAP / EWS**: Often disabled or blocked in enterprise tenants.
- **Desktop UI automation**: Possible future; heavier and more brittle across OS updates.
