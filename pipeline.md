# robo-lukas — automation pipeline

Living document. **Owner:** you. **PM role (for now):** align scope, sequence work, surface risks. Update this file when priorities or constraints change.

---

## 1. North star

Build a **modular toolkit** (not one monolith) that lets you and your agents:

- Pull context from work systems (mail, tasks, chat, tickets, code, org).
- Act where safe (drafts, summaries, suggested commits, scratch scripts) with **human approval** until automation is proven.
- Grow new connectors without rewiring everything.

**Success looks like:** less tab-switching and manual copy-paste; repeatable “get me context for X” and “prepare Y” flows; each integration replaceable behind a small interface.

---

## 2. Design principles

| Principle | Implication |
|-----------|----------------|
| **One domain per directory** | Each integration is `modules/<name>/` with its own README, config schema, and tests. Shared code only when two modules need it. |
| **Secrets never in repo** | Env vars, OS keychain, or a local ignored `.env` / `config.local.json`. Document *names* of vars, not values. |
| **Thin adapters** | Prefer official SDKs or stable HTTP APIs where allowed. For blocked vendors, isolate **browser automation** in the relevant module so the rest of the repo stays API-driven. |
| **Graduated autonomy** | Phase 1: read-only + summaries. Phase 2: drafts / local file output. Phase 3: writes with explicit approval and audit logs. |
| **Observable failures** | Timeouts, rate limits, and auth expiry should be loud and structured (exit codes / JSON errors), not silent hangs. |

---

## 3. Suggested repository layout

```
robo-lukas/
├── pipeline.md                 # this file
├── README.md                   # quick start, repo map
├── modules/
│   ├── outlook/                # Outlook on the web (browser automation — no Graph)
│   ├── ms-todo/                # Microsoft To Do web (browser automation — no Graph)
│   ├── slack/                  # Slack Web API / Bolt (unless policy forces UI later)
│   ├── meetings/               # transcription / transcript files, optional UI download
│   ├── jira/                   # Jira Cloud/Server REST
│   ├── git-local/              # local repo introspection (git CLI)
│   ├── salesforce/             # SF CLI, Tooling/Metadata API, optional SOQL
│   └── coding-agent/           # prompts, task specs, agent glue (optional)
├── workflows/                  # composed pipelines: "morning briefing", "ticket digest"
├── docs/
│   └── adr/                    # architecture decision records (e.g. Microsoft browser path)
├── .env.example                # variable names only (copy to .gitignored .env)
└── .gitignore
```

*(Optional later: `pyproject.toml`, `package.json`, or `Makefile` at repo root once the first real CLI is added.)*

Names are suggestions; rename if you standardize on a different metaphor (`connectors/`, `integrations/`).

---

## 4. Capability map → modules

| You need | Likely technical approach | Module | Notes |
|----------|---------------------------|--------|--------|
| Outlook email | **Browser automation** (Selenium or Playwright) against Outlook on the web; **persistent browser profile** for session | `modules/outlook/` | **Microsoft Graph / mail APIs are not used** here. Expect MFA, DOM churn, possible headless blocks. See [ADR 0001](docs/adr/0001-microsoft-browser-automation.md). |
| Microsoft To Do | Same pattern as Outlook where the session allows (shared profile) | `modules/ms-todo/` | To Do may live on a different host or redirect; tune URLs per tenant. |
| Slack | Slack APIs, possibly Socket Mode for events | `modules/slack/` | Bot vs user token changes what you can read; retention/compliance policies matter. UI automation only if APIs are blocked (new ADR). |
| Meeting transcription | Transcript file ingest + optional local STT; optional **browser export** from meeting product | `modules/meetings/` | **Realtime** vs **post-meeting** is a product fork; start with post-meeting. |
| Jira | Jira REST + personal access token or OAuth | `modules/jira/` | Cloud vs Server/Data Center URL and auth differ. |
| Local Git | `git` CLI or libgit2 | `modules/git-local/` | Path to canonical repo(s) as config; watch out for multiple remotes / worktrees. |
| Salesforce org | SF CLI, Tooling API, Metadata API, Bulk/query | `modules/salesforce/` | Separate **read sandbox** vs prod; never default scripts to prod mutation. |
| Code/features | Your editor agents + repo module | `coding-agent/` + `git-local/` | Keep “generation” separate from “integration glue.” |

---

## 5. Phased roadmap (proposal)

### Phase 0 — Foundations (week 0–1)

