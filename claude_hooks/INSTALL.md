# Claude Code Install — file_metadata_and_embeddings grounding pipeline

This directory is the source of truth for the Claude Code hooks that implement
session grounding for this project. Scripts live here and are symlinked into
`~/.claude/scripts/` so they are version controlled alongside the project.

## What this installs

| Script | Hook event | Purpose |
|---|---|---|
| `session-start-ground.py` | SessionStart | Reads previous session transcript (Pool A + Pool B), writes `prior_art_notes.md` to cwd before first prompt |
| `prompt-ground.py` | UserPromptSubmit | Per-prompt dual-pool grounding; injects matching prior work + rolling 10-turn delta |
| `autoground.py` | — (retired) | Former Stop hook; superseded by session-start-ground.py |
| `context-stop.py` | Stop | Warns when transcript exceeds 400KB |
| `context-status.py` | statusCommand | Shows context window % in status line |
| `test_prompt_ground.py` | — | pytest suite for prompt-ground.py scoring and state logic |

`settings.json.example` is a reference copy of `~/.claude/settings.json` showing
how hooks are wired. Merge carefully — do not overwrite blindly.

## Install steps

```sh
# 1. Clone or ensure this repo is at ~/Documents/src/file_metadata_and_embeddings
# 2. Symlink each hook script into ~/.claude/scripts/
cd ~/Documents/src/file_metadata_and_embeddings/claude_hooks

for f in prompt-ground.py session-start-ground.py autoground.py \
          test_prompt_ground.py context-stop.py context-status.py; do
    ln -sf "$(pwd)/$f" ~/.claude/scripts/$f
done

# 3. Merge settings.json.example into ~/.claude/settings.json
#    Key entries to add:
#      SessionStart: session-start-ground.py (uv run --project ...)
#      UserPromptSubmit: prompt-ground.py (uv run --project ...)
#      Stop: context-stop.py
#      statusCommand: context-status.py

# 4. Verify
uv run pytest ~/.claude/scripts/test_prompt_ground.py -v
```

## Runtime dependencies

- `uv` at `~/.local/bin/uv`
- Project venv: `uv run --project ~/Documents/src/file_metadata_and_embeddings`
- `~/data/file_metadata.sqlite3` — indexed file database
- `~/data/substrate.sqlite3` — session/node graph DB
- `~/bin/aifilter` + Ollama llama3 — keyword extraction and prior art rendering
  (Python fallback active if Ollama unavailable — hook never blocks)

## Design

The grounding pipeline externalizes *train of thought* across session boundaries.
The context window is complete and correct — what is lost at session close is
the accumulated vocabulary, decisions, and direction of reasoning. This pipeline
re-injects that as `prior_art_notes.md` (cross-session anchor) and a rolling
dual-pool delta block (within-session shift signal), sustaining the functional
continuity the model needs to reason without cold-start overhead.

See `TODO_substrate_paper.md` Track 7 for the paper argument.
