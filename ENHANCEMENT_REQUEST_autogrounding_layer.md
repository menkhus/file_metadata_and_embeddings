# Enhancement Request: KG-as-Grounding-Layer + Autogrounding Hook

*Filed April 2026. Two related enhancements — the backend and the intercept.*

---

## Enhancement 1: KG as Active Grounding Layer

### The idea

The current autograph KG learns from grounding decisions made during
sessions. It is a passive recorder. This enhancement makes it active:
a grounding layer that the LLM queries before answering, giving it
both internal prior work and external literature as context.

### The search bridge (prerequisite)

Before the KG can ground external literature, it needs outward-facing
nodes. Three pieces:

**1. Idea signature extractor**
```
Input:  a project directory (or session set)
Method: aggregate LDA + TF-IDF keywords across files
        weight by frequency across files, not just within one file
Output: ranked keyword list — the "idea signature" for that project
```

The `content_analysis` table already has `lda_topics` and
`tfidf_keywords` per file. This is an aggregation step, not new
extraction.

**2. Signal searcher**
```
Input:  idea signature keywords
Method: query arXiv API (free, structured, machine-readable)
        query Semantic Scholar API (also free)
Output: papers matching your keyword clusters, with date + abstract
```

Keywords are the bridge — not embeddings. arXiv does not expose
embedding search. Keywords are the common language between your
internal LDA/TF-IDF and external search APIs. Stable, interpretable,
model-independent.

**3. Signal annotator**
```
Input:  new papers from step 2
Method: add as nodes to autograph KG (nodes.csv)
        edge: keyword_cluster → paper (with date, score, source)
Output: KG grows outward into the literature
```

**Signal detection:** run the searcher on a schedule (weekly/monthly).
New edges that didn't exist last run = signal. Papers appearing in
your keyword neighborhood for the first time = the field is moving
toward your ideas.

**Absence of signal is signal.** If a keyword cluster has no external
matches, that is either a gap in the literature (potentially novel)
or a gap in your keywords (calibration needed). Both are worth knowing.

### The grounding layer

Once external nodes exist, the LLM can be grounded against the full KG:

```
LLM call
  → query KG: what do I know about the keywords in this prompt?
  → returns: internal nodes (your projects, sessions)
             + external nodes (papers, dated)
             + edge metadata (when found, match strength, source)
  → injected as context before the prompt reaches the model
  → LLM answers grounded in both your prior work AND the literature
  → new response adds nodes back to KG (session becomes prior art)
```

This is not RAG. RAG retrieves similar chunks. This retrieves
**provenance** — where this idea has been before, inside and outside
your work, and when.

### Implementation path

1. `extract_idea_signatures.py` — aggregate keywords per project dir
2. `signal_searcher.py` — arXiv + Semantic Scholar query, returns papers
3. `signal_annotator.py` — adds papers as KG nodes/edges
4. `autoground_query.py` — given a prompt, returns relevant KG context
5. Schedule: cron or launchd, weekly, writes new nodes to KG
6. MCP tool: `ground_prompt(text)` → returns KG context for injection

### Prior art (author's own)

This system was built in ~2015 at HP as an internal technical
disclosure. Markdown documents linked to each other, monthly search
annotations, LDA keyword extraction, cosine similarity. The keyword
layer was chosen deliberately over embeddings — stable signal,
model-independent, survives tool changes. That choice is still correct.

---

## Enhancement 2: Autogrounding Hook — Intercept, Clean, Ground

### The idea

Intercept every prompt before it reaches an AI, run three operations
deterministically, inject the result back into the prompt:

```
user types prompt
      ↓
[HOOK FIRES]
      ↓
1. spell-check        — aspell/hunspell, deterministic, fast
2. keyword extract    — TF-IDF on prompt text, no AI cost
3. KG query           — find matching internal + external nodes
      ↓
enhanced prompt = corrected text + KG context preamble
      ↓
AI receives enhanced prompt
      ↓
response + grounding decision logged back to KG
```

This is huge for several reasons:
- Spell-checked prompts produce cleaner AI output (model distributions
  skew toward clean text)
- The AI gets automatic context about Mark's prior work — no manual
  "look for prior art" step
