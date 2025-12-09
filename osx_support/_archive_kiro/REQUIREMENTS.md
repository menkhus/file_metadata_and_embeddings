# FileSearch v1.0 - Requirements Document

**Project:** Native macOS semantic file search system  
**Version:** 1.0  
**Status:** Ready for implementation  
**Last Updated:** 2025-11-14

---

## Executive Summary

Build a native macOS application that provides semantic search capabilities for local files, integrated with Spotlight. Zero Python dependencies, using C++/Swift with FAISS for vector search and Core ML for embeddings.

**Core Value:** Find files by meaning, not just keywords.

---

## 1. Functional Requirements

### 1.1 Core Features (Must Have)

#### FR-1.1: File Indexing
- **Description:** Automatically discover and index files in user-specified directories
- **Acceptance Criteria:**
  - Discovers all files in watched directories (default: ~/Documents, ~/src, ~/Desktop)
  - Supports file types: .py, .js, .ts, .swift, .c, .cpp, .h, .md, .txt
  - Chunks files appropriately (code: 350 chars, prose: 800 chars)
  - Generates embeddings for each chunk using all-MiniLM-L6-v2 model
  - Stores metadata and embeddings in SQLite database
  - Updates incrementally when files change (FSEvents monitoring)

#### FR-1.2: Semantic Search
- **Description:** Search files by meaning using natural language queries
- **Acceptance Criteria:**
  - Accepts natural language query (e.g., "authentication code")
  - Returns ranked results by semantic similarity
  - Returns results in <100ms (warm cache)
  - Returns top-k results (default: 5, configurable)
  - Includes file path, chunk content, and similarity score

#### FR-1.3: Spotlight Integration
- **Description:** Integrate semantic search results into macOS Spotlight
- **Acceptance Criteria:**
  - Works with ⌘Space Spotlight search
  - Shows semantic results alongside traditional results
  - Clicking result opens file in default application
  - No configuration required by user

#### FR-1.4: Background Processing
- **Description:** Index files in background without impacting user experience
- **Acceptance Criteria:**
  - Runs as background daemon (launchd service)
  - Low priority (QOS_CLASS_BACKGROUND)
  - Throttled to max 10 files/minute
  - Pauses when battery <20%
  - Pauses when system not idle (>5 min idle required)
  - Uses <200MB RAM
  - Uses <5% CPU average

### 1.2 Secondary Features (Nice to Have)

#### FR-2.1: Menu Bar App
- **Description:** Simple GUI for status and control
- **Acceptance Criteria:**
  - Shows indexing status (idle/indexing/paused)
  - Shows basic stats (files indexed, last update)
  - Allows manual trigger of indexing
  - Allows pause/resume
  - Quit option

#### FR-2.2: Siri Integration
- **Description:** Voice-activated file search
- **Acceptance Criteria:**
  - Responds to "Search my files for X"
  - Returns results via Siri interface
  - Works offline (no cloud required)

#### FR-2.3: Preferences Panel
- **Description:** User configuration interface
- **Acceptance Criteria:**
  - Configure watched directories
  - Configure file type filters
  - View indexing statistics
  - Clear index option
  - Enable/disable background indexing

---

## 2. Non-Functional Requirements

### 2.1 Performance

#### NFR-1.1: Search Performance
- Cold query (index not loaded): <500ms
- Warm query (index loaded): <100ms
- Index build time: <1s per 10,000 files

#### NFR-1.2: Indexing Performance
- Throughput: 10 files/minute (throttled)
- Memory usage: <200MB during indexing
- CPU usage: <5% average, <20% peak
- Disk I/O: <1MB/s

#### NFR-1.3: Storage Efficiency
- Metadata: ~1KB per file
- Embeddings: ~1.5KB per chunk (384 dimensions)
- FAISS index: ~2KB per chunk
- Total: ~5KB per chunk
- Example: 10,000 files × 5 chunks = 250MB

