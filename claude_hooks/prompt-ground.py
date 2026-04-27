#!/usr/bin/env python3
"""
prompt-ground.py — Claude Code UserPromptSubmit hook: dual-pool prompt grounding.

DESIGN NARRATIVE
================
Every prompt has two signal sources — Pool A and Pool B — that carry
different kinds of information about what the session is working on.

Pool A — the user's prompt text.
    Declared intent. The user's vocabulary, which may be imprecise or
    abbreviated. Already grounded: the user carries their own context and
    history. Pool A does not need the hints — it IS the intent.

Pool B — the most recent model response from the session transcript.
    Interpreted signal. What the model activated and elaborated in response
    to the previous turn. The model's vocabulary tends toward precision and
    expands the semantic scope of A. Pool B is what the hints are FOR —
    the model starts cold each session and needs situating in the user's
    specific prior work.

Matching against both pools separately gives richer signal than either alone:
    - Node confirmed in both A and B: highest confidence — intent and
      elaboration agree. This is a session-central concept.
    - Node in A only: declared intent, not yet elaborated.
    - Node in B only (persistent): model keeps activating this concept
      unprompted across turns. Most interesting case — may surface a
      connection the session hasn't named yet.
    - Node in B only (one-time): may be model bias or injection feedback loop.
      Watch: if a node was injected as context and then appears in B, that is
      the system talking to itself, not a genuine signal.

The seen tracker records (a_count, b_count, last_turn) per node per session.
This is the foundation for the weighted focus accumulation model where
weight = recency × frequency, and the active set narrows as the session
progresses toward what it is actually about.

SESSION CHAIN
=============
Cross-session memory: the last N completed sessions for this project are
injected at the top of every context block. This answers "what was this
project working on before this session started?" — without keyword matching.

The session chain is a direct temporal query on the sessions table, scoped
to the current project (basename of cwd). It fires even when Pool A/B keyword
matching returns nothing — a new session on a known project always gets its
prior context, regardless of what the first prompt says.

REFERENCES
==========
- Reflective Memory Management (ACL 2025): session-level memory with
  response-citation feedback — closest published work to the B-pool concept.
  https://aclanthology.org/2025.acl-long.413.pdf

- MARK architecture (2025): temporal + semantic + feedback-aware scoring
  for memory persistence. Ebbinghaus decay curves for recency weighting.
  https://www.emergentmind.com/topics/memory-augmented-llm

- Memory-Augmented Query Reconstruction (ACL 2025): uses memory to rewrite
  queries before retrieval — adjacent to using B-pool to enrich A-pool queries.
  https://aclanthology.org/2025.findings-acl.1234.pdf

- AriGraph (2024): knowledge graph world models with episodic memory for agents.
  https://arxiv.org/abs/2407.04363

- LongMemEval (2024): benchmark for long-term interactive memory in chat
  assistants — establishes the evaluation framing for this problem space.
  https://arxiv.org/abs/2410.10813

Hook event: UserPromptSubmit
Input:  JSON from stdin — {hook_event_name, prompt, session_id, cwd,
                           transcript_path (optional)}
Output: JSON to stdout — {hookEventName: "UserPromptSubmit",
                          additionalContext: "..."}

The model sees injected context before answering. The prompt is not modified.
All failures exit 0 with empty additionalContext — session is never blocked.
Failures logged to ~/.claude/logs/prompt-ground.log
"""

import json
import logging
import re
import subprocess
import sys
import traceback
from pathlib import Path

# --- config ---
HOME               = Path.home()
SUBSTRATE_DIR      = HOME / "Documents" / "src" / "file_metadata_and_embeddings"
AIFILTER           = HOME / "bin" / "aifilter"
MODEL              = "llama3"
TOP_K              = 8
MIN_KEYWORDS       = 2
SESSION_CHAIN_LIMIT = 3   # prior sessions to surface at session start
DELTA_INTERVAL     = 10  # inject dual-pool diff every N turns (0 = disabled)
LOG_FILE           = HOME / ".claude" / "logs" / "prompt-ground.log"
SEEN_DIR           = HOME / ".claude" / "logs" / "prompt-ground-seen"

# Claude Code transcript root — transcripts live at
# ~/.claude/projects/<slug>/<session_id>.jsonl
TRANSCRIPT_ROOT = HOME / ".claude" / "projects"

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
log = logging.getLogger("prompt-ground")