- Every session grows the KG — the system gets more grounded over time
- Deterministic layer costs zero tokens, zero AI calls

### Hook mechanism — Claude Code `UserPromptSubmit`

Claude Code supports a `UserPromptSubmit` hook that fires when the
user submits a prompt, before it reaches the model. This is the
correct intercept point.

Add to `~/.claude/settings.json`:

```json
"hooks": {
    "UserPromptSubmit": [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "python3 /Users/mark/.claude/scripts/autoground.py"
                }
            ]
        }
    ],
    "Stop": [ ... existing ... ]
}
```

The hook script receives the prompt on stdin (JSON), processes it,
and returns the enhanced prompt on stdout.

### Hook script design: `autoground.py`

```python
#!/usr/bin/env python3
"""
autoground.py — UserPromptSubmit hook.

Intercepts every prompt before it reaches Claude.
Three deterministic operations: spell-check, keyword extract, KG query.
Returns enhanced prompt with grounding context prepended.
"""

import json, sys, subprocess
from pathlib import Path

# Step 1: read prompt from hook stdin
data = json.load(sys.stdin)
prompt = data.get("prompt", "")

# Step 2: spell-check
# aspell --mode=none reads from stdin, outputs corrected text
corrected = spellcheck(prompt)   # aspell/hunspell subprocess

# Step 3: keyword extract from prompt
# TF-IDF against the prompt text — fast, no model
keywords = extract_keywords(corrected)   # lightweight sklearn TF-IDF

# Step 4: query KG for matching nodes
# calls autoground_query against file_metadata DB + autograph KG
context = query_kg(keywords)   # returns top-N matching nodes

# Step 5: build enhanced prompt
if context:
    enhanced = f"[Prior work context: {context}]\n\n{corrected}"
else:
    enhanced = corrected

# Step 6: return to Claude Code
data["prompt"] = enhanced
json.dump(data, sys.stdout)
sys.exit(0)
```

### Hook mechanism — aifilter (pipe layer)

For `aifilter` — since it is a pipe tool, the intercept is simpler:

```sh
# before: 
cat prompt.txt | aifilter -b behavior

# after:
cat prompt.txt | autoground | aifilter -b behavior
```

`autoground` is a standalone pipe script: reads stdin, spell-checks,
queries KG, injects context, writes to stdout. No AI calls. Pure
deterministic preprocessing. `aifilter` receives the grounded prompt.

### Shell wrapper enhancement

The `_logged_ai()` function in `~/.zshrc` already wraps `claude`,
`ollama`, `gemini`. For non-interactive use cases (piped input,
`-p` flag), the wrapper can call `autoground` before dispatch:

```sh
_logged_ai() {
    local app="$1"; shift
    # ... existing logging setup ...
    # autoground: intercept piped input if non-interactive
    if [[ ! -t 0 ]]; then
        input=$(cat | autoground)
        echo "$input" | script -q "$logfile" command "$app" "$@"
    else
        script -q "$logfile" command "$app" "$@"
    fi
}
```

Interactive sessions use the Claude Code hook. Piped sessions use
the shell wrapper. Both paths covered.

---

## What this enables

The full loop:

```
prompt entered
  → spell-checked (deterministic)
  → keyword-extracted (deterministic)
  → KG-queried (deterministic, your prior work + literature)
  → AI receives grounded, clean prompt
  → response generated
  → grounding decision logged to KG
  → KG grows
  → next prompt is better grounded
```

Each session makes the next session smarter. Not because the model
changed. Because the KG grew.

This is the 2015 HP system, completed. Manual annotation replaced
by the deterministic gate and the hook. Monthly search replaced by
the signal searcher on a schedule. Human reading the matches replaced
by KG edges that surface automatically in the next prompt.

---

## Enhancement 3: Database as Truth — File as Optional Rendering

### The core shift

The file model is document-based thinking: generate a file, AI reads
the file. `prior_art_notes.md` was a useful convenience for Claude's
file-reading habit. It is not the architecture.

The database model is different:

```
work happens
    ↓
keywords extracted, edges computed, nodes written — all to DB
    ↓
next session: hook queries DB directly
    ↓
AI receives computed context — not a file, a query result
```

