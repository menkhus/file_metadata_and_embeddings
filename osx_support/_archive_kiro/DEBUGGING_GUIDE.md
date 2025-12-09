# Debugging & Profiling Guide

Complete guide to debugging and profiling FileSearch.

## Philosophy

**SQLite is your debugging interface!**

- ✅ Inspect data at any time
- ✅ Write external tools (Python, shell scripts)
- ✅ Query from command line
- ✅ No special debugging UI needed
- ✅ Standard SQL - everyone knows it

## SQLite Debugging

### Interactive Exploration

```bash
# Open database
sqlite3 ~/Library/Application\ Support/FileSearch/file_metadata.db

# Enable better output
.mode column
.headers on
.width 50 10 10

# Explore schema
.schema

# Count everything
SELECT 'Files' as type, COUNT(*) as count FROM file_metadata
UNION ALL
SELECT 'Chunks', COUNT(*) FROM text_chunks_v2
UNION ALL
SELECT 'With Embeddings', COUNT(*) FROM text_chunks_v2 WHERE embedding IS NOT NULL;

# Recent activity
SELECT 
    file_path,
    datetime(created_at) as indexed,
    total_chunks
FROM text_chunks_v2
WHERE created_at > datetime('now', '-1 hour')
GROUP BY file_path
ORDER BY created_at DESC
LIMIT 10;

# Find problems
SELECT 
    file_path,
    COUNT(*) as chunks,
    SUM(CASE WHEN embedding IS NULL THEN 1 ELSE 0 END) as missing_embeddings
FROM text_chunks_v2
GROUP BY file_path
HAVING missing_embeddings > 0;

# Check index size
SELECT 
    COUNT(*) as vectors,
    COUNT(*) * 1536 / 1024 / 1024 as estimated_mb
FROM text_chunks_v2
WHERE embedding IS NOT NULL;
```

### Useful Queries

```sql
-- What's being indexed?
SELECT 
    file_type,
    COUNT(*) as files,
    SUM(total_chunks) as chunks,
    AVG(total_chunks) as avg_chunks_per_file
FROM (
    SELECT DISTINCT file_path, file_type, total_chunks
    FROM text_chunks_v2
)
GROUP BY file_type
ORDER BY files DESC;

-- Largest files
SELECT 
    file_path,
    total_chunks,
    total_chunks * 1536 as bytes_in_index
FROM text_chunks_v2
GROUP BY file_path
ORDER BY total_chunks DESC
LIMIT 20;

-- Indexing timeline
SELECT 
    date(created_at) as day,
    COUNT(DISTINCT file_path) as files_indexed,
    COUNT(*) as chunks_created
FROM text_chunks_v2
GROUP BY date(created_at)
ORDER BY day DESC;

-- Search FTS
SELECT 
    file_path,
    chunk_index,
    snippet(chunks_fts, 2, '**', '**', '...', 32) as match
FROM chunks_fts
WHERE chunks_fts MATCH 'error handling'
LIMIT 5;

-- Verify embeddings
SELECT 
    file_path,
    chunk_index,
    length(embedding) as embedding_bytes,
    length(embedding) / 4 as dimensions
FROM text_chunks_v2
WHERE embedding IS NOT NULL
LIMIT 5;
```

### Python Debugging Tools

