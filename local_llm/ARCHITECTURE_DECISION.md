# Local LLM Integration - Architecture Decision

**Date**: October 6, 2025
**Status**: Design Phase
**Decision Owner**: Mark

## Context

We have a working V2 file metadata and embeddings system with MCP-compatible tools. We want to integrate this with local LLMs (specifically gpt-oss:20b via Ollama) to create a powerful local AI assistant with file search capabilities.

**Key Requirements:**
- No terminal compatibility issues or tinkering
- Clean integration with Ollama
- Streaming support for responsive UX
- Custom context management (sliding windows, session continuity)
- Standard MCP protocol compliance
- Local-first architecture (no cloud dependencies)

## Research Summary

From `research/gemini_simple_list_pythonic_mcp_client_mcp_trouble_shooting.md`, we evaluated four MCP client options:

### Option 1: ollmcp (mcp-client-for-ollama)
**Type**: TUI (Text-based User Interface)

**Pros:**
- Multi-server MCP support
- Dynamic model switching
- Human-in-the-loop safety controls
- Advanced configuration

**Cons:**
- Terminal compatibility issues (experienced in testing)
- Less control over UX and context management
- Not designed for programmatic use

**Verdict**: ❌ Not suitable - terminal issues, limited customization

### Option 2: Ollama MCP Bridge ⭐ SELECTED
**Type**: FastAPI-based proxy

**Pros:**
- Sits between any Ollama client and Ollama server
- Automatically adds tool definitions from MCP servers
- Seamless integration - no client code changes needed
- Handles streaming responses
- Intercepts `/api/chat` transparently
- Well-architected separation of concerns

**Cons:**
- Adds another process to manage
- Potential performance overhead (minimal)

**Verdict**: ✅ **SELECTED** - Best fit for our requirements

### Option 3: Ollamaton
**Type**: Universal client (CLI + API + GUI)

**Pros:**
- Cross-platform
- Multiple interface options
- Auto-discovers configs

**Cons:**
- Opinionated UI - less control over UX
- Heavier weight than needed
- May conflict with custom context management

**Verdict**: ❌ Too opinionated for our needs

### Option 4: MCPJam
**Type**: Testing/debugging tool

**Pros:**
- Good for MCP server validation
- LLM playground

**Cons:**
- Not designed for production use
- Testing-focused, not integration-focused

**Verdict**: 🔧 Useful for testing, not for production

## Selected Architecture: Ollama MCP Bridge

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  Custom Python Client (Your Interface Layer)                │
│  - Streaming chat interface                                 │
│  - Context window management (sliding windows)              │
│  - Session continuity (breadcrumbs pattern)                 │
│  - User intent preservation                                 │
│  - Custom UX/UI (CLI, web, or other)                        │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
                  Ollama API (HTTP)
                  POST /api/chat
                  (standard Ollama protocol)
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Ollama MCP Bridge (FastAPI Proxy)                          │
│  - Intercepts /api/chat requests                            │
│  - Injects tool definitions from connected MCP servers      │
│  - Executes tool calls when LLM requests them               │
│  - Merges tool results back into streaming response         │
│  - Transparent to client (looks like normal Ollama)         │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
            ┌──────────────┴───────────────┐
            ↓                              ↓
   ┌────────────────────┐      ┌──────────────────────────┐
   │  Ollama Server     │      │  MCP Servers             │
   │  (Local LLM)       │      │  (Tool Providers)        │
   │                    │      │                          │
   │  - gpt-oss:20b     │      │  - file_search_server    │
   │  - llama3          │      │    (V2 FTS search)       │
   │  - other models    │      │  - semantic_search       │
   │                    │      │    (V2 embeddings)       │
   │                    │      │  - file_metadata         │
   │                    │      │    (V2 queries)          │
   └────────────────────┘      └──────────────────────────┘
```

### Data Flow Example

**User Query:** "Find files about authentication"

1. **User → Custom Client**
   - User types query in your interface
   - Client adds context from session history

2. **Custom Client → Bridge**
   - `POST http://localhost:8000/api/chat`
   - Standard Ollama chat request with streaming

3. **Bridge → MCP Servers**
   - Bridge queries connected MCP servers for available tools
   - Receives tool definitions: `search_files`, `full_text_search`, `semantic_search`

4. **Bridge → Ollama**
   - Injects tool definitions into chat request
   - Sends augmented request to Ollama server

5. **Ollama → Bridge**
   - LLM decides to use `full_text_search` tool
   - Returns tool call in streaming response

6. **Bridge → MCP Server**
   - Executes `full_text_search("authentication")`
   - Receives JSON results from V2 FTS tool

7. **Bridge → Ollama**
   - Sends tool results back to LLM
   - LLM processes results and generates response

8. **Bridge → Custom Client**
   - Streams final response back
   - Looks like normal Ollama response

9. **Custom Client → User**
   - Displays response with formatting
   - Updates context window
   - Maintains session continuity

## Key Design Decisions

### Decision 1: Use Ollama MCP Bridge (Not TUI clients)

**Rationale:**
- Separates concerns: Ollama API ↔ MCP protocol ↔ Your tools
- No terminal compatibility issues (we control the client)
- Transparent to our client code (standard Ollama API)
- Handles complexity (tool injection, execution, response merging)