Nothing needs to exist as a file. The DB is the truth. The file is
a rendering — generate it at session start if needed, discard it
when done. Or skip it entirely and inject directly via the hook.

```python
# hook queries DB, returns computed context
context = kg.query(keywords=session_keywords, top_k=10)
# optional: write ephemeral prior_art_notes.md for this session
# or: inject directly as system context
# either works — the DB doesn't care
```

### The schema

SQLite — same backend already used by this project.

```sql
-- every session that ran
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,  -- SHA256 of cwd+timestamp
    cwd         TEXT,
    project     TEXT,
    started_at  TEXT,
    keywords    TEXT               -- JSON array, extracted post-session
);

-- every node: internal or external
CREATE TABLE nodes (
    id          TEXT PRIMARY KEY,
    type        TEXT,  -- project | session | paper | concept | person
    label       TEXT,
    source      TEXT,  -- file path, arXiv URL, or 'unpublished'
    first_seen  TEXT,
    last_seen   TEXT,
    metadata    TEXT   -- JSON
);

-- relationships with provenance
CREATE TABLE edges (
    from_id     TEXT,
    to_id       TEXT,
    relation    TEXT,  -- matched | cited | evolved_from | session_referenced
    score       REAL,
    created_at  TEXT,
    session_id  TEXT   -- which session created this edge
);

-- signal detection: external matches over time
CREATE TABLE signals (
    keyword     TEXT,
    source_url  TEXT,
    title       TEXT,
    detected_at TEXT,
    is_new      INTEGER  -- 1 if first time seen — this IS the signal
);

-- FTS over everything
CREATE VIRTUAL TABLE nodes_fts USING fts5(label, source, metadata);
```

### What the DB answers that a file never could

```sql
-- what ideas have I worked on that nobody is publishing about?
SELECT n.label FROM nodes n
LEFT JOIN signals s ON s.keyword LIKE '%' || n.label || '%'
WHERE s.keyword IS NULL AND n.type = 'concept';

-- what ideas are heating up externally that match my work?
SELECT keyword, COUNT(*) as hits, MAX(detected_at) as latest
FROM signals WHERE is_new = 1
GROUP BY keyword ORDER BY hits DESC;

-- which sessions connected to this project?
SELECT s.cwd, s.started_at FROM sessions s
JOIN edges e ON e.session_id = s.id
WHERE e.to_id = 'project:universal_ai_shell_history';
```

Milliseconds. No file scan. No AI call.

### Local AI as the rendering layer

When a file IS needed — for Claude to read, for a human to review —
local AI generates it from the DB query result:

```
DB query → raw KG matches (JSON)
    ↓
phi4 via aifilter — behavior: "summarize_prior_art"
    ↓
clean prior_art_notes.md — terse, file paths, one-liners
    ↓
written to cwd — ephemeral, session-scoped
    ↓
discarded or committed, depending on value
```

Single shot. Local model. Zero cloud cost. The file is a view over
the DB, not the source of truth.

### The PIM distinction

Most PIMs store documents. You open them to add things. This stores
*relationships between moments of work*. You never open it to add
something — the sessions write to it automatically. You open it to
query what the work already knows.

The data does not exist as files. It is computed and stored. The
computation happens at session boundaries. The storage is permanent
and queryable. The rendering is on-demand and ephemeral.

This is closer to a research journal that indexes itself than to a
note-taking app. The scaffolding generalizes to any knowledge domain
that produces text and has a quality signal: code, writing, research,
reading. Same schema, same hook, same signal detection.

---

## Implementation order

1. `autoground_query.py` — KG query given keyword list (core primitive)
2. `autoground.py` — hook script (spell-check + keyword extract + KG query)
3. `UserPromptSubmit` hook in `~/.claude/settings.json`
4. `extract_idea_signatures.py` — project-level keyword aggregation
5. `signal_searcher.py` — arXiv + Semantic Scholar
6. `signal_annotator.py` — writes external nodes to KG
7. Schedule signal searcher (launchd weekly)
8. `ground_prompt` MCP tool — exposes grounding to all AI sessions

Items 1–3 are the intercept layer. Items 4–7 are the outward bridge.
Item 8 makes it universally accessible.

Items 1–3 can be built and used immediately — no external search needed
to get value from internal KG grounding.