```python
#!/usr/bin/env python3
"""
debug_index.py - Inspect FileSearch database
"""

import sqlite3
import sys
import json
from pathlib import Path

DB_PATH = Path.home() / "Library/Application Support/FileSearch/file_metadata.db"

def connect():
    return sqlite3.connect(DB_PATH)

def stats():
    """Show database statistics"""
    conn = connect()
    
    # Counts
    files = conn.execute("SELECT COUNT(DISTINCT file_path) FROM text_chunks_v2").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM text_chunks_v2").fetchone()[0]
    with_embeddings = conn.execute("SELECT COUNT(*) FROM text_chunks_v2 WHERE embedding IS NOT NULL").fetchone()[0]
    
    # Size
    db_size = DB_PATH.stat().st_size / 1024 / 1024
    index_size = with_embeddings * 1536 / 1024 / 1024
    
    print(f"Database Statistics")
    print(f"==================")
    print(f"Files indexed: {files:,}")
    print(f"Total chunks: {chunks:,}")
    print(f"With embeddings: {with_embeddings:,} ({with_embeddings/chunks*100:.1f}%)")
    print(f"Database size: {db_size:.1f} MB")
    print(f"Estimated FAISS size: {index_size:.1f} MB")
    print()

def inspect_file(file_path):
    """Inspect a specific file"""
    conn = connect()
    
    rows = conn.execute("""
        SELECT 
            chunk_index,
            chunk_strategy,
            chunk_size,
            length(embedding) as emb_size,
            json_extract(chunk_envelope, '$.content') as content
        FROM text_chunks_v2
        WHERE file_path = ?
        ORDER BY chunk_index
    """, (file_path,)).fetchall()
    
    if not rows:
        print(f"File not found: {file_path}")
        return
    
    print(f"File: {file_path}")
    print(f"Chunks: {len(rows)}")
    print()
    
    for idx, strategy, size, emb_size, content in rows:
        print(f"Chunk {idx}:")
        print(f"  Strategy: {strategy}")
        print(f"  Size: {size} chars")
        print(f"  Embedding: {emb_size} bytes ({emb_size//4} dims)")
        print(f"  Content: {content[:100]}...")
        print()

def find_issues():
    """Find potential problems"""
    conn = connect()
    
    print("Potential Issues")
    print("================")
    
    # Missing embeddings
    missing = conn.execute("""
        SELECT file_path, COUNT(*) as chunks
        FROM text_chunks_v2
        WHERE embedding IS NULL
        GROUP BY file_path
    """).fetchall()
    
    if missing:
        print(f"\nFiles with missing embeddings: {len(missing)}")
        for path, count in missing[:10]:
            print(f"  {path}: {count} chunks")
    
    # Duplicate files
    dupes = conn.execute("""
        SELECT file_path, COUNT(*) as occurrences
        FROM (SELECT DISTINCT file_path, file_hash FROM text_chunks_v2)
        GROUP BY file_hash
        HAVING occurrences > 1
    """).fetchall()
    
    if dupes:
        print(f"\nDuplicate files: {len(dupes)}")
        for path, count in dupes[:10]:
            print(f"  {path}: {count} copies")
    
    # Orphaned chunks
    orphans = conn.execute("""
        SELECT COUNT(*) 
        FROM text_chunks_v2 t
        WHERE NOT EXISTS (
            SELECT 1 FROM file_metadata f 
            WHERE f.file_path = t.file_path
        )
    """).fetchone()[0]
    
    if orphans > 0:
        print(f"\nOrphaned chunks: {orphans}")

def export_embeddings(output_file):
    """Export embeddings for analysis"""
    import numpy as np
    
    conn = connect()
    rows = conn.execute("""
        SELECT file_path, chunk_index, embedding
        FROM text_chunks_v2
        WHERE embedding IS NOT NULL
        ORDER BY file_path, chunk_index
    """).fetchall()
    
    embeddings = []
    metadata = []
    
    for path, idx, emb_blob in rows:
        emb = np.frombuffer(emb_blob, dtype=np.float32)
        embeddings.append(emb)
        metadata.append({'file': path, 'chunk': idx})
    
    np.savez(output_file, 
             embeddings=np.array(embeddings),
             metadata=metadata)
    
    print(f"Exported {len(embeddings)} embeddings to {output_file}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python debug_index.py stats")
        print("  python debug_index.py inspect <file_path>")
        print("  python debug_index.py issues")
        print("  python debug_index.py export <output.npz>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "stats":
        stats()
    elif cmd == "inspect" and len(sys.argv) > 2:
        inspect_file(sys.argv[2])
    elif cmd == "issues":
        find_issues()
    elif cmd == "export" and len(sys.argv) > 2:
        export_embeddings(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}")
```

