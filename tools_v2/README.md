# File Metadata Tools V2 - JSONB Edition

LLM-optimized database query tools with complete JSONB chunk envelopes.

## Overview

These refactored tools work with the new `text_chunks_v2` table and output LLM-consumable JSON format. Each tool:

- ✅ Uses JSONB chunk envelopes with complete metadata
- ✅ Returns structured JSON optimized for LLM consumption
- ✅ Supports adjacent chunk context retrieval
- ✅ Provides usage hints and metadata in responses
- ✅ Maintains backward compatibility (reads existing tables)

## Installation

1. **Initialize the new schema**:
   ```bash
   cd /Users/mark/src/file_metadata_tool
   sqlite3 file_metadata.db < schema_refactor.sql
   ```

2. **Make tools executable**:
   ```bash
   chmod +x tools_v2/*.py
   ```

3. **Install dependencies** (for semantic search):
   ```bash
   pip install faiss-cpu numpy sentence-transformers
   ```

## Tools

### 1. find_using_fts_v2.py - Full-Text Search

Search chunk content using FTS5 with complete JSONB envelopes.

**Basic Usage:**
```bash
# JSON output (LLM-optimized)
python tools_v2/find_using_fts_v2.py --query "error handling" --json

# Pretty-printed JSON
python tools_v2/find_using_fts_v2.py --query "function" --json --pretty

# Include adjacent chunks for context
python tools_v2/find_using_fts_v2.py --query "import" --context 1 --json

# Limit results
python tools_v2/find_using_fts_v2.py --query "class" --limit 5 --json
```

**Human-Readable Output:**
```bash
python tools_v2/find_using_fts_v2.py --query "error"
```

**JSON Output Structure:**
```json
{
  "status": "success",
  "query_metadata": {
    "total_results": 10,
    "query": "error handling",
    "search_type": "full_text_search",
    "database": "file_metadata.db"
  },
  "results": [
    {
      "match_rank": -1.5,
      "snippet": "...error **handling** logic...",
      "chunk_envelope": {
        "metadata": {
          "filename": "example.py",
          "chunk_index": 3,
          "total_chunks": 10,
          "chunk_strategy": "code_discrete",
          "ai_metadata": {
            "line_count": 15,
            "chunk_position": "middle",
            "retrieval_context_suggestion": "adjacent_1"
          }
        },
        "content": "actual chunk content..."
      },
      "search_metadata": {
        "file_path": "/path/to/example.py",
        "chunk_index": 3
      },
      "context_chunks": [...]  // if --context used
    }
  ],
  "usage_hints": {...},
  "summary": {...}
}
```

### 2. find_most_similar_v2.py - Semantic Search

Semantic similarity search using embeddings and FAISS.

**Basic Usage:**
```bash
# Semantic search (JSON output)
python tools_v2/find_most_similar_v2.py --query "error handling in python" --json

# Top 10 results
python tools_v2/find_most_similar_v2.py --query "authentication" --top_k 10 --json

# Include context chunks
python tools_v2/find_most_similar_v2.py --query "database connection" --context 1 --json

# Custom model
python tools_v2/find_most_similar_v2.py --query "search" --model "all-mpnet-base-v2" --json
```

**JSON Output Structure:**
```json
{
  "status": "success",
  "query_metadata": {
    "query": "error handling",
    "total_results": 5,
    "search_type": "semantic_similarity",
    "model": "all-MiniLM-L6-v2",
    "index_size": 1500
  },
  "results": [
    {
      "rank": 1,
      "similarity_distance": 0.234,
      "similarity_score": 0.810,
      "chunk_envelope": {...},
      "search_metadata": {...},
      "context_chunks": [...]
    }
  ],
  "usage_hints": {...},
  "summary": {
    "avg_similarity_score": 0.75,
    "top_match_file": "/path/to/file.py",
    "top_match_score": 0.810
  }
}
```

**Note**: Requires embeddings to be generated first. The similarity_score ranges from 0-1 (higher is better).

### 3. file_query_tool_v2.py - File & Chunk Query

Query files by metadata and retrieve complete chunk envelopes.

