# ER: Gemini Session Log Indexing

**Status:** Open  
**Priority:** High — completes the "all AI sessions are searchable" design goal  

---

## Motivation

Gemini CLI session logs contain design decisions, code reviews, and problem-solving
threads that are not captured anywhere else. They should be first-class recall
sources alongside Claude logs (already indexed via `~/.claude`).

This is a "post-AI" feature: the AI session log is part of the computer's
knowledge record, not a disposable side effect.

---

## Log Location and Format

Gemini CLI stores sessions at:

```
~/.gemini/tmp/<project-slug>/chats/session-<timestamp>-<uuid>.json
```

Known project slugs on this machine:
- `the-mathematician`
- `scrivner-docs`
- `writing`
- `ai-plus-kg`
- `ai-log-explainability-and-security`
- `osx-os-security-research`
- `mark` (general)

Additional files (lower priority):
- `~/.gemini/tmp/<project>/logs.json` — project-level event log
- `~/.gemini/history/<project>/` — directory-based history (format TBD)

Reference: `~/Documents/src/gemini_audit_log/` has `gemini_extractor.py`
and `SCHEMA_NOTES.md` documenting the session JSON schema.

---

## Implementation Options

### Option A — Direct `.json` scan (simplest)
Add `~/.gemini/tmp` as an allowlisted scan target in `run-file-metadata-index`:
```bash
run --allowlist ~/.gemini/tmp ~/.gemini/tmp
```
Add `.json` to `EXTENSIONS`.

**Problem:** `.json` is broad — config files, schema files, and data files
would all be ingested. Needs a targeted denylist or path filter.

### Option B — Pre-processor script (recommended)
Write `gemini_log_extractor.py` (adapt `~/Documents/src/gemini_audit_log/gemini_extractor.py`):
- Reads `session-*.json` files
- Extracts user/model turns as plain text
- Writes `~/.gemini/extracted/<project>/<session>.md` (markdown, one per session)
- Idempotent: skips sessions already extracted (by mtime or hash)

Then add `~/.gemini/extracted` as a normal scan target (`.md` already in extensions, no allowlist needed since it's not hidden).

Run extractor from `run-file-metadata-index` before the scan calls:
```bash
python3 "$PROJECT/gemini_log_extractor.py"
run ~/.gemini/extracted
```

**Advantage:** Markdown extraction gives the chunker clean prose, not JSON structure.
Consistent with how Claude `.jsonl` logs are currently handled (indexed raw).

### Option C — Hybrid
Index raw `.json` sessions directly (Option A) as a fast start,
then add extraction later when recall quality needs improvement.

---

## Recommended Path

Option B. The extractor already has prior art in `gemini_extractor.py`.
Extracted markdown can be inspected and cleaned; raw JSON cannot.

---

## Files to Create/Modify

| File | Change |
|---|---|
| `~/src/file_metadata_and_embeddings/gemini_log_extractor.py` | New — adapt from `gemini_audit_log/gemini_extractor.py` |
| `~/bin/run-file-metadata-index` | Add extractor call + `run ~/.gemini/extracted` |
