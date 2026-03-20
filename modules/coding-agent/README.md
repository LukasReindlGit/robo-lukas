# modules/coding-agent

Glue between this repo and your editor agents: **task briefs**, **prompt fragments**, and conventions — not a replacement for Cursor/Codex.

## Contents (expected)

- Prompt templates that consume JSON/Markdown from other modules (Jira + git + org context).
- Checklists for “implement feature X” with links back to tickets and commits.

## Rules

- No secrets; reference env var **names** only.
- Keep outputs **actionable** and scoped (avoid unbounded context dumps).
