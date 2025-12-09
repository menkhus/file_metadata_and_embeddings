# macOS First-Class Design

Proper macOS application architecture - the Apple way.

## The Problem

Current design is a "science experiment":
- ❌ Manual `make install` to system directories
- ❌ Scattered files across `/usr/local/`
- ❌ No proper app bundle
- ❌ Command-line focused, not Mac-like
- ❌ Requires user to know about SQLite extensions

## The Solution: Proper macOS App

```
FileSearch.app/
├── Contents/
│   ├── MacOS/
│   │   └── FileSearch              # Main GUI app
│   ├── Resources/
│   │   ├── faiss_extension.dylib   # Bundled extension
│   │   └── FileIndexer             # Background helper
│   ├── Library/
│   │   └── LoginItems/
│   │       └── FileIndexerHelper.app
│   ├── Frameworks/                  # Embedded frameworks
│   │   ├── libfaiss.dylib
│   │   └── libonnxruntime.dylib
│   └── Info.plist
```

## User Experience

### Installation
1. Download `FileSearch.dmg`
2. Drag `FileSearch.app` to Applications
3. Done!

### First Launch
1. App opens with welcome screen
2. Asks permission to index directories
3. Starts background indexer (sandboxed)
4. Shows menu bar icon

### Usage
- **Menu bar app** - Always accessible
- **Spotlight-like search** - ⌘Space equivalent
- **Siri integration** - "Search my code for authentication"
- **Shortcuts** - Pre-built shortcuts included
- **No terminal required** - Everything in GUI

### Uninstallation
1. Quit app
2. Drag to Trash
3. Done! (App cleans up on quit)

## Architecture

```
┌─────────────────────────────────────────┐
│  FileSearch.app (SwiftUI)               │
│  • Menu bar interface                   │
│  • Search UI                            │
│  • Settings panel                       │
│  • Manages all components               │
└────────────┬────────────────────────────┘
             │
             ├─→ Embedded SQLite Extension
             │   • Loaded from app bundle
             │   • No system installation
             │
             ├─→ Background Indexer Helper
             │   • XPC Service (sandboxed)
             │   • Managed by main app
             │   • Auto-starts/stops
             │
             └─→ App Intents
                 • Siri integration
                 • Shortcuts support
                 • System integration
```

## Database Location

**Proper macOS location:**
```
~/Library/Application Support/FileSearch/
├── file_metadata.db
├── faiss_index.bin
└── config.json
```

**Not:** `/usr/local/` or system directories!

## Component Design

### 1. Main App (SwiftUI)

```swift
@main
struct FileSearchApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    
    var body: some Scene {
        // Menu bar app
        MenuBarExtra("FileSearch", systemImage: "magnifyingglass") {
            SearchView()
            Divider()
            SettingsLink()
            Divider()
            Button("Quit") { NSApplication.shared.terminate(nil) }
        }
        .menuBarExtraStyle(.window)
        
        // Settings window
        Settings {
            SettingsView()
        }
    }
}
```

### 2. SQLite Extension (Embedded)

**Load from app bundle:**
```swift
func loadExtension() -> Bool {
    guard let extensionPath = Bundle.main.path(
        forResource: "faiss_extension",
        ofType: "dylib"
    ) else {
        return false
    }
    
    // Load extension from app bundle
    sqlite3_load_extension(db, extensionPath, nil, nil)
    return true
}
```

**No system installation needed!**

### 3. Background Indexer (XPC Service)

```swift
// FileIndexerService.xpc
// Runs sandboxed, managed by main app
class FileIndexerService: NSObject, FileIndexerProtocol {
    func startIndexing(paths: [URL]) async throws {
        // Index files
    }
}
```

**Benefits:**
- Sandboxed for security
- Managed lifecycle
- Automatic crash recovery
- Proper resource limits

### 4. App Intents (Built-in)

```swift
struct SearchFilesIntent: AppIntent {
    static var title: LocalizedStringResource = "Search Files"
    
    @Parameter(title: "Query")
    var query: String
    
    func perform() async throws -> some IntentResult {
        // Search using embedded extension
        let results = await FileSearchManager.shared.search(query)
        return .result(value: results)
    }
}
```

## Xcode Project Structure

```
FileSearch/
├── FileSearch.xcodeproj
├── FileSearch/                      # Main app target
│   ├── FileSearchApp.swift
│   ├── Views/
│   │   ├── SearchView.swift
│   │   ├── ResultsView.swift
│   │   └── SettingsView.swift
│   ├── Models/
│   │   ├── SearchManager.swift
│   │   └── DatabaseManager.swift
│   └── Resources/
│       ├── Assets.xcassets
│       └── Info.plist
│
├── FileIndexerService/              # XPC service target
│   ├── FileIndexerService.swift
│   └── Info.plist
│
├── FAISSExtension/                  # C++ extension target
│   ├── faiss_extension.cpp
│   └── onnx_encoder.cpp
│
└── FileSearchIntents/               # Intents extension target
    ├── SearchFilesIntent.swift
    └── Info.plist
```

## Build Configuration

### Xcode Targets

1. **FileSearch** (macOS App)
   - Type: Application
   - Language: Swift
   - UI: SwiftUI
   - Deployment: macOS 13.0+

2. **FAISSExtension** (Dynamic Library)
   - Type: Dynamic Library
   - Language: C++
   - Embedded in app bundle

3. **FileIndexerService** (XPC Service)
   - Type: XPC Service
   - Language: Swift
   - Sandboxed: Yes

