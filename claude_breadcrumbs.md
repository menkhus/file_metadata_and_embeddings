# Claude Breadcrumbs - File Metadata and Embeddings Project

This file tracks our development journey, decisions, lessons learned, and current state for continuity across sessions.

## Project Timeline & Decisions

### Phase 1: Foundation Built (2024-2025)
**What We Built:**
- Complete file metadata extraction system (`file_metadata_content.py`)
- Rich database schema with embeddings, FTS5, TF-IDF, LDA
- Multiple search interfaces (semantic, full-text, topical)
- 2GB+ database with processed file metadata at `/Users/mark/data/file_metadata.sqlite3`
- Working MCP server exposing file search tools

**Key Architecture Decisions:**
- Single-file design pattern for core logic
- SQLite with multiple specialized tables
- Parallel processing with ThreadPoolExecutor
- Multiple search modes for different use cases

### Phase 2: MCP Integration Exploration
**Initial Problem:** How to integrate MCP server with Ollama for local AI

**Discovery Process:**
1. **First Attempt:** Tried Ollama native MCP support
   - **Result:** Ollama doesn't support MCP natively (GitHub issue #7865 open)
   - **Lesson:** Always research current capabilities before assuming

2. **MCPhost Approach:** Used MCPhost as bridge
   - **Result:** Functional but had display issues (`[10]` errors, black text)
   - **Success:** Proved MCP server works (`mcp_server_fixed.py`), tools are called correctly
   - **Lesson:** Functional doesn't mean usable

3. **Tinkering Detour:** Created multiple workarounds
   - Custom web interface, plain text wrappers, etc.
   - **User Feedback:** "I don't want this tinkering direction"
   - **Lesson:** Stay focused on core architecture goals, avoid scope creep

4. **Research Breakthrough:** Found proper MCP clients
   - `ollmcp` - Python-based MCP client for Ollama
   - `ollama-mcp-bridge` - TypeScript bridge
   - **Decision:** Focus on `ollmcp` for clean Python integration

**Key Technical Findings:**
- **gpt-oss:20b Function Calling:** Model shows understanding of function concepts, likely compatible with proper tool setup
- **ollmcp Configuration:** Couldn't load MCP server properly, terminal compatibility issues
- **MCPhost Validation:** MCP server works correctly, bridge tools have their own quirks

**Strategic Insight - Local Integration Focus:**
- **User Vision:** Ollama as API service (LLM manager), MCP as protocol (structured tool access), custom integration layer (streaming, context management, UX)
- **Architecture Pattern:** User → Custom UI/Interface → Ollama API (streaming) ↔ MCP Tools ↔ File Search System
- **Context Management Features:** Sliding context windows, user intent preservation (like CLAUDE.md/breadcrumbs.md patterns), session workflow continuity

### Phase 3: V2 Refactoring - AI-Optimized Chunking (Oct 5, 2025)
**Major Breakthrough:** Complete system refactoring with AI-consumable JSON envelopes

**What We Built:**
1. **AI-Optimized Chunker** (`chunking_refactor.py`)
   - Code: ~350 characters, discrete (no overlap), logical boundaries
   - Prose: Paragraph boundaries, discrete chunks
   - Auto-detection based on file extension
   - **Design Rationale:** 350 chars balances semantic coherence with embedding model limits (most sentence transformers work best under 512 tokens) while avoiding truncation that degrades search quality

2. **JSONB Database Integration** (`chunk_db_integration.py`)
   - Complete metadata in JSON envelope
   - Dual storage: SQL columns (fast queries) + JSONB document (AI consumption)
   - Extended AI-specific metadata (adjacency hints, retrieval suggestions)

3. **V2 Database Schema** (`schema_refactor.sql`)
   - `text_chunks_v2` table with JSONB storage
   - `chunks_fts` - FTS5 full-text search
   - `chunks_with_metadata` - Convenience view
   - Indexes for adjacency queries
   - Built-in support for context expansion (±N chunks around matches)

4. **Refactored Search Tools** (`tools_v2/`)
   - `find_using_fts_v2.py` - Full-text search with JSONB envelopes
   - `find_most_similar_v2.py` - Semantic search with embeddings
   - `file_query_tool_v2.py` - File/chunk queries with metadata
   - All tools return structured JSON (status, envelopes, hints, statistics)

