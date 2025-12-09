# Architecture - Native macOS Semantic Search

## Overview

Native macOS implementation that exposes semantic file search capabilities to Apple Intelligence through Apple Intents framework.

**Core Principle:** Build proven Python V2 architecture natively in Swift/C++ for production-quality macOS integration.

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Apple Intelligence / Siri                  │
│            "Find files about authentication"            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────┐
│              Apple Intents Framework                    │
│  • SemanticSearchIntent                                 │
│  • GetFileContextIntent                                 │
│  • RecentFilesIntent                                    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────┐
│         SQLite FAISS Extension (C++)                    │
│  • faiss_search(query, top_k)                           │
│  • faiss_build_index()                                  │
│  • Vector similarity search                             │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────┐
│              SQLite Database                            │
│  • files_v2: File metadata                              │
│  • text_chunks_v2: Content + embeddings                 │
│  • FTS5: Full-text search                               │
└────────────────────┬────────────────────────────────────┘
                     ↑
                     │
┌─────────────────────────────────────────────────────────┐
│         Background Indexer (Swift)                      │
│  • FSEvents file monitoring                             │
│  • Core ML embedding generation                         │
│  • Low-priority background processing                   │
│  • Battery-aware throttling                             │
└─────────────────────────────────────────────────────────┘
```

## Components

### 1. Background Indexer (Swift)

**Purpose:** Non-intrusive file monitoring and indexing.

**Responsibilities:**
- Monitor directories via FSEvents
- Detect file changes (create, modify, delete)
- Chunk files (code: 350 chars, prose: 800 chars)
- Generate embeddings via Core ML
- Store in SQLite database
- Update FAISS index

**Implementation:**
- Swift daemon (launchd managed)
- QOS_CLASS_BACKGROUND priority
- Throttled: 10 files/minute max
- Battery-aware: pauses <20%
- Memory limit: 200MB max
- Runs only when system idle >5 min

**Key Files:**
- `background_indexer/Sources/FileIndexer.swift`
- `background_indexer/Package.swift`

### 2. SQLite FAISS Extension (C++)

**Purpose:** Native vector search without Python dependencies.

**Responsibilities:**
- Load embeddings from SQLite
- Build FAISS index in memory
- Execute semantic searches
- Return ranked results

**SQL Functions Provided:**
```sql
-- Build index from embeddings in database
SELECT faiss_build_index();

-- Semantic search with text query
SELECT * FROM faiss_search('authentication code', 5);

-- Search with pre-computed embedding vector
SELECT * FROM faiss_search_vector(embedding_blob, 5);

-- Index statistics
SELECT faiss_index_stats();
```

**Implementation:**
- Pure C++17
- Statically linked FAISS
- Lazy index loading (on first search)
- LRU cache for index
- Memory-efficient (unload after 5 min idle)

**Key Files:**
- `sqlite_faiss_extension/Sources/faiss_extension.cpp`
- `sqlite_faiss_extension/Sources/onnx_encoder.cpp`

### 3. Apple Intents (Swift)

**Purpose:** Expose search capabilities to Apple Intelligence.

**Why Apple Intents:**
- Apple Intelligence can discover and use Intents as tools
- Siri integration (voice queries)
- Shortcuts integration (automation)
- System-wide availability
- Proper macOS integration

**Intents Defined:**

#### SemanticSearchIntent
```swift
struct SemanticSearchIntent: AppIntent {
    static var title: LocalizedStringResource = "Semantic Search"
    static var description = IntentDescription(
        "Find files by meaning, not just keywords. " +
        "Understands concepts like 'authentication', 'error handling'."
    )

    @Parameter(title: "Query")
    var query: String

    @Parameter(title: "Number of Results", default: 5)
    var topK: Int

    func perform() async throws -> IntentResult
}
```

#### GetFileContextIntent
```swift
struct GetFileContextIntent: AppIntent {
    static var title: LocalizedStringResource = "Get File Context"
    static var description = IntentDescription(
        "Get surrounding context for a file chunk"
    )

    @Parameter(title: "File Path")
    var filePath: String

    @Parameter(title: "Chunk Index")
    var chunkIndex: Int

    @Parameter(title: "Context Size", default: 1)
    var contextSize: Int

    func perform() async throws -> IntentResult
}
```

#### RecentFilesIntent
```swift
struct RecentFilesIntent: AppIntent {
    static var title: LocalizedStringResource = "Recent Files"

    @Parameter(title: "Hours", default: 24)
    var hours: Int

    @Parameter(title: "File Type")
    var fileType: String?

    func perform() async throws -> IntentResult
}
```

**How Apple Intelligence Uses It:**

User: "Explain how authentication works in my codebase"

Apple Intelligence:
1. Calls `SemanticSearchIntent(query: "authentication")`
2. Gets top 5 file results
3. Calls `GetFileContextIntent()` for each result
4. Synthesizes answer using local LLM
5. Responds to user

**Key Files (not yet implemented):**
- `intents/SemanticSearchIntent.swift`
- `intents/GetFileContextIntent.swift`
- `intents/RecentFilesIntent.swift`

## Data Flow

### Indexing Flow

```
1. User saves file.py
    ↓
2. FSEvents triggers notification
    ↓
3. Background Indexer queues file
    ↓
4. Chunker splits file (350 char chunks)
    ↓
5. Core ML generates embeddings (384-dim vectors)
    ↓
6. Store in SQLite (text_chunks_v2 table)
    ↓
7. Update FTS5 index for full-text search
    ↓
