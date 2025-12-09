# Requirements - v0

Native macOS semantic file search with Apple Intents integration.

**Version:** 0.1.0
**Target:** Proof of concept at production scale
**Last Updated:** 2025-11-14

## v0 Goals

**Primary Objective:** Prove Python V2 architecture works natively at scale (200K files) with Apple Intents integration.

**Success Criteria:**
- [ ] Index 200,000 files
- [ ] Semantic search <100ms (warm)
- [ ] Apple Intents working with Siri
- [ ] Background indexing non-intrusive
- [ ] Self-contained .app bundle

## Functional Requirements

### FR-1: Background Indexing

**Requirement:** Automatically index files in user-specified directories.

**Acceptance Criteria:**
- Discovers all files in watched directories
  - Default: `~/Documents`, `~/src`, `~/Desktop`
  - Configurable via preferences
- Supports file types: `.py`, `.js`, `.ts`, `.swift`, `.c`, `.cpp`, `.h`, `.m`, `.md`, `.txt`
- Chunks files appropriately:
  - Code files: ~350 characters (logical boundaries)
  - Prose files: ~800 characters (paragraph boundaries)
- Generates embeddings via Core ML (all-MiniLM-L6-v2)
- Stores in SQLite database with metadata
- Updates incrementally on file changes (FSEvents)
- Handles 200,000 files without crashing

**Performance:**
- Throughput: 10 files/minute (throttled)
- Memory: <200MB during indexing
- CPU: <5% average, <20% peak
- Battery impact: <5% per day

### FR-2: Semantic Search

**Requirement:** Search files by meaning using natural language queries.

**Acceptance Criteria:**
- Accepts natural language query (e.g., "authentication code")
- Returns ranked results by semantic similarity
- Warm query <100ms, cold query <500ms
- Returns top-k results (configurable, default: 5)
- Includes: file path, chunk content, similarity score, surrounding context
- Works with 200K file corpus

**Search Quality:**
- Finds relevant files even without exact keyword matches
- Ranks results by semantic relevance
- Handles queries in different phrasings
- Returns results from multiple file types

### FR-3: Apple Intents Integration

**Requirement:** Expose search capabilities via Apple Intents for Siri and Apple Intelligence.

**Intents Required:**

#### SemanticSearchIntent
- **Trigger:** "Search my files for [query]"
- **Parameters:**
  - `query`: String (natural language)
  - `topK`: Int (default: 5)
- **Returns:** Array of file results with paths and snippets
- **Performance:** <2 seconds end-to-end

#### GetFileContextIntent
- **Trigger:** "Get context for this file"
- **Parameters:**
  - `filePath`: String
  - `chunkIndex`: Int
  - `contextSize`: Int (default: 1)
- **Returns:** File chunk with surrounding context
- **Use Case:** Apple Intelligence requests more context for understanding

#### RecentFilesIntent
- **Trigger:** "Show recent [type] files"
- **Parameters:**
  - `hours`: Int (default: 24)
  - `fileType`: String (optional)
- **Returns:** Recently modified files
- **Use Case:** Quick access to recent work

**Acceptance Criteria:**
- Intents appear in Shortcuts app
- Siri recognizes and executes intents
- Works offline (no cloud required)
- Integrates with Apple Intelligence

### FR-4: Background Processing

**Requirement:** Index files in background without impacting user experience.

**Acceptance Criteria:**
- Runs as background daemon (launchd service)
- Low priority (QOS_CLASS_BACKGROUND)
- Throttled to max 10 files/minute
- Pauses when battery <20%
- Pauses when system not idle (requires >5 min idle)
- Memory limit: 200MB
- Automatically starts on login
- Graceful shutdown on logout/restart

**User Experience:**
- No visible UI unless user requests it
- No system slowdown
- No battery drain
- No heat/fan noise

## Non-Functional Requirements

### NFR-1: Performance

**Indexing:**
- Speed: 10 files/minute (throttled for non-intrusiveness)
- Memory: <200MB peak during indexing
- CPU: <5% average, <20% peak
- Disk I/O: <1MB/s
- Time to index 200K files: ~14 days (background, non-intrusive)

