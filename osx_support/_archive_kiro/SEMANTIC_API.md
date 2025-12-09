# Semantic API - Complete Intent Layer

Every semantic primitive exposed as an App Intent.

## Philosophy

**Intents = Semantic API for AI Agents**

- Every query capability → Intent
- Every metadata accessor → Intent
- Every semantic operation → Intent
- Rich descriptions → AI understands what each does
- Composable → AI chains them together

**This is the last mile for semantic features!**

## Complete Intent Catalog

### Category 1: Semantic Search

#### SearchByMeaningIntent
```swift
struct SearchByMeaningIntent: AppIntent {
    static var title: LocalizedStringResource = "Search by Meaning"
    
    static var description = IntentDescription(
        """
        Search files by semantic meaning, not keywords.
        Understands concepts: 'authentication logic', 'error handling patterns',
        'database connections', 'API endpoints', etc.
        Returns ranked results with similarity scores.
        """,
        categoryName: "Semantic Search",
        searchKeywords: ["search", "find", "semantic", "meaning", "similar"]
    )
    
    @Parameter(title: "What to search for", description: "Natural language query")
    var query: String
    
    @Parameter(title: "Number of results", default: 10)
    var limit: Int
    
    @Parameter(title: "Minimum similarity", default: 0.7)
    var minSimilarity: Double
    
    func perform() async throws -> some IntentResult & ReturnsValue<[SemanticMatch]> {
        // Implementation
    }
}
```

#### FindSimilarToTextIntent
```swift
struct FindSimilarToTextIntent: AppIntent {
    static var title: LocalizedStringResource = "Find Similar to Text"
    
    static var description = IntentDescription(
        """
        Find code/text similar to a given example.
        Useful for: finding duplicates, related implementations, 
        similar patterns, or code that does something similar.
        """,
        categoryName: "Semantic Search"
    )
    
    @Parameter(title: "Example text or code")
    var exampleText: String
    
    @Parameter(title: "Number of results", default: 5)
    var limit: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<[SemanticMatch]> {
        // Implementation
    }
}
```

#### FindSimilarToFileIntent
```swift
struct FindSimilarToFileIntent: AppIntent {
    static var title: LocalizedStringResource = "Find Similar to File"
    
    static var description = IntentDescription(
        """
        Find files semantically similar to a given file.
        Compares overall content and purpose, not just keywords.
        """,
        categoryName: "Semantic Search"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    @Parameter(title: "Number of results", default: 5)
    var limit: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<[FileMatch]> {
        // Implementation
    }
}
```

### Category 2: Context & Navigation

#### GetChunkContextIntent
```swift
struct GetChunkContextIntent: AppIntent {
    static var title: LocalizedStringResource = "Get Chunk Context"
    
    static var description = IntentDescription(
        """
        Get surrounding context for a specific code chunk.
        Returns adjacent chunks before and after for understanding code flow.
        Essential for understanding code in context.
        """,
        categoryName: "Context"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    @Parameter(title: "Chunk index")
    var chunkIndex: Int
    
    @Parameter(title: "Context size (chunks before/after)", default: 2)
    var contextSize: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<ChunkContext> {
        // Implementation
    }
}
```

#### GetAdjacentChunksIntent
```swift
struct GetAdjacentChunksIntent: AppIntent {
    static var title: LocalizedStringResource = "Get Adjacent Chunks"
    
    static var description = IntentDescription(
        """
        Get chunks immediately before and after a given chunk.
        Useful for understanding code flow and dependencies.
        """,
        categoryName: "Context"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    @Parameter(title: "Chunk index")
    var chunkIndex: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<AdjacentChunks> {
        // Implementation
    }
}
```

#### GetFullFileIntent
```swift
struct GetFullFileIntent: AppIntent {
    static var title: LocalizedStringResource = "Get Full File"
    
    static var description = IntentDescription(
        """
        Get all chunks for a file in order.
        Reconstructs the complete file content with metadata.
        """,
        categoryName: "Context"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    func perform() async throws -> some IntentResult & ReturnsValue<FileContent> {
        // Implementation
    }
}
```

### Category 3: Metadata Queries

#### GetFileMetadataIntent
```swift
struct GetFileMetadataIntent: AppIntent {
    static var title: LocalizedStringResource = "Get File Metadata"
    
    static var description = IntentDescription(
        """
        Get complete metadata for a file: size, type, chunks, 
        when indexed, hash, chunking strategy, etc.
        """,
        categoryName: "Metadata"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    func perform() async throws -> some IntentResult & ReturnsValue<FileMetadata> {
        // Implementation
    }
}
```

