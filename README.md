# File Metadata and Embeddings System

A comprehensive system for extracting file metadata, chunking content for AI consumption, generating embeddings, and providing multiple search interfaces (semantic, full-text, topical).

## Features

### V2 Architecture (Current - AI-Optimized)

- **AI-Optimized Chunking**: Discrete chunks (~350 chars for code, paragraph boundaries for prose)
- **JSONB Envelopes**: Complete metadata in self-contained JSON documents for AI consumption
- **Multiple Search Modes**: Full-text (FTS5), semantic (embeddings + FAISS), file/metadata queries
- **Context-Aware Retrieval**: Built-in adjacency hints for intelligent context expansion
- **LLM-Consumable Output**: All tools return structured JSON with status, hints, and statistics
- **Dual Storage**: SQL columns for fast queries + JSONB documents for complete context

### V1 System (Legacy)

- **File Metadata Extraction**: Cross-platform file scanning with comprehensive metadata
- **NLP Analysis**: Keywords, TF-IDF, LDA topic modeling
- **Vector Embeddings**: Sentence-transformers with FAISS indexing
- **Multiple Search Interfaces**: Semantic, full-text, topical, LDA-based

## Quick Start

### Installation

```bash
cd ~/src/file_metadata_and_embeddings
pip install -r requirements.txt
```

### Initialize V2 Database

```bash
sqlite3 file_metadata.db < schema_refactor.sql
```

### Process Files with V2 Chunking

```python
from chunk_db_integration import ChunkDatabase

db = ChunkDatabase()
db.process_and_store_file('/path/to/file.py')
```

### Search with V2 Tools

```bash
# Full-text search
python tools_v2/find_using_fts_v2.py --query "error handling" --json

# Semantic search (requires embeddings)
python tools_v2/find_most_similar_v2.py --query "authentication logic" --json

# File/chunk queries
python tools_v2/file_query_tool_v2.py --file-path "example.py" --chunks --json
```

## Project Structure

```
file_metadata_and_embeddings/
├── Core V2 System
│   ├── chunking_refactor.py              # AI-optimized chunker
│   ├── chunk_db_integration.py           # JSONB database operations
│   ├── schema_refactor.sql               # V2 database schema
│   └── test_chunking_refactor.py         # Comprehensive test suite
│
├── V2 Search Tools
│   └── tools_v2/
│       ├── find_using_fts_v2.py          # Full-text search
│       ├── find_most_similar_v2.py       # Semantic search
│       ├── file_query_tool_v2.py         # File/chunk queries
│       ├── README.md                     # Tool documentation
│       └── TOOLS_REFACTOR_SUMMARY.md     # Migration guide
│
├── Legacy V1 System
│   └── file_metadata_content.py          # Original processor
│
├── Configuration
│   ├── requirements.txt                   # Core dependencies
│   ├── requirements_mcp.txt               # MCP dependencies
│   └── .gitignore                         # Repository hygiene
│
└── Documentation
    ├── README.md                          # This file
    ├── CLAUDE.md                          # Claude Code context
    └── claude_breadcrumbs.md              # Project timeline
```

## V2 Chunking Strategy

### Code Files (~350 characters, discrete)

- Breaks at logical boundaries (newlines, statement ends)
- No overlap needed (code is inherently discrete)
- Preserves code structure and readability
- **Rationale**: 350 chars balances semantic coherence with embedding model limits while avoiding truncation

**Supported file types**: `.py`, `.js`, `.c`, `.cpp`, `.java`, `.rs`, `.go`, `.sh`, `.rb`, `.php`, `.swift`, `.kt`, `.ts`, `.jsx`, `.tsx`

### Prose Files (paragraph boundaries, discrete)

- Breaks at paragraph boundaries (`\n\n`)
- Groups paragraphs up to ~800 chars
- Optional 15% overlap (configurable)

**Supported file types**: `.md`, `.txt`, `.org`, `.rst`, `.tex`

## V2 JSONB Chunk Envelopes

Every chunk is a self-contained JSON document with complete metadata:

```json
{
  "metadata": {
    "filename": "example.py",
    "chunk_index": 0,
    "total_chunks": 5,
    "chunk_size": 350,
    "chunk_strategy": "code_discrete",
    "overlap_chars": 0,
    "file_type": "py",
    "file_hash": "sha256:abc123...",
    "created_at": "2025-10-06T12:00:00Z",
    "ai_metadata": {
      "line_count": 15,
      "word_count": 87,
      "chunk_position": "start",
      "has_previous": false,
      "has_next": true,
      "adjacent_chunk_indexes": [0, 1, 2],
      "retrieval_context_suggestion": "adjacent_1",
      "starts_with": "def example():",
      "ends_with": "return result"
    }
  },
  "content": "def example():\n    # Function implementation...\n    return result"
}
```

**Key Features:**
- **Self-contained**: All context needed for AI processing
- **Adjacency hints**: AI agents can request surrounding chunks intelligently
- **Position awareness**: Start/middle/end of file indicated
- **Retrieval suggestions**: Built-in hints for context expansion

