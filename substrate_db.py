#!/usr/bin/env python3
"""
substrate_db.py — Personal knowledge substrate database

SQLite DB computed from work sessions, file analysis, and external signals.
Schema: sessions, nodes, edges, signals, nodes_fts (full-text search)

Self-labeling: keywords come from TF-IDF/LDA (already computed by file_metadata).
No curation required. The work labels itself.

Default DB path: ~/data/substrate.sqlite3
"""

import sqlite3
import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_DB = Path.home() / "data" / "substrate.sqlite3"

# Bump this when any table is added, removed, or altered.
# _upsert_readme() inserts a new versioned row on every schema init,
# so the full change history is preserved in the readme table.
SCHEMA_VERSION = 2

SCHEMA = """
-- ─────────────────────────────────────────────────────────────────────────────
-- substrate.sqlite3  —  personal knowledge substrate
-- ─────────────────────────────────────────────────────────────────────────────
-- This database is the grounding and memory layer for AI sessions.
-- It stores session fingerprints, project/file knowledge graph nodes,
-- cross-session edges, and keyword signal detections.
--
-- It is NOT the file index (that is ~/data/file_metadata.sqlite3).
-- It IS the layer that connects sessions to prior work.
--
-- Schema managed by: substrate_db.py (SubstrateDB._init_schema)
-- Default path:      ~/data/substrate.sqlite3
-- ─────────────────────────────────────────────────────────────────────────────

-- readme
--   Self-documentation table.  One row per schema version.  The highest
--   version row is current; older rows are history.
--   Created by:  substrate_db.py (_init_schema → _upsert_readme)
--   Updated by:  substrate_db.py on every init when SCHEMA_VERSION increases
CREATE TABLE IF NOT EXISTS readme (
    version     INTEGER PRIMARY KEY,  -- matches SCHEMA_VERSION constant
    updated_at  TEXT,                 -- ISO8601, set at init time
    content     TEXT                  -- full human-readable schema description
);

-- sessions
--   One row per AI session (claude, ollama, gemini, etc.).
--   Records the working directory, start/end timestamps, and the keyword
--   fingerprint extracted at session end by the LLM (gemma3/phi4).
--   Created by:  substrate_db.py (this schema)
--   Written by:  session_end.py  (upsert_session, called from _logged_ai shell wrapper)
--   Read by:     prompt-ground.py (recent_sessions → session chain injection)
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,   -- SHA256 of cwd+started_at
    cwd         TEXT,               -- absolute working directory of the session
    project     TEXT,               -- basename of cwd
    started_at  TEXT,               -- ISO8601
    ended_at    TEXT,               -- ISO8601
    keywords    TEXT                -- JSON array of keywords extracted post-session
);

-- nodes
--   Knowledge graph nodes — projects, files, sessions, papers, concepts, skills.
--   FTS-queryable via nodes_fts virtual table (kept in sync by triggers below).
--   type values: project | session | file | paper | concept | skill
--   Created by:  substrate_db.py (this schema)
--   Written by:  extract_idea_signatures.py  (project + file nodes, batch ingest)
--                session_end.py              (session nodes, one per session)
--   Read by:     autoground_query.py         (query_by_keywords → prompt grounding)
--                prompt-ground.py            (UserPromptSubmit hook)
--                autoground.py               (Stop hook)
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,   -- SHA256 of type+source
    type        TEXT,               -- project | session | file | paper | concept | skill
    label       TEXT,               -- human-readable display name
    source      TEXT,               -- file path, arXiv URL, or 'unpublished'
    first_seen  TEXT,               -- ISO8601
    last_seen   TEXT,               -- ISO8601, updated on every upsert
    metadata    TEXT                -- JSON: keywords, project, cwd, app, etc.
);

-- edges
--   Directed relationships between nodes.
--   relation values: matched | cited | evolved_from | session_referenced | skill_used
--   Created by:  substrate_db.py (this schema)
--   Written by:  (not yet wired — 0 rows as of schema v2)
--   Intended for: linking session nodes to the file/project nodes they referenced
CREATE TABLE IF NOT EXISTS edges (
    from_id     TEXT,
    to_id       TEXT,
    relation    TEXT,               -- matched | cited | evolved_from | session_referenced | skill_used
    score       REAL,               -- confidence or strength of relation
    created_at  TEXT,               -- ISO8601
    session_id  TEXT,               -- which session created this edge
    PRIMARY KEY (from_id, to_id, relation)
);

-- signals
--   Novel keyword detections from external sources (arXiv, blogs, etc.).
--   is_new=1 means first time this keyword+source_url pair was seen.
--   The is_new flag IS the signal — it resets to 0 after acknowledgement.
--   Created by:  substrate_db.py (this schema)
--   Written by:  (not yet wired — 0 rows as of schema v2)
CREATE TABLE IF NOT EXISTS signals (
    id          TEXT PRIMARY KEY,   -- SHA256 of keyword+source_url
    keyword     TEXT,
    source_url  TEXT,
    title       TEXT,
    abstract    TEXT,
    detected_at TEXT,               -- ISO8601
    is_new      INTEGER DEFAULT 1   -- 1 if first time seen — this IS the signal
);

-- nodes_fts
--   FTS5 virtual table mirroring nodes for keyword search.
--   Kept in sync with nodes via INSERT/UPDATE/DELETE triggers below.
--   Never written directly — always via trigger.
--   Created by:  substrate_db.py (this schema)
--   Read by:     autoground_query.py (query_by_keywords, MATCH queries)
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts
    USING fts5(id UNINDEXED, label, source, metadata, content='nodes', content_rowid='rowid');

CREATE TRIGGER IF NOT EXISTS nodes_fts_insert AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts(rowid, id, label, source, metadata)
    VALUES (new.rowid, new.id, new.label, new.source, new.metadata);
END;

CREATE TRIGGER IF NOT EXISTS nodes_fts_update AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, id, label, source, metadata)
    VALUES ('delete', old.rowid, old.id, old.label, old.source, old.metadata);
    INSERT INTO nodes_fts(rowid, id, label, source, metadata)
    VALUES (new.rowid, new.id, new.label, new.source, new.metadata);
END;

CREATE TRIGGER IF NOT EXISTS nodes_fts_delete AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, id, label, source, metadata)
    VALUES ('delete', old.rowid, old.id, old.label, old.source, old.metadata);
END;
"""

