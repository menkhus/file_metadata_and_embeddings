# macOS Native Implementation Plan
## File Metadata & Semantic Search System

**Goal:** Zero-Python, native macOS solution with Apple Intents, background indexing, and conversational file access.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    User Interfaces                          │
│  • Siri/Shortcuts  • Menu Bar App  • Spotlight Plugin       │
└────────────┬────────────────────────────────────────────────┘
             │
             ↓
┌─────────────────────────────────────────────────────────────┐
│              Apple Intents Framework (Swift)                │
│  • SearchFilesIntent  • SemanticSearchIntent                │
│  • GetFileContextIntent  • RecentFilesIntent                │
└────────────┬────────────────────────────────────────────────┘
             │
             ↓
┌─────────────────────────────────────────────────────────────┐
│           SQLite + FAISS Extension (C++)                    │
│  • faiss_search()  • faiss_build_index()                    │
│  • Embeddings stored as BLOBs                               │
└────────────┬────────────────────────────────────────────────┘
             │
             ↓
┌─────────────────────────────────────────────────────────────┐
│         Background Indexer (Swift/launchd)                  │
│  • FSEvents monitoring  • Low-priority processing           │
│  • ONNX Runtime for embeddings  • Incremental updates       │
└─────────────────────────────────────────────────────────────┘
```

---

## Component 1: SQLite FAISS Extension (C++)

**Purpose:** Native semantic search without Python

**Files:**
- `osx_support/sqlite_faiss_extension/faiss_extension.cpp`
- `osx_support/sqlite_faiss_extension/Makefile`
- `osx_support/sqlite_faiss_extension/onnx_encoder.cpp`

**Key Features:**
- Statically linked FAISS (no runtime dependencies)
- ONNX Runtime for text encoding (all-MiniLM-L6-v2)
- SQL functions: `faiss_search()`, `faiss_build_index()`, `faiss_encode_text()`
- Memory-efficient: lazy loading, LRU cache

**Build:**
```bash
cd osx_support/sqlite_faiss_extension
make release  # Creates faiss_extension.dylib
make install  # Installs to /usr/local/lib/sqlite3/
```

**Usage:**
```sql
.load faiss_extension
SELECT * FROM faiss_search('error handling', 5);
```

---

## Component 2: Background Indexer (Swift + launchd)

**Purpose:** Non-intrusive, automatic file indexing

**Files:**
- `osx_support/background_indexer/FileIndexer.swift`
- `osx_support/background_indexer/com.fileindexer.plist` (launchd)
- `osx_support/background_indexer/IndexerConfig.swift`

**Key Features:**
- FSEvents monitoring (watches directories for changes)
- Low-priority QoS (QOS_CLASS_BACKGROUND)
- Throttled processing (max 10 files/minute)
- Idle-only mode (only runs when system idle >5 min)
- Battery-aware (pauses on battery <20%)
- Memory limit (max 200MB)

**Configuration:**
```swift
struct IndexerConfig {
    let watchPaths: [String] = [
        "~/Documents",
        "~/src",
        "~/Desktop"
    ]
    let maxFilesPerBatch = 10
    let idleThresholdSeconds = 300
    let maxMemoryMB = 200
    let batteryThreshold = 0.20
}
```

**Installation:**
```bash
cd osx_support/background_indexer
swift build -c release
cp .build/release/FileIndexer /usr/local/bin/
launchctl load com.fileindexer.plist
```

**Control:**
```bash
# Start/stop
launchctl start com.fileindexer
launchctl stop com.fileindexer

# Status
launchctl list | grep fileindexer

# Logs
log show --predicate 'subsystem == "com.fileindexer"' --last 1h
```

---

## Component 3: Apple Intents (Swift)

**Purpose:** Siri/Shortcuts integration

**Files:**
- `osx_support/intents/FileSearchIntents/`
  - `SearchFilesIntent.swift`
  - `SemanticSearchIntent.swift`
  - `GetFileContextIntent.swift`
  - `RecentFilesIntent.swift`
- `osx_support/intents/FileSearchIntents.intentdefinition`

**Intents Defined:**

### 1. SearchFilesIntent
```swift
@available(iOS 16.0, macOS 13.0, *)
struct SearchFilesIntent: AppIntent {
    static var title: LocalizedStringResource = "Search Files"
    static var description = IntentDescription("Search files by name or content")
    
    @Parameter(title: "Query")
    var query: String
    
    @Parameter(title: "Search Type", default: .name)
    var searchType: SearchType
    
    func perform() async throws -> some IntentResult & ReturnsValue<[FileResult]>
}
```

### 2. SemanticSearchIntent
```swift
struct SemanticSearchIntent: AppIntent {
    static var title: LocalizedStringResource = "Semantic Search"
    static var description = IntentDescription("Find files by meaning, not just keywords")
    
