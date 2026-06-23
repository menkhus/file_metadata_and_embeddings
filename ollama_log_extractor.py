#!/usr/bin/env python3
"""
Extract Ollama session logs to markdown for indexing.

Reads ai_sessions from ~/Documents/src/llm_session_database/llm_sessions.db
and writes one .md file per session to ~/.ollama_extracted/<project>/<session_id>.md.

Idempotent: tracks last-run timestamp in ~/.ollama_extracted/.last_run so only
sessions updated since the last extraction are processed.

Usage:
    python ollama_log_extractor.py              # extract new/updated sessions
    python ollama_log_extractor.py --force      # re-extract everything
    python ollama_log_extractor.py --stats      # print counts and exit
"""

import argparse
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DB_PATH = Path.home() / "Documents" / "src" / "llm_session_database" / "llm_sessions.db"
EXTRACT_DIR = Path.home() / ".ollama_extracted"
LAST_RUN_FILE = EXTRACT_DIR / ".last_run"


def load_last_run() -> str:
    """Return ISO timestamp of last run, or epoch if never run."""
    if LAST_RUN_FILE.exists():
        return LAST_RUN_FILE.read_text().strip()
    return "1970-01-01 00:00:00"


def save_last_run() -> None:
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    LAST_RUN_FILE.write_text(now)


def slug(text: str) -> str:
    """Make a filesystem-safe slug from arbitrary text."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)[:40].strip("_") or "unknown"


def extract_session(row: sqlite3.Row) -> str:
    """Convert a session row to a markdown document."""
    session_id = row["session_id"]
    model = row["model_name"] or "unknown"
    project = row["project_name"] or "general"
    created = (row["created_at"] or "")[:10]
    prompt = (row["prompt_text"] or "").strip()
    response = (row["response_text"] or "").strip()
    summary = (row["response_summary"] or "").strip()
    tags_raw = row["tags"] or ""

    lines = [
        f"# Ollama session — {project} — {created}",
        f"",
        f"session: {session_id}  model: {model}  project: {project}  date: {created}",
    ]

    if tags_raw:
        lines.append(f"tags: {tags_raw}")

    lines += ["", "---", ""]

    if prompt:
        lines.append(f"**User:** {prompt}")
        lines.append("")

    if response:
        lines.append(f"**{model}:** {response}")
        lines.append("")

    if summary:
        lines.append(f"*Summary: {summary}*")
        lines.append("")

    return "\n".join(lines)


def process_all(force: bool = False) -> tuple[int, int, int]:
    """Extract sessions. Returns (extracted, skipped, errors)."""
    if not DB_PATH.exists():
        log.warning("DB not found: %s", DB_PATH)
        return 0, 0, 0

    last_run = "1970-01-01 00:00:00" if force else load_last_run()
    extracted = skipped = errors = 0

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute("""
            SELECT session_id, model_name, project_name, created_at, updated_at,
                   prompt_text, response_text, response_summary, tags
            FROM ai_sessions
            WHERE updated_at > ?
            ORDER BY created_at
        """, (last_run,)).fetchall()

        if not rows:
            log.info("Ollama logs: 0 new sessions since %s", last_run)
            return 0, 0, 0

        for row in rows:
            project = slug(row["project_name"] or "general")
            out_dir = EXTRACT_DIR / project
            out_path = out_dir / f"{row['session_id']}.md"

            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path.write_text(extract_session(row))
                extracted += 1
                log.debug("extracted %s", row["session_id"])
            except Exception as e:
                log.warning("failed %s: %s", row["session_id"], e)
                errors += 1

    finally:
        conn.close()

    save_last_run()
    return extracted, skipped, errors


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-extract all sessions")
    parser.add_argument("--stats", action="store_true", help="Print counts only")
    args = parser.parse_args()

    if args.stats:
        if not DB_PATH.exists():
            log.warning("DB not found: %s", DB_PATH)
            return
        conn = sqlite3.connect(DB_PATH)
        total = conn.execute("SELECT COUNT(*) FROM ai_sessions").fetchone()[0]
        conn.close()
        done = sum(1 for _ in EXTRACT_DIR.glob("*/*.md")) if EXTRACT_DIR.exists() else 0
        log.info("Sessions in DB: %d | Extracted: %d | Pending: %d", total, done, total - done)
        return

    extracted, skipped, errors = process_all(force=args.force)
    log.info("Ollama logs: %d extracted, %d up-to-date, %d errors → %s",
             extracted, skipped, errors, EXTRACT_DIR)


if __name__ == "__main__":
    main()