#### ListFilesByTypeIntent
```swift
struct ListFilesByTypeIntent: AppIntent {
    static var title: LocalizedStringResource = "List Files by Type"
    
    static var description = IntentDescription(
        """
        List all indexed files of a specific type.
        Supports: code files (.py, .js, .swift), docs (.md, .txt), 
        config (.json, .yaml), etc.
        """,
        categoryName: "Metadata"
    )
    
    @Parameter(title: "File type (e.g., 'py', 'js', 'md')")
    var fileType: String
    
    @Parameter(title: "Limit", default: 100)
    var limit: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<[FileInfo]> {
        // Implementation
    }
}
```

#### ListFilesByDateIntent
```swift
struct ListFilesByDateIntent: AppIntent {
    static var title: LocalizedStringResource = "List Files by Date"
    
    static var description = IntentDescription(
        """
        List files modified or indexed within a date range.
        Useful for finding recent work or changes.
        """,
        categoryName: "Metadata"
    )
    
    @Parameter(title: "Start date")
    var startDate: Date
    
    @Parameter(title: "End date", default: Date())
    var endDate: Date
    
    @Parameter(title: "Limit", default: 100)
    var limit: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<[FileInfo]> {
        // Implementation
    }
}
```

#### GetChunkMetadataIntent
```swift
struct GetChunkMetadataIntent: AppIntent {
    static var title: LocalizedStringResource = "Get Chunk Metadata"
    
    static var description = IntentDescription(
        """
        Get metadata for a specific chunk: size, strategy, position,
        line count, word count, adjacent chunk hints, etc.
        """,
        categoryName: "Metadata"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    @Parameter(title: "Chunk index")
    var chunkIndex: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<ChunkMetadata> {
        // Implementation
    }
}
```

### Category 4: Statistics & Analytics

#### GetIndexStatsIntent
```swift
struct GetIndexStatsIntent: AppIntent {
    static var title: LocalizedStringResource = "Get Index Statistics"
    
    static var description = IntentDescription(
        """
        Get comprehensive statistics about the index:
        total files, chunks, size, last update, file types, etc.
        """,
        categoryName: "Statistics"
    )
    
    func perform() async throws -> some IntentResult & ReturnsValue<IndexStats> {
        // Implementation
    }
}
```

#### GetFileTypeStatsIntent
```swift
struct GetFileTypeStatsIntent: AppIntent {
    static var title: LocalizedStringResource = "Get File Type Statistics"
    
    static var description = IntentDescription(
        """
        Get statistics broken down by file type:
        how many Python files, JavaScript files, etc.
        Includes chunk counts and sizes per type.
        """,
        categoryName: "Statistics"
    )
    
    func perform() async throws -> some IntentResult & ReturnsValue<[FileTypeStats]> {
        // Implementation
    }
}
```

#### GetDirectoryStatsIntent
```swift
struct GetDirectoryStatsIntent: AppIntent {
    static var title: LocalizedStringResource = "Get Directory Statistics"
    
    static var description = IntentDescription(
        """
        Get statistics for a specific directory:
        file count, total size, file types, last updated, etc.
        """,
        categoryName: "Statistics"
    )
    
    @Parameter(title: "Directory path")
    var directoryPath: String
    
    func perform() async throws -> some IntentResult & ReturnsValue<DirectoryStats> {
        // Implementation
    }
}
```

### Category 5: Semantic Relationships

#### FindRelatedFilesIntent
```swift
struct FindRelatedFilesIntent: AppIntent {
    static var title: LocalizedStringResource = "Find Related Files"
    
    static var description = IntentDescription(
        """
        Find files semantically related to a given file.
        Uses embeddings to find files that work together,
        import each other, or serve similar purposes.
        """,
        categoryName: "Relationships"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    @Parameter(title: "Number of results", default: 10)
    var limit: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<[RelatedFile]> {
        // Implementation
    }
}
```

#### FindCodePatternsIntent
```swift
struct FindCodePatternsIntent: AppIntent {
    static var title: LocalizedStringResource = "Find Code Patterns"
    
    static var description = IntentDescription(
        """
        Find recurring patterns in code.
        Identifies similar implementations, common idioms,
        or repeated structures across the codebase.
        """,
        categoryName: "Relationships"
    )
    
    @Parameter(title: "Pattern description")
    var patternDescription: String
    
    @Parameter(title: "Minimum occurrences", default: 3)
    var minOccurrences: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<[CodePattern]> {
        // Implementation
    }
}
```

