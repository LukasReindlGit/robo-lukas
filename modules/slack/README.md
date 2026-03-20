# modules/slack

Slack integration where **API access** is allowed (bot or user token per workspace policy).

## Approach

- Slack Web API for channels, threads, and messages **within allowed scopes**.
- If API is later restricted, evaluate **browser automation** as a fallback (separate ADR).

## Configuration

Document tokens and scopes in this README as you implement; names only in root `.env.example`.

## CLI / contract (target)

```text
python -m robo_lukas.slack fetch-channel --channel C012345 --limit 50 --format json
```