# Human-readable content written into the readme table at SCHEMA_VERSION.
# Update this block whenever SCHEMA_VERSION is bumped.
_README_VERSIONS = {
    1: """\
substrate.sqlite3 — personal knowledge substrate
=================================================
Schema version 1 (initial)

Tables: sessions, nodes, edges, signals, nodes_fts
""",
    2: """\
substrate.sqlite3 — personal knowledge substrate
=================================================
Schema version 2 — added readme table for self-documentation

RELATED DATABASES
-----------------
~/data/file_metadata.sqlite3
    40K+ indexed files, TF-IDF keywords, FAISS embeddings, FTS5 full-text.
    Managed by: file_metadata_content.py (indexing), build_faiss_index.py (FAISS),
                mcp_server_fixed.py (MCP read layer).
    Read by extract_idea_signatures.py to populate nodes in this database.

~/data/substrate.sqlite3  (this file)
    Session memory, knowledge graph, grounding layer.
    Managed by: substrate_db.py

TABLE REGISTRY
--------------
readme          Versioned self-documentation. One row per schema version.
                Created/updated by: substrate_db.py (_upsert_readme)

sessions        One row per AI session (claude, ollama, gemini, etc.).
                Keyword fingerprint extracted at session end.
                Written by: session_end.py
                Read by:    prompt-ground.py (session chain injection)

nodes           Knowledge graph nodes: project | session | file | paper | concept | skill
                Written by: extract_idea_signatures.py (project/file nodes)
                            session_end.py (session nodes)
                Read by:    autoground_query.py, prompt-ground.py, autoground.py

nodes_fts       FTS5 virtual table. Mirrors nodes. Maintained by triggers.
                Never written directly.
                Read by:    autoground_query.py (MATCH queries)

edges           Directed relationships between nodes.
                relation: matched | cited | evolved_from | session_referenced | skill_used
                Written by: (not yet wired — 0 rows)

signals         Novel keyword detections from external sources.
                is_new flag resets to 0 after acknowledgement.
                Written by: (not yet wired — 0 rows)

SCHEMA VERSION HISTORY
----------------------
v1  Initial schema: sessions, nodes, edges, signals, nodes_fts
v2  Added readme table; strengthened -- comments on all CREATE TABLE statements
""",
}


def _make_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


