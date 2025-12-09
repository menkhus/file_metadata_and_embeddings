# Storage Architecture - The Full Picture

Complete storage requirements for embeddings + FAISS + metadata.

## The Reality: You Need Everything

### What Gets Stored

```
For 100,000 files (500,000 chunks):

1. SQLite Database (Persistent)
   ├── Metadata: ~100 MB
   │   └── File paths, timestamps, chunk info
   ├── Chunk Content: ~500 MB
   │   └── Actual text chunks (JSONB)
   └── Embeddings: ~750 MB
       └── 500K vectors × 384 dims × 4 bytes
   
   Total SQLite: ~1.35 GB on disk

2. FAISS Index (Memory)
   └── Vector index: ~750 MB in RAM
       └── Same vectors, optimized for search

3. Core ML Model (Memory, when encoding)
   └── Embedding model: ~80 MB in RAM
       └── all-MiniLM-L6-v2

Total Storage: ~1.35 GB disk + ~830 MB RAM
```

## Why Both?

### SQLite (Persistent Storage)

**Purpose:** Source of truth
- Store embeddings permanently
- Survive app restarts
- Incremental updates
- Backup/restore

**Can't search efficiently:**
- SQLite is row-based
- Vector similarity requires specialized indexes
- Would be extremely slow (seconds per query)

### FAISS (In-Memory Index)

**Purpose:** Fast search
- Optimized data structures
- SIMD operations
- Sub-millisecond queries

**Can't persist easily:**
- Binary format
- Needs to be rebuilt from SQLite
- Memory-only (by design)

### The Flow

```
┌─────────────────────────────────────────┐
│  New File                               │
└────────────┬────────────────────────────┘
             │
             ↓
┌─────────────────────────────────────────┐
│  1. Chunk File                          │
│     350 chars per chunk                 │
└────────────┬────────────────────────────┘
             │
             ↓
┌─────────────────────────────────────────┐
│  2. Generate Embeddings (Core ML)       │
│     384-dim vector per chunk            │
└────────────┬────────────────────────────┘
             │
             ↓
┌─────────────────────────────────────────┐
│  3. Store in SQLite                     │
│     • Chunk content (text)              │
│     • Embedding (BLOB)                  │
│     • Metadata (JSON)                   │
└────────────┬────────────────────────────┘
             │
             ↓
┌─────────────────────────────────────────┐
│  4. Update FAISS Index (if loaded)      │
│     Add vector to in-memory index       │
└─────────────────────────────────────────┘
```

## Storage Breakdown

### Per File

```
Average file: 5 chunks

Metadata per file:
- File path: 100 bytes
- Timestamps: 24 bytes
- File hash: 32 bytes
- Misc: 44 bytes
Total: ~200 bytes

Per chunk:
- Chunk content: ~350 bytes (text)
- Chunk metadata: ~500 bytes (JSON)
- Embedding: 1,536 bytes (384 × 4)
Total per chunk: ~2,386 bytes

Per file total: 200 + (5 × 2,386) = ~12 KB
```

### Scaling

| Files | Chunks | SQLite Size | FAISS RAM | Total RAM |
|-------|--------|-------------|-----------|-----------|
| 1,000 | 5,000 | 12 MB | 8 MB | ~90 MB |
| 10,000 | 50,000 | 120 MB | 75 MB | ~160 MB |
| 50,000 | 250,000 | 600 MB | 375 MB | ~460 MB |
| 100,000 | 500,000 | 1.2 GB | 750 MB | ~830 MB |
| 500,000 | 2,500,000 | 6 GB | 3.75 GB | ~3.8 GB |
| 1,000,000 | 5,000,000 | 12 GB | 7.5 GB | ~7.6 GB |

**This is first-gen AI - it's bulky!**

## Database Schema

### text_chunks_v2 Table

```sql
CREATE TABLE text_chunks_v2 (
    id INTEGER PRIMARY KEY,
    file_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    
    -- The actual chunk (JSONB envelope)
    chunk_envelope TEXT NOT NULL,  -- ~850 bytes
    
    -- Extracted for indexing
    chunk_strategy TEXT NOT NULL,
    chunk_size INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL,
    file_hash TEXT NOT NULL,
    file_type TEXT,
    created_at TEXT NOT NULL,
    
    -- The embedding (BLOB)
    embedding BLOB,  -- 1,536 bytes (384 floats)
    
    UNIQUE(file_path, chunk_index)
);
```

**Storage per row:** ~2,400 bytes

### Indexes

```sql
-- For lookups
CREATE INDEX idx_chunks_file_path ON text_chunks_v2(file_path);
CREATE INDEX idx_chunks_adjacency ON text_chunks_v2(file_path, chunk_index);

-- For FTS
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    file_path,
    chunk_index,
    content
);
```

**Index overhead:** ~20% of data size

## FAISS Index Structure

### In Memory

