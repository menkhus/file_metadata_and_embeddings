# Enhancement Request: SQLAlchemy Core + Alembic Migration

**Requested by:** long_context_local_ai project
**Date:** 2026-01-19
**Priority:** High (blocking downstream development)
**Estimated effort:** 41-57 hours (~2 weeks)

---

## Summary

Retrofit the database layer to use SQLAlchemy Core (not ORM) with Alembic migrations. This enables:
- Database portability (SQLite → PostgreSQL → MySQL → SQL Server)
- Schema version enforcement
- Safe, tracked migrations
- Open source readiness

---

## Blocking Issue

**Downstream project `long_context_local_ai` is blocked** from adding database enhancements until this is complete. Current options are:
1. Hand-edit raw SQL (error-prone, no versioning)
2. Wait for this migration capability

The experimental → promotion workflow requires Alembic migrations to promote `exp_` tables properly.

---

## Current State

- **Database:** Pure SQLite3 with raw SQL
- **Connection management:** Thread-local manual pooling
- **Tables:** 9 tables including FTS5 virtual tables
- **Lines of DB code:** ~1500

### Existing Tables

| Table | Purpose |
|-------|---------|
| `file_metadata` | Core file info (path, size, type, hash) |
| `content_analysis` | NLP results (keywords, topics, sentiment) |
| `text_chunks` | Legacy chunks (v1) |
| `text_chunks_v2` | JSONB-aware chunks with envelope |
| `chunks_fts` | FTS5 virtual table for full-text search |
| `embeddings_index` | FAISS-ready vectors |
| `directory_structure` | Hierarchy statistics |
| `processing_stats` | Session audit trail |

---

## Target State

```
src/database/
├── __init__.py
├── models.py          # SQLAlchemy Core table definitions
├── engine.py          # Connection pooling, config
├── schema.sql         # FTS5 + triggers (raw SQL escape hatch)
└── migrations/
    ├── env.py         # Alembic configuration
    └── versions/      # Migration scripts
```

### Key Patterns (from reference implementation)

```python
from sqlalchemy import JSON, Text
from sqlalchemy.dialects import postgresql, mysql

# JSON type with per-database variants
json_type = (
    JSON()
    .with_variant(postgresql.JSONB, "postgresql")
    .with_variant(mysql.JSON, "mysql")
    .with_variant(Text, "sqlite")
    .with_variant(Text, "mssql")
)
```

**Reference code:** `~/src/general_purpose_db_stubs_using_ORM/`
**Working implementation:** `~/src/long_context_local_ai/src/database/`

---

## Implementation Plan

### Phase 1: Setup (3-4 days)
- [ ] Create `src/database/` module structure
- [ ] Define all tables in `models.py` using SQLAlchemy Core
- [ ] Create `engine.py` with connection pool configuration
- [ ] Add `schema.sql` for FTS5 virtual tables (raw SQL)
- [ ] Initialize Alembic: `alembic init migrations`
- [ ] Configure `alembic.ini` and `migrations/env.py`
- [ ] Unit tests for connection pooling

### Phase 2: DatabaseManager Refactor (2-3 days)
- [ ] Replace raw SQL in `DatabaseManager` with Core statements
- [ ] Maintain backward-compatible API (no breaking changes)
- [ ] Refactor retry logic to use SQLAlchemy mechanisms
- [ ] Add `check_schema_version()` for version enforcement
- [ ] Integration tests with file scanning

### Phase 3: Tools Refactor (2-3 days)
- [ ] Refactor `tools_v2/file_query_tool_v2.py` query building
- [ ] Refactor `tools_v2/find_using_fts_v2.py` (keep FTS as raw SQL)
- [ ] Refactor `tools_v2/find_most_similar_v2.py` embedding loading
- [ ] CLI tests for all tools

### Phase 4: Integration & Testing (2-3 days)
- [ ] End-to-end tests: metadata extraction → chunking → search
- [ ] Performance benchmarks vs. original
- [ ] Migration validation (existing DB data loads correctly)
- [ ] Documentation updates

### Phase 5: Cleanup (1 day)
- [ ] Remove deprecated raw SQL paths
- [ ] Final validation
- [ ] Update README with new architecture

---

## Risk Areas

| Risk | Mitigation |
|------|------------|
| FTS5 virtual tables not supported by SQLAlchemy | Keep as raw SQL in `schema.sql`, use `text()` for queries |
| SQLite-specific PRAGMAs (WAL, busy_timeout) | Configure via engine connect events |
| JSON handling differences | `get_json_type()` abstracts per-dialect |
| Performance regression | Benchmark before/after, optimize if needed |
| Breaking existing consumers | Maintain API compatibility during transition |

---

## Acceptance Criteria

1. [ ] All existing tests pass
2. [ ] `alembic upgrade head` creates schema from scratch
3. [ ] `alembic downgrade` works for rollback
4. [ ] Schema version check prevents code/DB mismatch
5. [ ] Same codebase works with SQLite and PostgreSQL
6. [ ] Performance within 10% of original
7. [ ] Downstream `long_context_local_ai` can promote experimental tables via PR

---

## Dependencies

- SQLAlchemy >= 2.0
- Alembic >= 1.0
- Reference: `~/src/general_purpose_db_stubs_using_ORM/`
- Working pattern: `~/src/long_context_local_ai/src/database/`

---

## Notes

This enhancement enables the **experimental → promotion workflow**:

1. Downstream projects define `exp_` prefixed tables
2. When proven, create PR to this repo with:
   - Table definition in `models.py`
   - Alembic migration
   - Documentation
3. After merge, downstream uses reflection/import

The tail (downstream) experiments, the dog (this repo) owns the schema.