### 2.2 Scalability

#### NFR-2.1: Dataset Size
- Target: 10,000-100,000 files
- Maximum: 100,000 files (warn user if exceeded)
- Graceful degradation beyond limits

#### NFR-2.2: Memory Management
- Lazy loading: Load FAISS index on first search
- Unload after 5 minutes idle
- Respond to memory pressure events
- Never exceed 1GB total memory

### 2.3 Reliability

#### NFR-3.1: Stability
- No crashes during normal operation
- Graceful handling of corrupted files
- Automatic recovery from errors
- Proper cleanup on shutdown

#### NFR-3.2: Data Integrity
- SQLite transactions for all writes
- Atomic index updates
- Backup before major operations
- Corruption detection and recovery

### 2.4 Compatibility

#### NFR-4.1: Platform Support
- macOS 13.0+ (Ventura) required
- Apple Silicon (M1/M2/M3) primary target
- Intel Mac support (secondary)
- No Python dependencies
- No external runtime dependencies

#### NFR-4.2: File System
- Works with APFS (primary)
- Works with HFS+ (legacy)
- Respects file permissions
- Handles symlinks correctly

### 2.5 Security & Privacy

#### NFR-5.1: Privacy
- All processing local (no cloud)
- Per-user database (no sharing by default)
- Respects file permissions
- No telemetry or analytics

#### NFR-5.2: Sandboxing
- Compatible with App Sandbox
- Minimal permissions required
- User-approved directory access only

---

## 3. Technical Requirements

### 3.1 Architecture

#### TR-1.1: Components
1. **SQLite FAISS Extension** (C++)
   - Provides SQL functions for semantic search
   - Integrates FAISS for vector similarity
   - Statically linked (no runtime dependencies)

2. **Background Indexer** (Swift)
   - Discovers and processes files
   - Generates embeddings
   - Updates database
   - Runs as launchd daemon

3. **Spotlight Plugin** (Swift/Objective-C)
   - mdimporter bundle
   - Provides metadata to Spotlight
   - Integrates semantic results

4. **Menu Bar App** (SwiftUI) - Optional
   - Status display
   - Manual controls
   - Preferences

#### TR-1.2: Data Flow
```
Files → Indexer → Chunking → Embeddings → SQLite → FAISS Index → Search Results
```

### 3.2 Database Schema

#### TR-2.1: Required Tables

**files_v2**
```sql
CREATE TABLE files_v2 (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT,
    size_bytes INTEGER,
    modified_time REAL,
    created_time REAL,
    indexed_time REAL,
    file_hash TEXT,
    metadata_json TEXT
);
```

**text_chunks_v2**
```sql
CREATE TABLE text_chunks_v2 (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    start_char INTEGER,
    end_char INTEGER,
    embedding BLOB,
    FOREIGN KEY (file_id) REFERENCES files_v2(id)
);
```

**Full-Text Search**
```sql
CREATE VIRTUAL TABLE text_chunks_fts USING fts5(
    content,
    content=text_chunks_v2,
    content_rowid=id
);
```

### 3.3 Embedding Model

#### TR-3.1: Model Specification
- Model: all-MiniLM-L6-v2
- Dimensions: 384
- Format: ONNX or Core ML
- Size: ~80MB
- Device: Neural Engine (preferred), GPU, or CPU

#### TR-3.2: Embedding Generation
- Input: Text chunk (string)
- Output: Float32 vector [384]
- Normalization: L2 normalized
- Batch size: 1 (real-time) or 32 (batch indexing)

### 3.4 FAISS Configuration

#### TR-4.1: Index Type
- V1.0: IndexFlatL2 (exact search)
- Future: IndexIVFFlat (approximate search for >100K vectors)

#### TR-4.2: Search Parameters
- Metric: L2 distance
- Top-k: 5 (default), configurable
- Threshold: None (return all top-k)

