# Enhancement Request: Directory-Level Compound Queries

**Requested by:** Claude Code session (cross-project exploration)
**Date:** 2026-02-08
**Priority:** Medium (usability gap, workaround exists)
**Estimated effort:** TBD

---

## Summary

The MCP service currently thinks in **files**, not **directories/projects**. There is no way to ask: "which directories contain files matching criterion A AND criterion B AND criterion C?" This is a natural question when exploring a workspace of many projects.

---

## The Use Case That Failed

**User request:** "Find directories in ~/src that have .git, a README, and Python code."

This is a simple, common developer question — "show me my real Python projects." It should be one query. Instead it required:

1. `list_directories` — returned results dominated by exploitdb subdirectories (sorted by file count), not useful for project-level orientation
2. `search_files(name_pattern="README")` — returned 50 results sorted by modification date, missing older projects
3. `search_files(file_type=".py")` — returned 50 results sorted by modification date, missing older projects
4. **Bash fallback** for `.git` detection — the MCP service doesn't index `.git` directories at all
5. **16 additional targeted `search_files` calls** — to verify README and .py presence in each of the 27 git repos that the first batch missed
6. **Manual cross-referencing** by the AI — assembling results from 3+ data sources into a unified answer

Total: ~20 MCP calls + 1 bash command + significant AI reasoning to assemble what should have been a single query.

---

## Why It Didn't Work

### 1. No directory-level predicates
The service indexes individual files. There's no concept of "this directory contains at least one file of type X." The question "which projects have Python code?" requires scanning every .py file and deduplicating to parent directories.

### 2. Result limit of 50 with recency bias
`search_files` returns max 50 results sorted by modification date. For a workspace with 65 projects spanning 2024-2026, this systematically misses older projects. The user's question was about **all** projects, not recent ones.

### 3. No compound/boolean file queries
Can't express: `directory HAS (*.py) AND HAS (README*) AND HAS (.git)`. Each criterion requires a separate API call, and the AI must intersect the results.

### 4. `.git` is invisible to the index
The indexer (correctly) skips `.git` directories, but this means "is this a git repo?" can't be answered by the service at all. This is a common attribute users care about.

---

## What Would Have Worked

### Option A: Directory profile / project summary tool
A new tool like `get_directory_profile(path)` or `list_projects(parent)` that returns:
```json
{
  "path": "/Users/mark/src/ai_shell_logging",
  "is_git_repo": true,
  "has_readme": true,
  "file_types": [".py", ".md", ".json", ".yaml"],
  "file_count": 34,
  "total_size": "1.2MB",
  "last_modified": "2026-02-01"
}
```

A single `list_projects("/Users/mark/src")` call could answer the original question.

### Option B: Compound search_files with directory grouping
Extend `search_files` to support:
- `group_by="directory"` — return directories instead of individual files
- Multiple criteria in one call (has file_type=.py AND has name_pattern=README)
- A `has_git` boolean flag (check for `.git` dir existence without indexing it)

### Option C: SQL passthrough / view
Since the backing store is SQLite, expose a `project_summary` view that pre-aggregates file metadata to the directory level. The AI could query this directly.

---

## Workaround (Current)

The AI must:
1. Use bash `ls -d ~/src/*/.git` to find git repos
2. Use multiple `search_files` calls (one per criterion per directory) to check for README and .py
3. Cross-reference results manually

This works but consumes ~20 tool calls and significant context window for what should be a trivial question.

---

## Broader Pattern

This is an instance of a general gap: the service is **file-granular** but users often think at the **project/directory level**. Other questions that hit the same wall:
- "Which of my projects have tests?"
- "Which repos haven't been touched in 6 months?"
- "Which projects use FastAPI vs Flask?"
- "Show me projects that have both a Dockerfile and a requirements.txt"

All of these are directory-level compound queries that the current file-level API can't express efficiently.
