# Agentic Intents - AI-Powered Tools

App Intents as composable tools for Apple Intelligence.

## The Vision

**Not this:** "Search files" button in Shortcuts

**This:** Apple Intelligence uses your intents as **tools** to answer complex questions

```
User: "Explain how authentication works in my codebase"

Apple Intelligence thinks:
1. Use SearchFilesIntent("authentication") → Get relevant files
2. Use GetFileContextIntent(file, chunk) → Get surrounding code
3. Use SummarizeCodeIntent(context) → Understand the code
4. Synthesize answer using local LLM

User sees: Natural language explanation with code references
```

**Your intents = Tools for AI agents!**

## App Intents as Tools

### Tool 1: Semantic Search

```swift
import AppIntents

struct SearchFilesIntent: AppIntent {
    static var title: LocalizedStringResource = "Search Files"
    
    static var description = IntentDescription(
        """
        Search files by meaning, not just keywords. 
        Understands concepts like 'authentication', 'error handling', 
        'database connections' and finds relevant code even if exact 
        words don't match. Returns ranked results with context.
        """,
        categoryName: "Search",
        searchKeywords: ["find", "search", "semantic", "code", "files"]
    )
    
    @Parameter(
        title: "Query",
        description: "Natural language description of what you're looking for",
        requestValueDialog: "What would you like to search for?"
    )
    var query: String
    
    @Parameter(
        title: "Number of Results",
        description: "How many results to return",
        default: 5
    )
    var topK: Int
    
    @Parameter(
        title: "Include Context",
        description: "Include surrounding code chunks for better understanding",
        default: true
    )
    var includeContext: Bool
    
    static var parameterSummary: some ParameterSummary {
        Summary("Search for \(\.$query)") {
            \.$topK
            \.$includeContext
        }
    }
    
    func perform() async throws -> some IntentResult & ReturnsValue<[FileSearchResult]> {
        // 1. Generate embedding for query
        let embedding = try await EmbeddingService.shared.encode(query)
        
        // 2. Search FAISS index
        let results = try await SearchManager.shared.search(
            embedding: embedding,
            topK: topK,
            includeContext: includeContext
        )
        
        // 3. Return structured results
        return .result(value: results)
    }
}

struct FileSearchResult: AppEntity {
    var id: String
    var filePath: String
    var fileName: String
    var chunkIndex: Int
    var content: String
    var similarityScore: Double
    var context: [String]?  // Adjacent chunks
    
    static var typeDisplayRepresentation = TypeDisplayRepresentation(
        name: "Search Result"
    )
    
    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(
            title: "\(fileName)",
            subtitle: "Score: \(String(format: "%.2f", similarityScore))",
            image: .init(systemName: "doc.text")
        )
    }
}
```

### Tool 2: Get File Context

```swift
struct GetFileContextIntent: AppIntent {
    static var title: LocalizedStringResource = "Get File Context"
    
    static var description = IntentDescription(
        """
        Get surrounding context for a specific code chunk. 
        Returns the chunk plus adjacent chunks before and after 
        for better understanding of the code flow.
        """,
        categoryName: "Analysis"
    )
    
    @Parameter(title: "File Path")
    var filePath: String
    
    @Parameter(title: "Chunk Index")
    var chunkIndex: Int
    
    @Parameter(
        title: "Context Size",
        description: "Number of chunks before and after to include",
        default: 2
    )
    var contextSize: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<CodeContext> {
        let context = try await DatabaseManager.shared.getContext(
            filePath: filePath,
            chunkIndex: chunkIndex,
            contextSize: contextSize
        )
        
        return .result(value: context)
    }
}

struct CodeContext: AppEntity {
    var id: String
    var filePath: String
    var targetChunk: String
    var beforeChunks: [String]
    var afterChunks: [String]
    var fullContext: String  // Combined text
    
    static var typeDisplayRepresentation = TypeDisplayRepresentation(
        name: "Code Context"
    )
    
    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(
            title: "Context for \(filePath)",
            subtitle: "\(beforeChunks.count + afterChunks.count + 1) chunks"
        )
    }
}
```

### Tool 3: Find Similar Code

```swift
struct FindSimilarCodeIntent: AppIntent {
    static var title: LocalizedStringResource = "Find Similar Code"
    
    static var description = IntentDescription(
        """
        Find code similar to a given example. 
        Useful for finding patterns, duplicates, or related implementations.
        """,
        categoryName: "Analysis"
    )
    
    @Parameter(title: "Example Code")
    var exampleCode: String
    
    @Parameter(title: "Number of Results", default: 5)
    var topK: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<[FileSearchResult]> {
        // Encode the example code
        let embedding = try await EmbeddingService.shared.encode(exampleCode)
        
        // Find similar
        let results = try await SearchManager.shared.search(
            embedding: embedding,
            topK: topK
        )
        
        return .result(value: results)
    }
}
```

