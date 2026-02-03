# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**File Metadata and Embeddings System** - A comprehensive system for extracting file metadata, chunking content for AI consumption, generating embeddings, and providing multiple search interfaces (semantic, full-text, topical).

**Current Version:** V2 (AI-optimized with JSONB chunk envelopes)

**Project Location:** `~/src/file_metadata_and_embeddings`

## Essential Commands

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Run file metadata extraction (V1 - Legacy):**
```bash
python3 file_metadata_content.py <directory> [--db <dbfile>] [--workers N] [--verbose|--debug]
```

**Process files with V2 chunking (Recommended):**
```python
from chunk_db_integration import ChunkDatabase
db = ChunkDatabase()
db.process_and_store_file('/path/to/file.py')
```

**Initialize V2 database schema:**
```bash
sqlite3 file_metadata.db < schema_refactor.sql
```

**Search using V2 tools:**
```bash
# Full-text search
python tools_v2/find_using_fts_v2.py --query "error handling" --json

# Semantic search
python tools_v2/find_most_similar_v2.py --query "authentication logic" --json

# File/chunk queries
python tools_v2/file_query_tool_v2.py --file-path "example.py" --chunks --json
```

## Architecture Overview

### V2 Architecture (Current)

**AI-Optimized Design:**
- Discrete chunking: ~350 chars for code, paragraph boundaries for prose
- JSONB envelopes with complete metadata for AI consumption
- Dual storage: SQL columns (fast queries) + JSONB documents (complete context)
- Built-in adjacency hints for context expansion
- LLM-consumable JSON output from all tools

**Core Components:**
- `AIOptimizedChunker` (chunking_refactor.py): Content-aware chunking
- `ChunkDatabase` (chunk_db_integration.py): JSONB storage and retrieval
- `tools_v2/`: Refactored search tools with JSON output
- `schema_refactor.sql`: V2 database schema with FTS5

**Data Flow:**
```
File Input → AIOptimizedChunker → ChunkEnvelope (JSONB)
          ↓
  ChunkDatabase (dual storage: SQL + JSONB)
          ↓
  Search Tools (FTS/Semantic/Query) → JSON output
```

**Database Schema V2:**
- `text_chunks_v2`: JSONB chunk storage with complete metadata
- `chunks_fts`: FTS5 full-text search table
- `chunks_with_metadata`: Convenience view for querying
- Adjacency indexes for context retrieval

### V1 Architecture (Legacy)

**Core Components (all in `file_metadata_content.py`):**
- `CrossPlatformFileScanner`: File discovery and metadata extraction
- `TextProcessor`: NLP analysis, embeddings, TF-IDF, LDA topic modeling
- `DatabaseManager`: SQLite schema management and data persistence
- `FileMetadataExtractor`: Orchestration and parallel processing

**Database Schema V1:**
- `file_metadata`: Core file information
- `content_analysis`: NLP results
- `text_chunks`: Segmented text content
- `embeddings_index`: Vector embeddings (JSON for FAISS)
- `content_fts`: Full-text search virtual table

## Key Design Patterns

### V2 Chunking Strategy

**Code Files (~350 characters, discrete):**
- Breaks at logical boundaries (newlines, statement ends)
- No overlap needed (code is inherently discrete)
- Preserves code structure and readability
- File types: `.py`, `.js`, `.c`, `.cpp`, `.java`, `.rs`, `.go`, etc.

**Design Rationale:** 350 characters balances semantic coherence (keeps logical units together) with embedding model context limits while avoiding truncation that degrades search quality. Discrete chunks avoid duplication and simplify adjacency retrieval.

**Prose Files (paragraph boundaries, discrete):**
- Breaks at paragraph boundaries (`\n\n`)
- Groups paragraphs up to ~800 chars
- Optional 15% overlap (configurable for retrieval tasks)
- File types: `.md`, `.txt`, `.org`, etc.

### JSONB Chunk Envelopes

