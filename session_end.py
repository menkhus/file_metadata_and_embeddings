#!/usr/bin/env python3
"""
session_end.py — Universal AI session-end handler.

Called by _logged_ai() in ~/.zshrc after every AI session ends,
regardless of which AI tool was used (claude, ollama, gemini, etc.).

Responsibilities:
  1. Extract keywords from the session log (ANSI-stripped text)
  2. Write a session node to the substrate DB
  3. Write prior_art_notes.md to the cwd — context seed for the next session

This is the write side of the cross-session working memory loop.
The read side is prompt-ground.py (UserPromptSubmit hook / _logged_ai pipe).

DESIGN NARRATIVE
================
Session nodes are first-class citizens in the substrate DB alongside
project and file nodes. When prompt-ground.py queries for prior work
relevant to a prompt, it finds not just files and projects but prior
sessions — what was actually worked on, in what context, with what
converged keywords.

This is the mechanism that gives the AI cross-session memory without
requiring cloud services, managed memory APIs, or vendor lock-in.
The substrate DB is local, portable, and works for all AI tools equally.

The converged keyword set at session end is a low-dimensional semantic
fingerprint of the session — what it was actually about after the work
narrowed from broad exploration to focused execution. This fingerprint
is stored as the session node's metadata and used for future retrieval.
It is also a candidate LoRA training signal for session-conditioned
domain adaptation (see TODO_substrate_paper.md Track 5).

References:
  - AriGraph (2024): episodic memory nodes in knowledge graphs
    https://arxiv.org/abs/2407.04363
  - Reflective Memory Management (ACL 2025): session-level memory
    https://aclanthology.org/2025.acl-long.413.pdf
  - MARK (2025): temporal + feedback-aware memory persistence

Usage (from _logged_ai shell wrapper):
    python3 ~/src/file_metadata_and_embeddings/session_end.py \
        --app claude \
        --logfile /path/to/session.log \
        --cwd /Users/mark/src/myproject \
        --started-at 2026-04-10T08:00:00Z

Also callable directly for manual session registration:
    python3 session_end.py --app ollama --logfile session.log --cwd .
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────

HERE          = Path(__file__).parent
SUBSTRATE_DIR = HERE  # substrate_db.py and autoground_query.py are siblings
AIFILTER      = Path.home() / "bin" / "aifilter"
MODEL         = "gemma3"
OUTPUT_FILE   = "prior_art_notes.md"
LOG_FILE      = Path.home() / ".claude" / "logs" / "session-end.log"
MIN_KEYWORDS  = 3
TOP_K         = 10

sys.path.insert(0, str(SUBSTRATE_DIR))

# ── logging ────────────────────────────────────────────────────────────────────

import logging
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("session-end")

# ── ANSI stripping ─────────────────────────────────────────────────────────────

def _strip_ansi(text: str) -> str:
    """
    Strip ANSI/VT escape sequences using a simple character walk.

    Handles the three common forms found in script(1) log files:
      ESC [ ... letter   — CSI sequences (colors, cursor movement)
      ESC ] ... BEL/ST   — OSC sequences (window title, hyperlinks)
      ESC <any>          — 2-char escapes (charset switches etc.)
    Also drops non-printable control characters except LF and TAB.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '\x1b' and i + 1 < n:
            i += 1
            nxt = text[i]
            if nxt == '[':
                # CSI: skip digits, semicolons, spaces, ? until final letter
                i += 1
                while i < n and text[i] not in (
                    'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
                ):
                    i += 1
                if i < n:
                    i += 1          # consume final letter
            elif nxt == ']':
                # OSC: skip until BEL or ESC\ (ST)
                i += 1
                while i < n:
                    if text[i] == '\x07':
                        i += 1
                        break
                    if text[i] == '\x1b' and i + 1 < n and text[i + 1] == '\\':
                        i += 2
                        break
                    i += 1
            else:
                i += 1              # 2-char escape — skip nxt
        elif c < ' ' and c not in ('\n', '\t', '\r'):
            i += 1                  # drop non-printable control chars
        elif c == '\x7f':
            i += 1
        else:
            out.append(c)
            i += 1
    return ''.join(out)


# ── text extraction ────────────────────────────────────────────────────────────

