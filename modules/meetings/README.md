# modules/meetings

Transcription and meeting notes — **post-meeting first** (file in → structured summary), realtime later.

## Approach

- Accept transcript files (`.txt`, `.vtt`, vendor exports) or audio where you add a local STT step.
- Optional: browser automation to **download** transcripts from Teams/Zoom web if APIs are blocked (parallel to Microsoft constraint).

## Outputs

- Summary, decisions, action items with owners (as far as detectable), and timestamps.

## CLI / contract (target)

```text
python -m robo_lukas.meetings ingest --file ./transcript.vtt --format json
```