**File Queries:**
```bash
# Files by date
python tools_v2/file_query_tool_v2.py --created-since 2024-01-01 --json

# Files by name pattern
python tools_v2/file_query_tool_v2.py --name "test" --json

# Files by type
python tools_v2/file_query_tool_v2.py --type "py" --json

# Files by size
python tools_v2/file_query_tool_v2.py --greater 10000 --less 100000 --json

# Combined filters
python tools_v2/file_query_tool_v2.py --name "config" --type "json" --json
```

**Chunk Queries:**
```bash
# All chunks for a file
python tools_v2/file_query_tool_v2.py --file-path "/path/to/file.py" --chunks --json

# Specific chunk
python tools_v2/file_query_tool_v2.py --file-path "/path/to/file.py" --chunk-index 5 --json

# Chunk with context (±1 chunks)
python tools_v2/file_query_tool_v2.py --file-path "/path/to/file.py" --chunk-index 5 --context 1 --json

# Chunk statistics
python tools_v2/file_query_tool_v2.py --file-path "/path/to/file.py" --stats --json
```

**JSON Output Structure:**
```json
{
  "status": "success",
  "query_metadata": {...},
  "database": "file_metadata.db",
  "files": {
    "total_count": 15,
    "results": [...]
  },
  "chunks": {
    "total_count": 10,
    "results": [
      {
        "chunk_index": 5,
        "chunk_envelope": {...},
        "context_chunks": [...]
      }
    ]
  },
  "chunk_statistics": {
    "total_chunks": 10,
    "chunk_strategy": "code_discrete",
    "avg_size": 345.2
  },
  "usage_hints": {...}
}
```

## Common Options

All tools support:

- `--db PATH` - Database path (default: `file_metadata.db`)
- `--json` - Output LLM-optimized JSON
- `--pretty` - Pretty-print JSON (indent=2)
- `--context N` - Include N adjacent chunks for context

## Output Format Philosophy

### LLM-Consumable JSON Features

1. **Complete Envelopes**: Each result includes full chunk envelope with metadata + content
2. **Usage Hints**: JSON includes hints on accessing nested data
3. **Summary Statistics**: Aggregated info for quick understanding
4. **Status Fields**: Clear success/error indication
5. **Nested Structure**: Logical grouping (metadata, results, hints, summary)

### Chunk Envelope Structure

Every chunk envelope contains:

```json
{
  "metadata": {
    // Core metadata (mirrored in SQL)
    "filename": "example.py",
    "chunk_index": 0,
    "total_chunks": 5,
    "chunk_size": 350,
    "chunk_strategy": "code_discrete",
    "overlap_chars": 0,
    "file_type": "py",
    "file_hash": "sha256...",
    "created_at": "2025-10-05T21:00:00Z",

    // AI-specific metadata
    "ai_metadata": {
      "line_count": 15,
      "word_count": 87,
      "chunk_position": "start",  // start|middle|end
      "has_previous": false,
      "has_next": true,
      "previous_chunk_index": null,
      "next_chunk_index": 1,
      "starts_with": "def example()...",
      "ends_with": "...return result",
      "adjacent_chunk_indexes": [0, 1, 2],
      "retrieval_context_suggestion": "adjacent_1"
    }
  },
  "content": "actual chunk text content here..."
}
```

## Integration Examples

### Python Integration

```python
import json
import subprocess

# Run tool and parse JSON
result = subprocess.run(
    ['python', 'tools_v2/find_using_fts_v2.py',
     '--query', 'error handling',
     '--json'],
    capture_output=True,
    text=True
)

data = json.loads(result.stdout)

# Access results
for item in data['results']:
    envelope = item['chunk_envelope']
    content = envelope['content']
    metadata = envelope['metadata']

    print(f"Found in {metadata['filename']} chunk {metadata['chunk_index']}")
    print(f"Content: {content[:100]}...")

    # Check AI hints
    suggestion = metadata['ai_metadata']['retrieval_context_suggestion']
    if suggestion == 'adjacent_1':
        print("Hint: Consider fetching adjacent chunks for more context")
```

### LLM Prompt Integration

```python
# Prepare context for LLM
search_results = json.loads(tool_output)

context = []
for result in search_results['results']:
    envelope = result['chunk_envelope']

    # Build context string
    chunk_info = f"""
File: {envelope['metadata']['filename']}
Chunk: {envelope['metadata']['chunk_index']}/{envelope['metadata']['total_chunks']}
Strategy: {envelope['metadata']['chunk_strategy']}

Content:
{envelope['content']}
"""
    context.append(chunk_info)

# Send to LLM
prompt = f"""
Based on the following code chunks:

{chr(10).join(context)}

Please explain the error handling strategy.
"""
```

