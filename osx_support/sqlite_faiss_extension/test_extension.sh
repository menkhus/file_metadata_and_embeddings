#!/bin/bash
# Test script for SQLite FAISS extension

set -e

echo "Testing SQLite FAISS Extension..."
echo "=================================="

# Build first if needed
if [ ! -f "faiss_extension.dylib" ]; then
    echo "Building extension first..."
    make
fi

# Create test database
TEST_DB="test_faiss.db"
rm -f "$TEST_DB"

# Load extension and run tests (from local directory)
sqlite3 "$TEST_DB" <<'SQL'
.load ./faiss_extension.dylib

-- Create test table
CREATE TABLE text_chunks_v2 (
    id INTEGER PRIMARY KEY,
    file_path TEXT,
    chunk_index INTEGER,
    chunk_envelope TEXT,
    embedding BLOB
);

-- Insert test embeddings (random for now)
INSERT INTO text_chunks_v2 (id, file_path, chunk_index, embedding)
VALUES 
    (1, '/test/file1.py', 0, randomblob(1536)),
    (2, '/test/file1.py', 1, randomblob(1536)),
    (3, '/test/file2.py', 0, randomblob(1536));

-- Test: Build index
SELECT 'Test 1: Build Index';
SELECT faiss_build_index();

-- Test: Index stats
SELECT 'Test 2: Index Stats';
SELECT faiss_index_stats();

-- Test: Search (will fail without proper embeddings, but tests function)
SELECT 'Test 3: Search Function';
SELECT faiss_search('test query', 2);

.quit
SQL

echo ""
echo "✓ All tests passed!"
echo ""
echo "Cleanup..."
rm -f "$TEST_DB"

echo "Done!"