**Search:**
- Cold query (index build): <500ms
- Warm query (index loaded): <100ms
- 95th percentile: <200ms
- Memory for index: <500MB for 200K files
- Index build time: <5 seconds for 200K files

**Storage:**
- Metadata: ~1KB per file
- Embeddings: ~1.5KB per chunk (384 floats)
- FAISS index: ~2KB per chunk (in-memory)
- Database size: ~5KB per chunk on disk
- Example: 200K files × 5 chunks = 1M chunks = ~5GB

### NFR-2: Scalability

**Target:** 200,000 files for v0

**Scaling limits:**
- 0-100K files: IndexFlatL2 (exact search)
- 100K-200K files: IndexFlatL2 (still acceptable)
- 200K+ files: Warn user, suggest filtering

**Memory management:**
- Lazy load FAISS index on first search
- Unload after 5 minutes idle
- Respond to memory pressure events
- Never exceed 1GB total memory

### NFR-3: Reliability

**Stability:**
- No crashes during normal operation
- Graceful handling of corrupted files
- Automatic recovery from indexing errors
- Proper cleanup on shutdown
- Database integrity maintained (SQLite ACID)

**Error Handling:**
- Skip files >100MB (log warning)
- Handle permission errors gracefully
- Recover from Core ML failures
- Continue indexing if individual files fail

### NFR-4: Compatibility

**Platform:**
- macOS 13.0+ (Ventura) required
- Apple Silicon (M1/M2/M3) primary target
- Intel Mac support (universal binary)

**File System:**
- APFS (primary)
- HFS+ (legacy, basic support)
- Respects file permissions
- Handles symlinks correctly

**Dependencies:**
- Zero Python runtime dependencies
- Zero Homebrew runtime dependencies
- Self-contained .app bundle
- Statically linked native libraries

### NFR-5: Security & Privacy

**Privacy:**
- All processing local (no cloud)
- No telemetry or analytics
- Per-user database (no sharing)
- Respects file permissions
- User controls what's indexed

**Sandboxing:**
- Compatible with App Sandbox
- Minimal permissions required
- User-approved directory access only
- No network access needed

**Code Signing:**
- All binaries code signed
- Notarized for Gatekeeper
- Hardened runtime enabled

## Technical Requirements

### TR-1: Embedding Model

**Model:** all-MiniLM-L6-v2 (converted to Core ML)

**Specifications:**
- Dimensions: 384
- Format: Core ML (.mlmodel)
- Size: ~80MB
- Inference: <10ms per chunk
- Device: Neural Engine (preferred), GPU fallback, CPU fallback

### TR-2: FAISS Configuration

**Index Type:** IndexFlatL2 (v0)
- Exact L2 distance search
- Simple and reliable
- Good for <1M vectors

**Search:**
- Distance metric: L2 (Euclidean)
- Top-k: Configurable (default: 5)
- No filtering (return all top-k)

### TR-3: Database Schema

**Files Table:**
```sql
CREATE TABLE files_v2 (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT,
    size_bytes INTEGER,
    modified_time REAL,
    indexed_time REAL,
    file_hash TEXT
);
```

**Chunks Table:**
```sql
CREATE TABLE text_chunks_v2 (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB,  -- 384 floats × 4 bytes = 1536 bytes
    FOREIGN KEY (file_id) REFERENCES files_v2(id)
);
```

**Full-Text Search:**
```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    content,
    content=text_chunks_v2,
    content_rowid=id
);
```

### TR-4: Configuration

**Default Configuration:**
```json
{
  "database_path": "~/Library/Application Support/FileSearch/file_metadata.db",
  "watch_paths": [
    "~/Documents",
    "~/src",
    "~/Desktop"
  ],
  "exclude_paths": [".git", "node_modules", "__pycache__", ".build"],
  "file_extensions": ["py", "js", "ts", "swift", "c", "cpp", "h", "m", "md", "txt"],
  "max_files_per_batch": 10,
  "max_memory_mb": 200,
  "idle_threshold_seconds": 300,
  "battery_threshold": 0.20,
  "code_chunk_size": 350,
  "prose_chunk_size": 800
}
```