### Adjacent Context Expansion

```python
def get_with_context(file_path, chunk_index, context=1):
    """Get a chunk with surrounding context"""
    result = subprocess.run([
        'python', 'tools_v2/file_query_tool_v2.py',
        '--file-path', file_path,
        '--chunk-index', str(chunk_index),
        '--context', str(context),
        '--json'
    ], capture_output=True, text=True)

    data = json.loads(result.stdout)
    main_chunk = data['chunks']['results'][0]

    # Reconstruct full context
    all_chunks = main_chunk.get('context_chunks', [])
    all_chunks.insert(chunk_index - max(0, chunk_index - context), main_chunk)

    full_text = '\n\n---\n\n'.join(
        c['chunk_envelope']['content'] for c in all_chunks
    )

    return full_text
```

## Comparison: V1 vs V2

| Feature | V1 Tools | V2 Tools |
|---------|----------|----------|
| Output Format | Text/partial JSON | Complete JSON envelopes |
| Chunk Metadata | Minimal | Rich AI-optimized |
| Context Retrieval | Manual | Built-in --context flag |
| LLM Integration | Requires parsing | Direct JSON consumption |
| Usage Hints | None | Included in response |
| Summary Stats | None | Included in response |
| Status Handling | Implicit | Explicit status field |

## Troubleshooting

### "chunks_fts table not found"

Run the schema initialization:
```bash
sqlite3 file_metadata.db < schema_refactor.sql
```

### "No embeddings found"

Semantic search requires embeddings. Generate them first or use FTS search instead.

### "No results found"

The new `text_chunks_v2` table is empty. Process files using:
```python
from chunk_db_integration import ChunkDatabase

db = ChunkDatabase()
db.process_and_store_file('/path/to/file.py')
```

Or update your main file processing to use the new chunker.

## Migration from V1 Tools

| Old Tool | New Tool | Changes |
|----------|----------|---------|
| find_using_fts.py | find_using_fts_v2.py | + JSONB chunks, + context, + hints |
| find_most_similar.py | find_most_similar_v2.py | + JSONB chunks, + context, + similarity score |
| file_query_tool.py | file_query_tool_v2.py | + chunk queries, + JSONB, + stats |
| find_by_lda.py | (deprecated) | Use content_analysis table directly |
| find_by_tfidf.py | (deprecated) | Use content_analysis table directly |

## Best Practices

1. **Always use --json flag** for programmatic access
2. **Use --context** when you need surrounding code/text
3. **Check ai_metadata hints** for retrieval suggestions
4. **Parse status field** to handle errors gracefully
5. **Use usage_hints** to understand response structure

## Examples by Use Case

### Code Review
```bash
# Find error handling code with context
python tools_v2/find_using_fts_v2.py \
  --query "try except" \
  --context 2 \
  --json > error_handling.json
```

### Documentation Search
```bash
# Semantic search for concepts
python tools_v2/find_most_similar_v2.py \
  --query "how to configure authentication" \
  --top_k 3 \
  --context 1 \
  --json
```

### File Analysis
```bash
# Get all chunks for a file
python tools_v2/file_query_tool_v2.py \
  --file-path "/path/to/module.py" \
  --chunks \
  --json | jq '.chunks.results[].chunk_envelope.metadata'
```

### RAG Pipeline
```bash
# Search + retrieve with context for RAG
python tools_v2/find_using_fts_v2.py \
  --query "database connection pool" \
  --context 1 \
  --limit 5 \
  --json | \
  jq '.results[] | {file: .search_metadata.file_path, content: .chunk_envelope.content}'
```

## Future Enhancements

- [ ] Hybrid search (combine FTS + semantic)
- [ ] Re-ranking support
- [ ] Batch query API
- [ ] Export formats (markdown, HTML)
- [ ] Query result caching
- [ ] Multi-database queries

## See Also

- [CHUNKING_REFACTOR_README.md](../CHUNKING_REFACTOR_README.md) - Chunking system details
- [REFACTOR_SUMMARY.md](../REFACTOR_SUMMARY.md) - Migration summary
- [schema_refactor.sql](../schema_refactor.sql) - Database schema