```cpp
class FAISSIndex {
private:
    // The actual index
    std::unique_ptr<faiss::IndexFlatL2> index_;
    
    // Mapping: FAISS index position → SQLite row ID
    std::vector<int64_t> id_map_;
    
    // Metadata cache (optional)
    std::unordered_map<int64_t, ChunkMetadata> metadata_cache_;
    
public:
    // Memory usage:
    // - index_: vectors × 384 × 4 bytes
    // - id_map_: vectors × 8 bytes
    // - metadata_cache_: vectors × ~200 bytes (if used)
    
    size_t memoryUsage() const {
        size_t index_size = index_->ntotal * 384 * 4;
        size_t map_size = id_map_.size() * 8;
        size_t cache_size = metadata_cache_.size() * 200;
        return index_size + map_size + cache_size;
    }
};
```

**Memory breakdown:**
- Vectors: 1,536 bytes per chunk
- ID mapping: 8 bytes per chunk
- Metadata cache: 200 bytes per chunk (optional)
- **Total: ~1,744 bytes per chunk in RAM**

## Building FAISS Index

### From SQLite

```swift
class IndexBuilder {
    func buildFAISSIndex() async throws -> FAISSIndex {
        logger.info("Building FAISS index from SQLite...")
        
        // 1. Count vectors
        let count = try database.countEmbeddings()
        logger.info("Loading \(count) vectors...")
        
        // 2. Allocate memory
        var vectors: [Float] = []
        vectors.reserveCapacity(count * 384)
        
        var idMap: [Int64] = []
        idMap.reserveCapacity(count)
        
        // 3. Load from SQLite in batches
        let batchSize = 10_000
        for offset in stride(from: 0, to: count, by: batchSize) {
            let batch = try database.loadEmbeddings(
                limit: batchSize,
                offset: offset
            )
            
            for (id, embedding) in batch {
                vectors.append(contentsOf: embedding)
                idMap.append(id)
            }
            
            // Progress
            let progress = Double(offset + batch.count) / Double(count)
            logger.info("Progress: \(Int(progress * 100))%")
        }
        
        // 4. Build FAISS index
        logger.info("Building FAISS index...")
        let index = FAISSIndex(
            dimension: 384,
            vectors: vectors,
            idMap: idMap
        )
        
        logger.info("FAISS index built: \(index.memoryUsage() / 1_000_000) MB")
        return index
    }
}
```

**Build time:**
- 10K vectors: ~50ms
- 100K vectors: ~500ms
- 1M vectors: ~5s

## Incremental Updates

### Adding New Files

```swift
func indexNewFile(_ path: String) async throws {
    // 1. Chunk file
    let chunks = try await chunker.chunk(path)
    
    // 2. Generate embeddings
    let embeddings = try await embedder.encode(chunks)
    
    // 3. Store in SQLite
    try await database.storeChunks(path, chunks, embeddings)
    
    // 4. Update FAISS index (if loaded)
    if let index = faissIndex {
        for (i, embedding) in embeddings.enumerated() {
            let chunkId = try database.getChunkId(path, index: i)
            index.add(embedding, id: chunkId)
        }
    }
    // If index not loaded, it will be rebuilt on next search
}
```

### Updating Existing Files

```swift
func updateFile(_ path: String) async throws {
    // 1. Remove old chunks from SQLite
    let oldChunkIds = try database.getChunkIds(path)
    try database.deleteChunks(path)
    
    // 2. Remove from FAISS (if loaded)
    if let index = faissIndex {
        for id in oldChunkIds {
            index.remove(id)
        }
    }
    
    // 3. Add new version
    try await indexNewFile(path)
}
```

### Deleting Files

```swift
func deleteFile(_ path: String) async throws {
    // 1. Get chunk IDs
    let chunkIds = try database.getChunkIds(path)
    
    // 2. Remove from SQLite
    try database.deleteChunks(path)
    
    // 3. Remove from FAISS (if loaded)
    if let index = faissIndex {
        for id in chunkIds {
            index.remove(id)
        }
    }
}
```

## Persistence Strategy

### Option 1: Rebuild on Demand (Recommended)

```swift
class LazyIndexManager {
    private var index: FAISSIndex?
    
    func search(query: String) async throws -> [Result] {
        // Build index if not loaded
        if index == nil {
            index = try await buildFAISSIndex()
        }
        
        return try await index!.search(query)
    }
}
```

**Pros:**
- Simple
- Always up-to-date
- No stale index issues

**Cons:**
- First search has delay
- Rebuild time grows with dataset

### Option 2: Serialize FAISS Index (Advanced)

```swift
class PersistentIndexManager {
    func saveIndex() throws {
        guard let index = index else { return }
        
        // Serialize FAISS index to disk
        let indexPath = getIndexPath()
        try index.write(to: indexPath)
        
        // Save metadata
        let metadata = IndexMetadata(
            vectorCount: index.count,
            lastModified: Date(),
            databaseHash: database.hash()
        )
        try metadata.save()
    }
    
    func loadIndex() async throws -> FAISSIndex {
        let indexPath = getIndexPath()
        
        // Check if index is stale
        let metadata = try IndexMetadata.load()
        if metadata.databaseHash != database.hash() {
            // Database changed, rebuild
            return try await buildFAISSIndex()
        }
        
        // Load from disk
        return try FAISSIndex.read(from: indexPath)
    }
}
```

