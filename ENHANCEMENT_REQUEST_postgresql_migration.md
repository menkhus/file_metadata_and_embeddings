# Enhancement Request: PostgreSQL + pgvector Migration

**Requested by:** disk-space incident, May 2026
**Date:** 2026-05-18
**Priority:** High
**Estimated effort:** 3–5 days

---

## Summary

Replace SQLite + FAISS with PostgreSQL + pgvector. Eliminates the architectural
causes of the May 2026 disk incident (120M-row content_analysis duplication,
15 GB WAL never checkpointed, 552 MB FAISS flat file) and unlocks production-grade
vector similarity search.

---

## Root Causes Being Eliminated

| Problem | SQLite cause | PostgreSQL fix |
|---------|-------------|----------------|
| 120M duplicate rows in `content_analysis` | No UNIQUE constraint; `INSERT OR REPLACE` silently appended | `UNIQUE(file_path)` enforced at DDL level; `ON CONFLICT DO UPDATE` |
| 15 GB WAL never truncated | Manual `PRAGMA wal_checkpoint` required; never called on close | autovacuum + WAL archiving built-in; no manual intervention |
| FAISS flat index (552 MB external file) | Vectors serialized to JSON, loaded into memory FAISS flat index | `pgvector` HNSW index stored in-database; query with SQL |
| No concurrent writers | SQLite writer lock | PostgreSQL MVCC |
| FTS via FTS5 virtual table | Fragile triggers to keep sync | `tsvector` column + `GIN` index; updated via trigger or generated column |

---

## Current Stack

```
file_metadata.sqlite3   124 GB (post-incident; normally ~4 GB)
faiss_index.bin         552 MB  — FAISS flat index (all-MiniLM-L6-v2, 384-dim)
file_search_major.faiss 275 MB  — second FAISS index
shell_ai.faiss          26 MB
embeddings_index table  JSON arrays → loaded into FAISS at query time
content_fts             FTS5 virtual table
```

Model: `sentence-transformers/all-MiniLM-L6-v2` → **384-dimensional vectors**

---

## Target Stack

```
PostgreSQL 16+ on localhost:5432
Extensions: vector (pgvector 0.7+), pg_trgm
DB: file_metadata (new DB, separate from vuln_intel)
```

No FAISS files. No external index rebuild script. No WAL discipline required.

---

## PostgreSQL Schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Core file index (unchanged semantics)
CREATE TABLE file_metadata (
    file_path       TEXT PRIMARY KEY,
    file_hash       TEXT,
    file_size       BIGINT,
    file_type       TEXT,
    extension       TEXT,
    mime_type       TEXT,
    is_text_file    BOOLEAN,
    line_count      INTEGER,
    encoding        TEXT,
    last_modified   TIMESTAMPTZ,
    last_indexed    TIMESTAMPTZ DEFAULT now(),
    processing_status TEXT DEFAULT 'success',
    error_message   TEXT
);

-- One row per file; UNIQUE enforced at DDL (no duplicates possible)
CREATE TABLE content_analysis (
    file_path           TEXT PRIMARY KEY REFERENCES file_metadata ON DELETE CASCADE,
    file_hash           TEXT NOT NULL,
    word_count          INTEGER,
    char_count          INTEGER,
    language            TEXT,
    topic_summary       TEXT,
    keywords            JSONB,
    tfidf_keywords      JSONB,
    lda_topics          JSONB,
    sentiment_score     REAL,
    processing_status   TEXT DEFAULT 'success',
    error_message       TEXT,
    analysis_date       TIMESTAMPTZ DEFAULT now(),
    processing_time_s   REAL,
    -- Full-text search: updated via trigger or INSERT ... ON CONFLICT DO UPDATE
    ts_content          TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(topic_summary, '') || ' ' || coalesce(keywords::text, ''))
    ) STORED
);

CREATE INDEX ON content_analysis USING GIN (ts_content);
CREATE INDEX ON content_analysis (file_hash);