Every chunk is a self-contained JSON document:
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
    "file_hash": "sha256...",
    "created_at": "2025-10-05T21:00:00Z",
    "ai_metadata": {
      "line_count": 15,
      "word_count": 87,
      "chunk_position": "start",
      "has_previous": false,
      "has_next": true,
      "adjacent_chunk_indexes": [0, 1, 2],
      "retrieval_context_suggestion": "adjacent_1",
      "starts_with": "def example()...",
      "ends_with": "...return result"
    }
  },
  "content": "actual chunk content..."
}
```

**Design Rationale:** Complete metadata in each envelope enables AI agents to understand context boundaries, request adjacent chunks intelligently, and maintain conversation coherence across retrieval operations.

### Error Handling

- All operations use try/catch with detailed logging
- Graceful degradation when NLTK data or models unavailable
- Files >100MB are skipped or partially processed
- Status codes track processing success/failure for each file

## Development Notes

- Python 3.10+ required (uses modern typing features)
- NLTK data downloads automatically at runtime if missing
- Hidden/system files are skipped by default
- Log output goes to `file_metadata_system.log` and console
- Default database location: `/Users/mark/data/file_metadata.sqlite3`
- Processing uses ThreadPoolExecutor for parallelism

## File Organization

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
└── Configuration
    ├── requirements.txt                   # Core dependencies
    ├── requirements_mcp.txt               # MCP dependencies
    └── .gitignore                         # Clean repo maintenance
```

## Current Project Phase: Clean V2 Foundation

**Status:** V2 refactoring complete, clean repository established

**Recent Work (Oct 5-6, 2025):**
- ✅ Complete V2 chunking system with AI-optimized envelopes
- ✅ Refactored search tools with JSON output
- ✅ Comprehensive testing and documentation
- ✅ Clean project directory with proper git hygiene
- ✅ All production code tracked in git

**Architecture Vision:**
```
File Metadata Backend (V2)
    ↓
┌──────────────┬─────────────────┐
│  MCP Tools   │  Apple Intents  │
│  (for LLMs)  │  (for Shortcuts)│
└──────────────┴─────────────────┘
```

**Next Milestones:**
1. MCP server integration with V2 tools
2. Local LLM integration via Ollama API
3. Custom integration layer for streaming and context management
4. Apple Intents exploration for mobile/voice interface

## Working Principles & Process

**User Directives:**
- User directs the experience and maintains control of the session
- No tinkering or rabbit holes without explicit user request
- Focus on architecture, implementation, documentation, and forward progress
- Context management is critical - both human and AI need continuity
- This is hard work that requires partnership and discipline

**Required Session Management:**
1. **Start every session** by reading CLAUDE.md and claude_breadcrumbs.md
2. **Update claude_breadcrumbs.md** at end of significant work/decisions
3. **Document lessons learned** - what worked, what didn't, why
4. **Track architecture decisions** and their reasoning
5. **Maintain clear next steps** for session continuity

**Breadcrumbs Process:**
- Record our work, steps, intents, and successes
- Capture lessons learned to avoid repeating mistakes
- Document decision points and reasoning
- Track what we've tried and results
- Maintain project timeline and current state
- Enable effective session handoffs

**Communication Style:**
- Be direct and concise
- Focus on moving forward, not explaining past decisions
- Ask clarifying questions when user intent is unclear
- Propose specific next actions based on documented goals

**Code Documentation Requirements:**
When creating or modifying code, always explain:
- **Design decisions** and their reasoning
- **Subtle nuances** that might not be obvious from reading the code
- **Knowledge boundaries** and why they matter
- **Trade-offs made** and alternatives considered
- **Performance implications** of choices made
- **Integration patterns** and why they were selected
- **Error handling strategies** and their rationale
- **Future extensibility** considerations built into the design

**Git Hygiene:**
- All production code must be tracked in git
- Commit meaningful work with clear messages
- Use .gitignore to prevent pollution
- No experimental/throwaway files in production repo