4. **FileSearchIntents** (Intents Extension)
   - Type: Intents Extension
   - Language: Swift
   - Provides: App Intents

### Embedding Dependencies

**Frameworks folder:**
```xml
<!-- Copy Files Build Phase -->
<key>Destination</key>
<string>Frameworks</string>
<key>Files</key>
<array>
    <string>libfaiss.dylib</string>
    <string>libonnxruntime.dylib</string>
</array>
```

**Resources folder:**
```xml
<key>Destination</key>
<string>Resources</string>
<key>Files</key>
<array>
    <string>faiss_extension.dylib</string>
    <string>all-MiniLM-L6-v2.onnx</string>
</array>
```

## Sandboxing & Entitlements

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- App Sandbox -->
    <key>com.apple.security.app-sandbox</key>
    <true/>
    
    <!-- File Access -->
    <key>com.apple.security.files.user-selected.read-write</key>
    <true/>
    <key>com.apple.security.files.bookmarks.app-scope</key>
    <true/>
    
    <!-- Network (for future features) -->
    <key>com.apple.security.network.client</key>
    <true/>
</dict>
</plist>
```

## Distribution

### 1. Build Archive

```bash
xcodebuild archive \
  -project FileSearch.xcodeproj \
  -scheme FileSearch \
  -archivePath FileSearch.xcarchive
```

### 2. Export App

```bash
xcodebuild -exportArchive \
  -archivePath FileSearch.xcarchive \
  -exportPath . \
  -exportOptionsPlist ExportOptions.plist
```

### 3. Create DMG

```bash
create-dmg \
  --volname "FileSearch" \
  --window-pos 200 120 \
  --window-size 800 400 \
  --icon-size 100 \
  --icon "FileSearch.app" 200 190 \
  --hide-extension "FileSearch.app" \
  --app-drop-link 600 185 \
  "FileSearch.dmg" \
  "FileSearch.app"
```

### 4. Notarize

```bash
xcrun notarytool submit FileSearch.dmg \
  --apple-id "your@email.com" \
  --team-id "TEAMID" \
  --password "app-specific-password" \
  --wait

xcrun stapler staple FileSearch.dmg
```

## User Experience Flow

### First Launch

```
1. User opens FileSearch.app
   ↓
2. Welcome screen appears
   "Welcome to FileSearch
    Let's set up your file indexing"
   ↓
3. Directory selection
   [x] Documents
   [x] Desktop
   [x] Code Projects
   [ ] Custom...
   ↓
4. Permission request
   "FileSearch needs access to index these folders"
   [Allow] [Deny]
   ↓
5. Indexing starts
   "Indexing your files... (234 files found)"
   Progress bar
   ↓
6. Complete
   "Ready to search!"
   Menu bar icon appears
```

### Daily Use

```
1. Click menu bar icon
   ↓
2. Search field appears (Spotlight-like)
   ↓
3. Type query: "error handling"
   ↓
4. Results appear instantly
   - file.py (line 42)
   - utils.js (line 156)
   ↓
5. Click result → Opens in default editor
```

### Siri Integration

```
User: "Hey Siri, search my code for authentication"
  ↓
Siri: "I found 5 files about authentication"
  ↓
Shows results in Siri UI
  ↓
Tap to open in FileSearch.app
```

## Migration Path

### Phase 1: Core App (2 weeks)
- [ ] Create Xcode project
- [ ] SwiftUI menu bar app
- [ ] Embed SQLite extension
- [ ] Basic search UI
- [ ] Settings panel

### Phase 2: Background Indexer (1 week)
- [ ] XPC service
- [ ] FSEvents monitoring
- [ ] Progress reporting
- [ ] Resource management

### Phase 3: App Intents (1 week)
- [ ] Intent definitions
- [ ] Siri integration
- [ ] Shortcuts support
- [ ] System integration

### Phase 4: Polish (1 week)
- [ ] Icon design
- [ ] Animations
- [ ] Error handling
- [ ] Help documentation

### Phase 5: Distribution (1 week)
- [ ] Code signing
- [ ] Notarization
- [ ] DMG creation
- [ ] Website/landing page

## Comparison

### Before (Science Experiment)
```bash
# Install dependencies
brew install faiss sqlite

# Build
cd osx_support && make

# Install (pollutes system)
sudo make install

# Use (command line)
sqlite3 db.db
.load /usr/local/lib/sqlite3/faiss_extension.dylib
SELECT * FROM faiss_search('query', 5);
```

### After (First-Class Mac App)
```
1. Download FileSearch.dmg
2. Drag to Applications
3. Open FileSearch
4. Click menu bar icon
5. Type search query
6. Get results
```

**That's it!**

## Benefits

✅ **Native macOS experience**
- Menu bar app
- SwiftUI interface
- System integration
- Sandboxed security

✅ **Zero installation hassle**
- Drag and drop
- No terminal required
- No system pollution
- Easy uninstall

✅ **Professional quality**
- Code signed
- Notarized
- App Store ready
- Proper architecture

✅ **User-friendly**
- GUI for everything
- Siri integration
- Shortcuts support
- Help documentation

## Next Steps

1. **Create new Xcode project** with proper structure
2. **Migrate C++ extension** to embedded resource
3. **Build SwiftUI interface** for search
4. **Implement XPC service** for indexing
5. **Add App Intents** for Siri
6. **Polish and distribute**

This is the **Apple way** - a proper macOS application that users will love!
