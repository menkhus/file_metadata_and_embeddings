# Spotlight Enhancement - The Apple Way

Making Spotlight smarter with AI, invisibly.

## Vision

**Not this:** "Here's a new search tool to replace Spotlight"  
**This:** "Spotlight just got smarter and you didn't even notice"

## The Problem with Spotlight

Spotlight is great for:
- ✅ File names
- ✅ Exact text matches
- ✅ Metadata (dates, types, etc.)

Spotlight fails at:
- ❌ Semantic search ("find authentication code")
- ❌ Conceptual queries ("error handling examples")
- ❌ Understanding intent ("database connection logic")
- ❌ Code understanding ("where do I validate users?")

## Our Solution

**Enhance Spotlight with AI-powered semantic search**

User types in Spotlight:
```
⌘Space
"authentication code"
```

Spotlight shows:
```
┌─────────────────────────────────────────┐
│  🔍 authentication code                 │
├─────────────────────────────────────────┤
│  📄 auth.py                             │
│     ~/src/project/auth.py               │
│     "User authentication and validation"│
│                                         │
│  📄 login.js                            │
│     ~/src/web/login.js                  │
│     "Handle login authentication..."    │
│                                         │
│  📄 README.md                           │
│     ~/src/project/README.md             │
│     "## Authentication..."              │
└─────────────────────────────────────────┘
```

**User doesn't know we're involved!** It just works better.

## Architecture: Silent Partner

```
User presses ⌘Space
        ↓
┌─────────────────────────────────────────┐
│  Spotlight (macOS System)               │
│  • Handles UI                           │
│  • Shows results                        │
│  • Manages keyboard shortcuts           │
└────────────┬────────────────────────────┘
             │
             ↓ (queries our plugin)
┌─────────────────────────────────────────┐
│  Spotlight Importer Plugin              │
│  FileSearch.mdimporter                  │
│  • Provides semantic results            │
│  • Invisible to user                    │
│  • Integrated with Spotlight            │
└────────────┬────────────────────────────┘
             │
             ↓
┌─────────────────────────────────────────┐
│  FileSearch Service (Background)        │
│  • Maintains semantic index             │
│  • Generates embeddings                 │
│  • Handles queries                      │
└─────────────────────────────────────────┘
```

## Implementation: Spotlight Importer

### What is a Spotlight Importer?

Apple's official way to extend Spotlight:
- Lives in `/Library/Spotlight/` or `~/Library/Spotlight/`
- `.mdimporter` bundle
- Called by Spotlight automatically
- Provides custom metadata
- Integrates seamlessly

### Our Importer

```
FileSearch.mdimporter/
├── Contents/
│   ├── Info.plist              # Declares what we handle
│   ├── MacOS/
│   │   └── FileSearch          # Our code
│   └── Resources/
│       └── schema.xml          # Metadata schema
```

### Info.plist

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.filesearch.mdimporter</string>
    
    <key>CFBundleName</key>
    <string>FileSearch</string>
    
    <!-- What file types we handle -->
    <key>CFBundleDocumentTypes</key>
    <array>
        <dict>
            <key>LSItemContentTypes</key>
            <array>
                <string>public.source-code</string>
                <string>public.text</string>
                <string>public.plain-text</string>
            </array>
        </dict>
    </array>
    
    <!-- Custom metadata attributes -->
    <key>MDImporterAttributes</key>
    <array>
        <string>com_filesearch_semantic_content</string>
        <string>com_filesearch_embedding</string>
        <string>com_filesearch_similarity_score</string>
    </array>
</dict>
</plist>
```

### Importer Code

```objc
// GetMetadataForFile.m
#import <CoreFoundation/CoreFoundation.h>