### 3.5 Build System

#### TR-5.1: Build Requirements
- Xcode 15+ (for Swift 5.9)
- Command-line tools only (no Xcode IDE required)
- Makefile-based build
- Swift Package Manager for dependencies

#### TR-5.2: Dependencies
- FAISS (statically linked)
- ONNX Runtime or Core ML (for embeddings)
- SQLite 3.38+ (system provided)
- ArgumentParser (Swift package)

---

## 4. User Interface Requirements

### 4.1 Spotlight Integration

#### UI-1.1: Search Results
- Show in Spotlight results list
- Display: filename, path, snippet
- Icon: Custom file type icon
- Action: Open file on click

### 4.2 Menu Bar App (Optional)

#### UI-2.1: Status Display
- Icon states: idle (gray), indexing (blue), paused (yellow), error (red)
- Tooltip: "FileSearch - X files indexed"

#### UI-2.2: Menu Items
- Search... (opens search window)
- Status: "Indexing..." or "Idle"
- Statistics: "10,234 files indexed"
- Preferences...
- Quit

#### UI-2.3: Preferences Window
- Watched Directories (list with +/- buttons)
- File Types (checkboxes)
- Indexing Settings (sliders for throttling)
- Statistics (read-only display)
- Clear Index (button with confirmation)

---

## 5. Configuration Requirements

### 5.1 Default Configuration

```json
{
  "database_path": "~/Library/Application Support/FileSearch/file_metadata.db",
  "watch_paths": [
    "~/Documents",
    "~/src",
    "~/Desktop"
  ],
  "exclude_paths": [".git", "node_modules", "__pycache__", ".build"],
  "file_extensions": ["py", "js", "ts", "swift", "c", "cpp", "h", "md", "txt"],
  "max_files_per_batch": 10,
  "max_memory_mb": 200,
  "idle_threshold_seconds": 300,
  "battery_threshold": 0.20,
  "code_chunk_size": 350,
  "prose_chunk_size": 800,
  "embedding_model": "all-MiniLM-L6-v2",
  "embedding_device": "auto"
}
```

### 5.2 Configuration File Location
- User config: `~/Library/Application Support/FileSearch/config.json`
- System config: `/Library/Application Support/FileSearch/config.json` (optional)
- Command-line overrides: `--database`, `--watch-paths`, etc.

---

## 6. Testing Requirements

### 6.1 Unit Tests

#### TEST-1.1: Embedding Generation
- Test: Generate embedding for sample text
- Expected: 384-dimensional float vector
- Validation: Vector is L2 normalized

#### TEST-1.2: FAISS Search
- Test: Build index with known vectors, search
- Expected: Returns correct top-k results
- Validation: Results ranked by similarity

#### TEST-1.3: File Chunking
- Test: Chunk sample files (code and prose)
- Expected: Appropriate chunk sizes
- Validation: No data loss, proper boundaries

### 6.2 Integration Tests

#### TEST-2.1: End-to-End Indexing
- Test: Index sample directory (100 files)
- Expected: All files processed, embeddings stored
- Validation: Database contains correct data

#### TEST-2.2: End-to-End Search
- Test: Search for known content
- Expected: Returns relevant files
- Validation: Results match expected files

#### TEST-2.3: Spotlight Integration
- Test: Trigger Spotlight search
- Expected: Semantic results appear
- Validation: Results clickable and correct

### 6.3 Performance Tests

#### TEST-3.1: Search Latency
- Test: Measure search time (cold and warm)
- Expected: <500ms cold, <100ms warm
- Validation: 95th percentile meets target

#### TEST-3.2: Indexing Throughput
- Test: Index 1,000 files, measure time
- Expected: ~100 minutes (10 files/min)
- Validation: Throttling works correctly

#### TEST-3.3: Memory Usage
- Test: Monitor memory during indexing and search
- Expected: <200MB indexing, <50MB search
- Validation: No memory leaks