- [ ] Choose **one** primary language/runtime for glue code (Python + Playwright/Selenium is a natural fit for Microsoft modules).
- [x] Repo skeleton: `modules/*`, `workflows/`, `docs/adr/`, root `README.md`, `.gitignore`, `.env.example`.
- [ ] Define a **minimal shared interface**: e.g. each module exposes `status` (auth OK?), `read` stubs, and JSON or Markdown output for agents.
- [ ] Document **where this repo may run** (WSL only? CI? laptop only?) — **browser automation is typically laptop-only**; CI for Microsoft modules is usually impractical without interactive login.

### Phase 1 — Read-only context (highest daily value)

Order is **suggested**; reorder based on your actual pain.

1. **Jira** — ticket + comments + status in one CLI/JSON blob (feeds planning and standups).
2. **Local Git** — branch, recent commits, open diff vs main for your canonical repo.
3. **Microsoft To Do** — list tasks due today / by list via **browser session** (profile already logged in).
4. **Outlook** — unread from key senders / folders, or search by query (scope carefully to avoid dumping entire mailbox into prompts).

### Phase 2 — Communication surfaces

5. **Slack** — channels you care about, threads, DMs (with explicit allowlists).
6. **Meetings** — ingest recording/transcript file → summary + action items (realtime later).

### Phase 3 — Safe writes & workflows

7. **Salesforce** — read-only SOQL/report export first; then scripted deploys behind confirmation.
8. **Workflows** — compose Phase 1–2 into `workflows/morning.md` or scripted briefings.

### Phase 4 — Hardening

- Rate limits, retries, caching, local audit log for anything that touched external systems.
- Optional: small web UI or TUI **only if** CLI stops being enough.

---

## 6. Cross-cutting concerns (don’t defer forever)

- **Identity:** **Microsoft: interactive login + persistent browser profile** (no Graph app). Slack app vs Atlassian API token still need their own setup.
- **Microsoft UI automation:** CAPTCHA, “unusual activity,” and A/B UI tests can break runs; keep human fallback and short, scoped scrapes.
- **Compliance:** employer policies on storing transcripts, email bodies, and customer data in local files or in LLM context. Prefer summarization + redaction patterns early.
- **Cost:** realtime transcription and large Slack exports can get expensive; set caps and filters.
- **Salesforce safety:** naming conventions like `ORG_ALIAS=...` required for mutating commands; default read-only.

---

## 7. Open questions (need your answers)

Answer inline or in a short `docs/decisions.md` as you go.

1. **Microsoft stack:** Personal vs **corporate Entra ID**? (Affects login UX and which Outlook/To Do URL you land on — APIs remain unused.)
2. **Outlook scope:** Full mailbox automation or **narrow** (specific folders, VIP senders, keyword search only)?
3. **Slack:** Workspace you **own** vs employer workspace? Bot with limited scopes vs user token?
4. **Jira:** Cloud (`atlassian.net`) or on-prem? Do you already have an API token?
5. **Meetings:** Primary tool (Teams, Zoom, Meet)? Is **post-meeting transcript** enough for v1?
6. **Git:** Single canonical repo path, or several? Monorepo or many checkouts?
7. **Salesforce:** sandboxes you use daily (names/aliases)? Any org where **mutation** from scripts is forbidden?
8. **Runtime:** Strong preference for **Python**, **Node**, or **shell + small utilities**?
9. **Orchestration:** Do you want **CLI-first** only, or is a local dashboard acceptable later?

---

## 8. PM pushback / suggestions

- **Don’t boil the ocean on realtime transcription** — ship “transcript file in → structured notes out” first; add streaming when the rest of the spine works.
- **Reuse one browser profile** for Outlook + To Do when the product allows a single session — fewer MFA prompts than separate incognito runs.
- **Calendar (web)** could be a future `modules/outlook-calendar/` (or merged doc) using the **same browser approach** — only if you need it after mail/todo are stable.
- **“Agent memory”** — avoid dumping raw emails into long-lived files without a retention policy; prefer summaries + pointers (message IDs, ticket keys, commit SHAs).

---

## 9. Definition of done (per module)

A module is “v1 done” when:

- README lists prerequisites, auth steps, and env vars.
- A **non-interactive** command returns structured output (JSON or Markdown) for at least one real use case.
- Failure modes are documented (401, 429, missing scope for APIs; **stale session / selector mismatch** for browser modules).
- No secrets committed; example config checked in.

---

## 10. What we do next (your move)

1. Answer **§7** (even roughly).
2. Pick **Phase 1 item #1** (recommendation: **Jira** or **local Git** — least auth friction).
3. Implement the first module CLI (see module README); extend `.env.example` as needed.

## Changelog

- 2025-03-20: Repo structure scaffolded; Microsoft path fixed to **browser automation** per ADR 0001 (no Graph).

---

*End of pipeline.md v0.2*