### Tool 4: List Recent Files

```swift
struct ListRecentFilesIntent: AppIntent {
    static var title: LocalizedStringResource = "List Recent Files"
    
    static var description = IntentDescription(
        """
        List recently modified or indexed files. 
        Useful for finding what you were just working on.
        """,
        categoryName: "Browse"
    )
    
    @Parameter(
        title: "Time Period",
        description: "How far back to look",
        default: .lastDay
    )
    var timePeriod: TimePeriod
    
    @Parameter(title: "File Type", default: nil)
    var fileType: String?
    
    func perform() async throws -> some IntentResult & ReturnsValue<[FileInfo]> {
        let files = try await DatabaseManager.shared.getRecentFiles(
            since: timePeriod.date,
            fileType: fileType
        )
        
        return .result(value: files)
    }
}

enum TimePeriod: String, AppEnum {
    case lastHour = "Last Hour"
    case lastDay = "Last Day"
    case lastWeek = "Last Week"
    case lastMonth = "Last Month"
    
    static var typeDisplayRepresentation = TypeDisplayRepresentation(
        name: "Time Period"
    )
    
    static var caseDisplayRepresentations: [TimePeriod: DisplayRepresentation] = [
        .lastHour: "Last Hour",
        .lastDay: "Last Day",
        .lastWeek: "Last Week",
        .lastMonth: "Last Month"
    ]
    
    var date: Date {
        switch self {
        case .lastHour: return Date().addingTimeInterval(-3600)
        case .lastDay: return Date().addingTimeInterval(-86400)
        case .lastWeek: return Date().addingTimeInterval(-604800)
        case .lastMonth: return Date().addingTimeInterval(-2592000)
        }
    }
}
```

### Tool 5: Get Index Stats

```swift
struct GetIndexStatsIntent: AppIntent {
    static var title: LocalizedStringResource = "Get Index Stats"
    
    static var description = IntentDescription(
        """
        Get statistics about the indexed files. 
        Shows how many files are indexed, index size, and recent activity.
        """,
        categoryName: "Info"
    )
    
    func perform() async throws -> some IntentResult & ReturnsValue<IndexStats> {
        let stats = try await DatabaseManager.shared.getStats()
        return .result(value: stats)
    }
}

struct IndexStats: AppEntity {
    var id: String = UUID().uuidString
    var totalFiles: Int
    var totalChunks: Int
    var indexSizeMB: Double
    var lastUpdated: Date
    var filesIndexedToday: Int
    
    static var typeDisplayRepresentation = TypeDisplayRepresentation(
        name: "Index Statistics"
    )
    
    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(
            title: "\(totalFiles) files indexed",
            subtitle: "\(String(format: "%.1f", indexSizeMB)) MB"
        )
    }
}
```

## Apple Intelligence Integration

### How AI Uses Your Intents

```
User: "Show me all the error handling code in my project"

Apple Intelligence:
1. Calls SearchFilesIntent(query: "error handling", topK: 10)
2. Gets results with file paths and chunks
3. For each result, calls GetFileContextIntent(filePath, chunkIndex, contextSize: 1)
4. Synthesizes answer with code snippets
5. Presents to user with "Open in Editor" buttons

User sees:
"I found 10 examples of error handling:

1. auth.py (line 42)
   try:
       authenticate_user(credentials)
   except AuthError as e:
       log_error(e)
       return error_response(401)

2. database.py (line 156)
   ...

[Open in Editor] [Show More]"
```

### Complex Queries

```
User: "Find files similar to my authentication code and explain the differences"

Apple Intelligence:
1. Calls ListRecentFilesIntent(timePeriod: .lastDay, fileType: "py")
2. Finds auth.py (user's recent work)
3. Calls GetFileContextIntent(auth.py, chunk: 0, contextSize: 5)
4. Calls FindSimilarCodeIntent(exampleCode: <auth code>, topK: 5)
5. For each similar file, calls GetFileContextIntent()
6. Compares implementations using local LLM
7. Explains differences

User sees:
"I found 5 similar authentication implementations:

Your code (auth.py):
- Uses JWT tokens
- Validates with database
- Includes rate limiting

Similar code in login.js:
- Uses session cookies instead of JWT
- Validates with Redis cache
- No rate limiting

Would you like me to add rate limiting to login.js?"
```

## Intent Composition

### Shortcuts Can Chain Intents

```
Shortcut: "Code Review Assistant"

1. SearchFilesIntent("TODO comments")
   → Get all TODOs

2. For each result:
   GetFileContextIntent(file, chunk, context: 2)
   → Get surrounding code

3. Summarize with Apple Intelligence
   → "You have 23 TODOs. 5 are critical..."

4. Create reminder
   → "Review critical TODOs"
```

### Siri Can Compose