-- Chunks with embeddings inline (replaces text_chunks + embeddings_index + FAISS)
CREATE TABLE text_chunks (
    id              BIGSERIAL PRIMARY KEY,
    file_path       TEXT NOT NULL REFERENCES file_metadata ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    file_hash       TEXT NOT NULL,
    chunk_strategy  TEXT NOT NULL,   -- 'code_discrete' | 'prose_discrete' | 'prose_overlap'
    chunk_size      INTEGER NOT NULL,
    total_chunks    INTEGER NOT NULL,
    content         TEXT NOT NULL,
    metadata        JSONB,
    embedding       vector(384),     -- all-MiniLM-L6-v2; NULL until embedded
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (file_path, chunk_index)
);

-- HNSW index for ANN search (better recall than IVFFlat; no cluster count needed)
-- ef_construction=128, m=16 is a good starting point for 384-dim
CREATE INDEX ON text_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128);

-- Full-text search on chunk content
CREATE INDEX ON text_chunks USING GIN (to_tsvector('english', content));

-- Directory tree
CREATE TABLE directory_structure (
    directory_path  TEXT PRIMARY KEY,
    parent_path     TEXT,
    file_count      INTEGER DEFAULT 0,
    total_size      BIGINT DEFAULT 0,
    last_scanned    TIMESTAMPTZ DEFAULT now()
);