# ---------------------------------------------------------------------------
# Session state — dual-pool weighted counter
# ---------------------------------------------------------------------------

def _seen_file(session_id: str) -> Path:
    """Per-session state file tracking node match counts across both pools."""
    SEEN_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", session_id)[:32]
    return SEEN_DIR / f"{safe}.json"


def _load_state(session_id: str) -> dict:
    """
    Load session state.

    Returns a dict with:
        nodes: {node_id: {a_count, b_count, last_turn}}
        turn:  current turn number
    """
    p = _seen_file(session_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"nodes": {}, "turn": 0}


def _save_state(session_id: str, state: dict):
    _seen_file(session_id).write_text(json.dumps(state))


# ---------------------------------------------------------------------------
# Pool B — extract most recent assistant response from transcript
# ---------------------------------------------------------------------------

def _find_transcript(session_id: str, transcript_path: str | None) -> Path | None:
    """
    Locate the session transcript JSONL file.

    Tries transcript_path from hook payload first, then searches
    ~/.claude/projects/ for a file matching session_id.
    """
    if transcript_path:
        p = Path(transcript_path)
        if p.exists():
            return p

    # Search all project dirs for a matching session file
    try:
        for project_dir in TRANSCRIPT_ROOT.iterdir():
            candidate = project_dir / f"{session_id}.jsonl"
            if candidate.exists():
                return candidate
    except (OSError, PermissionError):
        pass
    return None


def _extract_pool_b(session_id: str, transcript_path: str | None) -> str:
    """
    Pool B: extract the most recent assistant response text from the transcript.

    This is the model's last elaboration — what it activated and said in
    response to the previous turn. Used as a second signal source alongside
    the current user prompt (Pool A).

    Returns empty string if transcript is unavailable or has no assistant turns.
    """
    tpath = _find_transcript(session_id, transcript_path)
    if not tpath:
        return ""

    try:
        lines = tpath.read_text(encoding="utf-8").strip().split("\n")
    except (OSError, UnicodeDecodeError):
        return ""

    # Walk backward to find the most recent assistant text block
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        if record.get("type") != "assistant":
            continue

        content = record.get("message", {}).get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        return text
        elif isinstance(content, str) and content.strip():
            return content.strip()

    return ""


# ---------------------------------------------------------------------------
# Session chain — cross-session memory
# ---------------------------------------------------------------------------