### 6.4 Manual Testing

#### TEST-4.1: Real-World Usage
- Test: Use on developer's own files for 1 week
- Expected: Useful results, no crashes
- Validation: Subjective quality assessment

#### TEST-4.2: Edge Cases
- Test: Large files, binary files, corrupted files, permission errors
- Expected: Graceful handling, no crashes
- Validation: Appropriate error messages

---

## 7. Deployment Requirements

### 7.1 Installation

#### DEPLOY-1.1: Installer Package
- Format: DMG with .app bundle
- Installation: Drag to Applications
- First run: Request directory access permissions
- Auto-start: Install launchd plist

#### DEPLOY-1.2: Uninstallation
- Remove: /Applications/FileSearch.app
- Remove: ~/Library/Application Support/FileSearch/
- Remove: ~/Library/LaunchAgents/com.filesearch.indexer.plist
- Remove: Spotlight plugin

### 7.2 Code Signing & Notarization

#### DEPLOY-2.1: Code Signing
- Sign all binaries with Developer ID
- Sign .app bundle
- Sign SQLite extension
- Sign Spotlight plugin

#### DEPLOY-2.2: Notarization
- Submit to Apple for notarization
- Staple notarization ticket
- Verify notarization before distribution

### 7.3 Distribution

#### DEPLOY-3.1: Distribution Channels
- Direct download (primary)
- GitHub releases
- Homebrew cask (future)
- Mac App Store (future, optional)

---

## 8. Documentation Requirements

### 8.1 User Documentation

#### DOC-1.1: README
- What is FileSearch
- Installation instructions
- Basic usage
- Troubleshooting
- FAQ

#### DOC-1.2: User Guide
- How semantic search works
- Configuring watched directories
- Understanding results
- Performance tips

### 8.2 Developer Documentation

#### DOC-2.1: Architecture Overview
- Component diagram
- Data flow
- Technology choices

#### DOC-2.2: Build Instructions
- Prerequisites
- Build steps
- Testing
- Debugging

#### DOC-2.3: API Documentation
- SQL functions
- Swift APIs
- Configuration options

---

## 9. Success Criteria

### 9.1 Launch Criteria (Must Meet All)

- ✅ Indexes 10,000 files without crashing
- ✅ Search returns results in <100ms (warm)
- ✅ Works with Spotlight (⌘Space)
- ✅ Runs in background without user intervention
- ✅ Uses <1GB RAM total
- ✅ Installs in <2 minutes
- ✅ Works without configuration
- ✅ Uninstalls cleanly
- ✅ Code signed and notarized
- ✅ Documentation complete

### 9.2 Quality Criteria

- ✅ No crashes in 1 week of testing
- ✅ Search results subjectively useful
- ✅ No noticeable system slowdown
- ✅ Battery impact <5% per day
- ✅ Disk space usage reasonable (<500MB for 10K files)

### 9.3 User Adoption Criteria (Post-Launch)

- 🎯 100 downloads in first month
- 🎯 10 active daily users
- 🎯 5 pieces of user feedback
- 🎯 0 critical bugs reported
- 🎯 Positive sentiment in feedback

---

## 10. Out of Scope (V1.0)

Explicitly NOT included in v1.0:

- ❌ Cloud sync
- ❌ Multi-user sharing
- ❌ Advanced UI (custom search interface)
- ❌ File preview
- ❌ Collaboration features
- ❌ Advanced compression (LEANN, PQ)
- ❌ Distributed indexing
- ❌ Plugin system
- ❌ Non-English languages
- ❌ Non-text files (images, PDFs)
- ❌ Advanced analytics
- ❌ Integration with other apps

These may be considered for v2.0 based on user feedback.

---

## 11. Risks & Mitigations

### 11.1 Technical Risks

**RISK-1: FAISS memory usage too high**
- Impact: High
- Probability: Medium
- Mitigation: Lazy loading, memory pressure handling, warn users at 100K files