## Testing Requirements

### T-1: Unit Tests

**SQLite Extension:**
- [ ] Extension loads successfully
- [ ] `faiss_build_index()` builds index from database
- [ ] `faiss_search()` returns correct results
- [ ] Performance meets targets
- [ ] Memory usage within limits

**Background Indexer:**
- [ ] File discovery works
- [ ] Chunking logic correct
- [ ] Embedding generation works
- [ ] Database writes succeed
- [ ] FSEvents monitoring works

### T-2: Integration Tests

**End-to-End Indexing:**
- [ ] Index 1,000 test files
- [ ] Verify all files processed
- [ ] Check database consistency
- [ ] Validate embeddings generated

**End-to-End Search:**
- [ ] Search known content
- [ ] Verify correct files returned
- [ ] Check ranking quality
- [ ] Validate performance

**Intents Integration:**
- [ ] Intents visible in Shortcuts
- [ ] Siri recognizes phrases
- [ ] Results returned correctly
- [ ] Performance acceptable

### T-3: Performance Tests

**Scale Testing:**
- [ ] Index 200,000 files
- [ ] Measure indexing time
- [ ] Monitor memory usage
- [ ] Check search performance

**Stress Testing:**
- [ ] Continuous indexing for 24 hours
- [ ] No memory leaks
- [ ] No CPU spikes
- [ ] Database remains consistent

### T-4: Manual Testing

**Real-World Usage:**
- [ ] Use on developer's own files for 1 week
- [ ] Evaluate result quality
- [ ] Check for crashes/bugs
- [ ] Assess user experience

## Out of Scope (v0)

Explicitly NOT included in v0:

- ❌ Spotlight plugin integration
- ❌ Advanced GUI (menu bar only)
- ❌ Multi-user support
- ❌ Cloud sync
- ❌ Collaboration features
- ❌ Advanced analytics
- ❌ Non-text files (images, PDFs, videos)
- ❌ Knowledge graph
- ❌ PII detection
- ❌ Advanced compression (IVF, PQ)
- ❌ Distributed indexing

These may be considered for v1.0+ based on v0 success.

## Success Criteria

v0 is considered successful when:

**Functional:**
- [x] Indexes 200,000 files without crashing
- [x] Search returns relevant results <100ms
- [x] Apple Intents work with Siri
- [x] Background indexing non-intrusive

**Quality:**
- [x] No crashes in 1 week of testing
- [x] Search results subjectively useful
- [x] No system performance impact
- [x] Battery impact <5% per day

**Technical:**
- [x] Code signed and notarized
- [x] Self-contained .app bundle
- [x] Complete documentation
- [x] Clean installation/uninstallation

## Timeline

**v0 Development:** 8-12 weeks

**Phase 1: Core Implementation (4 weeks)**
- Week 1-2: SQLite extension + Core ML embeddings
- Week 3-4: Background indexer + FSEvents

**Phase 2: Intents Integration (2 weeks)**
- Week 5: Intent definitions and implementations
- Week 6: Siri integration and testing

**Phase 3: Testing & Polish (2 weeks)**
- Week 7: Scale testing (200K files)
- Week 8: Bug fixes and optimization

**Phase 4: Distribution (1 week)**
- Week 9: Code signing, notarization, packaging

## Risk Mitigation

**Risk: Memory usage too high at 200K files**
- Mitigation: Lazy loading, memory pressure handling, warn at limits

**Risk: Search quality not good enough**
- Mitigation: Use proven Python V2 architecture, same model/chunking

**Risk: Battery impact too high**
- Mitigation: Aggressive throttling, battery awareness, idle-only mode

**Risk: Intents integration complex**
- Mitigation: Start simple, iterate, use Apple documentation

## References

- Python V2 proof: `../chunking_refactor.py`, `../tools_v2/`
- Apple Intents: https://developer.apple.com/documentation/appintents
- FAISS: https://github.com/facebookresearch/faiss
- Core ML: https://developer.apple.com/documentation/coreml