Boolean GetMetadataForFile(
    void *thisInterface,
    CFMutableDictionaryRef attributes,
    CFStringRef contentTypeUTI,
    CFStringRef pathToFile
) {
    @autoreleasepool {
        // Get file path
        NSString *path = (__bridge NSString *)pathToFile;
        
        // Query our semantic index
        NSDictionary *semanticData = [FileSearchService querySemanticData:path];
        
        if (semanticData) {
            // Add custom metadata to Spotlight
            CFDictionarySetValue(
                attributes,
                CFSTR("com_filesearch_semantic_content"),
                (__bridge CFStringRef)semanticData[@"content"]
            );
            
            CFDictionarySetValue(
                attributes,
                CFSTR("com_filesearch_similarity_score"),
                (__bridge CFNumberRef)semanticData[@"score"]
            );
        }
        
        return TRUE;
    }
}
```

### Schema.xml

```xml
<?xml version="1.0" encoding="UTF-8"?>
<schema version="1.0" xmlns="http://www.apple.com/metadata">
    <!-- Semantic content attribute -->
    <attribute name="com_filesearch_semantic_content" 
               multivalued="false" 
               type="CFString">
        <displayname>
            <name>Semantic Content</name>
        </displayname>
    </attribute>
    
    <!-- Make it searchable in Spotlight -->
    <attribute name="com_filesearch_semantic_content">
        <allattrs>true</allattrs>
    </attribute>
</schema>
```

## User Experience

### Scenario 1: Semantic Search

**User types:**
```
⌘Space
"error handling"
```

**What happens (invisible to user):**
1. Spotlight calls our importer
2. We generate embedding for "error handling"
3. We search our FAISS index
4. We return semantic matches
5. Spotlight shows results

**User sees:**
```
Results for "error handling"
📄 auth.py - "Handle authentication errors..."
📄 utils.js - "Error handling middleware..."
📄 README.md - "## Error Handling..."
```

**User thinks:** "Wow, Spotlight is really good now!"

### Scenario 2: Siri Integration

**User says:**
```
"Hey Siri, find my authentication code"
```

**What happens:**
1. Siri uses Spotlight search
2. Spotlight calls our importer
3. We return semantic results
4. Siri shows/speaks results

**User sees:**
```
Siri: "I found 3 files about authentication"
[Shows results]
```

### Scenario 3: Quick Look

**User presses Space on result:**
```
Quick Look shows file preview
With semantic highlights
```

## Installation (Invisible)

### App Installation

```
1. User downloads FileSearch.app
2. Drags to Applications
3. Opens app
4. App installs importer automatically
5. Restarts Spotlight (mdimport -r)
6. Done - Spotlight is now smarter
```

**User never knows about the importer!**

### Automatic Updates

```swift
class ImporterManager {
    func ensureImporterInstalled() {
        let importerPath = "/Library/Spotlight/FileSearch.mdimporter"
        
        if !FileManager.default.fileExists(atPath: importerPath) {
            // Install importer
            installImporter()
            
            // Restart Spotlight
            restartSpotlight()
        }
    }
    
    private func installImporter() {
        // Copy from app bundle
        let bundledImporter = Bundle.main.url(
            forResource: "FileSearch",
            withExtension: "mdimporter"
        )!
        
        // Install to system
        try? FileManager.default.copyItem(
            at: bundledImporter,
            to: URL(fileURLWithPath: "/Library/Spotlight/FileSearch.mdimporter")
        )
    }
    
    private func restartSpotlight() {
        // Tell Spotlight to reload importers
        Process.launchedProcess(
            launchPath: "/usr/bin/mdimport",
            arguments: ["-r", "/Library/Spotlight/FileSearch.mdimporter"]
        )
    }
}
```

## Background Service

### Invisible Indexing

```swift
// Runs as XPC service, completely invisible
class SemanticIndexService {
    func start() {
        // Monitor file changes
        startFSEventsMonitoring()
        
        // Index new/changed files
        startIncrementalIndexing()
        
        // Respond to Spotlight queries
        startQueryService()
    }
    
    private func startFSEventsMonitoring() {
        // Watch for file changes
        FSEventStreamCreate(
            callback: { [weak self] paths in
                self?.handleFileChanges(paths)
            },
            paths: smartDiscoveredPaths()
        )
    }
    
    private func handleFileChanges(_ paths: [String]) {
        // File changed - update index
        for path in paths {
            Task {
                await updateSemanticIndex(path)
            }
        }
    }
}
```

## Integration Points

### 1. Spotlight Search

```
User: ⌘Space "authentication"
  ↓
Spotlight → Our Importer → Semantic Results
  ↓