5. **Comprehensive Testing** (`test_chunking_refactor.py`)
   - All tests passing ✅
   - Code chunking, prose chunking, envelope serialization
   - Adjacent chunk retrieval, file type detection, metadata completeness

6. **Complete Documentation**
   - `CHUNKING_REFACTOR_README.md` - System architecture
   - `REFACTOR_SUMMARY.md` - Chunking summary
   - `tools_v2/README.md` - Tool usage guide
   - `tools_v2/TOOLS_REFACTOR_SUMMARY.md` - Migration guide
   - `COMPLETE_REFACTOR_INDEX.md` - Complete index

**Key Benefits:**
- **AI-Consumable:** Complete metadata in JSON envelopes
- **Context-Aware:** Built-in adjacency hints and retrieval suggestions
- **Efficient:** Dual storage (SQL + JSONB) for fast queries and AI consumption
- **Flexible:** Easy to extend ai_metadata with new fields
- **Self-Documenting:** Metadata describes chunking strategy and context

### Phase 4: Clean Repository Establishment (Oct 6, 2025)
**Problem:** Original repository polluted with 47 untracked experimental files

**What We Did:**
1. **Created Clean Project Directory:** `~/src/file_metadata_and_embeddings`
2. **Migrated V2 Code:**
   - Core: `chunking_refactor.py`, `chunk_db_integration.py`, `schema_refactor.sql`, `test_chunking_refactor.py`
   - Tools: `tools_v2/` directory (7 files)
   - Legacy: `file_metadata_content.py` (V1 system)
   - Config: `requirements.txt`, `requirements_mcp.txt`, `LICENSE.txt`
3. **Git Hygiene:**
   - ✅ Initialized clean git repository
   - ✅ Created comprehensive `.gitignore` (Python, databases, logs, FAISS indexes, etc.)
   - ✅ Updated `CLAUDE.md` with V2 architecture and current state
   - ✅ Updated `claude_breadcrumbs.md` with complete timeline

**Architecture Change:**
- **Old Location:** `/Users/mark/src/file_metadata_tool` (polluted, experimental)
- **New Location:** `/Users/mark/src/file_metadata_and_embeddings` (clean, production)
- **Database:** Still at `/Users/mark/data/file_metadata.sqlite3` (shared resource)

**Git Status:** Ready for initial commit of clean V2 codebase

## Current State (Oct 6, 2025)

### Working Components:
- ✅ **V2 Chunking System:** Complete, tested, documented
- ✅ **V2 Search Tools:** FTS, semantic, file query with JSON output
- ✅ **Database Schema:** V2 schema ready for deployment
- ✅ **Legacy V1 System:** Preserved in `file_metadata_content.py`
- ✅ **Clean Repository:** Proper git hygiene, comprehensive .gitignore
- ✅ **Complete Documentation:** Architecture, usage, migration guides

### File Organization:
```
~/src/file_metadata_and_embeddings/
├── Core V2 System
│   ├── chunking_refactor.py
│   ├── chunk_db_integration.py
│   ├── schema_refactor.sql
│   └── test_chunking_refactor.py
├── V2 Tools
│   └── tools_v2/ (7 files)
├── Legacy V1
│   └── file_metadata_content.py
├── Configuration
│   ├── requirements.txt
│   ├── requirements_mcp.txt
│   ├── LICENSE.txt
│   └── .gitignore
└── Documentation
    ├── CLAUDE.md
    └── claude_breadcrumbs.md (this file)
```

### Research Resources:
User collected MCP reference materials in old repo at `/Users/mark/src/file_metadata_tool/research/`:
- `chat_gpt_explains_tools_and_mcp_with_examples.md`
- `gemini_simple_list_pythonic_mcp_client_mcp_trouble_shooting.md`

## Key Lessons Learned

### Technical Insights:
1. **Chunking Strategy Matters:**
   - Discrete chunks (no overlap) work better for code than sliding windows
   - ~350 chars balances coherence, embedding limits, and search quality
   - Paragraph boundaries are natural semantic units for prose

