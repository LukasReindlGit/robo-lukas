# modules/coding-agent

This module defines how your editor agents should use the automation modules in this repo
instead of guessing from raw code only.

## Goal

Give `/robo-lukas` a repeatable operating model:
- collect context from read-only module CLIs (`robo-git`, `robo-jira`, `robo-outlook`, `robo-todo`)
- synthesize a short action plan
- execute coding work with clear ticket + repo context

## Installed globally

- `~/.cursor/commands/robo-lukas.md` — global slash command prompt.
- `~/.cursor/skills/robo-lukas/SKILL.md` — global Cursor skill with module-first workflow.

Use in chat:

```text
/robo-lukas Ship ECOM-808 acceptance criteria and update tests
```

## Module-first workflow

1. **Git context first**
   - `robo-git summary --format json`
   - If needed: `robo-git diff --base main --format json`
2. **Jira scope**
   - `robo-jira show <ISSUE-KEY> --format json`
   - Optional backlog sweep: `robo-jira list-mine --format json`
3. **Inbox and task signals (optional)**
   - `robo-outlook list --folder jira --filter-unread --limit 20 --format json`
   - `robo-todo all-tasks --format json`
4. **Implementation + report**
   - implement
   - run relevant checks
   - summarize changes + verification

## Rules

- Read-only module usage only for context gathering (unless explicitly requested otherwise).
- Prefer JSON output for machine-readable context.
- No secrets in prompts or generated artifacts; mention env var names only.
- Keep outputs scoped: concise findings, concrete next steps, minimal noise.
