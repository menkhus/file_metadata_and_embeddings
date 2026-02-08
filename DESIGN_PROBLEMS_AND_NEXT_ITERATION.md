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

## Future Direction: Index-on-Write and Per-Project Knowledge Layers

### The architectural shift

The freshness problem (Problem 3) assumes a traditional flow:

```
write file → file sits on disk → later, maybe, run indexer → index goes stale
```

The solution isn't better polling or smarter re-indexing schedules. It's inverting the flow:

```
write file → hook intercepts → index updated → embeddings updated → AI knows immediately
```

Don't poll for changes. React to them.

### SQLite is the git of knowledge

`.git` is a hidden directory that makes a project *versioned*. You don't think about it — you just expect `git log` to work. The same pattern applies to knowledge:

A `.index` (or equivalent) SQLite database in every project, maintained automatically, makes the project *intelligent*. You don't think about it — you just expect the AI to know what's in the project.

SQLite is purpose-built for this role:
- Embedded, zero-config, no server process needed
- FTS5 for full-text search built in
- Handles concurrent reads from multiple AI agents
- Single file, portable, lives alongside the code
- Per-project isolation — each project carries its own knowledge layer

A typical project's index would be 10-50MB — trivial compared to `node_modules` or a `.git` directory. Storage is free. Freshness is priceless.

### Hook points

The write-to-index pipeline can hook at multiple levels:

| Hook point | Mechanism | Latency | Coverage |
|---|---|---|---|
| Claude Code hooks | Post-write hook triggers indexing | Instant | AI-written files |
| Editor plugins | On-save triggers indexing | Instant | All edited files |
| `git hooks` (post-commit) | Indexes changed files per commit | Per-commit | All committed changes |
| `fswatch` / `watchman` | OS-level file system events | Near-instant | Everything |
| CI/CD pipeline | Index as build step | Per-push | Shared/deployed code |

The lightest viable approach: **Claude Code hooks + git post-commit**. This covers the two main write paths (AI writes, human commits) without requiring OS-level watchers.

### Per-project index, federated queries

If every project has its own SQLite index that's always current:

- **No stale results, ever.** The trust problem disappears.
- **No cold start.** The index is already there when the AI arrives.
- **No central server needed.** Each project is self-aware.
- **Freshness is guaranteed by construction**, not by maintenance.

The top-of-tree experience (what we demonstrated in the 2026-02-07 session) becomes a federated query across per-project indexes. Each project maintains its own truth. The orchestration layer queries across all of them. Same architecture, but distributed and always fresh.

### What this makes possible

When every file write triggers indexing, the AI's knowledge is always current. The gap between "what's on disk" and "what the AI knows" drops to zero. This eliminates an entire class of problems:

- No ghost results from deleted files
- No stale snippets from modified files
- No missing results from new files
- No "did you re-index?" conversations

The AI becomes a **live collaborator** rather than a **periodic snapshot reviewer**. And the user never has to think about indexing — it just happens, like git tracking changes, like SQLite persisting data.

This is the answer to "I don't ever want to give this up." Make it unkillable by making it automatic.

---

## Future Direction: The Git DAG as a Semantic Filesystem

### The insight

Git already built the hard part. It tracked every change, every timestamp, every author, every relationship. It built a DAG (Directed Acyclic Graph) for free, as a side effect of version control. The semantic layer is *implicit* in the data but *invisible* to the tooling.

We don't need to build a knowledge graph from scratch. We need to **graft a semantic nervous system onto a skeleton that already exists.**

### Prior art in this corpus

The idea has been developing across the user's work since at least August 2025 (found via the MCP's own index):

- **`long_context_local_ai/PLAN.md`** — Knowledge graph schema with temporal edges: `action:edit --followed_by--> action:commit`. The DAG-as-knowledge-graph, already designed.
- **`linux-kernel/notes/tools/SEMANTIC-ANALYSIS-GUIDE.md`** — "The git repository is no longer just code history — it's a temporal database you can query semantically." Applied to kernel security research, mining commit histories for CVE patterns by meaning.
- **`fix_the_user_for_better_ai_outcomes/docs/cache_alignment_analysis.md`** — Reframe: "Old: how do I orchestrate a DAG of LLM calls? New: how do I structure payloads to maximize cache hits?" DAGs connected to semantic caching.
- **`ai_shell_tools/backup_strategy.md`** — "Git-Based Version Control Strategy for Cognitive Programming." Git as a record of cognitive decisions, not just code history.

### What git's DAG actually contains

Git stores five things, each mapping to a knowledge dimension:

| Git has | What it knows | Knowledge dimension |
|---|---|---|
| **Blobs** (content-addressed) | Exact content at every point in time | Historical truth |
| **Trees** (directory snapshots) | What was next to what, when | Structural co-location |
| **Commits** (DAG nodes) | Who, when, why (message), parent(s) | Temporal causation |
| **Diffs** (between any two nodes) | What changed between any two points | Evolution |
| **Branches/tags** (named refs) | Named lines of work, release points | Intent and milestones |

Nobody queries git this way. We use `git log`, `git diff`, `git blame` — line-level tools. The knowledge is there. The query layer isn't.

### Five capabilities a semantic layer on the DAG would provide

**1. Commit embeddings — search history by meaning**

