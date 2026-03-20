# modules/git-local

Read-only introspection of a **local clone** (no remote credentials required for basic use).

## Configuration

- `GIT_REPO_PATH` — absolute path to the canonical Salesforce / app repo.

## Approach

- Shell out to `git` for: branch, `status`, `log`, `diff` against a base ref.

## CLI / contract (target)

```text
python -m robo_lukas.git_local summary --base main --format json
```