```
User: "Hey Siri, what did I work on yesterday?"

Siri:
1. ListRecentFilesIntent(timePeriod: .lastDay)
2. For top 5 files:
   GetFileContextIntent(file, chunk: 0, context: 0)
3. Summarize

Siri speaks:
"Yesterday you worked on 12 files, mostly in the authentication module. 
You added error handling to auth.py and updated the login flow in login.js."
```

## Debugging Intents

### Intent Testing

```swift
// In Xcode: Product → Perform Action → <Your Intent>

// Or programmatically:
func testSearchIntent() async throws {
    let intent = SearchFilesIntent()
    intent.query = "authentication"
    intent.topK = 5
    
    let result = try await intent.perform()
    print("Found \(result.value.count) results")
    
    for item in result.value {
        print("- \(item.fileName): \(item.similarityScore)")
    }
}
```

### Intent Logging

```swift
struct SearchFilesIntent: AppIntent {
    func perform() async throws -> some IntentResult & ReturnsValue<[FileSearchResult]> {
        logger.info("SearchFilesIntent called: query=\(query), topK=\(topK)")
        
        let start = Date()
        let results = try await performSearch()
        let elapsed = Date().timeIntervalSince(start)
        
        logger.info("SearchFilesIntent completed: \(results.count) results in \(elapsed)s")
        
        return .result(value: results)
    }
}

// View logs:
// log show --predicate 'subsystem == "com.filesearch.app" AND category == "intents"'
```

### Intent Debugging in Shortcuts

```
1. Open Shortcuts app
2. Create test shortcut
3. Add your intent
4. Run with debugger attached
5. Set breakpoints in intent code
6. Inspect parameters and results
```

## Intent Discovery

### Make Intents Discoverable

```swift
struct FileSearchAppShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: SearchFilesIntent(),
            phrases: [
                "Search my files for \(\.$query)",
                "Find \(\.$query) in my code",
                "Look for \(\.$query)"
            ],
            shortTitle: "Search Files",
            systemImageName: "magnifyingglass"
        )
        
        AppShortcut(
            intent: ListRecentFilesIntent(),
            phrases: [
                "Show recent files",
                "What did I work on recently",
                "List my recent code"
            ],
            shortTitle: "Recent Files",
            systemImageName: "clock"
        )
    }
}
```

### Spotlight Integration

```swift
// Intents automatically appear in Spotlight!
// User types: "search files for authentication"
// Spotlight suggests: SearchFilesIntent with pre-filled query
```

## Advanced: Intent Parameters from Context

```swift
struct SmartSearchIntent: AppIntent {
    static var title: LocalizedStringResource = "Smart Search"
    
    // Parameter can be provided by Apple Intelligence
    @Parameter(title: "Query")
    var query: String
    
    // Optional: AI can infer from context
    @Parameter(title: "File Type", default: nil)
    var fileType: String?
    
    // Optional: AI can infer from recent activity
    @Parameter(title: "Related to Recent Work", default: false)
    var relatedToRecentWork: Bool
    
    func perform() async throws -> some IntentResult & ReturnsValue<[FileSearchResult]> {
        var results = try await basicSearch(query)
        
        // Filter by file type if specified
        if let fileType = fileType {
            results = results.filter { $0.filePath.hasSuffix(fileType) }
        }
        
        // Boost results related to recent work
        if relatedToRecentWork {
            let recentFiles = try await getRecentFiles()
            results = boostRecentFiles(results, recentFiles: recentFiles)
        }
        
        return .result(value: results)
    }
}
```

## Intent Analytics

### Track Usage

```swift
struct IntentAnalytics {
    static func logIntentUsage(_ intentName: String, parameters: [String: Any]) {
        // Log to database
        try? DatabaseManager.shared.logIntent(
            name: intentName,
            parameters: parameters,
            timestamp: Date()
        )
    }
    
    static func getPopularIntents() async -> [(String, Int)] {
        // Query most-used intents
        return try! await DatabaseManager.shared.execute("""
            SELECT intent_name, COUNT(*) as usage_count
            FROM intent_logs
            WHERE timestamp > datetime('now', '-30 days')
            GROUP BY intent_name
            ORDER BY usage_count DESC
        """)
    }
}
```

## Summary

**App Intents = Tools for AI Agents**

Your intents are:
- ✅ **Composable** - AI can chain them
- ✅ **Discoverable** - Appear in Spotlight, Siri, Shortcuts
- ✅ **Semantic** - Rich descriptions help AI understand
- ✅ **Debuggable** - Test in Xcode, log everything
- ✅ **Powerful** - Enable complex agentic workflows

**Example Flow:**
```
User: "Explain authentication in my code"
  ↓
Apple Intelligence:
  1. SearchFilesIntent("authentication")
  2. GetFileContextIntent(results)
  3. Synthesize explanation
  ↓
User: Natural language answer with code references
```

**This is the future of software interaction!**

Your app provides the tools, Apple Intelligence orchestrates them, users get magic. 🪄
