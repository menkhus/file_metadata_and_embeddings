#!/usr/bin/env python3
"""
autoground.py — Claude Code Stop hook: autogrounding layer.

Fires after every session. Extracts keywords from session transcript,
queries substrate DB for matching prior work, renders prior_art_notes.md
into the project directory via llama3 + aifilter.

The next session opens; prompt-ground.py (UserPromptSubmit hook) reads
prior_art_notes.md from cwd and includes it in the injected context block,
connecting the two hooks into one coherent grounding pipeline:

  Session ends   → autoground.py writes prior_art_notes.md  (Stop hook)
  Next prompt    → prompt-ground.py reads prior_art_notes.md + queries DB
                   injects both as labelled context to Claude             (Submit hook)

Hook event: Stop
Reads: JSON from stdin (Claude Code hook payload)
Writes: <cwd>/prior_art_notes.md  (ephemeral — globally gitignored)

Requires:
  - substrate_db.py + autoground_query.py in ~/src/file_metadata_and_embeddings/
  - aifilter in ~/bin/aifilter
  - behavior: summarize_prior_art.txt in ~/.config/aifilter/behaviors/
  - llama3 available in Ollama  (or override MODEL below)
"""

import json
import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path

# --- config ---
SUBSTRATE_DIR = Path.home() / "Documents" / "src" / "file_metadata_and_embeddings"
AIFILTER      = Path.home() / "bin" / "aifilter"
# When invoked via `uv run --project SUBSTRATE_DIR`, the venv is already
# active and imports resolve without sys.path manipulation. The insert below
# is a fallback for plain python3 invocation.
MODEL = "llama3"
TOP_K = 10
MIN_KEYWORDS = 2   # don't run if we extracted fewer than this
OUTPUT_FILE = "prior_art_notes.md"
LOG_FILE = Path.home() / ".claude" / "logs" / "autoground.log"
HOOK_ID = "[autoground hook — ~/.claude/scripts/autoground.py]"

sys.path.insert(0, str(SUBSTRATE_DIR))

# --- logging to file, never to stdout/stderr ---
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("autoground")


def extract_keywords_from_transcript(transcript_path: str) -> list[str]:
    """Pull recent user turns from transcript, extract keywords via llama3."""
    p = Path(transcript_path)
    if not p.exists():
        return []

    lines = []
    try:
        with p.open() as f:
            for line in f:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if record.get("type") == "user":
                    msg = record.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                lines.append(block.get("text", ""))
                    elif isinstance(content, str):
                        lines.append(content)
    except (OSError, IOError):
        return []

    # Take last 10 user turns — recent work, not ancient history
    recent = "\n".join(lines[-10:]).strip()
    if not recent:
        return []

    try:
        result = subprocess.run(
            [str(AIFILTER), "-b", "keyword_extract", "-m", MODEL],
            input=recent, capture_output=True, text=True, timeout=30
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []

    keywords = result.stdout.strip().split()
    return [k for k in keywords if len(k) > 2]  # drop noise tokens


def render_prior_art(nodes: list[dict]) -> str:
    """Call llama3 via aifilter to render nodes as terse markdown."""
    nodes_json = json.dumps(nodes)
    try:
        result = subprocess.run(
            [str(AIFILTER), "-b", "summarize_prior_art", "-m", MODEL],
            input=nodes_json, capture_output=True, text=True, timeout=60
        )
    except Exception:
        return "<!-- prior art render failed -->"
    if result.returncode != 0 or not result.stdout.strip():
        return "<!-- prior art render failed -->"
    return result.stdout.strip()


def main():
    # --- read hook payload ---
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    if payload.get("stop_hook_active"):
        sys.exit(0)

    cwd = payload.get("cwd", os.getcwd())
    transcript_path = payload.get("transcript_path", "")

    # --- extract keywords ---
    if not transcript_path:
        sys.exit(0)

    keywords = extract_keywords_from_transcript(transcript_path)
    if len(keywords) < MIN_KEYWORDS:
        sys.exit(0)

    # --- query substrate DB ---
    try:
        from autoground_query import query  # noqa: PLC0415
        nodes = query(keywords, top_k=TOP_K)
    except Exception as exc:  # noqa: BLE001
        log.warning("DB query failed: %s", exc)
        sys.exit(0)

    if not nodes:
        log.info("no matching nodes for keywords: %s", keywords[:5])
        sys.exit(0)

    # --- render prior_art_notes.md ---
    markdown = render_prior_art(nodes)
    output = Path(cwd) / OUTPUT_FILE
    try:
        output.write_text(
            f"# Prior Art — autoground ({len(nodes)} nodes)\n\n"
            f"{markdown}\n\n"
            f"<!-- keywords: {', '.join(keywords[:10])} -->\n",
            encoding="utf-8"
        )
        log.info("wrote %s (%d nodes, keywords: %s)", output, len(nodes), keywords[:5])
    except (OSError, IOError) as exc:
        log.warning("could not write %s: %s", output, exc)

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Log full traceback to file — never show raw exception in session.
        log.error("unhandled exception: %s\n%s", exc, traceback.format_exc())
        # Brief session-visible notice: who we are and where the log is.
        print(f"{HOOK_ID} failed — see {LOG_FILE}")
        sys.exit(0)
