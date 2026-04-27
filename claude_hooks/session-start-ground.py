#!/usr/bin/env python3
"""
session-start-ground.py — SessionStart hook: prior-art grounding at session open.

Fires once when a session opens. Finds the most recently completed transcript
for this project (previous session in ~/.claude/projects/<slug>/), extracts
the last 10 user prompts as Pool A and the last 5 assistant responses as Pool B,
queries the substrate DB, and writes prior_art_notes.md into the cwd.

Pool A (user prompts): declared intent — the user's fingerprint of what the
session was working toward. Precise but terse.

Pool B (assistant responses): elaborated intent — the model's expansion of that
intent into richer vocabulary, named concepts, and surfaced connections. Captures
what the prior session's reasoning *became*, not just what it was asked about.

Keywords confirmed in both pools (A+B) are prioritized in the DB query,
mirroring the dual-pool weighting in prompt-ground.py.

prompt-ground.py (UserPromptSubmit hook) reads prior_art_notes.md on the first
prompt and injects it as labelled prior-session context. This hook just produces
the file — injection happens through the existing pipeline.

Rationale for doing this at SessionStart rather than Stop:
  - Stop hook runs after the session — if the user force-quits, it may not fire
  - SessionStart is deterministic: it always runs before the first prompt
  - Reads the previous session's transcript directly — no dependency on the
    prior session's Stop hook having succeeded

Project slug derivation: Claude Code stores transcripts at
  ~/.claude/projects/<slug>/<session_id>.jsonl
where slug = cwd.replace('/', '-'). The previous session is the most recently
modified .jsonl in that directory that is not the current session_id.

Hook event: SessionStart
Input:  JSON from stdin — {session_id, cwd, ...}
Output: JSON to stdout — {"continue": true} (no additionalContext — that is
        handled by prompt-ground.py reading prior_art_notes.md on first prompt)
Writes: <cwd>/prior_art_notes.md  (ephemeral, globally gitignored)

All failures exit 0 silently — never block session start.
"""

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

# --- config ---
SUBSTRATE_DIR   = Path.home() / "Documents" / "src" / "file_metadata_and_embeddings"
AIFILTER        = Path.home() / "bin" / "aifilter"
MODEL           = "llama3"
TOP_K           = 10
MIN_KEYWORDS    = 2
PROMPT_LOOKBACK   = 10     # last N user prompts from previous session (Pool A)
RESPONSE_LOOKBACK = 5      # last N assistant responses from previous session (Pool B)
OUTPUT_FILE     = "prior_art_notes.md"
TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"
LOG_FILE        = Path.home() / ".claude" / "logs" / "session-start-ground.log"

_STOPWORDS = {
    "a","an","the","and","or","but","in","on","at","to","for","of","with",
    "by","from","up","as","is","was","are","were","be","been","being","have",
    "has","had","do","does","did","will","would","could","should","may","might",
    "i","we","you","he","she","they","it","this","that","these","those","what",
    "how","when","where","why","who","which","can","need","want","let","get",
    "make","use","just","also","so","if","then","all","not","no","yes",
}

sys.path.insert(0, str(SUBSTRATE_DIR))

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("session-start-ground")


def cwd_to_slug(cwd: str) -> str:
    """Derive the ~/.claude/projects slug for a given cwd path.

    Claude Code converts the cwd to a directory name by replacing '/' with '-'.
    Example: /Users/mark/Documents/src/foo → -Users-mark-Documents-src-foo
    """
    return cwd.replace("/", "-")


def find_previous_transcript(cwd: str, current_session_id: str) -> Path | None:
    """Find the most recently modified session transcript for this project
    that is not the current session."""
    slug = cwd_to_slug(cwd)
    project_dir = TRANSCRIPT_ROOT / slug
    if not project_dir.exists():
        return None

    candidates = [
        f for f in project_dir.glob("*.jsonl")
        if f.stem != current_session_id
    ]
    if not candidates:
        return None

    return max(candidates, key=lambda f: f.stat().st_mtime)


def extract_user_prompts(transcript: Path, n: int = PROMPT_LOOKBACK) -> str:
    """Extract the last N user prompt texts from a session transcript JSONL."""
    prompts = []
    try:
        for line in transcript.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "user":
                continue
            content = record.get("message", {}).get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            prompts.append(text)
            elif isinstance(content, str) and content.strip():
                prompts.append(content.strip())
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("could not read transcript %s: %s", transcript, exc)
        return ""

    return "\n".join(prompts[-n:]).strip()


