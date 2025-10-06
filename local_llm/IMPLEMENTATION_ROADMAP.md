# Local LLM Integration - Implementation Roadmap

**Project**: File Metadata and Embeddings + Ollama + MCP
**Last Updated**: October 6, 2025
**Status**: Phase 1 Complete, Planning Phase 2

## Overview

This roadmap tracks implementation of the Ollama MCP Bridge architecture documented in `ARCHITECTURE_DECISION.md`.

**Goal:** Create a local AI assistant powered by Ollama (gpt-oss:20b) with seamless access to our V2 file search tools via MCP.

## Phase 1: Foundation ✅ COMPLETE

**Timeline:** Completed October 6, 2025
**Status:** ✅ All objectives met

### Objectives
- [x] V2 chunking system with AI-optimized envelopes
- [x] V2 search tools (FTS, semantic, file query)
- [x] Clean git repository with proper structure
- [x] Comprehensive documentation
- [x] Architecture decision documented

### Deliverables
- `chunking_refactor.py` - AI-optimized chunker
- `chunk_db_integration.py` - JSONB database operations
- `schema_refactor.sql` - V2 database schema
- `tools_v2/` - Three search tools with JSON output
- `test_chunking_refactor.py` - Test suite (all passing)
- `local_llm/ARCHITECTURE_DECISION.md` - This roadmap

### Success Metrics
- ✅ All tests passing
- ✅ Tools return structured JSON
- ✅ Documentation complete
- ✅ Git repository clean

## Phase 2: MCP Bridge Setup 🚧 IN PLANNING

**Timeline:** TBD (estimated 1-2 sessions)
**Status:** 🚧 Planning phase

### Objectives
- [ ] Install and configure Ollama MCP Bridge
- [ ] Create/update MCP server for V2 tools
- [ ] Test bridge connectivity with Ollama
- [ ] Verify tool execution through bridge
- [ ] Document configuration and setup

### Tasks

#### Task 2.1: Install Ollama MCP Bridge
**Priority:** High
**Estimated Effort:** 30 minutes

**Steps:**
1. Research Ollama MCP Bridge repository (GitHub: QuantGeekDev/ollama-mcp-bridge)
2. Install bridge dependencies
3. Verify Ollama is running locally
4. Start bridge and test basic connectivity

**Acceptance Criteria:**
- Bridge responds to `/api/chat` endpoint
- Bridge can proxy to Ollama successfully
- Basic chat works through bridge (no tools yet)

#### Task 2.2: Create MCP Server for V2 Tools
**Priority:** High
**Estimated Effort:** 2-3 hours

**Current State:**
- Have `mcp_server_fixed.py` from old repo (validated, working)
- Need to copy/adapt for V2 tools

**Steps:**
1. Copy `mcp_server_fixed.py` from old repo to `local_llm/`
2. Review and update for V2 tool integration
3. Add V2 FTS search tool (`find_using_fts_v2.py`)
4. Add V2 semantic search tool (optional - requires embeddings)
5. Add V2 file metadata query tool
6. Add chunk context retrieval tool
7. Test MCP server independently (using test client)

**Tools to Expose:**
```python
tools = [
    {
        "name": "full_text_search",
        "description": "Search file content using full-text search (FTS5)",
        "parameters": {
            "query": "string - search query",
            "limit": "integer - max results (default 10)",
            "context": "integer - include N adjacent chunks (default 0)"
        }
    },
    {
        "name": "file_metadata_query",
        "description": "Query files by metadata (path, name, type)",
        "parameters": {
            "file_path": "string - optional file path pattern",
            "file_type": "string - optional file extension",
            "chunks": "boolean - include chunk list"
        }
    },
    {
        "name": "get_chunk_context",
        "description": "Retrieve chunk with surrounding context",
        "parameters": {
            "file_path": "string - file path",
            "chunk_index": "integer - chunk index",
            "context": "integer - adjacent chunks to include"
        }
    }
]
```

**Acceptance Criteria:**
- MCP server starts without errors
- All V2 tools callable via MCP protocol
- Tools return proper JSON envelopes
- Independent testing passes

#### Task 2.3: Configure Bridge with MCP Server
**Priority:** High
**Estimated Effort:** 1 hour

**Steps:**
1. Create `local_llm/mcp_config.json`
2. Configure bridge to connect to our MCP server
3. Start MCP server
4. Start bridge with config
5. Verify bridge sees available tools