_STOPWORDS = {
    "a","an","the","and","or","but","in","on","at","to","for","of","with",
    "by","from","up","as","is","was","are","were","be","been","being","have",
    "has","had","do","does","did","will","would","could","should","may","might",
    "i","we","you","he","she","they","it","this","that","these","those","what",
    "how","when","where","why","who","which","can","need","want","let","get",
    "make","use","just","also","so","if","then","all","not","no","yes","ok",
    "yeah","yes","no","got","get","like","think","know","say","said","tell",
}


def extract_text_from_log(logfile: Path, max_chars: int = 20_000) -> str:
    """
    Extract readable text from a script(1) log file.

    Strips ANSI escape sequences, deduplicates repeated lines (TUI noise),
    and returns the last max_chars of clean text — recent content is more
    signal-dense than session startup.
    """
    try:
        raw = logfile.read_text(encoding="utf-8", errors="replace")
    except (OSError, IOError) as e:
        log.warning("could not read log %s: %s", logfile, e)
        return ""

    clean = _strip_ansi(raw)
    # Collapse runs of whitespace/blank lines
    clean = re.sub(r'\n{3,}', '\n\n', clean)
    clean = re.sub(r'[ \t]+', ' ', clean)

    # Take the last max_chars — end of session is most focused
    return clean[-max_chars:].strip()


def extract_text_from_claude_jsonl(session_id: str) -> str:
    """
    For Claude sessions: extract clean text from the JSONL transcript,
    which is richer and cleaner than the script log.

    Returns combined user + assistant text from the last 20 turns.
    """
    projects_root = Path.home() / ".claude" / "projects"
    transcript = None

    for project_dir in projects_root.iterdir():
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            transcript = candidate
            break

    if not transcript:
        return ""

    turns = []
    try:
        for line in transcript.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            rtype = record.get("type")
            if rtype not in ("user", "assistant"):
                continue

            content = record.get("message", {}).get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        turns.append(block.get("text", ""))
            elif isinstance(content, str):
                turns.append(content)
    except (OSError, IOError):
        return ""

    return "\n".join(turns[-20:])


def _python_keywords(text: str) -> list[str]:
    """Stopword-filtered token extraction — fallback when phi4 unavailable."""
    words = re.findall(r"[a-zA-Z][a-zA-Z_\-']{2,}", text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        w = w.strip("'-_")
        if w and w not in _STOPWORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:40]


