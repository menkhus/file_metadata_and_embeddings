# Apple Intents Integration TODO

## Concept (2026-02-02)

Expose SQLite database and FAISS semantic search to Apple apps (Siri, Shortcuts, Apple Intelligence) via native Swift App Intents framework.

**Why this matters:**
- Apple Intelligence can use Intents as tools
- Voice queries via Siri: "Find files about authentication"
- Automation via Shortcuts
- System-wide availability without launching an app
- Proper macOS citizen (not a Python script)

## Current State

**Location:** `osx_support/`

**Overall: 15% complete (skeleton only)**

| Component | Structure | Implementation | Status |
|-----------|-----------|----------------|--------|
| SQLite FAISS Extension | 100% | 20% | Stubbed (returns fake vectors) |
| Background Indexer | 100% | 15% | Stubbed (discovers but doesn't process) |
| Apple Intents | 0% | 0% | Not started |
| Build System | 100% | 100% | Working |
| Documentation | 100% | 100% | Complete |

**What compiles but doesn't work:**
- `sqlite_faiss_extension/` - Returns stub results `[1, 2, 3, 4, 5]`
- `background_indexer/` - Finds files but doesn't index them

## Architecture

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

## Three Intents Planned

### 1. SemanticSearchIntent
```swift
struct SemanticSearchIntent: AppIntent {
    static var title: LocalizedStringResource = "Semantic Search"
    static var description = IntentDescription(
        "Find files by meaning, not just keywords."
    )

    @Parameter(title: "Query")
    var query: String

    @Parameter(title: "Number of Results", default: 5)
    var topK: Int

    func perform() async throws -> IntentResult
}
```

**Use case:** "Find authentication code" → returns files about login, OAuth, sessions

### 2. GetFileContextIntent
```swift
struct GetFileContextIntent: AppIntent {
    static var title: LocalizedStringResource = "Get File Context"

    @Parameter(title: "File Path")
    var filePath: String

    @Parameter(title: "Chunk Index")
    var chunkIndex: Int

    @Parameter(title: "Context Size", default: 1)
    var contextSize: Int

    func perform() async throws -> IntentResult
}
```

**Use case:** Expand context around a search result (adjacent chunks)

### 3. RecentFilesIntent
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

**Use case:** "What Python files did I edit today?"

## Technology Stack

| Component | Technology | Why |
|-----------|------------|-----|
| Language | Swift + C++ | Native macOS, Apple frameworks |
| Embeddings | Core ML | Neural Engine, low power, native |
| Model | all-MiniLM-L6-v2 | 384-dim, proven in Python V2 |
| Vector Search | FAISS (static) | Industry standard, fast |
| Database | SQLite | Built into macOS, FTS5 |
| Integration | App Intents | Apple Intelligence, Siri, Shortcuts |

## Implementation Roadmap

### Phase 1: Real Embeddings (Weeks 1-2)
**Goal:** Generate actual 384-float vectors from text

**Tasks:**
- [ ] Download all-MiniLM-L6-v2 ONNX model
- [ ] Convert to Core ML format (.mlmodel)
- [ ] Implement `onnx_encoder.cpp` with real encoding
- [ ] Test: "hello world" → actual vector (not zeros)
- [ ] Verify L2 normalization and dimensions

**Success criteria:** Can generate real embeddings from text.

### Phase 2: Real Indexing (Weeks 3-4)
**Goal:** Index files and store embeddings in SQLite

**Tasks:**
- [ ] Port chunking logic from Python V2 to Swift
- [ ] Implement file processing in `FileIndexer.swift`
- [ ] Connect to Core ML for embedding generation
- [ ] Write chunks + embeddings to SQLite
- [ ] Implement FSEvents file monitoring
- [ ] Add battery/idle detection

**Success criteria:** Files → chunks → embeddings → database

### Phase 3: Real Search (Weeks 5-6)
**Goal:** Semantic search returns relevant results

**Tasks:**
- [ ] Load embeddings from SQLite into FAISS
- [ ] Build FAISS index (IndexFlatL2)
- [ ] Implement `faiss_search()` with real similarity
- [ ] Return ranked results with content
- [ ] Add FTS5 fallback for keyword search

**Success criteria:** Query returns semantically relevant files.

### Phase 4: Apple Intents (Weeks 7-8)
**Goal:** Siri and Shortcuts integration

**Tasks:**
- [ ] Create `intents/` directory structure
- [ ] Implement SemanticSearchIntent
- [ ] Implement GetFileContextIntent
- [ ] Implement RecentFilesIntent
- [ ] Register Siri phrases
- [ ] Test with Shortcuts app
- [ ] Test with Siri voice commands

**Success criteria:** "Hey Siri, find authentication code" works.

### Phase 5: Scale & Polish (Weeks 9-12)
**Goal:** Production-ready for 200K files

**Tasks:**
- [ ] Test with 200,000 file corpus
- [ ] Performance tuning (<100ms search)
- [ ] Memory optimization (<50MB index)
- [ ] Code signing and notarization
- [ ] Menu bar status app (optional)
- [ ] Error handling and edge cases

**Success criteria:** Self-contained .app that indexes 200K files.

## v0 Requirements

**Scale:**
- 200,000 files indexed
- 1M text chunks
- ~5GB storage

**Performance:**
- Cold search: <500ms
- Warm search: <100ms
- Indexing: 10 files/minute (throttled)
- Memory: <200MB during indexing, <50MB at rest

**Integration:**
- Siri voice queries work
- Shortcuts automation works
- Apple Intelligence can use as tool

## Key Files

**Documentation:**
- `osx_support/README.md` - Vision and overview
- `osx_support/ARCHITECTURE.md` - Full system design
- `osx_support/BUILD.md` - Build instructions
- `osx_support/REQUIREMENTS.md` - v0 requirements
- `osx_support/STATUS.md` - Honest current state

**Code (stubbed):**
- `osx_support/sqlite_faiss_extension/` - C++ SQLite extension
- `osx_support/background_indexer/` - Swift file indexer
- `osx_support/intents/` - Not yet created

**Reference (archived Kiro docs):**
- `osx_support/_archive_kiro/` - 26 files, use for reference only

## Relationship to Python V2

The native implementation ports proven concepts:

| Python V2 | Native (Swift/C++) |
|-----------|-------------------|
| `chunking_refactor.py` | `FileIndexer.swift` |
| `faiss_index_manager.py` | `faiss_extension.cpp` |
| `mcp_server_fixed.py` | Apple Intents |
| all-MiniLM-L6-v2 (ONNX) | all-MiniLM-L6-v2 (Core ML) |

**Principle:** Port, don't reinvent. Python V2 proves the architecture works.

## Risk Assessment

**Risk Level: MEDIUM**

**Mitigations:**
- Architecture proven in Python V2
- Build system already works
- Focus on one phase at a time
- Test incrementally before moving on

**Biggest risks:**
- Core ML model conversion complexity
- FAISS static linking on macOS
- Apple Intents learning curve

## Next Concrete Action

When ready to start:

```bash
# Week 1, Day 1: Get real embeddings working
1. Download ONNX model
2. Convert to Core ML: coremltools.convert()
3. Update onnx_encoder.cpp
4. Test: "hello" → [0.123, -0.456, ...] (actual 384 floats)
```

## References

- `osx_support/ARCHITECTURE.md` - Full technical design
- [Apple App Intents](https://developer.apple.com/documentation/appintents)
- [Core ML](https://developer.apple.com/documentation/coreml)
- [FAISS](https://github.com/facebookresearch/faiss)
