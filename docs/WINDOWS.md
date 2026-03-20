# robo-lukas auf Windows (Cursor nativ)

Projektpfad: **`C:\Users\LukasReindl\OneDrive - Salesfive GmbH\Documents\Projects\robo-lukas`**

## Einmalig

1. **Cursor:** *File → Open Folder* → obigen Ordner wählen.
2. **Python 3.12** (oder 3.11+) installieren; im Terminal prüfen: `py -3.12 --version` (oder `py -3.13` / `py -3`, je nach Install).
3. **Chrome** installieren (Selenium Manager holt den passenden ChromeDriver).

```powershell
cd "C:\Users\LukasReindl\OneDrive - Salesfive GmbH\Documents\Projects\robo-lukas"
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

4. **`.env`** im Projektroot (von `.env.example` kopieren) mit **Windows-Pfaden**, z. B.:

```env
M365_BROWSER_USER_DATA_DIR=C:\Users\LukasReindl\AppData\Local\robo-lukas\chrome-profile
OUTLOOK_WEB_URL=https://outlook.office.com/mail/
```

Profilordner ggf. vorher anlegen: `mkdir "$env:LOCALAPPDATA\robo-lukas\chrome-profile" -Force`

## `.venv` automatisch beim Projektwechsel

**Cursor / VS Code (empfohlener Weg):** Im Repo liegt [`.vscode/settings.json`](../.vscode/settings.json) mit `python.defaultInterpreterPath` und `python.terminal.activateEnvironment`. Neues **integriertes Terminal** nach *Open Folder* sollte das venv automatisch aktivieren (`python`/`pip` zeigen auf `.venv`).

**Beliebiges Terminal (Git Bash, etc.) mit [direnv](https://direnv.net):**

1. direnv installieren und die Shell hooken (siehe Installationsanleitung).
2. Einmal im Projektordner: `direnv allow`
3. Bei jedem `cd` in dieses Verzeichnis lädt [`.envrc`](../.envrc) und stellt `PATH`/`VIRTUAL_ENV` auf `.venv` ein.

Ohne Cursor/direnv: weiter `source .venv/Scripts/activate` (Bash) bzw. `.\.venv\Scripts\Activate.ps1` (PowerShell).

## „Python was not found“ / Microsoft Store

Oft zeigt `python` auf den **Store-Stub** (Windows-Einstellungen → Apps → Erweiterte App-Einstellungen → **App-Ausführungsaliase**: `python.exe` / `python3.exe` aus).

**Zuverlässig** (ohne Activate): immer den Interpreter aus dem venv ansprechen:

```powershell
cd "C:\Users\LukasReindl\OneDrive - Salesfive GmbH\Documents\Projects\robo-lukas"
.\.venv\Scripts\python.exe -m robo_lukas.outlook search "read:no" --limit 5 --show-index 0 --format json
```

Oder Kurzform — Skripte im Repo:

```powershell
.\scripts\run-outlook.ps1 -m robo_lukas.outlook search "read:no" --limit 5 --show-index 0 --format json
```

**Git Bash** (gleiches Problem mit `python`):

```bash
./scripts/run-outlook.sh -m robo_lukas.outlook search "read:no" --limit 5 --show-index 0 --format json
```

## Outlook-CLI

```powershell
cd "C:\Users\LukasReindl\OneDrive - Salesfive GmbH\Documents\Projects\robo-lukas"
.\.venv\Scripts\Activate.ps1
python -m robo_lukas.outlook wait-login --login-timeout 600
python -m robo_lukas.outlook list --folder inbox --limit 20 --format json
python -m robo_lukas.outlook list --folder jira --filter-unread --limit 10 --format json

# Ungelesen: OWA-Filter (``--filter-unread``) oder Suchbegriff ``read:no``:
python -m robo_lukas.outlook search --folder inbox --filter-unread --limit 10 --format json
python -m robo_lukas.outlook search "read:no" --limit 10 --show-index 0 --format json
```

Falls `python` nach dem Activate trotzdem kaputt ist: `deactivate`, dann `.\.venv\Scripts\python.exe -m …` oder `.\scripts\run-outlook.ps1 -m …` wie oben.

## Microsoft To Do (`robo-todo`)

Gleiches Profil wie Outlook möglich:

```powershell
.\.venv\Scripts\python.exe -m robo_lukas.ms_todo lists --format json
.\.venv\Scripts\python.exe -m robo_lukas.ms_todo list --list "Work" --format json
```

Siehe [`modules/ms-todo/README.md`](../modules/ms-todo/README.md).

## WSL vs. Windows

- **Nur Windows:** keine `CHROMEDRIVER_REMOTE_URL`, kein `with-bridge`, kein `ROBO_OUTLOOK_USE_WINDOWS_CHROME` nötig.
- **Weiterhin WSL nutzen:** siehe [modules/outlook/README.md](../modules/outlook/README.md) (Bridge / ChromeDriver auf Windows).
