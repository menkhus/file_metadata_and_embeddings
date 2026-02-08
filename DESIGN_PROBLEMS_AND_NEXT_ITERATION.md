# Design Problems & Next Iteration

**Date:** 2026-02-07
**Status:** Active design discussion
**Context:** After a session that validated the MCP's effectiveness (see CASE_STUDY_MCP_EFFECTIVENESS.md), these are the architectural problems standing between "it works" and "it works reliably."

## The Success

The file_metadata MCP server, when warm and persistent, dramatically outperforms grep/glob/find for cross-project codebase exploration. A session exploring 40K files across 65 directories required ~12 MCP calls instead of an estimated 50-80 grep/find/read calls, with better results — full concept tracing, timeline reconstruction, architectural understanding.

See: `CASE_STUDY_MCP_EFFECTIVENESS.md` for the full case study.

## Problem 1: The Last Mile Is Not the API

The hardest problem isn't technical. It's **AI tool preference formation**.

### What happened in the 2026-02-07 session

1. Claude started with `ls` and `bash` — the defaults
2. User nudged: "perhaps use the file_metadata tool too"
3. Claude tried `list_directories` + `get_stats` — got structural awareness in one call
4. Claude tried `get_file_info` — got TF-IDF keywords without reading files
5. Claude tried `full_text_search` — got 50 matches with snippets in one call
6. From that point forward, Claude **preferentially chose the MCP over grep/glob** without being asked

The tool earned preference through results. Within 3 queries, the AI agent recognized that the MCP returned *meaning* (keywords, snippets, metadata, timestamps) while grep returned *data* (matching lines). The agent independently chose meaning over data for the rest of the session.

### The implication

The API works. The data structures work. The search works. But none of that matters if the AI agent never discovers that the tool is better than its built-in alternatives. The adoption curve is:

```
1. Discovery    — "This tool exists" (CLAUDE.md, tool listing)
2. First use    — "Let me try it" (often requires human nudge)
3. Comparison   — "This returned more than grep would have"
4. Preference   — "I'll reach for this first next time"
5. Integration  — "This is how I explore codebases now"
```

Most AI tool development focuses on making step 1 work (better descriptions, better schemas). The real leverage is in **making step 3 undeniable** — the results need to be so obviously better that the AI agent forms a preference after 2-3 uses.

### What makes step 3 work

The MCP succeeds at step 3 because each response carries multiple dimensions of information:
- File paths (same as grep)
- Modification dates (grep doesn't provide this)
- File sizes (grep doesn't provide this)
- Text snippets with context (grep provides this, but without the metadata)
- TF-IDF keywords (grep can't do this at all)
- Directory-level aggregations (grep can't do this at all)

The AI agent doesn't need to be told this is better. It can *see* that a single `full_text_search` call returned enough to trace a concept across 6 projects — something that would have taken dozens of grep + read cycles.

### Design principle

**Optimize for the AI's "oh shit" moment.** Every tool response should carry enough context that the AI agent can compare it favorably to what grep/glob would have returned. Rich metadata is not a luxury — it's what drives tool adoption.

## Problem 2: Cold Start vs. Persistence

### The problem

Loading sentence-transformers and a 187K-vector FAISS index on every MCP invocation is slow. This was identified during work with Gemini — the activation overhead made the tool feel sluggish, undermining the responsiveness that drives adoption (Problem 1).

### The current solution

Run the MCP server as a persistent process. Start it once, let it stay warm. Semantic search becomes near-instant because the model and index are already in memory.

### Why this works

- FAISS index loads once, subsequent searches are pure vector math
- Sentence transformer loads once, subsequent embeddings are fast inference
- SQLite connections stay warm
- The tool feels responsive enough to invite deeper exploration (which is exactly what happened in the case study session)

## Problem 3: Index Freshness / Lifecycle

### The problem

Persistence creates a cache lifecycle problem. The index represents a point-in-time snapshot:

- **New files** created after indexing are invisible
- **Modified files** have stale chunks, keywords, and embeddings
- **Deleted files** return ghost results
- **Moved/renamed files** appear as both ghosts and gaps

The more the tool is trusted (Problem 1 solved), the more freshness matters. If the AI agent makes decisions based on stale data, trust erodes.

### Dimensions of the problem

| What changed | Impact | Detection difficulty |
|---|---|---|
| New file created | Missing from all searches | Easy (file exists, not in DB) |
| File content modified | Stale snippets, wrong keywords, bad embeddings | Medium (compare file hash) |
| File deleted | Ghost results, broken references | Easy (DB entry, no file) |
| File moved/renamed | Ghost at old path + missing at new path | Hard (looks like delete + create) |
| New directory tree | Entire subtree invisible | Easy (directory not in DB) |

### Possible approaches

**1. Scheduled re-index (cron)**
- Simple, predictable
- Wasteful for large stable corpora (the exploit DB doesn't change)
- Gap between changes and visibility

**2. File system events (fswatch/watchman)**
- Near-real-time freshness
- Complex to implement reliably (especially across macOS quirks)
- Could trigger too many re-indexes during active development

**3. On-demand selective re-index**
- User or AI triggers re-index of specific directories
- Minimal wasted work
- Requires awareness of what's stale

**4. Hybrid: hash-check on query**
- When a file appears in search results, verify its hash against current file
- Flag stale results inline ("this file has changed since indexing")
- Lazy freshness — only checks what's actually being used
- Doesn't help with missing new files

**5. Git-aware differential indexing**
- Use `git status` / `git diff` to identify changed files
- Re-index only what git says changed
- Doesn't work for non-git directories
- Very efficient for active development repos

### Recommended approach

A combination: **git-aware differential for code repos** + **periodic full scan with hash comparison** for everything else. New directories should be detected on server startup. Stale results should be flagged, not silently served.

## Problem 4: Multi-AI Feature Collision

### The problem

Multiple AI assistants (Claude, Gemini, potentially others) work on the same project at different times, producing patches, plans, and code changes with no coordination. Example from this project:

- Gemini produced `gemini/cleanup.patch` (strips NLTK/LDA)
- Gemini produced `todo_plan_mcp_server_fixed.md` (FastAPI HTTP conversion)
- Claude is writing case studies and documentation
- Neither knows what the other did

### Why this matters here

The file_metadata MCP is a tool used BY AI agents. If multiple AI agents are also developing it, they need some form of shared state about what's in progress, what's been decided, and what's been rejected. Otherwise you get:

- Conflicting patches
- Redundant work
- Architectural decisions made without full context
- The human becomes the sole integration point (which doesn't scale)

### Current mitigation

The human (Mark) is the integration layer. This works for now but is exactly the problem that `ai_shell_and_agents_with_roles` (with its unified_handoff.py and mothership.py) was trying to solve.

### Future direction

This connects back to the project's own thesis: orchestration over intelligence. The coordination problem between AI agents working on the same codebase is an orchestration problem, not an intelligence problem. Each agent is smart enough — they just can't see each other's work.

---

## Summary

| Problem | Status | Severity |
|---|---|---|
| AI tool preference formation (last mile) | Validated — works when tool is responsive and results are rich | Solved in practice, needs design principles documented |
| Cold start latency | Solved — persistent server | Solved |
| Index freshness/lifecycle | Unsolved — running on stale snapshots | High — erodes trust as usage increases |
| Multi-AI coordination | Unsolved — human is integration layer | Medium — manageable at current scale |

The immediate priority is **index freshness**. The tool's effectiveness creates demand for reliability, and reliability requires freshness. Everything else is downstream of that.