#### ClusterSimilarFilesIntent
```swift
struct ClusterSimilarFilesIntent: AppIntent {
    static var title: LocalizedStringResource = "Cluster Similar Files"
    
    static var description = IntentDescription(
        """
        Group files into semantic clusters.
        Identifies modules, related functionality, or logical groupings
        based on content similarity.
        """,
        categoryName: "Relationships"
    )
    
    @Parameter(title: "Number of clusters", default: 5)
    var numClusters: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<[FileCluster]> {
        // Implementation
    }
}
```

### Category 6: Temporal Queries

#### GetRecentActivityIntent
```swift
struct GetRecentActivityIntent: AppIntent {
    static var title: LocalizedStringResource = "Get Recent Activity"
    
    static var description = IntentDescription(
        """
        Get recent indexing activity: files added, updated, or removed.
        Shows what's been happening in the index.
        """,
        categoryName: "Temporal"
    )
    
    @Parameter(title: "Time period", default: .lastDay)
    var timePeriod: TimePeriod
    
    func perform() async throws -> some IntentResult & ReturnsValue<[ActivityEvent]> {
        // Implementation
    }
}
```

#### GetFileHistoryIntent
```swift
struct GetFileHistoryIntent: AppIntent {
    static var title: LocalizedStringResource = "Get File History"
    
    static var description = IntentDescription(
        """
        Get indexing history for a specific file:
        when it was first indexed, updates, changes over time.
        """,
        categoryName: "Temporal"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    func perform() async throws -> some IntentResult & ReturnsValue<FileHistory> {
        // Implementation
    }
}
```

#### CompareFileVersionsIntent
```swift
struct CompareFileVersionsIntent: AppIntent {
    static var title: LocalizedStringResource = "Compare File Versions"
    
    static var description = IntentDescription(
        """
        Compare semantic similarity between different versions of a file.
        Shows how much the meaning/purpose has changed over time.
        """,
        categoryName: "Temporal"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    @Parameter(title: "Compare with date")
    var compareDate: Date
    
    func perform() async throws -> some IntentResult & ReturnsValue<VersionComparison> {
        // Implementation
    }
}
```

### Category 7: Advanced Semantic Operations

#### GetSemanticSummaryIntent
```swift
struct GetSemanticSummaryIntent: AppIntent {
    static var title: LocalizedStringResource = "Get Semantic Summary"
    
    static var description = IntentDescription(
        """
        Get a semantic summary of a file or chunk.
        Describes what the code does, its purpose, and key concepts.
        Uses embeddings to understand meaning.
        """,
        categoryName: "Advanced"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    @Parameter(title: "Chunk index (optional)")
    var chunkIndex: Int?
    
    func perform() async throws -> some IntentResult & ReturnsValue<SemanticSummary> {
        // Implementation
    }
}
```

#### ExtractKeyConceptsIntent
```swift
struct ExtractKeyConceptsIntent: AppIntent {
    static var title: LocalizedStringResource = "Extract Key Concepts"
    
    static var description = IntentDescription(
        """
        Extract key concepts from a file or chunk.
        Identifies main ideas, important functions, patterns, etc.
        """,
        categoryName: "Advanced"
    )
    
    @Parameter(title: "File path")
    var filePath: String
    
    @Parameter(title: "Number of concepts", default: 5)
    var limit: Int
    
    func perform() async throws -> some IntentResult & ReturnsValue<[Concept]> {
        // Implementation
    }
}
```

#### MeasureSemanticDistanceIntent
```swift
struct MeasureSemanticDistanceIntent: AppIntent {
    static var title: LocalizedStringResource = "Measure Semantic Distance"
    
    static var description = IntentDescription(
        """
        Measure semantic distance between two files or chunks.
        Returns similarity score (0-1) and explanation.
        """,
        categoryName: "Advanced"
    )
    
    @Parameter(title: "First file path")
    var filePath1: String
    
    @Parameter(title: "Second file path")
    var filePath2: String
    
    func perform() async throws -> some IntentResult & ReturnsValue<SemanticDistance> {
        // Implementation
    }
}
```

## Entity Definitions

### Core Entities