    @Parameter(title: "Query")
    var query: String
    
    @Parameter(title: "Number of Results", default: 5)
    var topK: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<[FileResult]>
}
```

### 3. GetFileContextIntent
```swift
struct GetFileContextIntent: AppIntent {
    static var title: LocalizedStringResource = "Get File Context"
    static var description = IntentDescription("Get surrounding context for a file chunk")
    
    @Parameter(title: "File Path")
    var filePath: String
    
    @Parameter(title: "Chunk Index")
    var chunkIndex: Int
    
    @Parameter(title: "Context Size", default: 1)
    var contextSize: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<FileContext>
}
```

### 4. RecentFilesIntent
```swift
struct RecentFilesIntent: AppIntent {
    static var title: LocalizedStringResource = "Recent Files"
    static var description = IntentDescription("Get recently modified files")
    
    @Parameter(title: "Hours", default: 24)
    var hours: Int
    
    @Parameter(title: "File Type")
    var fileType: String?
    
    func perform() async throws -> some IntentResult & ReturnsValue<[FileResult]>
}
```

**Siri Phrases:**
- "Search files for config"
- "Find files about authentication"
- "Show recent Python files"
- "Get context for this file"

---

## Component 4: Menu Bar App (SwiftUI)

**Purpose:** Quick access GUI

**Files:**
- `osx_support/gui_app/FileSearchApp/`
  - `FileSearchApp.swift`
  - `SearchView.swift`
  - `ResultsView.swift`
  - `SettingsView.swift`

**Features:**
- Menu bar icon with quick search
- Recent searches history
- Indexer status indicator
- Settings panel:
  - Watch directories
  - Indexer throttling
  - Database location
  - Enable/disable background indexing

**UI:**
```
┌─────────────────────────────────┐
│  🔍 File Search                 │
├─────────────────────────────────┤
│  Search: [________________]  🔍 │
│                                 │
│  ○ Name    ○ Content   ● Semantic│
│                                 │
│  Results:                       │
│  ┌───────────────────────────┐ │
│  │ config.py                 │ │
│  │ ~/src/project/config.py   │ │
│  │ Modified: 2 hours ago     │ │
│  └───────────────────────────┘ │
│  ┌───────────────────────────┐ │
│  │ settings.json             │ │
│  │ ~/Documents/settings.json │ │
│  │ Modified: 1 day ago       │ │
│  └───────────────────────────┘ │
│                                 │
│  [⚙️ Settings]  [📊 Stats]      │
└─────────────────────────────────┘
```

---

## Component 5: Spotlight Plugin (Optional)

**Purpose:** System-wide search integration

**Files:**
- `osx_support/spotlight_plugin/FileSearchSpotlight.mdimporter/`

**Features:**
- Integrates with macOS Spotlight
- Semantic search results in Spotlight UI
- Custom metadata attributes

---

## Apple Intelligence Integration

**Question:** Can Apple's local AI support simple queries with proper semantic descriptions?

**Answer:** YES! Here's how:

### App Intents + Apple Intelligence

Apple Intelligence (iOS 18+, macOS 15+) can:
1. **Understand natural language** → Route to correct Intent
2. **Extract parameters** → Fill Intent parameters automatically
3. **Chain Intents** → Multi-step workflows
4. **Suggest actions** → Proactive suggestions based on context

**Example Flow:**
```
User: "Show me Python files I worked on yesterday about authentication"
  ↓
Apple Intelligence parses:
  - File type: Python (.py)
  - Time: Yesterday
  - Semantic: "authentication"
  ↓
Calls: SemanticSearchIntent(
  query: "authentication",
  fileType: ".py",
  modifiedSince: yesterday
)
  ↓
Returns: Ranked results with context
```

### Semantic Descriptions for Intents

```swift
struct SemanticSearchIntent: AppIntent {
    static var title: LocalizedStringResource = "Semantic Search"
    
    // Rich semantic description for Apple Intelligence
    static var description = IntentDescription(
        "Find files by meaning and context, not just keywords. " +
        "Understands concepts like 'authentication', 'error handling', " +
        "'database connections' and finds relevant code even if exact " +
        "words don't match."
    )
    
    // Parameter descriptions help AI understand intent
    @Parameter(
        title: "Query",
        description: "Natural language description of what you're looking for"
    )
    var query: String
    
    // Suggested phrases for Siri
    static var suggestedInvocationPhrase: String = "Search my code"
    
    // Example queries for training
    static var examples: [IntentExample] = [
        IntentExample("Find authentication code"),
        IntentExample("Show error handling examples"),
        IntentExample("Search for database connections")
    ]
}
```

### Agentic Tools

Apple Intelligence can chain your Intents as "tools":

```swift
// Tool 1: Search
SemanticSearchIntent(query: "authentication")
  ↓ Returns file paths
  
