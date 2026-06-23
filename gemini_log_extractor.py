#!/usr/bin/env python3
"""
Extract Gemini CLI session logs to markdown for indexing.

Reads ~/.gemini/tmp/<project>/chats/session-*.json and writes one .md file
per session to ~/.gemini/extracted/<project>/<session>.md.

Idempotent: skips sessions whose output file is newer than the source JSON.
Run before the file scanner so new sessions are indexed on the same hourly pass.

Usage:
    python gemini_log_extractor.py              # extract all new/updated sessions
    python gemini_log_extractor.py --force      # re-extract everything
    python gemini_log_extractor.py --stats      # print counts and exit
"""

import argparse
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

GEMINI_TMP = Path.home() / ".gemini" / "tmp"
EXTRACT_DIR = Path.home() / ".gemini" / "extracted"


def get_text(content) -> str:
    """Normalize content field: string or list of {text: ...} dicts."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("text")]
        return " ".join(parts).strip()
    return str(content).strip()


def extract_session(path: Path) -> str:
    """Convert a session JSON to a markdown document."""
    with open(path) as f:
        data = json.load(f)

    session_id = data.get("sessionId", path.stem)
    start = data.get("startTime", "")[:10]  # date only
    messages = data.get("messages", [])

    # Derive project name from parent directory name
    project = path.parent.parent.name

    lines = [
        f"# Gemini session — {project} — {start}",
        f"",
        f"session: {session_id}  project: {project}  date: {start}",
        f"",
        f"---",
        f"",
    ]

    for msg in messages:
        role = msg.get("type", "unknown")
        content = get_text(msg.get("content", ""))
        thoughts = msg.get("thoughts", [])
        tool_calls = msg.get("toolCalls", [])
        model = msg.get("model", "")

        if role == "error":
            if content:
                lines.append(f"> **error:** {content}")
                lines.append("")
            continue

        if role == "user":
            if content:
                lines.append(f"**User:** {content}")
                lines.append("")

        elif role == "gemini":
            header = f"**Gemini**" + (f" ({model})" if model else "")
            lines.append(header)
            if content:
                lines.append(content)
            if thoughts:
                subjects = [t.get("subject", "") for t in thoughts if t.get("subject")]
                if subjects:
                    lines.append(f"*thinking: {'; '.join(subjects)}*")
            if tool_calls:
                names = []
                for tc in tool_calls:
                    name = tc.get("name") or tc.get("displayName") or tc.get("toolName") or ""
                    if name:
                        names.append(name)
                if names:
                    lines.append(f"*tools: {', '.join(names)}*")
            lines.append("")

    return "\n".join(lines)


def process_all(force: bool = False) -> tuple[int, int, int]:
    """Extract all sessions. Returns (extracted, skipped, errors)."""
    extracted = skipped = errors = 0

    session_files = sorted(GEMINI_TMP.glob("*/chats/session-*.json"))
    if not session_files:
        log.info("No Gemini session files found under %s", GEMINI_TMP)
        return 0, 0, 0

    for src in session_files:
        project = src.parent.parent.name
        out_dir = EXTRACT_DIR / project
        out_path = out_dir / (src.stem + ".md")

        # Skip if output is up to date
        if not force and out_path.exists() and out_path.stat().st_mtime >= src.stat().st_mtime:
            skipped += 1
            continue

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            content = extract_session(src)
            out_path.write_text(content)
            extracted += 1
            log.debug("extracted %s", src.name)
        except Exception as e:
            log.warning("failed %s: %s", src, e)
            errors += 1

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
        total = sum(1 for _ in GEMINI_TMP.glob("*/chats/session-*.json"))
        done = sum(1 for _ in EXTRACT_DIR.glob("*/*.md")) if EXTRACT_DIR.exists() else 0
        log.info("Sessions found: %d | Already extracted: %d | Pending: %d", total, done, total - done)
        return

    extracted, skipped, errors = process_all(force=args.force)
    log.info("Gemini logs: %d extracted, %d up-to-date, %d errors → %s",
             extracted, skipped, errors, EXTRACT_DIR)


if __name__ == "__main__":
    main()