**RISK-2: Embedding generation too slow**
- Impact: Medium
- Probability: Low
- Mitigation: Use Neural Engine, batch processing, throttling

**RISK-3: Spotlight integration breaks**
- Impact: High
- Probability: Low
- Mitigation: Thorough testing, fallback to standalone app

### 11.2 User Experience Risks

**RISK-4: Search results not useful**
- Impact: High
- Probability: Medium
- Mitigation: Beta testing, iterate on ranking algorithm

**RISK-5: Too intrusive (battery/CPU)**
- Impact: Medium
- Probability: Low
- Mitigation: Aggressive throttling, battery awareness, user controls

### 11.3 Business Risks

**RISK-6: Low adoption**
- Impact: Medium
- Probability: Medium
- Mitigation: Clear value proposition, good documentation, community engagement

---

## 12. Timeline

### 12.1 Development Phases

**Phase 1: Core Functionality (4 weeks)**
- Week 1: SQLite extension + embeddings
- Week 2: Background indexer
- Week 3: Spotlight integration
- Week 4: Polish and bug fixes

**Phase 2: Beta Testing (2 weeks)**
- Week 5: Internal testing
- Week 6: Friends & family beta

**Phase 3: Launch (2 weeks)**
- Week 7: Code signing, notarization, documentation
- Week 8: Launch and initial support

**Total: 8 weeks**

### 12.2 Milestones

- ✅ M1: Project setup and architecture (Week 0)
- 🎯 M2: Working end-to-end demo (Week 2)
- 🎯 M3: Spotlight integration working (Week 3)
- 🎯 M4: Beta ready (Week 5)
- 🎯 M5: Launch ready (Week 7)
- 🎯 M6: Public launch (Week 8)

---

## 13. Acceptance Criteria Summary

For v1.0 to be considered complete and ready to ship:

### 13.1 Functional
- [x] Indexes files automatically
- [x] Generates embeddings
- [x] Performs semantic search
- [x] Integrates with Spotlight
- [x] Runs in background
- [x] Respects system resources

### 13.2 Performance
- [x] Search <100ms (warm)
- [x] Memory <200MB (indexing)
- [x] CPU <5% (average)
- [x] Handles 10,000+ files

### 13.3 Quality
- [x] No crashes in testing
- [x] Useful search results
- [x] Clean installation/uninstallation
- [x] Complete documentation

### 13.4 Distribution
- [x] Code signed
- [x] Notarized
- [x] DMG created
- [x] Ready to distribute

---

## 14. Next Steps

1. **Review this requirements document** with team
2. **Create detailed task breakdown** for Phase 1
3. **Set up development environment** (Xcode, dependencies)
4. **Start with SQLite extension** (Week 1)
5. **Iterate based on testing** (continuous)

---

## Appendix A: Glossary

- **Embedding**: Vector representation of text (384 dimensions)
- **FAISS**: Facebook AI Similarity Search library
- **Semantic Search**: Search by meaning, not keywords
- **Chunk**: Segment of file content (350-800 chars)
- **mdimporter**: macOS Spotlight metadata importer plugin
- **launchd**: macOS system service manager
- **FSEvents**: macOS file system change notification API
- **Core ML**: Apple's machine learning framework
- **ONNX**: Open Neural Network Exchange format

---

## Appendix B: References

- [FAISS Documentation](https://github.com/facebookresearch/faiss)
- [all-MiniLM-L6-v2 Model](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
- [macOS Spotlight Importers](https://developer.apple.com/documentation/coreservices/spotlight_importers)
- [App Intents Framework](https://developer.apple.com/documentation/appintents)
- [SQLite Extensions](https://www.sqlite.org/loadext.html)

---

**Document Status:** ✅ Ready for Implementation  
**Approval Required:** Product Owner, Tech Lead  
**Next Review:** After Phase 1 completion