**Configuration Structure:**
```json
{
  "mcpServers": {
    "file-search": {
      "command": "python",
      "args": ["local_llm/mcp_server.py"],
      "env": {
        "DATABASE_PATH": "/Users/mark/data/file_metadata.sqlite3"
      }
    }
  }
}
```

**Acceptance Criteria:**
- Bridge starts with config
- Bridge lists tools from MCP server
- No connection errors in logs

#### Task 2.4: End-to-End Tool Execution Test
**Priority:** High
**Estimated Effort:** 1 hour

**Steps:**
1. Send test request to bridge with tool-using prompt
2. Verify bridge forwards request to Ollama
3. Verify Ollama decides to use tool
4. Verify bridge executes tool via MCP
5. Verify bridge returns tool results to Ollama
6. Verify Ollama processes results and responds
7. Document any issues or quirks

**Test Prompts:**
```
"Search for files about authentication"
"Find Python files that contain the word 'database'"
"What files are in my Documents folder?"
```

**Acceptance Criteria:**
- At least one test prompt successfully uses a tool
- Tool results appear in LLM response
- Streaming works smoothly
- No errors in bridge or MCP server logs

### Deliverables
- [ ] `local_llm/mcp_server.py` - MCP server with V2 tools
- [ ] `local_llm/mcp_config.json` - Bridge configuration
- [ ] `local_llm/BRIDGE_SETUP.md` - Setup instructions
- [ ] Test results documented

### Success Metrics
- Bridge proxies Ollama API successfully
- MCP server exposes V2 tools
- End-to-end tool execution works
- Documentation complete for setup

## Phase 3: Basic Python Client 📋 PLANNED

**Timeline:** TBD (estimated 2-3 sessions)
**Status:** 📋 Planned

### Objectives
- [ ] Simple Python client using Ollama API
- [ ] Streaming chat interface (terminal-based)
- [ ] Basic context management
- [ ] User-friendly error handling
- [ ] Session persistence (optional)

### Tasks

#### Task 3.1: Minimal Client Prototype
**Priority:** High
**Estimated Effort:** 2 hours

**Steps:**
1. Create `local_llm/client.py`
2. Implement Ollama API `/api/chat` integration
3. Add streaming response handling
4. Basic prompt/response loop
5. Test with and without tools

**Features:**
- Send message to Ollama via bridge
- Stream response to terminal
- Handle tool calls transparently
- Simple REPL interface

#### Task 3.2: Context Window Management
**Priority:** Medium
**Estimated Effort:** 3 hours

**Steps:**
1. Implement sliding context window
2. Store last N messages
3. Inject context into each request
4. Handle context size limits
5. Add context summarization (optional)

**Design Pattern:**
```python
class ContextManager:
    def __init__(self, max_messages=10):
        self.history = []
        self.max_messages = max_messages

    def add_message(self, role, content):
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.max_messages:
            self.history = self.history[-self.max_messages:]

    def get_context(self):
        return self.history
```

#### Task 3.3: User Experience Polish
**Priority:** Medium
**Estimated Effort:** 2 hours

**Features:**
- Colored output (user vs assistant vs system)
- Loading indicators during tool execution
- Error handling with helpful messages
- `/help`, `/clear`, `/exit` commands
- Optional: save/load sessions

### Deliverables
- [ ] `local_llm/client.py` - Basic chat client
- [ ] `local_llm/context_manager.py` - Context management
- [ ] `local_llm/CLIENT_USAGE.md` - User guide
- [ ] Demo session recording

### Success Metrics
- Client connects to bridge successfully
- Streaming works smoothly
- Context preserved across messages
- Tool execution transparent to user
- User experience is pleasant

## Phase 4: Advanced Context Management 📋 PLANNED

**Timeline:** TBD (estimated 3-4 sessions)
**Status:** 📋 Planned - Experimental Phase

### Objectives
- [ ] Implement breadcrumbs pattern for sessions
- [ ] User intent preservation
- [ ] CLAUDE.md-style project context injection
- [ ] Advanced context strategies (summarization, relevance)
- [ ] Multi-session management

### Research Areas
1. **Context Injection Patterns**
   - When to inject project context (CLAUDE.md)?
   - How to maintain user intent across sessions?
   - Breadcrumbs format for LLM consumption?

2. **Context Strategies**
   - Fixed window vs sliding window vs summarization?
   - Relevance scoring for context selection?
   - Token budget management?

