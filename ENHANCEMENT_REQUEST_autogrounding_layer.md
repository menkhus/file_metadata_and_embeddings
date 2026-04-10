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

## Enhancement 2: Prompt Micro-Processing Pipeline

### The framing shift

This is micro-processing, not macro-scope processing.

The industry default is macro: give the LLM everything, big context,
big model, let it resolve ambiguity. Expensive, opaque, not reproducible.

This is micro: process the smallest meaningful unit — the prompt —
precisely, before it goes anywhere. The prompt is an artifact, same
as any other. The funcspec gets processed before going to the AI. The
prompt gets the same treatment.

The raw prompt is noise. The processed prompt is signal.

### The pipeline — aifilter behaviors

The preprocessing pipeline is three aifilter behaviors in a pipe.
No new infrastructure. aifilter already exists. Behaviors are plain
text files. Each call is local, single shot, zero cloud cost.

```sh
echo "$prompt"                    \
  | aifilter -b keyword_extract   \
  | autoground_query              \
  | aifilter -b ground_prompt     \
  | aifilter -b clean_and_tighten \
  > enhanced_prompt.txt
```

**`keyword_extract`** — extract nouns and verbs from the prompt.
Not LDA — the prompt is too short for LDA to bootstrap. phi4 reads
the prompt and returns the intent keywords. Single shot. Fast.

**`autoground_query`** — deterministic DB query (not an AI call).
Takes the keywords, queries the substrate DB, returns matching nodes
as structured context. The one non-aifilter step — pure Python,
milliseconds.

**`ground_prompt`** — aifilter behavior. Receives original prompt +
DB query results. Prepends relevant prior work as grounding context.
Structured output: `[Prior work: ...]\n\n[Original prompt]`.

**`clean_and_tighten`** — aifilter behavior. Absorbs spell-check,
grammar fix, and intent clarification in one shot. phi4 cleans
"we was kind of thinking maybe" → "we want to". Fixes typos.
Tightens ambiguous intent. Preserves meaning. Single shot.

Two behaviors collapse into one because phi4 handles both cleaning
and tightening simultaneously — running aspell separately is
redundant when a local model does it better in the same pass.

### The result

```
raw prompt     "how do we ad the kG notes into the sesions so
                it carys the work forward?"

processed      [Prior work: substrate DB (file_metadata_and_embeddings),
                session KG (universal_ai_shell_history), autogrounding
                hook (ENHANCEMENT_REQUEST_autogrounding_layer.md)]

               How do we write KG session notes into the project
               directory so prior work carries forward across sessions?
```

The LLM receives clean intent + grounded context. It never sees the
raw prompt. It never has to ask clarifying questions about typos or
vague phrasing. It starts informed.

### Hook mechanism — Claude Code `UserPromptSubmit`

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
    ]
}
```

`autoground.py` is the thin wrapper: reads prompt from hook stdin
(JSON), runs the aifilter pipe, returns enhanced prompt on stdout.
The behaviors do the work. The script is just the plumbing.

### Hook mechanism — aifilter (pipe layer)

For aifilter workflows — the preprocessing slot is already in the pipe:

```sh
# before:
cat prompt.txt | aifilter -b behavior

# after — preprocessing is just more pipe stages:
cat prompt.txt                    \
  | aifilter -b keyword_extract   \
  | autoground_query              \
  | aifilter -b ground_prompt     \
  | aifilter -b clean_and_tighten \
  | aifilter -b behavior
```

The main behavior receives a clean, grounded prompt. It does better
work because the input is better. Same pattern as the funcspec:
precision input, bounded translation, measurable output.

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

## Enhancement 4: One Database, All the Feeds

### The vision

This is not a new database. It is an aggregation of feeds that
already exist, reusing the same schema, connected by the same
query layer.

Every tool in the knowledge stack produces the same kind of thing:
nodes with keywords, edges with provenance, timestamps. They all
overlap. The DB is where the overlap becomes useful.

```
Feed              What it contributes         Node type
─────────────────────────────────────────────────────────
ghost             archived files, projects    project | file
file_metadata     40K+ indexed files,         file | concept
                  TF-IDF, LDA, FAISS
session KG        moments of work,            session | concept
                  tool call sequences
uaish             AI session history,         session | prompt
                  Claude + Gemini + Ollama
signals           arXiv, Semantic Scholar     paper | concept
aifilter          behavior invocations,       skill | session
                  pass/fail outcomes
```

Same schema. Same keyword extraction. Same edge structure.
All queryable together.

### Ghost as a feed

Ghost already does the hard part — archives files, extracts semantic
content via TF-IDF + LSA (ghost diff). PRELOAD.md per project is
already a manually-written rendering of project state.

In the DB model:
- Ghost archive → nodes written to DB on archive
- Ghost diff → edge with semantic distance score between versions
- Ghost search → KG query (same index, better joins)
- PRELOAD.md → rendered on demand from DB, not hand-maintained

Cross-project connections emerge automatically. Two projects that
ghost manages separately, with overlapping keyword clusters, get
an edge. You don't create it. The keyword match creates it.

### Self-labeling is the key property

Every PIM that becomes noise does so because the user must decide
where things go. Taxonomy imposed from outside the content always
decays — life moves faster than filing.

This system never asks. Labels emerge from the content:
- Keywords from TF-IDF and LDA (already computed)
- Edges from keyword overlap (computed at write time)
- Signal from new external matches (computed on schedule)

You cannot mis-file something because you never file anything.
The organization is emergent from the work, not imposed on it.
The DB grows from the work. The work does not grow from the DB.

### The aggregation query

The value is in the joins no single tool can make:

```sql
-- what concept connects my ghost-archived writing project
-- to an arXiv paper published this month?
SELECT n1.label, e.relation, n2.label, s.detected_at
FROM nodes n1
JOIN edges e ON e.from_id = n1.id
JOIN nodes n2 ON n2.id = e.to_id
JOIN signals s ON s.keyword LIKE '%' || n2.label || '%'
WHERE n1.source LIKE '%the-mathematician%'
AND s.is_new = 1;

-- what skills (aifilter behaviors) have I used in sessions
-- that touched this project?
SELECT DISTINCT e2.from_id as skill
FROM edges e1
JOIN edges e2 ON e2.to_id = e1.session_id
WHERE e1.to_id = 'project:universal_ai_shell_history'
AND e2.relation = 'skill_used';
```

No single tool answers these. The DB answers both in milliseconds.

### What this is

Not a sock drawer. Not a note-taking app. Not a PIM in the
conventional sense.

A **personal knowledge substrate** — computed from work, not
curated from intention. Self-labeling. Self-connecting. Queryable
at any time. Renderable on demand via local AI. Growing from every
session without maintenance.

The ghost tooling, file_metadata, uaish, aifilter, and the session
KG are all feeds into the same substrate. They were always overlapping.
The DB is where the overlap becomes a capability instead of redundancy.

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
