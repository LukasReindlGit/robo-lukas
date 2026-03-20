# modules/salesforce

Salesforce DX CLI and/or Metadata, Tooling, and data APIs — **default read-only**.

## Configuration

- `SF_ORG_ALIAS` (or pass `--target-org` explicitly in every mutating command).

## Safety

- Never default scripts to production.
- Mutations require explicit flags and are out of scope until Phase 3 in `pipeline.md`.

## CLI / contract (target)

```text
python -m robo_lukas.salesforce query --soql "SELECT Id, Name FROM Account LIMIT 5" --format json
```