3. **Session Continuity**
   - Save/load conversation state?
   - Cross-session context sharing?
   - Session summaries for long conversations?

### Tasks (To be defined)
- Research best practices for context management
- Prototype different strategies
- Evaluate effectiveness with real usage
- Document patterns that work

### Success Metrics
- Sessions maintain continuity naturally
- User intent preserved across conversations
- Context injection improves responses
- No context overflow issues

## Phase 5: Production Polish 💭 FUTURE

**Timeline:** TBD
**Status:** 💭 Future consideration

### Potential Features
- [ ] Web UI option (Flask/FastAPI frontend)
- [ ] Multiple model support (switching between models)
- [ ] Advanced error handling and recovery
- [ ] Configuration management system
- [ ] Performance optimization and caching
- [ ] Usage analytics and logging
- [ ] Integration with Apple Intents (voice/mobile)

### To Be Determined
- Priority of features
- Implementation approach
- Timeline and effort

## Dependencies

### External Tools
- **Ollama**: Must be installed and running (`ollama serve`)
- **Ollama MCP Bridge**: GitHub repo (QuantGeekDev/ollama-mcp-bridge)
- **Python 3.7+**: For all our code
- **SQLite3**: For database (already installed on macOS)

### Internal Components
- V2 chunking system (complete)
- V2 search tools (complete)
- Database with processed files (may need initial population)
- MCP server implementation (to be created in Phase 2)

### Optional
- FAISS: For semantic search (if using embeddings)
- sentence-transformers: For embeddings generation

## Risk Management

### Known Risks

#### Risk 1: gpt-oss:20b function calling capability
**Impact:** High (core functionality)
**Probability:** Medium (showed promise in testing)
**Mitigation:**
- Test thoroughly in Phase 2
- Have fallback models ready (llama3, mistral)
- Document model requirements

#### Risk 2: Bridge performance overhead
**Impact:** Low (UX concern)
**Probability:** Low (FastAPI is fast)
**Mitigation:**
- Benchmark in Phase 2
- Profile if needed
- Direct integration fallback option

#### Risk 3: Context management complexity
**Impact:** Medium (affects UX quality)
**Probability:** Medium (new territory)
**Mitigation:**
- Start simple (fixed window)
- Iterate based on real usage
- Research proven patterns

#### Risk 4: Tool execution reliability
**Impact:** High (core functionality)
**Probability:** Low (V2 tools already tested)
**Mitigation:**
- Comprehensive error handling
- Tool timeout management
- Graceful degradation

## Success Criteria (Overall Project)

### Must Have ✅
- [ ] LLM can search files via natural language
- [ ] Tool execution is transparent to user
- [ ] Streaming responses work smoothly
- [ ] Basic context management working
- [ ] Standard Ollama API compatibility maintained

### Should Have ⭐
- [ ] Session continuity preserved
- [ ] Multiple tools composable
- [ ] Error handling graceful
- [ ] Documentation complete
- [ ] Easy to set up and use

### Nice to Have 💡
- [ ] Web UI option
- [ ] Advanced context strategies
- [ ] Multiple model switching
- [ ] Voice interface (Apple Intents)
- [ ] Usage analytics

## Next Immediate Actions

1. **Copy MCP server from old repo** - Get `mcp_server_fixed.py` into `local_llm/`
2. **Research Ollama MCP Bridge** - Find GitHub repo, read docs
3. **Install bridge locally** - Get it running with basic test
4. **Update MCP server** - Integrate V2 tools
5. **Test end-to-end** - Validate architecture works

## Documentation Standards

All work should maintain:
- **ARCHITECTURE_DECISION.md** - Updated with new decisions
- **IMPLEMENTATION_ROADMAP.md** - This file, updated as we progress
- **claude_breadcrumbs.md** - Session notes and lessons learned
- **CLAUDE.md** - Project context for AI assistant
- Code comments explaining design decisions
- Setup/usage documentation for each component

## Review Schedule

- **After Phase 2:** Validate architecture decision, adjust if needed
- **After Phase 3:** Evaluate UX, gather feedback, iterate
- **After Phase 4:** Assess context management effectiveness
- **Before Phase 5:** Re-evaluate priorities and goals

---

**Current Phase:** Phase 2 Planning
**Next Milestone:** MCP Bridge Setup Complete
**Estimated Completion:** TBD (2-3 weeks total for Phases 2-3)

**Status:** Ready to begin Phase 2 when user is ready.
