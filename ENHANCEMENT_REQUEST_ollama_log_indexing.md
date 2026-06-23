# ER: Ollama Session Log Indexing

**Status:** Open  
**Priority:** Medium — completes local-model session recall  

---

## Motivation

Ollama sessions contain prompts and completions from local model inference.
They should be searchable alongside Claude and Gemini logs.

This is part of the "post-AI" design: every AI interaction — cloud or local —
is a knowledge artifact worth indexing.

---

## Actual Log Location

**`~/Documents/src/llm_session_database/llm_sessions.db`** — this is the real store.

Schema (abridged):
```sql
ai_sessions:
  session_id, model_name, project_name,
  prompt_text, response_text, response_summary,
  created_at, tags, payload (full JSON)

ai_messages:
  message_id, session_id, sequence_number, role, content
```

Current data: **91 sessions**, model `gpt-oss:latest` (Ollama), project `web_chat`.
FTS5 virtual table already built on prompt_text + response_text + response_summary.

Project: `~/Documents/src/llm_session_database/` — Flask web UI + CLI + provider layer
(Ollama, OpenAI, Anthropic unified interface). See README.md there.

---

## Dead Path Removed

`run /Users/mark/ai_shell_logs` was in `run-file-metadata-index` but the directory
never existed. **Removed.** The scanner was silently skipping it every hour.

---

## Other Candidate Paths (lower priority)

- `~/Documents/src/ollamash/ollama_logs.db` — `sessions` table exists, 0 rows (unused)
- `~/.ai_shell_sessions/<timestamp>/prompts.jsonl` — shell-level prompt logs, not
  full sessions. Volume unknown. `.jsonl` already in EXTENSIONS if path is added.

---

## Implementation

The SQLite DB cannot be scanned directly by `file_metadata_content.py` (file-based scanner).
Needs an extractor:

### `ollama_log_extractor.py`
```
For each session in ai_sessions WHERE updated_at > last_run:
  filename = f"~/.ollama_extracted/{session_id}.md"
  write:
    # {model_name} — {project_name} — {created_at}
    ## Prompt
    {prompt_text}
    ## Response
    {response_text}
  track last_run in a state file or use file mtime
```

Then add to `run-file-metadata-index`:
```bash
OLLAMA_EXTRACT="$PROJECT/ollama_log_extractor.py"
"$UV" run --project "$PROJECT" python3 "$OLLAMA_EXTRACT"
run --allowlist ~/.ollama_extracted ~/.ollama_extracted
```

`.md` is already in EXTENSIONS, no other changes needed.

---

## Files to Create/Modify

| File | Change |
|---|---|
| `~/src/file_metadata_and_embeddings/ollama_log_extractor.py` | New — reads `llm_sessions.db`, writes per-session `.md` |
| `~/bin/run-file-metadata-index` | Add extractor call + `~/.ollama_extracted` scan |
