# CLAUDE.md

A pre-indexed knowledge base of your local files, exposed as MCP tools. **Use it before grep/find/glob when you need to search across projects by meaning, topic, or content.**

## When to use which tool

| You want to... | Tool | Example |
|---|---|---|
| Find files **about** a concept (meaning, not exact words) | `semantic_search` | "context management", "authentication flow" |
| Find files **containing** exact text or phrases | `full_text_search` | `"context management"`, `python AND async` |
| Find files where a term is **statistically important** (not just mentioned) | `search_by_keywords` | Files *about* "context" vs files that just mention it |
| Find files by **name, type, date, size** | `search_files` | All `.py` files modified since 2026-01-01 |
| Understand a **specific file's** content profile | `get_file_info` | Keywords, topics, chunk count, metadata |
| Read a file's **actual content** via chunks | `get_file_chunks` | Read indexed content without filesystem access |
| Explore **directory structure** of indexed files | `list_directories` | Where are files concentrated? |
| Get an **overview** of what's indexed | `get_stats` | Total files, types, sizes, FAISS status |

## Search mode comparison

- **`semantic_search`** — meaning-based (FAISS embeddings). Finds conceptual matches even with different wording. Best for open-ended exploration.
- **`full_text_search`** — exact/phrase/boolean (FTS5). Best when you know what words to look for. Supports `"exact phrase"`, `AND`, `OR`, `NOT`.
- **`search_by_keywords`** — TF-IDF statistical importance. Best for finding files *about* a topic vs files that merely mention it.
- **`search_files`** — metadata only (no content search). Best for filtering by file type, date, size, or name pattern.

**Example: finding "context management" projects**

- `semantic_search("context management for AI sessions")` — finds conceptual matches even if files say "session continuity" or "conversation history"
- `full_text_search('"context management"')` — finds files with that exact phrase
- `search_by_keywords(["context", "management"])` — finds files where these are statistically important terms

Combine modes: semantic for discovery, then full-text to confirm.

## Knowledge Graph / Autograph tools

These tools form a learning loop that improves source suggestions over time:

- **`log_autograph`** — record which sources were useful in what context
- **`query_autographs`** — find patterns from past grounding decisions
- **`autograph_suggest`** — get suggestions based on learned patterns
- **`autograph_stats`** — check KG health and bootstrap phase (Cold/Learning/Warm/Hot)

## What's indexed

- **Database:** `~/data/file_metadata.sqlite3`
- **Check what's indexed:** `get_stats` returns total files, types, sizes, and FAISS index status
- **FAISS index** may need rebuilding after adding many new files

## Tips

- Use `get_file_info` to understand a file's topic profile before diving into its content
- `list_directories` with a parent path scopes exploration to a subtree
- `get_file_chunks` with a specific chunk index retrieves just the part you need
- When a semantic search returns surprising results, check `get_file_info` on the match to see why it was relevant
