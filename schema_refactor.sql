-- AI-Optimized Text Chunks Schema with JSONB
-- Stores complete chunk envelopes as JSONB for maximum flexibility
--
-- STANDALONE INITIALIZATION SCRIPT
-- This file can be run safely on any database (new or existing)
-- Uses CREATE IF NOT EXISTS pattern - will not overwrite existing tables
--
-- Usage:
--   sqlite3 file_metadata.db < schema_refactor.sql
--
-- Note: This creates NEW tables (text_chunks_v2, chunks_fts) alongside existing tables
-- The old text_chunks and embeddings_index tables remain untouched

CREATE TABLE IF NOT EXISTS text_chunks_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,

    -- Store entire chunk envelope as JSONB
    chunk_envelope TEXT NOT NULL CHECK(json_valid(chunk_envelope)),

    -- Extracted fields for indexing and querying (denormalized from JSON)
    chunk_strategy TEXT NOT NULL,  -- 'code_discrete', 'prose_discrete', 'prose_overlap'
    chunk_size INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL,
    file_hash TEXT NOT NULL,
    file_type TEXT,
    created_at TEXT NOT NULL,

    -- Optional: embedding storage (can also be in envelope)
    embedding BLOB,

    -- Constraints
    UNIQUE(file_path, chunk_index),
    FOREIGN KEY (file_path) REFERENCES file_metadata (file_path) ON DELETE CASCADE
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON text_chunks_v2(file_path);
CREATE INDEX IF NOT EXISTS idx_chunks_strategy ON text_chunks_v2(chunk_strategy);
CREATE INDEX IF NOT EXISTS idx_chunks_file_hash ON text_chunks_v2(file_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_file_type ON text_chunks_v2(file_type);

-- Index for adjacent chunk retrieval (critical for context expansion)
CREATE INDEX IF NOT EXISTS idx_chunks_adjacency ON text_chunks_v2(file_path, chunk_index);

-- JSON extraction indexes (SQLite 3.38+)
-- These allow querying into the JSONB without deserializing
CREATE INDEX IF NOT EXISTS idx_chunks_json_filename
    ON text_chunks_v2(json_extract(chunk_envelope, '$.metadata.filename'));

CREATE INDEX IF NOT EXISTS idx_chunks_json_strategy
    ON text_chunks_v2(json_extract(chunk_envelope, '$.metadata.chunk_strategy'));

-- Full-text search on chunk content (extract from JSON)
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    file_path,
    chunk_index,
    content,
    content='text_chunks_v2',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS chunks_fts_insert AFTER INSERT ON text_chunks_v2 BEGIN
    INSERT INTO chunks_fts(rowid, file_path, chunk_index, content)
    VALUES (
        new.id,
        new.file_path,
        new.chunk_index,
        json_extract(new.chunk_envelope, '$.content')
    );
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON text_chunks_v2 BEGIN
    DELETE FROM chunks_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_update AFTER UPDATE ON text_chunks_v2 BEGIN
    DELETE FROM chunks_fts WHERE rowid = old.id;
    INSERT INTO chunks_fts(rowid, file_path, chunk_index, content)
    VALUES (
        new.id,
        new.file_path,
        new.chunk_index,
        json_extract(new.chunk_envelope, '$.content')
    );
END;

-- View for easy querying with metadata extraction
CREATE VIEW IF NOT EXISTS chunks_with_metadata AS
SELECT
    id,
    file_path,
    chunk_index,
    chunk_envelope,
    json_extract(chunk_envelope, '$.metadata.filename') as filename,
    json_extract(chunk_envelope, '$.metadata.chunk_strategy') as strategy,
    json_extract(chunk_envelope, '$.metadata.chunk_size') as size,
    json_extract(chunk_envelope, '$.metadata.total_chunks') as total,
    json_extract(chunk_envelope, '$.metadata.overlap_chars') as overlap,
    json_extract(chunk_envelope, '$.metadata.file_type') as type,
    json_extract(chunk_envelope, '$.metadata.file_hash') as hash,
    json_extract(chunk_envelope, '$.metadata.created_at') as created,
    json_extract(chunk_envelope, '$.content') as content
FROM text_chunks_v2;

-- Example queries:

-- 1. Get all chunks for a file
-- SELECT * FROM chunks_with_metadata WHERE file_path = '/path/to/file.py';

-- 2. Get adjacent chunks for context (chunk 5 ± 1)
-- SELECT * FROM chunks_with_metadata
-- WHERE file_path = '/path/to/file.py'
--   AND chunk_index BETWEEN 4 AND 6
-- ORDER BY chunk_index;

-- 3. Search chunk content
-- SELECT * FROM chunks_fts WHERE content MATCH 'search term';

-- 4. Get chunks by strategy
-- SELECT * FROM chunks_with_metadata WHERE strategy = 'code_discrete';

-- 5. Get complete envelope as JSON
-- SELECT chunk_envelope FROM text_chunks_v2 WHERE file_path = '...' AND chunk_index = 0;
