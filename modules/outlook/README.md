# Outlook on the web (read-only CLI)

Automates **Outlook Web App (OWA)** in Chrome via Selenium: list mail, search, export JSON, open a message for body text. **Read-only by design** — no send, compose, delete, or settings/compose URLs (`safety.py` enforces allowed navigation).

**Package path:** `src/robo_lukas/outlook/`  
**Entry points:** `python -m robo_lukas.outlook …` or `robo-outlook …` (after `pip install -e .`)

---

## Setup (short)

| Requirement | Notes |
|-------------|--------|
| Python | 3.11+ |
| Chrome | Installed; Selenium Manager fetches a matching ChromeDriver unless IT blocks it |
| Profile dir | **Dedicated** user-data dir — set `M365_BROWSER_USER_DATA_DIR` (do not reuse your daily Chrome profile) |

From repo root:

```bash
pip install -e .
```

Copy `.env.example` → `.env`. Minimum:

- `M365_BROWSER_USER_DATA_DIR` — **required**
- `OUTLOOK_WEB_URL` — optional; default `https://outlook.office.com/mail/`

Further variables (WSL bridge, timings, extra Chrome args) are documented in the root `.env.example`.

**Windows:** see [`docs/WINDOWS.md`](../../docs/WINDOWS.md) (venv Python path, `scripts/run-outlook.ps1` / `run-outlook.sh`).

**WSL + Windows Chrome:** remote ChromeDriver — `scripts/chromedriver-for-wsl.ps1`, `CHROMEDRIVER_REMOTE_URL`, optional `python -m robo_lukas.outlook with-bridge …`.

If sign-in works but OWA says you cannot access the resource, that is usually **Conditional Access**, not this tool — your admin must allow OWA for that browser/device/network.

---

## Invoking the CLI

- Put **global options after the subcommand** (e.g. `wait-login --keep-browser`, not ` --keep-browser wait-login`).
- `--format` is `text` or `json` where supported.

```bash
python -m robo_lukas.outlook <subcommand> [subcommand-args…] [shared-options…]
```

---

## Shared options (all subcommands)

These are available on **every** subcommand, **after** the subcommand name:

| Option | Meaning |
|--------|--------|
| `--browser-profile` | Chrome `--user-data-dir` (overrides `M365_BROWSER_USER_DATA_DIR`) |
| `--chrome-profile-directory` | Profile folder inside user-data-dir (e.g. `Default`) |
| `--chrome-binary` | Path to `chrome` / `chrome.exe` |
| `--mail-url` | Mail base URL (overrides `OUTLOOK_WEB_URL`) |
| `--headless` | Headless Chrome (often breaks SSO/MFA) |
| `--keep-browser` | Do not close the browser when the command exits |
| `--explicit-wait` | Max seconds to wait for list/reading-pane (env: `OUTLOOK_EXPLICIT_WAIT`, default 25) |
| `--remote-url` | ChromeDriver URL for WSL → Windows driver (`CHROMEDRIVER_REMOTE_URL`) |

**Environment timing tweaks** (optional): `OUTLOOK_POST_NAV_SLEEP`, `OUTLOOK_LOGIN_POLL`, `OUTLOOK_LIST_ROW_POLL`, `OUTLOOK_SCROLL_KEY_SLEEP`, `OUTLOOK_SEARCH_EXTRA_SLEEP`, `OUTLOOK_IMPLICIT_WAIT` — see `.env.example`.

---

## Folders and unread filter

### `--folder`

CLI accepts **`inbox`** or **`jira`** only (case-insensitive). Other mailbox folders require extending `ROBO_MAIL_FOLDERS` / `normalize_robo_mail_folder` in `safety.py`.

### `--filter-unread`

Uses the OWA list control **`#mailListFilterMenu`** → **Unread** (menu item radio, `title="Unread"`), then reads the list. Use this instead of—or together with—search queries like `read:no`.

Supported on: **`list`**, **`export`**, **`show`**, **`search`**.

---

## Commands reference

### `status`

Open the configured mail base URL and print current URL/title.

| Option | Default |
|--------|---------|
| `--format` | `text` |

```bash
python -m robo_lukas.outlook status --format json
```

---

### `wait-login`

Open OWA and **block until** the URL path contains `/mail/`.

While on Microsoft login hosts, the tool **auto-advances** safe steps via `microsoft_sso.py`: **Pick an account** (clicks a saved account tile — set **`MICROSOFT_ACCOUNT_HINT`** or **`M365_ACCOUNT_TILE_SUBSTRING`** in `.env` to match one UPN/email), **Stay signed in** (KMSI **Yes**), consent **Accept**, and **Next** when the email field is **already filled**. **Password** and **MFA** still need you in the browser.

| Option | Default |
|--------|---------|
| `--login-timeout` | `600` (seconds) |
| `--format` | `text` |

```bash
python -m robo_lukas.outlook wait-login --login-timeout 600 --keep-browser
```

---

### `folders`

Opens a folder, then **best-effort** scrapes names from the left navigation tree. Results depend on OWA DOM.