// Tool 2: Get context
GetFileContextIntent(filePath: result[0].path, contextSize: 2)
  ↓ Returns surrounding code
  
// Tool 3: Summarize (built-in Apple Intelligence)
SummarizeIntent(text: context)
  ↓ Returns summary
```

**User says:** "Explain how authentication works in my codebase"

**Apple Intelligence:**
1. Calls `SemanticSearchIntent("authentication")`
2. Gets top 3 results
3. Calls `GetFileContextIntent()` for each
4. Synthesizes answer using local LLM
5. Speaks/displays result

---

## Implementation Phases

### Phase 1: Core Foundation (Week 1)
- ✅ SQLite FAISS extension (C++)
- ✅ Basic SQL functions
- ✅ ONNX Runtime integration
- ✅ Build system (Makefile)

### Phase 2: Background Indexer (Week 2)
- ✅ Swift indexer daemon
- ✅ FSEvents monitoring
- ✅ launchd integration
- ✅ Throttling & resource limits
- ✅ Battery awareness

### Phase 3: Apple Intents (Week 3)
- ✅ Intent definitions
- ✅ Swift implementations
- ✅ Siri phrase registration
- ✅ Shortcuts integration
- ✅ Testing with Apple Intelligence

### Phase 4: GUI App (Week 4)
- ✅ SwiftUI menu bar app
- ✅ Search interface
- ✅ Settings panel
- ✅ Indexer controls

### Phase 5: Polish & Distribution (Week 5)
- ✅ Code signing
- ✅ Notarization
- ✅ Installer package
- ✅ Documentation
- ✅ App Store submission (optional)

---

## Technical Specifications

### Dependencies

**Required:**
- macOS 13.0+ (for App Intents)
- Xcode 15+
- SQLite 3.38+ (for JSON functions)
- FAISS (statically linked)
- ONNX Runtime (statically linked)

**Optional:**
- Apple Intelligence (macOS 15+)
- Spotlight integration

### Performance Targets

**Indexing:**
- Speed: 10 files/minute (throttled)
- Memory: <200MB
- CPU: <5% average
- Disk I/O: <1MB/s

**Search:**
- Cold query: <100ms
- Warm query: <10ms
- Index build: <1s for 10K files
- Memory: <50MB for index

### Storage

**Database Size:**
- Metadata: ~1KB per file
- Embeddings: ~1.5KB per chunk (384 dims)
- Index: ~2KB per chunk (FAISS)
- **Total:** ~5KB per chunk

**Example:** 10,000 files × 5 chunks/file = 50,000 chunks = 250MB

---

## File Structure

```
osx_support/
├── IMPLEMENTATION_PLAN.md (this file)
├── README.md
│
├── sqlite_faiss_extension/
│   ├── faiss_extension.cpp
│   ├── onnx_encoder.cpp
│   ├── onnx_encoder.h
│   ├── Makefile
│   ├── test_extension.sh
│   └── models/
│       └── all-MiniLM-L6-v2.onnx (80MB)
│
├── background_indexer/
│   ├── Sources/
│   │   ├── FileIndexer.swift
│   │   ├── IndexerConfig.swift
│   │   ├── FSEventsMonitor.swift
│   │   └── EmbeddingGenerator.swift
│   ├── Package.swift
│   ├── com.fileindexer.plist
│   └── install.sh
│
├── intents/
│   ├── FileSearchIntents/
│   │   ├── SearchFilesIntent.swift
│   │   ├── SemanticSearchIntent.swift
│   │   ├── GetFileContextIntent.swift
│   │   └── RecentFilesIntent.swift
│   ├── FileSearchIntents.intentdefinition
│   └── Package.swift
│
├── gui_app/
│   ├── FileSearchApp/
│   │   ├── FileSearchApp.swift
│   │   ├── Views/
│   │   │   ├── SearchView.swift
│   │   │   ├── ResultsView.swift
│   │   │   └── SettingsView.swift
│   │   └── Models/
│   │       ├── SearchManager.swift
│   │       └── IndexerStatus.swift
│   └── FileSearchApp.xcodeproj
│
└── shortcuts/
    ├── Search Files.shortcut
    ├── Semantic Search.shortcut
    ├── Recent Files.shortcut
    └── README.md
