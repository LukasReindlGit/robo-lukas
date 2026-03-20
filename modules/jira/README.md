# modules/jira

Jira **REST API** (Cloud or Server/Data Center — document which you use).

## Configuration

- `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` (or Server PAT as applicable).

## CLI / contract (target)

```text
python -m robo_lukas.jira issue --key PROJ-123 --comments --format json
```

## Notes

- Server/Data Center base URL and auth differ from Cloud; branch README sections when you support both.