8. FAISS index rebuilt on next search (lazy)
```

### Search Flow

```
1. User (via Siri): "Find authentication code"
    ↓
2. SemanticSearchIntent receives query
    ↓
3. Intent calls SQLite: faiss_search('authentication code', 5)
    ↓
4. Extension generates query embedding (Core ML)
    ↓
5. FAISS finds top-k similar vectors
    ↓
6. Join with text_chunks_v2 for content
    ↓
7. Return ranked results with context
    ↓
8. Intent formats and returns to Apple Intelligence
```

## Technology Choices

### Language: Swift + C++

**Swift:**
- Native macOS integration
- Apple Intents framework
- Modern concurrency (async/await)
- Memory safety

**C++:**
- FAISS integration (C++ library)
- Performance-critical code
- Static linking

### Embeddings: Core ML

**Why Core ML over ONNX:**
- Native Apple framework
- Neural Engine acceleration
- Better macOS integration
- Lower power consumption
- Optimized for Apple Silicon

**Model:** all-MiniLM-L6-v2
- Dimensions: 384
- Size: ~80MB
- Fast inference: <10ms per chunk
- Proven effective (from Python V2)

### Vector Search: FAISS

**Why FAISS:**
- Industry standard
- Fast (exact and approximate search)
- Scalable (handles 200K+ vectors)
- Well-maintained (Meta)

**Index Type (v0):** IndexFlatL2
- Exact search
- Simple, reliable
- Good for <1M vectors

**Future (v1+):** IndexIVFFlat
- Approximate search
- Faster for >1M vectors
- Trade accuracy for speed

### Database: SQLite

**Why SQLite:**
- Built into macOS
- Zero configuration
- ACID transactions
- FTS5 for full-text search
- Custom extensions supported
- File-based (easy backup)

**Schema:**
```sql
-- File metadata
CREATE TABLE files_v2 (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    filename TEXT,
    size_bytes INTEGER,
    modified_time REAL,
    file_hash TEXT
);

-- Text chunks with embeddings
CREATE TABLE text_chunks_v2 (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    chunk_index INTEGER,
    content TEXT,
    embedding BLOB,  -- 384 floats (1536 bytes)
    FOREIGN KEY (file_id) REFERENCES files_v2(id)
);

-- Full-text search
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    content,
    content=text_chunks_v2,
    content_rowid=id
);
```

## Design Patterns

### 1. Lazy Loading

FAISS index not loaded until first search:
- Saves memory at startup
- Fast app launch
- Index built on-demand from database

### 2. Background Processing

All indexing happens in background:
- QOS_CLASS_BACKGROUND priority
- System decides when to run
- Pauses on battery/high CPU
- User never waits

### 3. Incremental Updates

Files indexed as they change:
- FSEvents provides file notifications
- Only changed files reprocessed
- Database maintains consistency
- FAISS index rebuilt lazily

### 4. Dual Search

Support both semantic and keyword search:
- FAISS for semantic (meaning)
- FTS5 for keywords (exact)
- Combine results when needed

## Performance Targets

**Indexing:**
- Throughput: 10 files/minute (throttled)
- Memory: <200MB during indexing
- CPU: <5% average
- Battery impact: <5% per day

**Search:**
- Cold query: <500ms (build index + search)
- Warm query: <100ms (index loaded)
- Memory: <50MB for 200K file index

**Storage:**
- ~5KB per chunk (metadata + embedding + index)
- 200K files × 5 chunks = 1M chunks = ~5GB

## Scalability

**v0 Target:** 200,000 files

**Scaling Strategy:**
1. 0-100K files: IndexFlatL2 (exact search)
2. 100K-1M files: IndexIVFFlat (approximate)
3. 1M+ files: Distributed indexing (future)

**Memory Management:**
- Lazy load index on first search
- Unload after 5 min idle
- Respond to memory pressure events
- Never exceed 1GB total

## Security & Privacy

**Privacy:**
- All processing local (no cloud)
- No telemetry
- Per-user database
- Respects file permissions

**Sandboxing:**
- Compatible with App Sandbox
- User grants directory access
- No elevated privileges needed

**Code Signing:**
- All binaries signed
- Notarized for distribution
- Gatekeeper compatible

## Why This Doesn't Exist in macOS

**Spotlight limitations:**
- Keyword-based search only
- No semantic understanding
- Can't find by concept/meaning

**What we add:**
- Semantic layer on top of file system
- Understand meaning, not just keywords
- Find "authentication code" even if file doesn't contain those exact words
- Expose as tools for Apple Intelligence

## Future Enhancements (Post-v0)

**Spotlight Integration:**
- mdimporter plugin
- Show semantic results in Spotlight UI

**Knowledge Graph:**
- File relationships
- Cross-reference detection
- Project structure understanding

**Advanced Search:**
- Time-based queries
- Author filtering
- Project scoping

**Multi-Platform:**
- Windows version
- Linux version
- Shared core (C++)

## References

**Python V2 Proof:**
- `../chunking_refactor.py` - Chunking strategy
- `../tools_v2/find_most_similar_v2.py` - Semantic search
- Proves: Architecture works, embeddings effective, FAISS fast

**Apple Documentation:**
- [App Intents Framework](https://developer.apple.com/documentation/appintents)
- [Core ML](https://developer.apple.com/documentation/coreml)
- [FSEvents](https://developer.apple.com/documentation/coreservices/file_system_events)

**Libraries:**
- [FAISS](https://github.com/facebookresearch/faiss)
- [SQLite](https://www.sqlite.org/)
