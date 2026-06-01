# modules/jira — Read-only Jira access

Reads Jira issues via **browser session + REST API**.  No API token is required.

## How it works

1. Opens Chrome with the same persistent profile used by `robo-outlook` / `robo-todo`.
2. Navigates to the Jira instance URL.
3. Handles SSO login automatically where safe:
   - **Microsoft SSO**: auto-advances KMSI ("Stay signed in?"), account picker, consent — password and MFA remain manual.
   - **Atlassian login page** (`id.atlassian.com`): user clicks their SSO provider manually (Google, Microsoft, etc.).
4. Extracts session cookies from the browser.
5. Uses those cookies to call the **Jira REST API v3** (`/rest/api/3/…`) — no separate API token needed.

This approach works on **any Jira Cloud instance** (`*.atlassian.net`) including customer environments
where you cannot generate a personal API token.

## Prerequisites

- Chrome / Chromium installed.
- `pip install -e .` run from the repo root.
- `M365_BROWSER_USER_DATA_DIR` set to your persistent Chrome profile directory.

## Configuration

Add to `.env` (copy from `.env.example`):

```env
# Required: change per engagement
JIRA_BASE_URL=https://your-org.atlassian.net

# Shared Chrome profile (same as Outlook / To Do — reuses existing login)
M365_BROWSER_USER_DATA_DIR=C:\Users\You\AppData\Local\robo-lukas\chrome-profile
```

## One-time login

```powershell
robo-jira wait-login --jira-url https://your-org.atlassian.net
# → opens Chrome, prints a prompt, waits for you to click through SSO
# → once logged in, verifies the REST API and prints your username
```

With a persistent profile the browser may already be logged in and return immediately.

If `robo-jira` is not on your PATH (common on Windows), use:

```powershell
py -3 -m robo_lukas.jira.cli wait-login --jira-url https://your-org.atlassian.net
```

## CLI reference

```text
robo-jira wait-login            Open browser, wait for Jira SSO, verify REST API
robo-jira status                Print current user and connection info
robo-jira list-mine             List open issues assigned to you (default: 25)
robo-jira list-sprint           List issues in the current open sprint (yours)
robo-jira show PROJ-123         Show a specific issue with description + comments
robo-jira search "JQL"          Run a JQL query
robo-jira export-tree PROJ-123  Export root issue + direct subtasks to JSON files
```

### Common flags (available on every subcommand)

| Flag | Env var | Default | Description |
|---|---|---|---|
| `--jira-url URL` | `JIRA_BASE_URL` | — | Jira instance URL |
| `--browser-profile DIR` | `M365_BROWSER_USER_DATA_DIR` | — | Chrome user-data-dir |
| `--login-timeout SECS` | `JIRA_LOGIN_TIMEOUT` | 600 | Max seconds to wait for login |
| `--keep-browser` | — | off | Leave Chrome open after command |
| `--format json\|text` | — | `text` | Output format |

### Examples

```powershell
# List my open tickets as JSON (pipe into LLM context)
robo-jira list-mine --format json

# List sprint board
robo-jira list-sprint --format json

# Show a customer ticket with all comments
robo-jira show ECOM-808 --format json

# Search with JQL
robo-jira search "project = ECOM AND status = 'In Progress' AND assignee = currentUser()"

# Export one root issue + all direct subtasks to a folder
robo-jira export-tree ECOM-808 --out-dir hagetest --format json

# Switch to a different customer's Jira on the fly
robo-jira list-mine --jira-url https://other-customer.atlassian.net --format json
```

## Export issue trees

Use `export-tree` when you need a local folder with one parent issue, all direct subtasks,
and all comments for each item.

```powershell
# Parent + subtasks + comments → ./hagetest
robo-jira export-tree PHHPC-103 --jira-url https://hagebau.atlassian.net --out-dir hagetest --format json
```

Output files:

- `hagetest/PHHPC-103.json` (root issue)
- `hagetest/<SUBTASK-KEY>.json` (one file per subtask)
- `hagetest/manifest.json` (contains exported keys/files + metadata)

Use `--no-comments` if you only want issue fields and descriptions.

## Switching between customers

Each customer has their own `*.atlassian.net` subdomain. You can either:

1. **Set `JIRA_BASE_URL` in `.env`** for your primary project and override with `--jira-url` ad hoc.
2. Keep multiple `.env` files (`.env.ecom`, `.env.shopware`) and load with `dotenv .env.ecom robo-jira list-mine`.

A persistent Chrome profile will remember session cookies per domain, so you may need to log in once per customer org.

## Output format

All commands support `--format json` (default: `text`).  The JSON shape for an issue:

```json
{
  "key": "ECOM-808",
  "summary": "…",
  "status": "In Progress",
  "issue_type": "Story",
  "priority": "Medium",
  "assignee": "Lukas Reindl",
  "reporter": "Jane Doe",
  "sprint": "Sprint 12",
  "labels": [],
  "created": "2025-03-01T10:00:00.000+0100",
  "updated": "2025-05-20T14:30:00.000+0200",
  "url": "https://c-hafner.atlassian.net/browse/ECOM-808",
  "description_text": "As a user I want…",
  "comments": [
    {
      "author": "Jane Doe",
      "created": "2025-05-01T…",
      "updated": "2025-05-01T…",
      "body_text": "Updated the acceptance criteria…"
    }
  ]
}
```

## Failure modes

| Error | Cause | Fix |
|---|---|---|
| `TimeoutError: Timed out after 600s` | Login not completed in time | Increase `--login-timeout`; check for MFA prompts |
| `HTTP 401` | Session expired | Re-run `wait-login` to refresh cookies |
| `HTTP 400` for `list-sprint` | Project has no Agile/sprint board | Use `list-mine` instead |
| `HTTP 403` | Permission denied on that project | Use an account that has read access |
| `No Chrome/Chromium found` | Chrome not in PATH | Install Chrome or set `CHROME_BINARY` |
| `SessionNotCreatedException` | Profile lock or ChromeDriver version mismatch | See `modules/outlook/README.md` for debug steps |

### Windows launcher / PATH troubleshooting

- `robo-jira: command not found`: scripts directory is not on PATH. Use `py -3 -m robo_lukas.jira.cli ...` or add `Python\\Scripts` to PATH.
- `python3` opens Microsoft Store / not found: this alias is often disabled on Windows; use `py -3` instead.
- `ModuleNotFoundError: No module named 'requests'`: run `py -3 -m pip install -e .` from repo root.

## Read-only guarantee

`robo-jira` only makes **HTTP GET** requests to the Jira REST API.  No issues, comments,
or attachments are created, modified, or deleted.  The `X-Atlassian-Token: no-check` header
is set to bypass the browser CSRF check for read operations — it does not enable writes.