User sees enhanced results
```

### 2. Siri

```
User: "Hey Siri, find error handling code"
  ↓
Siri → Spotlight → Our Importer → Results
  ↓
Siri speaks results
```

### 3. Shortcuts

```
Shortcut: "Search my code"
  ↓
Spotlight API → Our Importer → Results
  ↓
Shortcut processes results
```

### 4. Quick Look

```
User: Space bar on file
  ↓
Quick Look → Our metadata → Enhanced preview
  ↓
Shows semantic highlights
```

## Menu Bar App (Optional)

**Minimal interface for power users:**

```
🔍 FileSearch
   ──────────
   ✓ Spotlight enhancement active
   12,453 files indexed
   Last updated: 2 min ago
   ──────────
   Preferences...
   About...
```

**Most users never open it!** It just works through Spotlight.

## Preferences (Minimal)

```
┌─────────────────────────────────────────┐
│  FileSearch Preferences                 │
├─────────────────────────────────────────┤
│  ☑ Enhance Spotlight with AI            │
│  ☑ Index code files                     │
│  ☑ Index documentation                  │
│                                         │
│  Status:                                │
│  • 12,453 files indexed                 │
│  • Spotlight integration: Active        │
│                                         │
│  [Advanced...]                          │
└─────────────────────────────────────────┘
```

## Technical Implementation

### Spotlight Importer (C/Objective-C)

```objc
// Fast, efficient, called by Spotlight
Boolean GetMetadataForFile(
    void *thisInterface,
    CFMutableDictionaryRef attributes,
    CFStringRef contentTypeUTI,
    CFStringRef pathToFile
) {
    // Query our index (fast!)
    SemanticData *data = queryIndex(pathToFile);
    
    // Add to Spotlight metadata
    addSemanticMetadata(attributes, data);
    
    return TRUE;
}
```

### Background Service (Swift)

```swift
// Maintains index, invisible to user
@main
class FileSearchService: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Start indexing service
        indexer.start()
        
        // Install Spotlight importer
        importerManager.ensureInstalled()
        
        // Hide from Dock
        NSApp.setActivationPolicy(.accessory)
    }
}
```

### Query Service (Swift)

```swift
// Responds to Spotlight queries
class QueryService {
    func handleQuery(_ query: String) -> [SearchResult] {
        // Generate embedding
        let embedding = await embedder.encode(query)
        
        // Search FAISS index
        let results = faissIndex.search(embedding, topK: 10)
        
        // Return to Spotlight
        return results
    }
}
```

## Performance

**Spotlight query:**
- User types: 0ms (instant)
- Our importer called: 1ms
- Semantic search: 2ms
- Results returned: 3ms total

**User perception:** Instant!

## Privacy

**All local:**
- ✅ No cloud services
- ✅ No data sent anywhere
- ✅ All processing on-device
- ✅ User's data stays on their Mac

**Apple's way!**

## Distribution

### App Store

```
FileSearch - Semantic Search for Spotlight
Free

"Makes Spotlight smarter with AI-powered semantic search.
 Find files by meaning, not just keywords."

• Enhances Spotlight automatically
• Works with Siri
• All processing on-device
• No configuration needed
```

### Direct Download

```
FileSearch.dmg
  ↓
Drag to Applications
  ↓
Open once
  ↓
Done - Spotlight is enhanced
```

## Summary

**The Apple Way:**
- ✅ Enhances existing system (Spotlight)
- ✅ Invisible integration
- ✅ Zero configuration
- ✅ Works with Siri
- ✅ Works with Shortcuts
- ✅ All on-device
- ✅ Respects privacy
- ✅ "It just works"

**Not:**
- ❌ Separate search tool
- ❌ Command-line interface
- ❌ Configuration files
- ❌ Cloud services
- ❌ Replacement for Spotlight

**Result:**
User presses ⌘Space, types "authentication code", gets semantic results.
**They don't even know we exist.** That's perfect.

## Next Steps

1. Build Spotlight importer (.mdimporter)
2. Build background indexing service
3. Integrate with Spotlight
4. Test with Siri
5. Test with Shortcuts
6. Polish and ship

**This is the right way to do it!**