def extract_assistant_responses(transcript: Path, n: int = RESPONSE_LOOKBACK) -> str:
    """Extract the last N assistant response texts from a session transcript JSONL.

    Assistant responses are longer and more semantically dense than user prompts.
    They capture the elaborated, precise vocabulary the model settled on — what
    the prior session's reasoning became, not just what it was asked about.
    """
    responses = []
    try:
        for line in transcript.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "assistant":
                continue
            content = record.get("message", {}).get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            responses.append(text)
            elif isinstance(content, str) and content.strip():
                responses.append(content.strip())
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("could not read transcript %s: %s", transcript, exc)
        return ""

    return "\n".join(responses[-n:]).strip()


def merge_keywords(kw_a: list[str], kw_b: list[str]) -> list[str]:
    """Merge Pool A and Pool B keywords with A+B confirmed terms first.

    Order: A+B intersection (highest confidence) → A-only → B-only.
    Preserves A ordering within each group; deduplicates across groups.
    """
    set_b = set(kw_b)
    set_a = set(kw_a)
    ab     = [k for k in kw_a if k in set_b]
    a_only = [k for k in kw_a if k not in set_b]
    b_only = [k for k in kw_b if k not in set_a]
    return ab + a_only + b_only


def _python_keywords(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z_\-']{2,}", text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        w = w.strip("'-_")
        if w and w not in _STOPWORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


def extract_keywords(text: str) -> list[str]:
    """Extract intent keywords via llama3/aifilter, Python fallback."""
    if AIFILTER.exists():
        try:
            result = subprocess.run(
                [str(AIFILTER), "-b", "keyword_extract", "-m", MODEL],
                input=text, capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                kws = [k for k in result.stdout.strip().split() if len(k) > 2]
                if kws:
                    return kws
        except Exception:
            pass
    return _python_keywords(text)


def render_prior_art(nodes: list[dict]) -> str:
    """Render nodes as terse markdown via llama3/aifilter."""
    if AIFILTER.exists():
        try:
            result = subprocess.run(
                [str(AIFILTER), "-b", "summarize_prior_art", "-m", MODEL],
                input=json.dumps(nodes), capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
    # Fallback: plain list
    lines = []
    for n in nodes:
        label  = n.get("label", "unknown")
        source = n.get("source", "")
        ntype  = n.get("type", "")
        seen   = (n.get("last_seen") or "")[:10]
        lines.append(f"- [{label}]({source}) ({ntype}, {seen})" if source
                     else f"- {label} ({ntype}, {seen})")
    return "\n".join(lines)


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        payload = {}

    session_id = payload.get("session_id", "")
    cwd        = payload.get("cwd", "") or os.getcwd()

    if not session_id:
        sys.exit(0)

    transcript = find_previous_transcript(cwd, session_id)
    if not transcript:
        log.info("no previous transcript found for %s", Path(cwd).name)
        sys.exit(0)

    prompt_text = extract_user_prompts(transcript)
    if not prompt_text:
        log.info("no user prompts in %s", transcript.name)
        sys.exit(0)

    response_text = extract_assistant_responses(transcript)

    kw_a = extract_keywords(prompt_text)
    kw_b = extract_keywords(response_text) if response_text else []
    keywords = merge_keywords(kw_a, kw_b)

    if len(keywords) < MIN_KEYWORDS:
        log.info("too few keywords (%d) from %s", len(keywords), transcript.name)
        sys.exit(0)

    ab_count = sum(1 for k in kw_a if k in set(kw_b))
    log.info("previous session: %s — A:%d B:%d A+B:%d merged:%d — top: %s",
             transcript.name, len(kw_a), len(kw_b), ab_count, len(keywords), keywords[:8])

    try:
        from autoground_query import query  # noqa: PLC0415
        nodes = query(keywords, top_k=TOP_K)
    except Exception as exc:
        log.warning("DB query failed: %s", exc)
        sys.exit(0)

    if not nodes:
        log.info("no matching nodes for keywords: %s", keywords[:5])
        sys.exit(0)

    markdown = render_prior_art(nodes)
    output = Path(cwd) / OUTPUT_FILE
    try:
        output.write_text(
            f"# Prior Art — session-start-ground ({len(nodes)} nodes)\n\n"
            f"{markdown}\n\n"
            f"<!-- source: {transcript.name} -->\n"
            f"<!-- pool A (prompts): {', '.join(kw_a[:8])} -->\n"
            f"<!-- pool B (responses): {', '.join(kw_b[:8])} -->\n",
            encoding="utf-8",
        )
        log.info("wrote %s (%d nodes)", output, len(nodes))
    except OSError as exc:
        log.warning("could not write %s: %s", output, exc)

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error("unhandled: %s", exc)
        sys.exit(0)