def extract_keywords(text: str) -> list[str]:
    """
    Extract session keywords via phi4, with Python fallback.

    The keyword set represents the session's semantic fingerprint —
    what the session was actually about after focus narrowed.
    """
    if AIFILTER.exists() and text:
        # Feed last 2000 chars — most focused content
        snippet = text[-2000:]
        try:
            result = subprocess.run(
                [str(AIFILTER), "-b", "keyword_extract", "-m", MODEL],
                input=snippet, capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                kws = [k for k in result.stdout.strip().split() if len(k) > 2]
                if kws:
                    return kws[:40]
        except Exception:
            pass
    return _python_keywords(text)


# ── substrate DB write ─────────────────────────────────────────────────────────

def write_session_node(app: str, cwd: str, logfile: str,
                       started_at: str, ended_at: str,
                       keywords: list[str]) -> str:
    """
    Write a session node to the substrate DB.

    The session node is queryable by keyword the same way project and
    file nodes are — FTS index fires on label, source, and metadata.
    Future prompts whose keywords overlap with this session's keywords
    will surface it as prior context.
    """
    try:
        from substrate_db import SubstrateDB, DEFAULT_DB
        db = SubstrateDB(DEFAULT_DB)

        project = Path(cwd).name

        # Write to sessions table
        sid = db.upsert_session(
            cwd=cwd,
            started_at=started_at,
            ended_at=ended_at,
            keywords=keywords,
        )

        # Write as a node so it's FTS-queryable like files and projects
        label = f"{project} — {ended_at[:10]} ({app})"
        db.upsert_node(
            node_type="session",
            label=label,
            source=logfile,
            metadata={
                "app": app,
                "project": project,
                "cwd": cwd,
                "started_at": started_at,
                "ended_at": ended_at,
                "keywords": keywords[:20],
                "session_id": sid,
            },
        )
        log.info("wrote session node: %s (%d keywords)", label, len(keywords))
        return sid

    except Exception as exc:
        log.warning("substrate DB write failed: %s", exc)
        return ""


# ── prior_art_notes.md render ──────────────────────────────────────────────────

def render_prior_art(nodes: list[dict], cwd: str, keywords: list[str]):
    """
    Write prior_art_notes.md to cwd — context seed for the next session.

    The file is ephemeral and session-scoped. It is the bridge between
    this session's converged knowledge and the next session's starting point.
    The next session's Pool B will find this file and use it as grounding.
    """
    if not nodes:
        return

    # Try phi4 render first
    if AIFILTER.exists():
        try:
            result = subprocess.run(
                [str(AIFILTER), "-b", "summarize_prior_art", "-m", MODEL],
                input=json.dumps(nodes), capture_output=True, text=True,
                timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                markdown = result.stdout.strip()
            else:
                markdown = _render_nodes_plain(nodes)
        except Exception:
            markdown = _render_nodes_plain(nodes)
    else:
        markdown = _render_nodes_plain(nodes)

    output = Path(cwd) / OUTPUT_FILE
    try:
        output.write_text(
            f"# Prior Art — session-end ({len(nodes)} nodes)\n\n"
            f"{markdown}\n\n"
            f"<!-- session keywords: {', '.join(keywords[:15])} -->\n",
            encoding="utf-8",
        )
        log.info("wrote %s (%d nodes)", output, len(nodes))
    except (OSError, IOError) as exc:
        log.warning("could not write %s: %s", output, exc)


def _render_nodes_plain(nodes: list[dict]) -> str:
    """Plain markdown render when phi4 unavailable."""
    lines = []
    for n in nodes:
        label  = n.get("label", "?")
        source = n.get("source", "")
        ntype  = n.get("type", "")
        seen   = n.get("last_seen", "")[:10]
        meta   = n.get("metadata", {})
        kws    = ", ".join(meta.get("keywords", meta.get("top_keywords", []))[:5])
        if source:
            lines.append(f"- [{label}]({source}) ({ntype}, {seen})")
        else:
            lines.append(f"- {label} ({ntype}, {seen})")
        if kws:
            lines.append(f"  keywords: {kws}")
    return "\n".join(lines)


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app",        required=True,
                        help="AI tool name: claude, ollama, gemini, etc.")
    parser.add_argument("--logfile",    required=True, type=Path,
                        help="Path to the session log file")
    parser.add_argument("--cwd",        default="",
                        help="Working directory of the session (default: $PWD)")
    parser.add_argument("--started-at", default="",
                        help="Session start ISO8601 timestamp")
    parser.add_argument("--session-id", default="",
                        help="Claude session UUID (enables JSONL transcript use)")
    args = parser.parse_args()

    cwd        = args.cwd or str(Path.cwd())
    ended_at   = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    started_at = args.started_at or ended_at
    logfile    = str(args.logfile)

    # Extract text — prefer JSONL transcript for Claude, log file for others
    if args.app == "claude" and args.session_id:
        text = extract_text_from_claude_jsonl(args.session_id)
        if not text:
            text = extract_text_from_log(args.logfile)
    else:
        text = extract_text_from_log(args.logfile)

    if not text:
        log.info("no text extracted from %s — skipping", logfile)
        sys.exit(0)

    # Extract keywords — session's semantic fingerprint
    keywords = extract_keywords(text)
    if len(keywords) < MIN_KEYWORDS:
        log.info("too few keywords (%d) from %s — skipping", len(keywords), logfile)
        sys.exit(0)

    log.info("app=%s cwd=%s keywords=%s", args.app, cwd, keywords[:8])

    # Write session node to substrate DB
    write_session_node(
        app=args.app,
        cwd=cwd,
        logfile=logfile,
        started_at=started_at,
        ended_at=ended_at,
        keywords=keywords,
    )

    # Query substrate DB for prior work matching this session's keywords
    try:
        from autoground_query import query
        nodes = query(keywords, top_k=TOP_K)
    except Exception as exc:
        log.warning("substrate query failed: %s", exc)
        nodes = []

    # Write prior_art_notes.md — context seed for next session
    render_prior_art(nodes, cwd, keywords)

    print(f"session-end: {args.app} — {len(keywords)} keywords, "
          f"{len(nodes)} prior nodes → {cwd}/{OUTPUT_FILE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error("unhandled: %s", exc, exc_info=True)
        sys.exit(0)