-- Session audit
CREATE TABLE processing_stats (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL,
    start_time      TIMESTAMPTZ,
    end_time        TIMESTAMPTZ,
    files_processed INTEGER DEFAULT 0,
    files_skipped   INTEGER DEFAULT 0,
    files_errored   INTEGER DEFAULT 0,
    interrupted     BOOLEAN DEFAULT false,
    metadata        JSONB
);
```

---

## Query Migration

### Semantic similarity (replaces FAISS flat search)

```python
# Before: load faiss_index.bin, encode query, flat L2 search
# After:
def semantic_search(query_text: str, k: int = 10, conn) -> list[dict]:
    embedding = model.encode(query_text).tolist()
    rows = conn.execute("""
        SELECT file_path, chunk_index, content,
               1 - (embedding <=> %s::vector) AS score
        FROM text_chunks
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (embedding, embedding, k)).fetchall()
    return [dict(r) for r in rows]
```

### Full-text search (replaces FTS5 + content_fts)

```python
def fts_search(query: str, conn) -> list[dict]:
    rows = conn.execute("""
        SELECT file_path, chunk_index, content,
               ts_rank(to_tsvector('english', content), query) AS rank
        FROM text_chunks, plainto_tsquery('english', %s) query
        WHERE to_tsvector('english', content) @@ query
        ORDER BY rank DESC
        LIMIT 20
    """, (query,)).fetchall()
    return [dict(r) for r in rows]
```

### Hybrid search (new capability; not possible with SQLite)

```python
def hybrid_search(query: str, k: int = 10, conn) -> list[dict]:
    """RRF fusion of vector + BM25-approximate results."""
    embedding = model.encode(query).tolist()
    rows = conn.execute("""
        WITH vec AS (
            SELECT file_path, chunk_index, content,
                   ROW_NUMBER() OVER (ORDER BY embedding <=> %s::vector) AS rank
            FROM text_chunks WHERE embedding IS NOT NULL LIMIT %s
        ),
        fts AS (
            SELECT file_path, chunk_index, content,
                   ROW_NUMBER() OVER (ORDER BY ts_rank(
                       to_tsvector('english', content),
                       plainto_tsquery('english', %s)
                   ) DESC) AS rank
            FROM text_chunks
            WHERE to_tsvector('english', content) @@ plainto_tsquery('english', %s)
            LIMIT %s
        )
        SELECT coalesce(v.file_path, f.file_path) AS file_path,
               coalesce(v.chunk_index, f.chunk_index) AS chunk_index,
               coalesce(v.content, f.content) AS content,
               (1.0/(%s + coalesce(v.rank,1e9)) + 1.0/(%s + coalesce(f.rank,1e9))) AS rrf_score
        FROM vec v FULL OUTER JOIN fts f USING (file_path, chunk_index)
        ORDER BY rrf_score DESC
        LIMIT %s
    """, (embedding, k*2, query, query, k*2, 60, 60, k)).fetchall()
    return [dict(r) for r in rows]
```

Hybrid search with RRF (Reciprocal Rank Fusion) is the 2023–2025 standard for
production RAG pipelines. See: Cormack et al. 2009; adopted in Elasticsearch 8.x,
pgvector cookbook, LlamaIndex hybrid retriever.

---

## Files to Remove After Migration

```
faiss_index.bin
file_search_major.faiss
file_search_major_meta.json
shell_ai.faiss
shell_ai_faiss_meta.json
build_faiss_index.py
faiss_index_manager.py
```

Remove `faiss`, `sentence-transformers` from requirements only if embedding
generation moves server-side (e.g., pgai / pgvector-remote). Otherwise keep
`sentence-transformers` for encoding at index time.

---

## Migration Plan

### Phase 0 — Disk cleanup (done, May 2026)
- [x] Checkpoint WAL and truncate
- [x] Dedup `content_analysis` (120M → 13K rows)
- [x] VACUUM SQLite
- [x] Add `PRAGMA wal_checkpoint(TRUNCATE)` to `close_connection()`

### Phase 1 — PostgreSQL setup (0.5 day)
- [ ] `createdb file_metadata`
- [ ] `CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;`
- [ ] Run DDL above; verify with `\d` in psql
- [ ] Confirm pgvector 0.7+ (`SELECT extversion FROM pg_extension WHERE extname='vector'`)

### Phase 2 — Data migration (1 day)
- [ ] Write `migrate_sqlite_to_pg.py`:
  - Copy `file_metadata`, `content_analysis`, `directory_structure`, `processing_stats`
  - Copy `text_chunks` content; leave `embedding` NULL (re-embed in Phase 3)
- [ ] Validate row counts match SQLite source

### Phase 3 — Re-embed chunks (1–2 days depending on chunk count)
- [ ] Write `backfill_embeddings.py`: batch encode with `all-MiniLM-L6-v2`, UPDATE rows
- [ ] Monitor with `SELECT COUNT(*) FROM text_chunks WHERE embedding IS NULL`
- [ ] Build HNSW index after all embeddings populated (faster than incremental build)

### Phase 4 — Swap MCP server (1 day)
- [ ] Replace `sqlite3.connect(...)` with `psycopg[binary]` pool in `DatabaseManager`
- [ ] Replace FAISS search in `tools_v2/find_most_similar_v2.py` with pgvector query
- [ ] Replace FTS5 query in `tools_v2/find_using_fts_v2.py` with `tsvector @@ tsquery`
- [ ] Add hybrid search endpoint to MCP server
- [ ] Update `~/.mcp.json` with `DB_URL` env var

### Phase 5 — Cleanup (0.5 day)
- [ ] Delete FAISS files (listed above)
- [ ] Remove `faiss`, `faiss-cpu` from requirements
- [ ] Archive or remove `build_faiss_index.py`, `faiss_index_manager.py`
- [ ] Update README

---

## Dependencies

```
psycopg[binary]>=3.1     # PostgreSQL driver (async-capable)
pgvector>=0.3.0          # Python pgvector adapter
sentence-transformers    # keep for encoding (all-MiniLM-L6-v2, 384-dim)
```

PostgreSQL must have `pgvector` extension installed:
```sh
brew install pgvector   # or: pip install pgvector then CREATE EXTENSION
```

---

## Acceptance Criteria

- [ ] `SELECT COUNT(*) FROM text_chunks WHERE embedding IS NOT NULL` = all chunks
- [ ] Semantic search returns results in < 100ms on local hardware
- [ ] Hybrid search MCP tool passes existing query test suite
- [ ] No FAISS files remain on disk
- [ ] `file_metadata.sqlite3` still exists as read-only archive (not deleted yet)
- [ ] `content_analysis` has `PRIMARY KEY (file_path)` — duplicates impossible