### Shell Script Tools

```bash
#!/bin/bash
# quick_stats.sh - Quick database stats

DB="$HOME/Library/Application Support/FileSearch/file_metadata.db"

echo "FileSearch Quick Stats"
echo "====================="

sqlite3 "$DB" <<SQL
.mode column
.headers on

SELECT 'Total Files' as metric, COUNT(DISTINCT file_path) as value
FROM text_chunks_v2
UNION ALL
SELECT 'Total Chunks', COUNT(*)
FROM text_chunks_v2
UNION ALL
SELECT 'With Embeddings', COUNT(*)
FROM text_chunks_v2 WHERE embedding IS NOT NULL
UNION ALL
SELECT 'Database Size (MB)', 
       CAST((page_count * page_size) / 1024.0 / 1024.0 AS INTEGER)
FROM pragma_page_count(), pragma_page_size();
SQL
```

## Xcode Profiling

### Instruments

**Memory Profiling:**
```
1. Product → Profile (⌘I)
2. Choose "Allocations"
3. Run app
4. Trigger search (loads FAISS index)
5. Look for:
   - Large allocations (FAISS index)
   - Memory leaks
   - Retain cycles
```

**Time Profiling:**
```
1. Product → Profile (⌘I)
2. Choose "Time Profiler"
3. Run app
4. Trigger search
5. Look for:
   - Hot paths (where time is spent)
   - Slow functions
   - Blocking operations
```

**System Trace:**
```
1. Product → Profile (⌘I)
2. Choose "System Trace"
3. Run app
4. Look for:
   - Thread activity
   - File I/O
   - System calls
```

### Debug Logging

```swift
import os.log

// Create subsystem logger
let logger = Logger(
    subsystem: "com.filesearch.app",
    category: "indexer"
)

// Log at different levels
logger.debug("Processing file: \(path)")           // Development only
logger.info("Indexed 100 files")                   // Normal operation
logger.warning("Disk space low: \(available) MB")  // Potential issues
logger.error("Failed to index: \(error)")          // Actual problems

// View logs in Console.app or terminal:
// log show --predicate 'subsystem == "com.filesearch.app"' --last 1h
```

### Breakpoint Debugging

```swift
// Set breakpoints in Xcode
class IndexManager {
    func search(_ query: String) async -> [Result] {
        // Breakpoint here
        let embedding = await embedder.encode(query)
        
        // Inspect variables:
        // po embedding
        // po embedding.count
        // po query
        
        // Breakpoint here
        let results = await faissIndex.search(embedding)
        
        // Inspect results:
        // po results
        // po results.count
        
        return results
    }
}
```

### LLDB Commands

```bash
# In Xcode debugger console

# Print variable
(lldb) po myVariable

# Print expression
(lldb) p embedding.count

# Print memory
(lldb) memory read 0x12345678

# Continue execution
(lldb) continue

# Step over
(lldb) next

# Step into
(lldb) step

# Print backtrace
(lldb) bt

# Print all local variables
(lldb) frame variable
```

## Performance Monitoring

### Custom Metrics

```swift
import os.signpost

class PerformanceMonitor {
    private let log = OSLog(
        subsystem: "com.filesearch.app",
        category: .pointsOfInterest
    )
    
    func measureSearch(_ query: String) async -> [Result] {
        let signpostID = OSSignpostID(log: log)
        
        os_signpost(.begin, log: log, name: "Search", signpostID: signpostID,
                   "Query: %{public}s", query)
        
        let results = await performSearch(query)
        
        os_signpost(.end, log: log, name: "Search", signpostID: signpostID,
                   "Results: %d", results.count)
        
        return results
    }
}

// View in Instruments → Points of Interest
```

