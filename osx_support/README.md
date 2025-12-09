# File Search - Native macOS Semantic Search

Native macOS implementation of semantic file search with Apple Intents integration.

## Vision

Take proven Python V2 semantic search architecture and implement natively in Swift/C++ for production-quality macOS integration. Expose search capabilities via Apple Intents for Siri and Spotlight.

**Why:** Apple Intelligence can use semantic search as a tool through Intents.

## Status

**v0 Development** - Skeleton implementation, not production ready.

See [STATUS.md](STATUS.md) for current reality.

## Architecture

```
User's Files
    ↓
Background Indexer (Swift) → Embeddings → SQLite + FAISS
    ↓
Apple Intents (Swift) → Siri/Shortcuts/Apple Intelligence
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for details.

## v0 Goals

- Index 200,000 files
- Native semantic search (<100ms)
- Apple Intents integration
- Background processing (battery-aware)
- Self-contained .app bundle

## Components

### SQLite FAISS Extension (C++)
Native vector search via SQL functions. Statically linked FAISS for semantic similarity.

**Location:** `sqlite_faiss_extension/`

### Background Indexer (Swift)
Low-priority daemon for file monitoring and indexing.

**Location:** `background_indexer/`

### Apple Intents (Swift)
Expose search capabilities to Siri, Shortcuts, and Apple Intelligence.

**Location:** `intents/` (not yet implemented)

## Technology Choices

**Language:** Swift + C++
**Embeddings:** Core ML (all-MiniLM-L6-v2)
**Vector Search:** FAISS (statically linked)
**Database:** SQLite with custom extension
**Integration:** Apple Intents framework
**Build:** Xcode + source-built dependencies

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System design and Apple Intents integration
- [BUILD.md](BUILD.md) - Build instructions and dependencies
- [REQUIREMENTS.md](REQUIREMENTS.md) - v0 requirements and performance targets
- [STATUS.md](STATUS.md) - Current implementation status

## Quick Start

See [BUILD.md](BUILD.md) for complete instructions.

```bash
# Build dependencies from source (one-time)
./scripts/build_dependencies.sh

# Build project
cd osx_support
make

# Test
make test
```

## Related Work

This builds on the Python V2 system in the parent directory, which proves:
- Chunking strategy (350 char code, 800 char prose)
- Embedding generation works
- FAISS search is effective
- Architecture is sound

The native implementation brings this to production quality with Apple ecosystem integration.

## License

See [LICENSE.txt](../LICENSE.txt)
