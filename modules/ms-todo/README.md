# Microsoft To Do (web)

**Read-only** automation of [Microsoft To Do](https://to-do.live.com) in Chrome via Selenium — **no Microsoft Graph**. Same ideas as `modules/outlook/`: dedicated Chrome profile, guarded URLs, OWA-style DOM fallbacks.

**Code:** `src/robo_lukas/ms_todo/`  
**CLI:** `python -m robo_lukas.ms_todo …` or `robo-todo …` (after `pip install -e .`)

**Account picker:** same as Outlook — optional `MICROSOFT_ACCOUNT_HINT` in `.env` to select the right tile on “Pick an account”.

---

## Setup

- **Python** 3.11+, **Chrome**, repo root: `pip install -e .`
- **`M365_BROWSER_USER_DATA_DIR`** — required (reuse the same profile as Outlook if both work in one session).
- **`MS_TODO_WEB_URL`** — optional. **Default** (when unset) is `https://to-do.office.com/tasks/inbox` so the first navigation opens the **Tasks** list on the commercial host (usually fewer redirects for M365). Personal/live accounts often set `https://to-do.live.com/tasks/` instead.

**Chrome profile / SSO every run:** Cookies are stored under `M365_BROWSER_USER_DATA_DIR` (and `CHROME_PROFILE_DIRECTORY`, default `Default`). If Microsoft keeps sending you through full sign-in:

1. Use the **same** `--browser-profile` / env path on every invocation; do not mix `to-do.live.com` and `to-do.office.com` entry URLs without signing in once on each host, or set `MS_TODO_WEB_URL` to match where you already have a session.
2. Close any **other Chrome windows** using that user-data-dir (or you’ll see `SingletonLock` / a fresh-looking session).
3. Set optional **`MICROSOFT_ACCOUNT_HINT`** if the tenant shows “Pick an account” every time.

Timing env vars (optional): defaults are tuned for **fast** runs once you’re signed in (To Do stays on `document.readyState === "interactive"` for a long time, so we **do not** wait for `"complete"` on the task app). Raise `MS_TODO_EXPLICIT_WAIT` / `MS_TODO_SHELL_BURST` only on slow machines or flaky first paint.

Vars: `MS_TODO_EXPLICIT_WAIT`, `MS_TODO_POST_NAV_SLEEP`, `MS_TODO_SHELL_SETTLE`, `MS_TODO_SHELL_POLL`, `MS_TODO_SHELL_BURST`, **`MS_TODO_PAGE_WAIT_MAX`** (default **4** — max seconds waiting on one To Do task URL for rows/empty list UI; then a clear error; raise only if your tenant is slow), `MS_TODO_LOGIN_POLL`, `MS_TODO_LIST_ROW_POLL`, `MS_TODO_SCROLL_KEY_SLEEP` — many fall back to matching `OUTLOOK_*` when unset.

**Note:** `MS_TODO_IMPLICIT_WAIT` is accepted for config parity with Outlook but **the To Do driver always uses Selenium implicit wait `0`**. Non-zero implicit wait applies to every `find_elements` call; this app probes many selectors per poll, so a small implicit value can stretch a single loop into minutes and look like a hang after the page is visibly correct.

**Windows / WSL:** same as Outlook — see [`docs/WINDOWS.md`](../../docs/WINDOWS.md) and `with-bridge` below.

---

## Shared options

Must be passed **after** the subcommand:

| Option | Purpose |
|--------|---------|
| `--browser-profile` | Overrides `M365_BROWSER_USER_DATA_DIR` |
| `--chrome-profile-directory` | e.g. `Default` |
| `--chrome-binary` | `CHROME_BINARY` |
| `--tasks-url` | Overrides `MS_TODO_WEB_URL` |
| `--headless` | Headless Chrome (often breaks login) |
| `--keep-browser` | Do not close the browser |
| `--explicit-wait` | Seconds to wait for task rows |
| `--remote-url` | WSL → Windows ChromeDriver |
| `--investigate [DIR]` | **Investigation mode** — timeline + browser snapshots (see below) |
| `--investigate-interval SEC` | Heartbeat interval during long DOM waits when investigating (default `16`) |

### Investigation mode (`--investigate`)

Use this when a run **hangs** or behaves oddly: the CLI writes under **DIR** (default `.robo-todo-investigate`):

- **`investigation.log`** — timestamped phases (`todo_session_loop_*`, `wait_until_todo_ready`, `login`, etc.) and heartbeat lines with row/nav/shell probe counts.
- **`NNN_phase.html`** — full page source at milestones.
- **`NNN_phase.png`** — screenshot (if the driver supports it).
- **`NNN_phase.json`** — URL, title, `document.readyState`, body text preview, and **`todo_probe`** (`visible_task_row_count`, `nav_candidate_count`, `shell_ready`, …).

Example:

```bash
robo-todo wait-login --investigate ./todo-debug --keep-browser
robo-todo list -l "Tasks" --investigate C:/temp/todo-inv
```

Share the folder (or redact HTML/JSON) when reporting issues or extending selectors.

---

## Commands

### `status`

Open the configured To Do URL and print URL / page title.

```bash
python -m robo_lukas.ms_todo status --format json
```

### `wait-login`

Load To Do and wait until the **task shell** (sidebar / list pane) is ready: **document ready**, Microsoft **KMSI / consent / pre-filled Next** auto-advance where safe (`src/robo_lukas/microsoft_sso.py`), then onboarding dismiss + shell checks. Password / MFA still manual.

| Option | Default |
|--------|---------|
| `--login-timeout` | `600` |

```bash
python -m robo_lukas.ms_todo wait-login --login-timeout 600 --keep-browser
```

### `lists`

Scrape **sidebar list names** (best effort; DOM-dependent).

| Option | Default |
|--------|---------|
| `--max-items` | `120` |
| `--login-timeout` | `600` |
| `--format` | `text` |

```bash
python -m robo_lukas.ms_todo lists --format json
```

### `all-tasks`

Scrapes the **Tasks** sidebar list by default (`--list` / `-l` overrides the name). Use **`--all-lists`** only if you want My Day, Important, Flagged email, and every other nav entry too.

Default output: **JSON** array of `{ "list_name", "tasks": [...] }` (optional `"error"` per block).

| Option | Default |
|--------|---------|
| `--list` / `-l` | `Tasks` |
| `--all-lists` | off (only iterate every sidebar list when set) |
| `--max-items` | `120` (with `--all-lists`: cap on list count) |
| `--limit` | `200` (tasks per list) |
| `--scroll-rounds` | `4` |
| `--login-timeout` | `600` |
| `--format` | `json` (`text` for a simple human view) |

```bash
robo-todo all-tasks --format json > tasks-inbox.json
robo-todo all-tasks --all-lists --format json > everything.json
```

### `list`

Open a list by **exact sidebar label** and print tasks from the main pane (titles, best-effort due/status/note from row text).

| Option | Default |
|--------|---------|
| `--list` / `-l` | **required** — list name |
| `--limit` | `50` |
| `--scroll-rounds` | `4` |
| `--login-timeout` | `600` |
| `--format` | `text` |

```bash
python -m robo_lukas.ms_todo list --list "Work" --format json
python -m robo_lukas.ms_todo list -l Tasks --limit 20 --format text
```

---

## WSL: `with-bridge`

Same ChromeDriver bridge as Outlook:

```bash
python -m robo_lukas.ms_todo with-bridge list --list Work --format json
```

Requires `CHROMEDRIVER_WINDOWS_EXE` or an already reachable `CHROMEDRIVER_REMOTE_URL`.

---

## Limits

- **No mutations** — no task create, complete, delete, or settings flows in the CLI.
- **Scraping** — Microsoft changes the DOM often; tune `selectors.py` if rows or list names go empty. The task pane may be **List** or **Grid** view; both are handled. In Grid view, **group rows** (e.g. the “Completed” bucket header) are skipped so they are not emitted as tasks.
- **List matching** — `--list` uses **case-insensitive exact match** on the sidebar control’s visible text.
- **Auth** — Conditional Access / blocked OWA-style policies may apply the same way as Outlook.
- **“Get started” / onboarding** — `wait-login` and `list` wait until the **sidebar or task pane** appears, not only the URL. The tool tries **Skip / Continue / Get started** (EN + DE); if you stay stuck, click through once manually, then rerun. Increase pauses with `MS_TODO_SHELL_SETTLE` and `MS_TODO_EXPLICIT_WAIT`.

---

## Future improvements

- Click a task to read **notes** in the detail pane without completing it.
- **Export** JSON to file (mirror `robo-outlook export`).
- **My Day / Planned** smart lists if URLs are stable per tenant.
- **Tests** with fixture HTML or recorded snapshots.
- Optional **Graph** backend when browser automation is blocked.
