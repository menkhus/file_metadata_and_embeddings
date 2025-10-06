# Local LLM Integration

This directory contains design decisions, implementation plans, and code for integrating our V2 file metadata and embeddings system with local LLMs via Ollama and MCP.

## Contents

### Design Documentation
- **[ARCHITECTURE_DECISION.md](ARCHITECTURE_DECISION.md)** - Selected architecture: Ollama MCP Bridge approach
- **[IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md)** - Phased implementation plan with tasks and timelines

### Implementation (Coming Soon)
- `mcp_server.py` - MCP server exposing V2 tools
- `client.py` - Python client for chat interface
- `context_manager.py` - Context window management
- `mcp_config.json` - Bridge configuration

## Quick Links

**Current Phase:** Phase 2 Planning - MCP Bridge Setup

**Selected Architecture:** Ollama MCP Bridge
- Custom Python client → Bridge (FastAPI proxy) → Ollama + MCP servers

**Key Decision Factors:**
- No terminal compatibility issues
- Standard Ollama API
- Full control over context management
- Clean separation of concerns

## Getting Started

1. **Read the architecture decision**: [ARCHITECTURE_DECISION.md](ARCHITECTURE_DECISION.md)
2. **Review the roadmap**: [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md)
3. **Follow Phase 2 tasks** when ready to implement

## Architecture Overview

```
Your Custom Client (Python)
    ↓
Ollama API (/api/chat)
    ↓
Ollama MCP Bridge (FastAPI Proxy)
    ↓
Ollama Server + MCP Servers (V2 Tools)
```

## Goals

- **Local-first**: No cloud dependencies
- **Clean integration**: Standard protocols (Ollama API, MCP)
- **Context-aware**: Sliding windows, session continuity
- **User-friendly**: Streaming responses, transparent tool execution

## Status

- ✅ Phase 1: Foundation Complete (V2 system with tools)
- 🚧 Phase 2: MCP Bridge Setup (Planning)
- 📋 Phase 3: Basic Client (Planned)
- 📋 Phase 4: Advanced Context Management (Planned)
- 💭 Phase 5: Production Polish (Future)

See [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) for details.
