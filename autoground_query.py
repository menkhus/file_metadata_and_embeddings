#!/usr/bin/env python3
"""
autoground_query.py — Query the substrate DB given keywords, return matching nodes.

This is the core primitive. Used by:
  - autoground.py (Stop hook)
  - the prompt micro-processing pipe
  - MCP tool ground_prompt()

Usage (standalone — reads keywords from stdin, one per line or space-separated):
    echo "knowledge graph grounding" | python3 autoground_query.py
    python3 autoground_query.py "knowledge graph" "LoRA" "session"

Output: JSON array of matching nodes, sorted by relevance (last_seen desc).

Usage (as a library):
    from autoground_query import query
    nodes = query(["knowledge graph", "grounding", "LoRA"], top_k=10)
"""

import json
import sys
from pathlib import Path

# Allow running from any cwd
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from substrate_db import SubstrateDB, DEFAULT_DB


def _sanitize_keyword(kw: str) -> str:
    """Strip characters that break FTS5 query syntax (apostrophes, quotes, operators)."""
    # FTS5 treats ' as a quote delimiter and special chars as operators
    kw = kw.replace("'", "").replace('"', '').replace("*", "")
    kw = kw.strip("-+^():")
    return kw.strip()


def query(keywords: list[str], top_k: int = 10,
          db_path: Path | None = None) -> list[dict]:
    """Return top_k substrate nodes matching keywords.

    Deduplicates across keywords. Returns dicts with keys:
        id, type, label, source, last_seen, metadata (parsed JSON)
    """
    db = SubstrateDB(db_path or DEFAULT_DB)
    raw = db.query_by_keywords(keywords, top_k=top_k)

    results = []
    for node in raw:
        try:
            node["metadata"] = json.loads(node.get("metadata") or "{}")
        except (json.JSONDecodeError, TypeError):
            node["metadata"] = {}
        results.append(node)

    # Sort: most recently seen first
    results.sort(key=lambda n: n.get("last_seen", ""), reverse=True)
    return results[:top_k]


def _parse_keywords_from_stdin() -> list[str]:
    """Read stdin: split on whitespace and commas, strip empty strings."""
    text = sys.stdin.read().strip()
    # Support both newline-separated and space-separated
    tokens = [t.strip().strip(",") for t in text.replace("\n", " ").split()]
    return [t for t in tokens if t]


def _render_nodes(nodes: list[dict]) -> str:
    """Render nodes as compact JSON for pipe consumption."""
    return json.dumps(nodes, indent=2)


if __name__ == "__main__":
    # Keywords from args or stdin
    if len(sys.argv) > 1:
        keywords = list(sys.argv[1:])
    elif not sys.stdin.isatty():
        keywords = _parse_keywords_from_stdin()
    else:
        print("Usage: echo 'keyword1 keyword2' | autoground_query.py", file=sys.stderr)
        print("       autoground_query.py keyword1 keyword2 ...", file=sys.stderr)
        sys.exit(1)

    top_k = int(sys.argv[-1]) if sys.argv[-1:] and sys.argv[-1].isdigit() else 10

    nodes = query(keywords, top_k=top_k)

    if not nodes:
        # Emit empty array — pipe continues cleanly
        print("[]")
    else:
        print(_render_nodes(nodes))