2. **JSONB Envelopes Enable AI Consumption:**
   - Complete metadata in each chunk enables intelligent retrieval
   - Adjacency hints let AI agents request context expansively
   - Self-contained envelopes simplify integration patterns

3. **Dual Storage Architecture:**
   - SQL columns for fast queries (file_path, chunk_index)
   - JSONB documents for complete AI consumption
   - Best of both worlds: performance and flexibility

4. **MCP Adoption Status (2025):**
   - Anthropic (Claude) has native support
   - Ollama requires bridges/clients (ollmcp, ollama-mcp-bridge)
   - Function calling capability is prerequisite
   - Bridge tools have terminal compatibility quirks

5. **Local AI Architecture:**
   - Shared backend, multiple interfaces works well
   - MCP + Apple Intents is viable dual approach
   - Standard compliance > custom solutions
   - Ollama API + MCP tools + custom layer = powerful local AI

### Process Insights:
1. **Context Management:** Critical for both human and AI productivity
2. **Scope Discipline:** Avoid tinkering rabbit holes without explicit user request
3. **Documentation Value:** Breadcrumbs enable session continuity and prevent repeated mistakes
4. **Research First:** Understand ecosystem before implementing
5. **Git Hygiene:** Clean repos prevent pollution, make progress visible
6. **Test Everything:** Comprehensive tests catch issues early
7. **Version Thoughtfully:** V1 → V2 migration shows clear evolution

## Next Steps

### Immediate (This Session):
1. ✅ Create clean project directory
2. ✅ Migrate V2 code
3. ✅ Initialize git repository
4. ✅ Create .gitignore
5. ✅ Update CLAUDE.md and breadcrumbs
6. ⏳ Create README.md
7. ⏳ Initial git commit

### Short Term (Following Sessions):
1. **MCP Integration:** Integrate V2 tools with MCP server
2. **Ollama API Integration:** Build custom layer (streaming + MCP tool access)
3. **Context Management:** Implement sliding context windows, session continuity
4. **Tool Expansion:** Add more MCP tools (metadata queries, batch operations)

### Medium Term:
1. **Apple Intents Research:** Plan dual-interface architecture (MCP + Intents)
2. **Performance Optimization:** Improve search response times
3. **Tool Composition:** Enable MCP tools to call each other
4. **Embedding Generation:** Integrate embedding generation into V2 pipeline

### Long Term:
1. **Multi-Interface Architecture:** MCP (LLMs) + Apple Intents (voice/mobile)
2. **Advanced Context Management:** Intent preservation, workflow continuity
3. **Local Knowledge Injection:** Intelligent context window management
4. **Production Deployment:** Stable, documented, maintainable system

## Architecture Vision

```
File Metadata Backend (V2)
    ↓
┌──────────────────────────────────────────────────┐
│  Shared Database & Core Logic                    │
│  - JSONB chunk storage                           │
│  - Multiple search modes (FTS, semantic, topical)│
│  - Context-aware retrieval                       │
└──────────────────┬───────────────────────────────┘
                   ↓
    ┌──────────────┴──────────────┐
    ↓                              ↓
┌───────────────┐          ┌──────────────────┐
│  MCP Tools    │          │  Apple Intents   │
│  (for LLMs)   │          │  (for Shortcuts) │
│               │          │                  │
│  - Ollama API │          │  - Voice         │
│  - gpt-oss    │          │  - Mobile        │
│  - Streaming  │          │  - Automation    │
└───────────────┘          └──────────────────┘
```

**Design Principle:** Keep it simple, local, and inventive with your own resources.

## Partnership Notes

**What Works Well:**
- Clear architecture discussions
- Focusing on standards (MCP) over custom solutions
- User directing experience and maintaining context
- Documentation-first approach
- Version management (V1 → V2 evolution)
- Git hygiene and clean repositories

**What to Improve:**
- Avoid tinkering detours without explicit user request
- Research compatibility before implementation
- Stay focused on stated goals
- Use breadcrumbs to maintain continuity
- Commit meaningful work regularly

---
*Last updated: Oct 6, 2025 - Clean repository established with V2 refactoring complete*