### Timing Utilities

```swift
func measure<T>(_ name: String, _ block: () throws -> T) rethrows -> T {
    let start = Date()
    defer {
        let elapsed = Date().timeIntervalSince(start)
        logger.info("\(name): \(elapsed * 1000, format: .fixed(precision: 2))ms")
    }
    return try block()
}

// Usage
let results = measure("FAISS Search") {
    faissIndex.search(embedding)
}
```

## Testing Utilities

### Test Database

```swift
class TestDatabase {
    static func create() -> URL {
        let tempDir = FileManager.default.temporaryDirectory
        let dbPath = tempDir.appendingPathComponent("test_\(UUID()).db")
        
        // Create schema
        let db = try! Connection(dbPath.path)
        try! db.execute(schemaSQL)
        
        return dbPath
    }
    
    static func populate(db: URL, fileCount: Int) {
        // Add test data
        for i in 0..<fileCount {
            let path = "/test/file\(i).txt"
            let chunks = generateTestChunks(count: 5)
            storeChunks(db, path: path, chunks: chunks)
        }
    }
}
```

### Mock Data

```swift
class MockEmbedder: EmbeddingService {
    func encode(_ text: String) async -> [Float] {
        // Return deterministic fake embedding
        var embedding = [Float](repeating: 0, count: 384)
        let hash = text.hashValue
        for i in 0..<384 {
            embedding[i] = Float((hash + i) % 1000) / 1000.0
        }
        return embedding
    }
}
```

## Debugging Checklist

### When Something Goes Wrong

1. **Check SQLite first**
   ```bash
   sqlite3 ~/Library/.../file_metadata.db
   SELECT COUNT(*) FROM text_chunks_v2;
   ```

2. **Check logs**
   ```bash
   log show --predicate 'subsystem == "com.filesearch.app"' --last 1h
   ```

3. **Check memory**
   - Open Activity Monitor
   - Find FileSearch process
   - Check memory usage

4. **Check disk space**
   ```bash
   df -h ~/Library/Application\ Support/FileSearch/
   ```

5. **Check FAISS index**
   ```python
   python debug_index.py stats
   ```

6. **Profile with Instruments**
   - Memory leaks?
   - CPU hotspots?
   - I/O bottlenecks?

## Common Issues

### Issue: Search is slow

**Debug:**
```sql
-- Check index size
SELECT COUNT(*) FROM text_chunks_v2 WHERE embedding IS NOT NULL;

-- Check if index is loaded
-- (check logs for "Loading FAISS index")
```

**Profile:**
- Use Time Profiler
- Look for slow functions
- Check if index is being rebuilt

### Issue: High memory usage

**Debug:**
```bash
# Check FAISS index size
python debug_index.py stats

# Profile with Instruments → Allocations
```

**Fix:**
- Implement lazy loading
- Add idle timeout
- Consider quantization

### Issue: Files not being indexed

**Debug:**
```sql
-- Check recent activity
SELECT * FROM text_chunks_v2 
WHERE created_at > datetime('now', '-1 hour')
ORDER BY created_at DESC;

-- Check for errors in logs
log show --predicate 'subsystem == "com.filesearch.app" AND messageType == "Error"'
```

**Fix:**
- Check file permissions
- Check FSEvents monitoring
- Check indexer is running

## Summary

**SQLite is your debugging superpower:**
- ✅ Inspect data anytime
- ✅ Write external tools
- ✅ Standard SQL queries
- ✅ No special UI needed

**Xcode Instruments:**
- ✅ Memory profiling
- ✅ Time profiling
- ✅ System trace

**Logging:**
- ✅ os.log for structured logging
- ✅ View in Console.app
- ✅ Filter by subsystem

**External tools:**
- ✅ Python scripts
- ✅ Shell scripts
- ✅ Command-line queries

**This makes debugging a joy, not a pain!**