```

---

## Build Instructions

### 1. Build SQLite Extension

```bash
cd osx_support/sqlite_faiss_extension
make release
sudo make install
```

### 2. Build Background Indexer

```bash
cd osx_support/background_indexer
swift build -c release
./install.sh
```

### 3. Build Intents Framework

```bash
cd osx_support/intents
swift build -c release
```

### 4. Build GUI App

```bash
cd osx_support/gui_app
xcodebuild -project FileSearchApp.xcodeproj -scheme FileSearchApp -configuration Release
```

### 5. Install Shortcuts

```bash
cd osx_support/shortcuts
open "Search Files.shortcut"  # Imports to Shortcuts app
```

---

## Testing

### Test SQLite Extension

```bash
cd osx_support/sqlite_faiss_extension
./test_extension.sh
```

### Test Background Indexer

```bash
# Start indexer
launchctl start com.fileindexer

# Monitor logs
log stream --predicate 'subsystem == "com.fileindexer"'

# Check status
sqlite3 ~/Library/Application\ Support/FileSearch/file_metadata.db \
  "SELECT COUNT(*) FROM text_chunks_v2 WHERE embedding IS NOT NULL;"
```

### Test Intents

```bash
# Via Shortcuts app
open shortcuts://run-shortcut?name=Semantic%20Search&input=authentication

# Via Siri
# Say: "Search my code for authentication"
```

---

## Configuration

### Database Location

Default: `~/Library/Application Support/FileSearch/file_metadata.db`

Override:
```bash
defaults write com.fileindexer databasePath "/custom/path/file_metadata.db"
```

### Watch Directories

```bash
defaults write com.fileindexer watchPaths -array \
  "$HOME/Documents" \
  "$HOME/src" \
  "$HOME/Desktop"
```

### Indexer Settings

```bash
# Throttle (files per minute)
defaults write com.fileindexer maxFilesPerMinute 10

# Memory limit (MB)
defaults write com.fileindexer maxMemoryMB 200

# Battery threshold (0.0-1.0)
defaults write com.fileindexer batteryThreshold 0.20

# Idle threshold (seconds)
defaults write com.fileindexer idleThresholdSeconds 300
```

---

## Troubleshooting

### Extension won't load

```bash
# Check if extension exists
ls -la /usr/local/lib/sqlite3/faiss_extension.dylib

# Check dependencies
otool -L /usr/local/lib/sqlite3/faiss_extension.dylib

# Test manually
sqlite3 test.db ".load /usr/local/lib/sqlite3/faiss_extension.dylib"
```

### Indexer not running

```bash
# Check launchd status
launchctl list | grep fileindexer

# Check logs
log show --predicate 'subsystem == "com.fileindexer"' --last 1h

# Restart
launchctl stop com.fileindexer
launchctl start com.fileindexer
```

### Intents not appearing in Shortcuts

```bash
# Rebuild intents
cd osx_support/intents
swift build -c release

# Clear Shortcuts cache
killall Shortcuts
```

---

## Distribution

### Code Signing

```bash
# Sign extension
codesign --sign "Developer ID Application" faiss_extension.dylib

# Sign app
codesign --sign "Developer ID Application" --deep FileSearchApp.app
```

### Notarization

```bash
# Create archive
ditto -c -k --keepParent FileSearchApp.app FileSearchApp.zip

# Submit for notarization
xcrun notarytool submit FileSearchApp.zip \
  --apple-id "your@email.com" \
  --team-id "TEAMID" \
  --password "app-specific-password"

# Staple ticket
xcrun stapler staple FileSearchApp.app
```

### Installer Package

```bash
pkgbuild --root /tmp/install \
  --identifier com.fileindexer.pkg \
  --version 1.0 \
  --install-location / \
  FileIndexer.pkg
```

---

## Next Steps

1. **Review this plan** - Ensure it meets your requirements
2. **Start with Phase 1** - Build SQLite extension first
3. **Test incrementally** - Each component independently
4. **Integrate gradually** - Connect components one by one
5. **Polish & ship** - Code sign, notarize, distribute

---

## Questions Answered

**Q: Do I need Python?**
A: No. Everything is native C++/Swift.

**Q: Will Apple Intelligence work?**
A: Yes. App Intents + semantic descriptions enable natural language queries.

**Q: Can I add a GUI?**
A: Yes. SwiftUI menu bar app included in plan.

**Q: Will it be intrusive?**
A: No. Background indexer is throttled, low-priority, battery-aware, and idle-only.

**Q: How do I know Intents will work?**
A: App Intents is a mature framework (iOS 16+, macOS 13+). Semantic search via Intents is proven in apps like Spotlight, Files, and third-party apps.

---

## Success Criteria

✅ Zero Python dependencies
✅ Native macOS integration
✅ Siri/Shortcuts support
✅ Background indexing (non-intrusive)
✅ Fast semantic search (<100ms)
✅ Low resource usage (<200MB, <5% CPU)
✅ Conversational file access via Apple Intelligence
✅ GUI for manual control
✅ Distributable (code signed, notarized)

---

**Ready to implement!** Start with Phase 1 (SQLite extension) and work through each phase systematically.