class SubstrateDB:
    """Connection manager and write primitives for the substrate DB."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self):
        with self.connect() as conn:
            conn.executescript(SCHEMA)
        self._upsert_readme()

    def _upsert_readme(self):
        """Insert a readme row for SCHEMA_VERSION if one doesn't exist yet."""
        content = _README_VERSIONS.get(SCHEMA_VERSION, f"Schema version {SCHEMA_VERSION}")
        with self.connect() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO readme (version, updated_at, content)
                VALUES (?, ?, ?)
            """, (SCHEMA_VERSION, _now(), content))

    # --- sessions ---

    def upsert_session(self, cwd: str, started_at: str,
                       ended_at: Optional[str] = None,
                       keywords: Optional[list] = None) -> str:
        sid = _make_id(cwd, started_at)
        project = os.path.basename(cwd.rstrip("/"))
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO sessions (id, cwd, project, started_at, ended_at, keywords)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    ended_at = excluded.ended_at,
                    keywords = excluded.keywords
            """, (sid, cwd, project, started_at, ended_at,
                  json.dumps(keywords or [])))
        return sid

    # --- nodes ---

    def upsert_node(self, node_type: str, label: str, source: str,
                    metadata: Optional[dict] = None) -> str:
        nid = _make_id(node_type, source)
        now = _now()
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO nodes (id, type, label, source, first_seen, last_seen, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    metadata  = excluded.metadata
            """, (nid, node_type, label, source, now, now,
                  json.dumps(metadata or {})))
        return nid

    # --- edges ---

    def upsert_edge(self, from_id: str, to_id: str, relation: str,
                    score: float = 1.0, session_id: Optional[str] = None):
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO edges (from_id, to_id, relation, score, created_at, session_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(from_id, to_id, relation) DO UPDATE SET
                    score      = excluded.score,
                    created_at = excluded.created_at,
                    session_id = excluded.session_id
            """, (from_id, to_id, relation, score, _now(), session_id))

    # --- signals ---

    def upsert_signal(self, keyword: str, source_url: str, title: str,
                      abstract: str = "") -> bool:
        """Insert signal. Returns True if this is a new detection."""
        sid = _make_id(keyword, source_url)
        now = _now()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM signals WHERE id = ?", (sid,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE signals SET is_new = 0 WHERE id = ?", (sid,)
                )
                return False
            conn.execute("""
                INSERT INTO signals (id, keyword, source_url, title, abstract, detected_at, is_new)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (sid, keyword, source_url, title, abstract, now))
            return True

    # --- queries ---

    def query_by_keywords(self, keywords: list[str], top_k: int = 10) -> list[dict]:
        """Return top_k nodes matching any keyword. FTS + label scan."""
        if not keywords:
            return []
        results = []
        seen = set()
        with self.connect() as conn:
            for kw in keywords:
                # FTS5 chokes on apostrophes and special operator chars
                safe_kw = kw.replace("'", "").replace('"', '').strip("-+^():")
                if not safe_kw:
                    continue
                try:
                    rows = conn.execute("""
                        SELECT n.id, n.type, n.label, n.source, n.last_seen, n.metadata
                        FROM nodes_fts f
                        JOIN nodes n ON n.id = f.id
                        WHERE nodes_fts MATCH ?
                        LIMIT ?
                    """, (safe_kw, top_k)).fetchall()
                except Exception:
                    continue
                for row in rows:
                    if row["id"] not in seen:
                        seen.add(row["id"])
                        results.append(dict(row))
        return results[:top_k]

    def new_signals(self, limit: int = 20) -> list[dict]:
        """Return signals flagged is_new=1, most recent first."""
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT keyword, title, source_url, detected_at
                FROM signals WHERE is_new = 1
                ORDER BY detected_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def recent_sessions(self, project: Optional[str] = None,
                        limit: int = 10) -> list[dict]:
        with self.connect() as conn:
            if project:
                rows = conn.execute("""
                    SELECT id, cwd, project, started_at, keywords
                    FROM sessions WHERE project = ?
                    ORDER BY started_at DESC LIMIT ?
                """, (project, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, cwd, project, started_at, keywords
                    FROM sessions ORDER BY started_at DESC LIMIT ?
                """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        with self.connect() as conn:
            return {
                "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                "nodes":    conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
                "edges":    conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
                "signals":  conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0],
                "new_signals": conn.execute(
                    "SELECT COUNT(*) FROM signals WHERE is_new=1"
                ).fetchone()[0],
            }


if __name__ == "__main__":
    import sys
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    db = SubstrateDB(db_path)
    s = db.stats()
    print(f"substrate.sqlite3 @ {db.db_path}")
    for k, v in s.items():
        print(f"  {k}: {v}")