**Trade-off:**
- Extra process to manage (bridge runs separately)
- Worth it: Clean separation, standard protocols, no compatibility hacks

### Decision 2: Custom Python Client (Not pre-built UIs)

**Rationale:**
- Full control over UX and context management
- Can implement sliding context windows
- Session continuity via breadcrumbs pattern
- Choose interface style (CLI, web, hybrid)
- Ollama API is simple HTTP - easy to use directly

**Trade-off:**
- More initial work to build client
- Worth it: Exactly the UX we want, no compromises

### Decision 3: Standard Ollama API (Not custom protocols)

**Rationale:**
- Well-documented, stable API
- Streaming support built-in
- Works with any Ollama model
- Bridge sits transparently in front

**Trade-off:**
- None - this is the right layer to integrate at

### Decision 4: V2 Tools via MCP (Not direct integration)

**Rationale:**
- MCP provides standard tool protocol
- Tools remain independent and testable
- Can be reused for other integrations (Apple Intents)
- Future-proof architecture

**Trade-off:**
- Need to maintain MCP server implementations
- Worth it: Clean architecture, multiple uses

## Implementation Phases

### Phase 1: Foundation (Current)
**Status:** ✅ Complete
- V2 file metadata and chunking system
- V2 search tools (FTS, semantic, file query)
- Working MCP server (`mcp_server_fixed.py` from old repo)
- Clean git repository

### Phase 2: MCP Bridge Setup (Next)
**Status:** 🚧 Planning
- Install/setup Ollama MCP Bridge
- Configure bridge to connect to our MCP servers
- Update/enhance MCP server to expose all V2 tools
- Test tool execution through bridge

### Phase 3: Basic Client (After Bridge)
**Status:** 📋 Planned
- Simple Python client using Ollama API
- Streaming chat interface (terminal-based initially)
- Basic context management
- Verify end-to-end flow

### Phase 4: Context Management (Enhancement)
**Status:** 📋 Planned
- Sliding context windows
- Session continuity
- User intent preservation
- CLAUDE.md-style context injection

### Phase 5: Production Polish (Future)
**Status:** 💭 Future
- Error handling and recovery
- Configuration management
- Multiple model support
- Performance optimization
- Optional web UI

## Technical Specifications

### Ollama API Endpoint
```
POST http://localhost:11434/api/chat
```

### Bridge Endpoint (After setup)
```
POST http://localhost:8000/api/chat
(Bridge proxy in front of Ollama)
```

### MCP Server Configuration
**Location:** TBD (likely `local_llm/mcp_config.json`)

**Format:**
```json
{
  "mcpServers": {
    "file-search": {
      "command": "python",
      "args": ["/path/to/mcp_server.py"],
      "env": {}
    }
  }
}
```

### V2 Tools to Expose
1. **full_text_search** - FTS5 search across chunks
2. **semantic_search** - Embedding-based similarity search
3. **file_metadata_query** - Query files by metadata
4. **get_chunk_context** - Retrieve adjacent chunks for context

## Success Criteria

### Must Have
- ✅ LLM can search files via natural language
- ✅ Streaming responses work smoothly
- ✅ Tool execution is transparent to user
- ✅ Standard Ollama API compatibility

### Should Have
- ⭐ Context window management working
- ⭐ Session continuity preserved
- ⭐ Multiple tools composable
- ⭐ Error handling graceful

### Nice to Have
- 💡 Web UI option
- 💡 Multiple model switching
- 💡 Advanced context strategies
- 💡 Voice interface via Apple Intents

## Risks and Mitigations

### Risk 1: Bridge performance overhead
**Mitigation:** Bridge is FastAPI (async) - minimal overhead expected. Can benchmark.

### Risk 2: gpt-oss:20b function calling capability
**Mitigation:** Previous testing showed promising signs. Can test thoroughly before committing.

### Risk 3: MCP server stability
**Mitigation:** Our `mcp_server_fixed.py` already validated. Start with simple tools, expand gradually.

### Risk 4: Context window management complexity
**Mitigation:** Start simple (fixed window), iterate based on experience.

## References

- **Research Document:** `research/gemini_simple_list_pythonic_mcp_client_mcp_trouble_shooting.md`
- **Ollama API Docs:** https://github.com/ollama/ollama/blob/main/docs/api.md
- **Ollama MCP Bridge:** https://github.com/QuantGeekDev/ollama-mcp-bridge
- **MCP Specification:** https://modelcontextprotocol.io/
- **Project Breadcrumbs:** `claude_breadcrumbs.md`

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2025-10-06 | Selected Ollama MCP Bridge architecture | Best separation of concerns, standard protocols, no terminal issues |
| 2025-10-06 | Custom Python client over pre-built UIs | Full control over context management and UX |
| 2025-10-06 | V2 tools via MCP protocol | Standard integration, reusable architecture |

---

**Next Steps:**
1. Set up Ollama MCP Bridge
2. Configure bridge with our MCP server
3. Build simple Python client for testing
4. Validate end-to-end flow
5. Iterate on context management

**Status:** Architecture documented, ready to proceed with implementation.