```swift
struct SemanticMatch: AppEntity {
    var id: String
    var filePath: String
    var fileName: String
    var chunkIndex: Int
    var content: String
    var similarityScore: Double
    var metadata: ChunkMetadata
    var context: [String]?
    
    static var typeDisplayRepresentation = TypeDisplayRepresentation(
        name: "Semantic Match"
    )
    
    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(
            title: "\(fileName)",
            subtitle: "Similarity: \(String(format: "%.0f%%", similarityScore * 100))",
            image: .init(systemName: "doc.text.magnifyingglass")
        )
    }
}

struct FileMetadata: AppEntity {
    var id: String
    var filePath: String
    var fileName: String
    var fileType: String
    var fileSize: Int
    var totalChunks: Int
    var chunkStrategy: String
    var fileHash: String
    var createdAt: Date
    var modifiedAt: Date
    var indexedAt: Date
    
    static var typeDisplayRepresentation = TypeDisplayRepresentation(
        name: "File Metadata"
    )
}

struct ChunkMetadata: AppEntity {
    var id: String
    var chunkIndex: Int
    var totalChunks: Int
    var chunkSize: Int
    var chunkStrategy: String
    var lineCount: Int
    var wordCount: Int
    var position: String  // "start", "middle", "end"
    var hasPrevious: Bool
    var hasNext: Bool
    var adjacentIndexes: [Int]
    
    static var typeDisplayRepresentation = TypeDisplayRepresentation(
        name: "Chunk Metadata"
    )
}

struct IndexStats: AppEntity {
    var id: String = UUID().uuidString
    var totalFiles: Int
    var totalChunks: Int
    var totalSize: Int64
    var indexSizeMB: Double
    var lastUpdated: Date
    var fileTypes: [String: Int]
    var averageChunksPerFile: Double
    
    static var typeDisplayRepresentation = TypeDisplayRepresentation(
        name: "Index Statistics"
    )
}
```

## Intent Discovery & Registration

```swift
struct FileSearchAppShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        // Semantic Search
        AppShortcut(
            intent: SearchByMeaningIntent(),
            phrases: [
                "Search for \(\.$query)",
                "Find \(\.$query) in my code",
                "Look for \(\.$query) semantically"
            ],
            shortTitle: "Semantic Search",
            systemImageName: "magnifyingglass.circle"
        )
        
        // Context
        AppShortcut(
            intent: GetChunkContextIntent(),
            phrases: [
                "Get context for \(\.$filePath)",
                "Show surrounding code"
            ],
            shortTitle: "Get Context",
            systemImageName: "doc.text"
        )
        
        // Metadata
        AppShortcut(
            intent: GetFileMetadataIntent(),
            phrases: [
                "Get info about \(\.$filePath)",
                "Show file metadata"
            ],
            shortTitle: "File Info",
            systemImageName: "info.circle"
        )
        
        // Statistics
        AppShortcut(
            intent: GetIndexStatsIntent(),
            phrases: [
                "Show index stats",
                "How many files are indexed"
            ],
            shortTitle: "Index Stats",
            systemImageName: "chart.bar"
        )
        
        // ... all other intents
    }
}
```

## Example: AI Agent Composition

```
User: "Explain how authentication works in my codebase and find similar implementations"

Apple Intelligence composes:
1. SearchByMeaningIntent("authentication")
   → Get relevant auth files

2. GetChunkContextIntent(file, chunk, context: 3)
   → Get surrounding code for understanding

3. ExtractKeyConceptsIntent(file)
   → Identify key concepts (JWT, sessions, etc.)

4. FindSimilarToFileIntent(auth_file)
   → Find similar implementations

5. MeasureSemanticDistanceIntent(file1, file2)
   → Compare implementations

6. Synthesize with local LLM
   → Natural language explanation

User sees:
"Your authentication system uses JWT tokens with Redis caching.
I found 3 similar implementations:
- login.js uses session cookies (75% similar)
- api_auth.py uses OAuth (60% similar)
- mobile_auth.swift uses biometric + JWT (85% similar)

The main difference is..."
```

## Summary

**Complete Semantic API:**
- ✅ 20+ intents covering all semantic operations
- ✅ Every metadata field accessible
- ✅ Every semantic primitive exposed
- ✅ Rich descriptions for AI understanding
- ✅ Composable for complex workflows
- ✅ Discoverable in Spotlight/Siri/Shortcuts

**This is the last mile:**
- Your index = Semantic database
- Your intents = Semantic API
- Apple Intelligence = Orchestrator
- Users = Natural language interface

**Every capability is now accessible to AI agents! 🚀**