Embed each commit's (message + diff summary). Now you can:
- `git log --semantic="authentication refactor"` — even if no commit message says "authentication"
- "When did the project shift from prototyping to production?" — semantic phase detection
- "Find all commits conceptually similar to this PR" — for review, for learning

**2. File trajectories — meaning over time**

Track each file's embedding across commits. A file's embedding *changes* as its content changes. Plot that drift:
- A file that starts as a utility and becomes a core module — the embedding trajectory shows it
- A file whose meaning is stable for 50 commits then shifts suddenly — that's a refactor point
- Two files whose trajectories converge — they're becoming coupled, whether or not they import each other

**3. Co-change semantic graphs**

Git already knows which files change together. Add embeddings and you get:
- Files that change together *and* their changes are semantically similar — strong coupling
- Files that change together but changes are semantically *different* — a dependency being dragged along
- Files that *never* change together but are semantically similar — missed abstractions

**4. Branch semantics**

Embed all commits on a branch and you get a branch-level topic vector:
- "What is this branch *about*?" — without reading any code
- Compare branch topics to find parallel or conflicting work
- Detect when a branch drifts from its stated purpose

**5. Semantic blame**

Not just "who changed this line" but "what conceptual thread does this change belong to?" Group changes by semantic similarity across time, and you get threads of intent woven through the history.

### The SQLite schema: a parallel universe to .git

```sql
-- Mirrors git's DAG structure
CREATE TABLE commits (
    hash TEXT PRIMARY KEY,
    timestamp TEXT,
    author TEXT,
    message TEXT,
    diff_summary TEXT,
    embedding BLOB          -- semantic vector of the commit
);

CREATE TABLE dag_edges (
    child_hash TEXT,
    parent_hash TEXT,
    PRIMARY KEY (child_hash, parent_hash)
);

-- File state at each commit
CREATE TABLE file_snapshots (
    commit_hash TEXT,
    file_path TEXT,
    content_hash TEXT,
    tfidf_keywords TEXT,    -- JSON array
    embedding BLOB,         -- semantic vector of file at this point
    PRIMARY KEY (commit_hash, file_path)
);

-- Auto-derived semantic relationships between commits
CREATE TABLE semantic_edges (
    source_hash TEXT,
    target_hash TEXT,
    similarity REAL,
    edge_type TEXT          -- 'conceptually_similar', 'continues_work', 'reverts_intent'
);

-- Meaning drift per file over time
CREATE TABLE file_trajectories (
    file_path TEXT,
    commit_hash TEXT,
    embedding BLOB,
    drift_from_previous REAL,  -- cosine distance from previous commit's embedding
    PRIMARY KEY (file_path, commit_hash)
);
```

### Example queries this enables

```sql
-- "What was this project about in October?"
SELECT message, diff_summary FROM commits
WHERE timestamp BETWEEN '2025-10-01' AND '2025-10-31'
ORDER BY embedding <-> query_embedding LIMIT 10;

-- "When did this file's purpose change?"
SELECT commit_hash, drift_from_previous FROM file_trajectories
WHERE file_path = 'ai_shell.py' AND drift_from_previous > 0.3
ORDER BY commit_hash;

-- "Find commits semantically related to this one"
SELECT c.message, se.similarity FROM semantic_edges se
JOIN commits c ON c.hash = se.target_hash
WHERE se.source_hash = ? AND se.similarity > 0.7
ORDER BY se.similarity DESC;

-- "Which files are semantically coupled but never co-change?"
SELECT a.file_path, b.file_path, cosine_sim(a.embedding, b.embedding) as sim
FROM file_snapshots a, file_snapshots b
WHERE a.commit_hash = b.commit_hash
AND a.file_path < b.file_path
AND sim > 0.8
AND NOT EXISTS (
    SELECT 1 FROM file_snapshots fa
    JOIN file_snapshots fb ON fa.commit_hash = fb.commit_hash
    WHERE fa.file_path = a.file_path AND fb.file_path = b.file_path
);
```

### How it connects to the existing architecture

This isn't a replacement for the current file_metadata MCP — it's the **time dimension** that's currently missing.

| Current MCP | Git-informed semantic layer |
|---|---|
| What files exist now | What files existed at any point |
| What a file is about now | How a file's meaning evolved |
| Which files are related by content | Which files are related by co-evolution |
| Snapshot-based (one point in time) | DAG-based (full history) |
| Answers "what is?" | Answers "how did it become?" |

The current index tells you the *state* of your work. The git-informed layer tells you the *story* of your work. Together: a complete semantic filesystem.

### The completion

Git is the DAG of knowledge. SQLite + embeddings is what makes it queryable by meaning. The filesystem is scaffolding. The index is the present tense. The DAG is the past tense. Together they give the AI not just awareness of your work, but understanding of how your work *became what it is*.

---

## Summary

| Problem | Status | Severity |
|---|---|---|
| AI tool preference formation (last mile) | Validated — works when tool is responsive and results are rich | Solved in practice, needs design principles documented |
| Cold start latency | Solved — persistent server | Solved |
| Index freshness/lifecycle | Architectural direction identified — index-on-write with per-project SQLite | High — erodes trust as usage increases |
| Multi-AI coordination | Unsolved — human is integration layer | Medium — manageable at current scale |

The immediate priority is **index freshness**, and the architectural answer is **index-on-write**: hook file writes, update the index immediately, and make freshness a property of the system rather than a maintenance task. SQLite per project, federated at the root. The git of knowledge.