| Option | Default |
|--------|---------|
| `--folder` | `inbox` (`inbox`\|`jira`) |
| `--max-items` | `200` |
| `--login-timeout` | `600` |
| `--format` | `text` |

```bash
python -m robo_lukas.outlook folders --folder inbox --format json
```

---

### `list`

Lists messages from the **list pane only** (does not open threads). Minimal server impact.

| Option | Default |
|--------|---------|
| `--folder` | `inbox` |
| `--limit` | `30` |
| `--scroll-rounds` | `4` |
| `--login-timeout` | `600` |
| `--filter-unread` | off |
| `--subject-contains` | — (client-side filter on row text) |
| `--format` | `text` |

```bash
python -m robo_lukas.outlook list --folder jira --filter-unread --limit 20 --format json
```

---

### `show`

Opens one row by **0-based index** and prints preview/body (reading pane). **May mark the message read** on the server.

| Option | Default |
|--------|---------|
| `--folder` | `inbox` |
| `--index` | **required** |
| `--no-body` | off (if set: list row only, no reading pane) |
| `--scroll-rounds` | `8` |
| `--login-timeout` | `600` |
| `--filter-unread` | off (open folder → apply Unread filter → open row) |
| `--format` | `text` |

```bash
python -m robo_lukas.outlook show --folder inbox --filter-unread --index 0 --format json
```

---

### `export`

Writes a **JSON array** of messages to `-o` / `--output`. Optional per-message body fetch.

| Option | Default |
|--------|---------|
| `--folder` | `inbox` |
| `--limit` | `50` |
| `--scroll-rounds` | `6` |
| `-o` / `--output` | **required** path |
| `--with-bodies` | off (opens each row — **slow**, may mark read) |
| `--body-delay` | `0.45` s between body fetches |
| `--login-timeout` | `600` |
| `--filter-unread` | off |
| `--subject-contains` | client-side filter |

```bash
python -m robo_lukas.outlook export --folder jira --filter-unread -o mail.json --limit 100
python -m robo_lukas.outlook export --folder inbox -o with-bodies.json --limit 10 --with-bodies
```

---

### `search`

Opens `--folder`, optionally applies **`--filter-unread`**, optionally types **`query`** into the Outlook search box, then lists result rows. **`query`** may be omitted if `--filter-unread` is set (filter only).

| Argument / option | Notes |
|-------------------|--------|
| `query` | Optional if `--filter-unread`. Example: `read:no` |
| `--folder` | `inbox`\|`jira` — default `inbox` |
| `--limit`, `--scroll-rounds`, `--login-timeout` | As in `list` |
| `--filter-unread` | Filter menu → Unread **before** optional search |
| `--subject-contains` | Extra client-side filter |
| `--show-index N` | After listing, open row `N` and print one message |
| `--no-body` | With `--show-index`: do not load reading pane |
| `--format` | `text` or `json` |

```bash
python -m robo_lukas.outlook search --folder inbox --filter-unread --limit 10 --format json
python -m robo_lukas.outlook search "read:no" --limit 5 --show-index 0 --format json
python -m robo_lukas.outlook search --filter-unread "from:acme" --folder jira --limit 20 --format json
```

**Error:** Neither `query` nor `--filter-unread` → exits with a usage error.

---

### `with-bridge` (WSL helper)

Prefix for any subcommand: starts or reuses **Windows** ChromeDriver when `CHROMEDRIVER_WINDOWS_EXE` (or an existing remote URL) is configured.

```bash
python -m robo_lukas.outlook with-bridge list --folder inbox --limit 10 --format json
python -m robo_lukas.outlook with-bridge --help
```

---

## Behaviour and limitations

- **`list`** — Tries to avoid opening threads; reads visible row text only.
- **`show`**, **`export --with-bodies`**, **`search --show-index`** (without `--no-body`) — May change **read** state on the server.
- **OWA changes often** — if lists are empty but mail is visible, update `selectors.py`.
- **IT policy** — blocked ChromeDriver downloads, Conditional Access, or non-compliant devices are outside what this module can fix.

---

## Possible future improvements

- **More folders / routing** — Map tenant-specific OWA segments (e.g. exact `jira` path), or accept validated full mail URLs from the CLI.
- **Reading pane / iframe** — Harden body extraction for current OWA layouts; optional attachment metadata without download.
- **Graph API path** — Optional second backend (admin-consented app) for stable read-only mail where Selenium is blocked.
- **Tests** — Recorded HTML fixtures or a small OWA mock for selector regression tests.
- **Retries and diagnostics** — Structured logging, screenshots on failure, automatic backoff when the list virtualizes slowly.
- **Filters** — Expose other list filters (flagged, to me, etc.) with the same menu pattern as Unread.
- **Performance** — Smarter scrolling/limit for huge folders; optional parallel safe patterns where OWA allows.
- **Configuration** — Single YAML/TOML profile for “account A: inbox+unread”, “account B: jira+search”, etc.
- **Accessibility / locale** — Selectors and filter labels for non-English OWA UI strings.