def _query_session_chain(cwd: str, limit: int = SESSION_CHAIN_LIMIT) -> list[dict]:
    """
    Return the last `limit` completed sessions for this project.

    This is temporal retrieval, not keyword matching. The sessions table is
    queried directly, scoped to the project name (basename of cwd). Sessions
    from all AI tools (claude, ollama, gemini) are returned — the substrate DB
    is tool-agnostic.

    The session chain is the cross-session memory surface: what the project was
    working on before this session. It anchors the model in accumulated context
    without requiring a relevant prompt to trigger it.
    """
    try:
        from substrate_db import SubstrateDB, DEFAULT_DB  # noqa: PLC0415
        db = SubstrateDB(DEFAULT_DB)
        project = Path(cwd).name if cwd else ""
        if not project:
            return []
        return db.recent_sessions(project=project, limit=limit)
    except Exception as exc:
        log.warning("session chain query failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

def _python_keywords(text: str) -> list[str]:
    """
    Fast Python fallback: extract content words without AI.
    Used when Ollama/llama3 is unavailable.
    """
    words = re.findall(r"[a-zA-Z][a-zA-Z_\-']{2,}", text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        w = w.strip("'-_")
        if w and w not in _STOPWORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


def clean_and_extract_keywords(text: str) -> tuple[str, list[str]]:
    """
    Clean the prompt and extract keywords in a single llama3 pass.

    Combines clean_and_tighten + keyword_extract into one LLM call,
    halving the latency vs two sequential calls.

    Returns (cleaned_text, keywords). If aifilter is unavailable or the
    response is malformed, falls back to (original_text, python_keywords).

    The cleaned text is used for:
      - Display: written to /dev/tty so the user sees the corrected prompt
        in the shell before Claude responds.
      - Retrieval: keyword matching against the substrate DB. Typos break
        FTS5 matching; clean keywords are essential here.

    The raw prompt is never modified — Claude still sees the original.

    Research note: frontier LLMs tolerate naturalistic typos in conversation,
    but retrieval pipelines (FTS5, BM25, embedding search) degrade measurably
    on malformed queries. The cleanup earns its cost at the retrieval step,
    not at the LLM input boundary. (SIGKDD 2024; arXiv 2504.08231)
    """
    if AIFILTER.exists():
        try:
            result = subprocess.run(
                [str(AIFILTER), "-b", "clean_and_keywords", "-m", MODEL],
                input=text, capture_output=True, text=True, timeout=25,
            )
            if result.returncode == 0 and result.stdout.strip():
                cleaned, keywords = _parse_clean_and_keywords(result.stdout)
                if keywords:
                    return cleaned or text, keywords
        except Exception:
            pass
    return text, _python_keywords(text)


def _parse_clean_and_keywords(output: str) -> tuple[str, list[str]]:
    """
    Parse the two-line output from clean_and_keywords behavior.

    Expected format:
        CLEANED: <corrected prompt>
        KEYWORDS: <space-separated keywords>

    Returns (cleaned, keywords). Either may be empty if parsing fails.
    """
    cleaned = ""
    keywords: list[str] = []
    for line in output.strip().splitlines():
        if line.startswith("CLEANED:"):
            cleaned = line[len("CLEANED:"):].strip()
        elif line.startswith("KEYWORDS:"):
            raw = line[len("KEYWORDS:"):].strip()
            keywords = [k for k in raw.split() if len(k) > 2]
    return cleaned, keywords


def extract_keywords(text: str) -> list[str]:
    """
    Extract intent keywords from text via llama3, with Python fallback.

    Used for Pool B (model response) only — Pool A uses clean_and_extract_keywords.
    llama3 understands intent and expands abbreviations; the Python fallback
    is stopword-filtered token extraction — sufficient for most cases.
    """
    if AIFILTER.exists():
        try:
            result = subprocess.run(
                [str(AIFILTER), "-b", "keyword_extract", "-m", MODEL],
                input=text, capture_output=True, text=True, timeout=20,
            )
            if result.returncode == 0 and result.stdout.strip():
                kws = [k for k in result.stdout.strip().split() if len(k) > 2]
                if kws:
                    return kws
        except Exception:
            pass
    return _python_keywords(text)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_context(nodes: list[dict], pool_labels: dict[str, str],
                   kw_a: list[str] | None = None,
                   kw_b: list[str] | None = None) -> str:
    """
    Format matching nodes as prior-work context with pool attribution and
    term evidence.

    pool_labels maps node_id → "A", "B", or "A+B".
    kw_a / kw_b are the keyword sets that drove the search, included in the
    header so the model understands the association chain.
    """
    if not nodes:
        return ""

    # Header explains the mechanism so the model treats this as background
    # awareness injected by the memory system, not as user directives.
    kw_a_str = ", ".join((kw_a or [])[:6]) or "—"
    kw_b_str = ", ".join((kw_b or [])[:6]) or "—"
    lines = [
        "## Autoground Context",
        "The following files were surfaced automatically by matching terms from",
        "your prompt and the prior model response against your indexed project",
        "history. This is a processing artifact — not your explicit request.",
        "Use it as background awareness to extend the historical horizon.",
        f"  prompt terms:   {kw_a_str}",
        f"  response terms: {kw_b_str}",
        "",
    ]
    for n in nodes:
        label  = n.get("label", "unknown")
        source = n.get("source", "")
        ntype  = n.get("type", "")
        seen   = n.get("last_seen", "")[:10]
        nid    = n.get("id") or source
        pool   = pool_labels.get(nid, "")
        tag    = f" [{pool}]" if pool else ""
        if source:
            lines.append(f"- [{label}]({source}) ({ntype}, {seen}){tag}")
        else:
            lines.append(f"- {label} ({ntype}, {seen}){tag}")
    return "\n".join(lines)


def read_prior_art(cwd: str) -> str:
    """
    Read prior_art_notes.md from the project directory if it exists.

    This file is written by autoground.py (Stop hook) at the end of each
    session — it contains a substrate DB summary of what the session worked
    on. Reading it here connects the two hooks: Stop writes the summary,
    Submit reads it and includes it as labelled prior-session context.

    The file is ephemeral and globally gitignored. It is session-scoped:
    it reflects the most recently completed session for this project.
    """
    p = Path(cwd) / "prior_art_notes.md"
    if not p.exists():
        return ""
    try:
        text = p.read_text(encoding="utf-8").strip()
        if not text or "prior art render failed" in text:
            return ""
        return "## Prior Session Summary (autoground Stop hook)\n\n" + text
    except OSError:
        return ""


def format_session_chain(sessions: list[dict]) -> str:
    """
    Format recent sessions as a compact session history block.

    Terse by design: date, project, top keywords. The model uses this to
    avoid re-explaining prior-session context and to recognise when a prompt
    continues work from a previous session.

    Keywords are stored as a JSON array in the sessions table; we show the
    first 8 — enough to convey the session's semantic fingerprint without
    consuming significant context budget.
    """
    if not sessions:
        return ""
    lines = ["## Session History"]
    for s in sessions:
        date    = (s.get("started_at") or "")[:10]
        project = s.get("project", "?")
        try:
            kws = json.loads(s.get("keywords") or "[]")[:8]
        except (json.JSONDecodeError, TypeError):
            kws = []
        kw_str = ", ".join(kws) if kws else "—"
        lines.append(f"- {date} {project}: {kw_str}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def score_node(entry: dict, turn: int) -> float:
    """
    Score a single node entry for injection priority this turn.

    Parameters
    ----------
    entry : dict with keys a_count, b_count, last_turn, shown_count, last_shown
    turn  : current turn number (1-based)

    Returns a non-negative float; higher = more injection-worthy.

    Scoring model: pool_weight × frequency × match_recency × staleness

    pool_weight   — A+B confirmed nodes outrank A-only or B-only
    frequency     — total independent matches (a_count + b_count)
    match_recency — 1 / (turns since last independent match + 1); decays
                    between matches, resets when the node matches again
    staleness     — min(1, frequency / shown_count); penalises nodes that
                    are re-injected more than they independently match,
                    catching injection feedback loops
    """
    a          = entry.get("a_count", 0)
    b          = entry.get("b_count", 0)
    shown      = entry.get("shown_count", 0)
    last_match = entry.get("last_turn", 0)

    match_recency = 1.0 / max(turn - last_match + 1, 1)
    pool_weight   = 3.0 if (a > 0 and b > 0) else (2.0 if a > 0 else 1.0)
    frequency     = a + b

    staleness = min(1.0, frequency / shown) if shown > 0 else 1.0

    return pool_weight * frequency * match_recency * staleness


def min_score_for_turn(turn: int) -> float:
    """
    Dynamic threshold: 0 at turn 1, asymptotes to 0.4 by turn ~10.

    Early turns accept everything (wide exploration).
    Later turns require accumulated independent confirmation.
    """
    return 0.4 * (1.0 - 1.0 / max(turn, 1))


def take_snapshot(node_state: dict) -> dict:
    """Capture a minimal snapshot of current A/B counts per node."""
    return {
        nid: {"a": e.get("a_count", 0), "b": e.get("b_count", 0)}
        for nid, e in node_state.items()
    }


def compute_delta(prev: dict, node_state: dict, turn: int) -> dict:
    """
    Diff current node state against a previous snapshot.

    Returns dict with four lists:
      new_ab       — both pools confirmed, neither was in prev
      promoted     — was A-only in prev, now A+B
      b_persistent — B-only across multiple turns (model surfacing unprompted)
      faded        — matched before turn-DELTA_INTERVAL, silent since
    """
    new_ab, promoted, b_persistent, faded = [], [], [], []
    all_ids = set(node_state) | set(prev)

    for nid in all_ids:
        cur = node_state.get(nid, {})
        pre = prev.get(nid, {"a": 0, "b": 0})
        a, b       = cur.get("a_count", 0), cur.get("b_count", 0)
        pa, pb     = pre["a"], pre["b"]
        last_turn  = cur.get("last_turn", 0)

        if a > 0 and b > 0 and pa == 0 and pb == 0:
            new_ab.append(nid)
        elif a > 0 and b > 0 and pa > 0 and pb == 0:
            promoted.append(nid)
        elif a == 0 and b > 1:
            b_persistent.append(nid)
        elif (pa > 0 or pb > 0) and last_turn < (turn - DELTA_INTERVAL):
            faded.append(nid)

    return {"new_ab": new_ab, "promoted": promoted,
            "b_persistent": b_persistent, "faded": faded}


def format_delta(delta: dict, nodes: dict, turn: int) -> str:
    """Format the dual-pool delta as a labelled context block."""
    def label(nid: str) -> str:
        n = nodes.get(nid, {})
        return n.get("label") or n.get("source") or nid

    lines = [
        f"## Autoground Delta — turn {turn}",
        "Shift in session focus since last snapshot. System artifact — not your request.",
        "",
    ]
    if delta["new_ab"]:
        lines.append("**Newly confirmed (A+B):** "
                     + ", ".join(label(n) for n in delta["new_ab"]))
    if delta["promoted"]:
        lines.append("**Promoted A→A+B:** "
                     + ", ".join(label(n) for n in delta["promoted"]))
    if delta["b_persistent"]:
        lines.append("**Persistent model signal (B-only):** "
                     + ", ".join(label(n) for n in delta["b_persistent"]))
    if delta["faded"]:
        lines.append("**Faded:** "
                     + ", ".join(label(n) for n in delta["faded"]))
    return "\n".join(lines)


def _empty_response() -> str:
    return json.dumps({
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "",
    })


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(_empty_response())
        sys.exit(0)

    prompt          = payload.get("prompt", "").strip()
    session_id      = payload.get("session_id", "unknown")
    cwd             = payload.get("cwd", "") or str(Path.cwd())
    transcript_path = payload.get("transcript_path", "")

    if not prompt:
        print(_empty_response())
        sys.exit(0)

    # --- Session chain: cross-session memory (temporal, not keyword-based) ---
    # Always query regardless of what the prompt says — a new session on a
    # known project should see its history from the first turn.
    session_chain   = _query_session_chain(cwd)
    chain_block     = format_session_chain(session_chain)
    prior_art_block = read_prior_art(cwd)
    log.info("session chain: %d sessions for %s — prior_art: %s",
             len(session_chain), Path(cwd).name, "yes" if prior_art_block else "no")

    # --- Pool A: clean + extract keywords in one llama3 pass ---
    # The raw prompt goes to Claude unchanged.
    # The cleaned version is used for: (a) substrate DB keyword matching,
    # (b) display in the UI so the user sees what was corrected.
    prompt_clean, kw_a = clean_and_extract_keywords(prompt)
    if prompt_clean != prompt:
        log.info("pool A cleaned: %s → %s", prompt[:50], prompt_clean[:50])
    log.info("pool A keywords: %s", kw_a[:5])

    if len(kw_a) < MIN_KEYWORDS:
        log.info("pool A too few keywords (%d): %s", len(kw_a), prompt[:60])
        # Still inject session chain even if prompt is too thin to keyword-match
        if chain_block:
            print(json.dumps({
                "hookEventName": "UserPromptSubmit",
                "additionalContext": chain_block,
            }))
        else:
            print(_empty_response())
        sys.exit(0)

    # --- Pool B: most recent model response ---
    pool_b_text = _extract_pool_b(session_id, transcript_path)
    kw_b = extract_keywords(pool_b_text) if pool_b_text else []

    log.info("pool A keywords: %s", kw_a[:5])
    log.info("pool B keywords: %s", kw_b[:5])

    # --- Query substrate DB for each pool independently ---
    nodes_a: dict = {}
    nodes_b: dict = {}
    try:
        from autoground_query import query  # noqa: PLC0415
        nodes_a = {
            (n.get("id") or n.get("source", "")): n
            for n in query(kw_a, top_k=TOP_K * 2)
        }
        nodes_b = {
            (n.get("id") or n.get("source", "")): n
            for n in (query(kw_b, top_k=TOP_K * 2) if kw_b else [])
        }
    except Exception as exc:
        log.warning("DB query failed: %s", exc)
        # Still surface the session chain if DB is unavailable
        if chain_block:
            print(json.dumps({
                "hookEventName": "UserPromptSubmit",
                "additionalContext": chain_block,
            }))
        else:
            print(_empty_response())
        sys.exit(0)

    # --- Load session state and update dual-pool match counts ---
    state = _load_state(session_id)
    turn  = state["turn"] + 1
    state["turn"] = turn
    node_state = state["nodes"]

    all_node_ids = set(nodes_a.keys()) | set(nodes_b.keys())
    for nid in all_node_ids:
        entry = node_state.get(nid, {"a_count": 0, "b_count": 0, "last_turn": 0,
                                     "shown_count": 0, "last_shown": 0})
        if nid in nodes_a:
            entry["a_count"] = entry.get("a_count", 0) + 1
        if nid in nodes_b:
            entry["b_count"] = entry.get("b_count", 0) + 1
        entry["last_turn"] = turn
        node_state[nid] = entry

    all_nodes = {**nodes_b, **nodes_a}  # A overwrites B for the node object
    ranked = sorted(
        all_nodes.keys(),
        key=lambda nid: score_node(node_state.get(nid, {}), turn),
        reverse=True,
    )

    min_score  = min_score_for_turn(turn)
    selected_ids = [
        nid for nid in ranked
        if score_node(node_state.get(nid, {}), turn) >= min_score
    ][:TOP_K]
    selected_nodes = [all_nodes[nid] for nid in selected_ids]

    # --- Update shown_count for injected nodes, then persist state ---
    for nid in selected_ids:
        entry = node_state.get(nid, {"a_count": 0, "b_count": 0, "last_turn": 0,
                                     "shown_count": 0, "last_shown": 0})
        entry["shown_count"] = entry.get("shown_count", 0) + 1
        entry["last_shown"]  = turn
        node_state[nid] = entry

    state["nodes"] = node_state

    # --- Dual-pool delta: snapshot at turn 1, diff every DELTA_INTERVAL turns ---
    delta_block = ""
    if DELTA_INTERVAL > 0:
        snapshots = state.setdefault("snapshots", {})
        if turn == 1:
            snapshots["0"] = take_snapshot(node_state)
        if turn > 0 and turn % DELTA_INTERVAL == 0:
            prev_key = str(turn - DELTA_INTERVAL)
            prev_snapshot = snapshots.get(prev_key, {})
            delta = compute_delta(prev_snapshot, node_state, turn)
            snapshots[str(turn)] = take_snapshot(node_state)
            # Keep only last 2 snapshots to bound state file size
            for old_key in [k for k in snapshots if k not in (prev_key, str(turn), "0")]:
                del snapshots[old_key]
            if any(delta.values()):
                delta_block = format_delta(delta, all_nodes, turn)
                log.info("turn %d delta — new_ab:%d promoted:%d b_persist:%d faded:%d",
                         turn, len(delta["new_ab"]), len(delta["promoted"]),
                         len(delta["b_persistent"]), len(delta["faded"]))

    _save_state(session_id, state)

    # Build pool labels for display
    pool_labels = {}
    for nid in selected_ids:
        in_a = nid in nodes_a
        in_b = nid in nodes_b
        pool_labels[nid] = "A+B" if (in_a and in_b) else ("A" if in_a else "B")

    nodes_block = format_context(selected_nodes, pool_labels, kw_a=kw_a, kw_b=kw_b)

    log.info(
        "turn %d (min_score=%.2f) — chain:%d A:%d B:%d selected:%d (A+B=%d A=%d B=%d)",
        turn, min_score,
        len(session_chain),
        len(nodes_a), len(nodes_b), len(selected_nodes),
        sum(1 for v in pool_labels.values() if v == "A+B"),
        sum(1 for v in pool_labels.values() if v == "A"),
        sum(1 for v in pool_labels.values() if v == "B"),
    )

    # --- Assemble final context ---
    # Cleaned prompt first (so the user sees it and the model gets clean intent),
    # then session chain (temporal anchor), then keyword-matched prior work.
    cleaned_block = ""
    if prompt_clean != prompt:
        cleaned_block = f"**[autoground cleaned]** {prompt_clean}"
        try:
            with open("/dev/tty", "w") as tty:
                tty.write(f"[autoground] {prompt_clean}\n")
        except OSError:
            pass
    parts = [p for p in (cleaned_block, prior_art_block, chain_block, nodes_block, delta_block) if p]
    final_context = "\n\n".join(parts)

    if not final_context:
        print(_empty_response())
        sys.exit(0)

    print(json.dumps({
        "hookEventName": "UserPromptSubmit",
        "additionalContext": final_context,
    }))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error("unhandled exception: %s\n%s", exc, traceback.format_exc())
        print(_empty_response())
        sys.exit(0)