**Pros:**
- Faster startup (load vs rebuild)
- Good for large datasets

**Cons:**
- More complex
- Need to track staleness
- Disk space (duplicate of embeddings)

## Optimization Strategies

### 1. Quantization (Reduce Size)

```cpp
// Use 8-bit quantization instead of 32-bit floats
// Reduces memory by 75%!

// Original: 384 × 4 bytes = 1,536 bytes per vector
faiss::IndexFlatL2 index(384);

// Quantized: 384 × 1 byte = 384 bytes per vector
faiss::IndexScalarQuantizer index(384, faiss::ScalarQuantizer::QT_8bit);

// Trade-off: Slight accuracy loss (~1-2%)
// Benefit: 4x less memory
```

**For 100K files:**
- Original: 750 MB
- Quantized: 190 MB
- **Savings: 560 MB!**

### 2. Product Quantization (Extreme Compression)

```cpp
// Compress to 64 bytes per vector (24x compression!)
faiss::IndexPQ index(384, 64, 8);

// Trade-off: More accuracy loss (~5-10%)
// Benefit: 24x less memory
```

**For 100K files:**
- Original: 750 MB
- PQ: 31 MB
- **Savings: 719 MB!**

### 3. Hierarchical Indexes (Large Datasets)

```cpp
// For > 1M vectors
// Use IVF (Inverted File) index
faiss::IndexIVFFlat index(quantizer, 384, nlist);

// Trade-off: Slightly slower search
// Benefit: Much faster build, less memory
```

## Disk Space Management

### Database Location

```
~/Library/Application Support/FileSearch/
├── file_metadata.db          # Main database (1.2 GB)
├── file_metadata.db-wal      # Write-ahead log (varies)
├── file_metadata.db-shm      # Shared memory (32 KB)
└── faiss_index.bin           # Optional: Serialized index (750 MB)

Total: ~2 GB for 100K files
```

### Cleanup Strategy

```swift
class StorageManager {
    func cleanupOldData() async {
        // Remove chunks for deleted files
        try await database.vacuum()
        
        // Remove old FAISS index if stale
        if isFAISSIndexStale() {
            try FileManager.default.removeItem(at: faissIndexPath)
        }
        
        // Compact database
        try await database.execute("VACUUM")
    }
    
    func estimateDiskUsage() -> DiskUsage {
        let dbSize = getDatabaseSize()
        let indexSize = getFAISSIndexSize()
        
        return DiskUsage(
            database: dbSize,
            faissIndex: indexSize,
            total: dbSize + indexSize
        )
    }
}
```

## User Communication

### Storage Stats

```
┌─────────────────────────────────────────┐
│  FileSearch Storage                     │
├─────────────────────────────────────────┤
│  Files indexed: 100,000                 │
│  Chunks: 500,000                        │
│                                         │
│  Disk Usage:                            │
│  • Database: 1.2 GB                     │
│  • Search index: 750 MB (in memory)     │
│  • Total: 1.2 GB disk + 750 MB RAM      │
│                                         │
│  [Optimize Storage...]                  │
│  [Clear Index...]                       │
└─────────────────────────────────────────┘
```

### Optimization Options

```
┌─────────────────────────────────────────┐
│  Optimize Storage                       │
├─────────────────────────────────────────┤
│  Current: 750 MB in memory              │
│                                         │
│  ○ Full precision (current)             │
│     750 MB RAM, best accuracy           │
│                                         │
│  ● Compressed (recommended)             │
│     190 MB RAM, 99% accuracy            │
│                                         │
│  ○ Maximum compression                  │
│     31 MB RAM, 95% accuracy             │
│                                         │
│  [Apply]  [Cancel]                      │
└─────────────────────────────────────────┘
```

## Summary

**The Reality:**
- SQLite: ~2.4 KB per chunk on disk
- FAISS: ~1.5 KB per chunk in RAM
- Core ML: ~80 MB when encoding
- **Total: ~4 KB per chunk (disk + RAM)**

**For 100K files (500K chunks):**
- Disk: 1.2 GB
- RAM: 750 MB (when searching)
- Total: ~2 GB footprint

**This is first-gen AI - it's bulky!**

**Optimizations:**
- Quantization: 4x compression (190 MB vs 750 MB)
- Product Quantization: 24x compression (31 MB vs 750 MB)
- Lazy loading: Only load when needed
- Partitioning: Split large datasets

**The Apple Way:**
- Be honest about requirements
- Provide optimization options
- Show clear storage stats
- Degrade gracefully on low-end hardware
- Make it work great for 95% of users
