# robo-lukas

Modular automation for a Salesforce developer workflow: mail, tasks, chat, tickets, meetings, local git, and org data — each in **`modules/<name>/`**.

## Layout

| Path | Purpose |
|------|---------|
| [pipeline.md](./pipeline.md) | Roadmap, phases, open questions |
| `modules/outlook/` | Outlook via **browser automation** (Graph not available) |
| `modules/ms-todo/` | Microsoft To Do via **browser automation** |
| `modules/slack/` | Slack (API where allowed) |
| `modules/meetings/` | Transcripts / audio → structured notes |
| `modules/jira/` | Jira REST |
| `modules/git-local/` | Local clone introspection |
| `modules/salesforce/` | SF CLI / APIs |
| `modules/coding-agent/` | Prompts, specs, agent glue |
| `workflows/` | Composed multi-step flows |
| `docs/adr/` | Architecture decisions |

## Setup

1. Python 3.11+, Chrome or Chromium installed (Selenium Manager will fetch a matching ChromeDriver).
2. `pip install -e .` from this repository root.
3. Copy `.env.example` to `.env` and set at least `M365_BROWSER_USER_DATA_DIR` for Outlook.

### Windows (Cursor nativ)

Projekt unter **OneDrive → `Documents\Projects`** (z. B. `…\OneDrive - Salesfive GmbH\Documents\Projects\robo-lukas`): Kurzanleitung in [docs/WINDOWS.md](docs/WINDOWS.md).

### Outlook (read-only CLI)

See [modules/outlook/README.md](modules/outlook/README.md). Quick start:

```bash
export M365_BROWSER_USER_DATA_DIR="$HOME/.local/share/robo-lukas/chrome-profile"
python -m robo_lukas.outlook wait-login --login-timeout 600
python -m robo_lukas.outlook list --folder inbox --limit 20 --format json
```

Or use the console script: `robo-outlook list --folder sent --limit 10`.

## Constraint: Microsoft 365

Tenant policy blocks **Microsoft Graph** (or similar API access). Outlook and To Do integrations **must** use **browser automation** (e.g. Selenium or Playwright), persistent profiles, and tolerant selectors — see each module README and [ADR 0001](docs/adr/0001-microsoft-browser-automation.md).