## Architecture

### Data Flow

```
File Input → AIOptimizedChunker → ChunkEnvelope (JSONB)
          ↓
  ChunkDatabase (dual storage: SQL + JSONB)
          ↓
  Search Tools (FTS/Semantic/Query) → JSON output for AI consumption
```

### Database Schema V2

- **text_chunks_v2**: JSONB chunk storage with complete metadata
- **chunks_fts**: FTS5 full-text search virtual table
- **chunks_with_metadata**: Convenience view for querying
- **Indexes**: Adjacency support for context retrieval

### Integration Architecture (Vision)

```
File Metadata Backend (V2)
    ↓
┌──────────────────────────────────┐
│  Shared Database & Core Logic    │
│  - JSONB chunk storage            │
│  - Multiple search modes          │
│  - Context-aware retrieval        │
└────────────┬─────────────────────┘
             ↓
    ┌────────┴────────┐
    ↓                 ↓
┌─────────┐     ┌──────────────┐
│ MCP     │     │ Apple        │
│ Tools   │     │ Intents      │
│ (LLMs)  │     │ (Shortcuts)  │
└─────────┘     └──────────────┘
```

## Testing

```bash
# Run V2 chunking tests
python test_chunking_refactor.py

# Expected output:
# ✓ Code chunking tests passed
# ✓ Prose chunking tests passed
# ✓ Chunk envelope serialization tests passed
# ✓ Adjacent chunk retrieval tests passed
# ✓ File type detection tests passed
# ✓ Metadata completeness tests passed
# ALL TESTS PASSED ✓
```

## Usage Examples

### Processing Files

```python
from chunk_db_integration import ChunkDatabase

db = ChunkDatabase()

# Process a single file
db.process_and_store_file('/path/to/code.py')

# Process content directly
content = "def hello():\n    print('world')"
db.process_and_store_file('example.py', content=content)
```

### Full-Text Search

```bash
# Basic search
python tools_v2/find_using_fts_v2.py --query "error handling"

# JSON output for AI consumption
python tools_v2/find_using_fts_v2.py --query "error handling" --json --pretty

# Include surrounding context
python tools_v2/find_using_fts_v2.py --query "error handling" --context 2 --json
```

### Semantic Search

```bash
# Semantic similarity search (requires embeddings)
python tools_v2/find_most_similar_v2.py --query "user authentication" --json

# With context expansion
python tools_v2/find_most_similar_v2.py --query "user authentication" --context 1 --json
```

### File/Chunk Queries

```bash
# Get file metadata and chunks
python tools_v2/file_query_tool_v2.py --file-path "/path/to/file.py" --chunks --json

# Get specific chunk with context
python tools_v2/file_query_tool_v2.py --file-path "/path/to/file.py" --chunk-index 5 --context 1 --json
```

## Legacy V1 System

The original system is preserved in `file_metadata_content.py`:

```bash
# Run V1 file metadata extraction
python3 file_metadata_content.py /path/to/directory --db file_metadata.db --workers 4
```

V1 includes legacy search tools (not in tools_v2):
- `find_by_tfidf.py` - Topical search using TF-IDF
- `find_by_lda.py` - Topic modeling search using LDA

## Requirements

- **Python 3.7+**
- **Core**: SQLite3, NLTK, sentence-transformers, FAISS
- **Optional**: torch (for embeddings), sklearn (for TF-IDF/LDA)

See `requirements.txt` for complete list.

## MCP Integration

MCP (Model Context Protocol) integration is planned for exposing file search tools to LLMs:

- MCP server will integrate with V2 tools
- Support for Ollama API and local LLMs
- Custom integration layer for streaming and context management

See `requirements_mcp.txt` for MCP dependencies.

## Development

### Running Tests

```bash
# V2 chunking tests
python test_chunking_refactor.py

# Manual testing of tools
python tools_v2/find_using_fts_v2.py --query "test" --json
```

### Git Workflow

```bash
# Check status
git status

# Stage changes
git add .

# Commit with descriptive message
git commit -m "Add feature: description"
```

### Documentation

- **CLAUDE.md**: Context for Claude Code AI assistant
- **claude_breadcrumbs.md**: Project timeline and lessons learned
- **tools_v2/README.md**: Complete tool documentation
- **CHUNKING_REFACTOR_README.md**: (if copied) Detailed chunking architecture

## License

See `LICENSE.txt` for license information.

## Project Status

**Current Version**: V2 (AI-optimized with JSONB envelopes)

**Status**: Production-ready for V2 chunking and search tools

**Last Updated**: October 6, 2025

**Active Development**:
- MCP integration with V2 tools
- Ollama API integration for local LLMs
- Apple Intents exploration for mobile/voice interface

## Contact & Contributing

This is a learning project with real utility goals. Development follows these principles:

- User directs the experience
- No tinkering without explicit request
- Focus on architecture, implementation, documentation
- Git hygiene and clean repositories
- Context management via CLAUDE.md and breadcrumbs

See `CLAUDE.md` for development workflow and principles.
