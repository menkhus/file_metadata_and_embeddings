# Substrate Engineering: A Personal Knowledge System Built from Work
## Long-term AI memory from behavioral exhaust, self-labeling and engineer-owned

*A research paper outline. Author's words are the spine.*
*April 2026.*

*Companion paper: "Gleanings from AI Work Logs" (PITR, trajectory extraction,*
*LoRA training signal) — see `~/src/universal_ai_shell_history/aifilter_notes.dir/PAPER_OUTLINE.md`*

---

## Opening — The $10,000/Hour Consultant

The first time it happened, it was startling.

An engineer started a Claude Code session from `~/Documents/src` — the
root of 101 active projects, years of accumulated work, interconnected
CLAUDE.md files, prior research, half-finished ideas, completed tools.
Claude immediately reasoned across all of it. It knew the vocabulary.
It knew the project relationships. It surfaced prior work the engineer
had half-forgotten. It felt, in the engineer's words, like a
$10,000/hour consultant who had read everything.

Claude did not get smarter. The context got richer.

The model was the same model available to everyone. What was different
was the substrate — the accumulated, structured residue of years of
real work, present in the context window, available for reasoning.
The intelligence was always there. The grounding made it visible.

That experience is the starting point for this paper.

The mechanism, it turns out, is simple. It is slipping a note under
the office door before the next person arrives.

The session ends. A hook fires. The system writes what it knows —
prior projects that connect, ideas that surfaced, literature that
matches — to a file in the project directory. The next session opens.
The note is there. The AI reads it. The AI is grounded.

No handshake. No vendor cooperation. No protocol. No API that can
break. A file in a directory — the oldest, most durable interface
in computing. Any model that reads files picks it up. All of them do.

The note is not a summary. It is a provenance trail: specific projects,
specific sessions, specific ideas that connected, with dates and sources.
Computed from instrumented session history. Written by local AI in one
shot. Read by the next session as ordinary project context.

Vendor memory systems require the vendor. This requires a directory.

---

## Abstract

This paper describes a personal knowledge substrate — a SQLite database
computed from the behavioral exhaust of instrumented AI work sessions,
self-labeling via TF-IDF and LDA keyword extraction, queryable at any
time, renderable on demand via local AI. The substrate grows from the
work without curation. It grounds every AI session with prior work and
annotated literature. It detects signal when the external field moves
toward the engineer's ideas.

The contribution is not a new memory architecture. It is a new source:
behavioral exhaust from real work sessions is a superior memory substrate
because it is self-labeling, provenance-rich, and engineer-owned. A
deterministic gate — a Unix test, an exit code — replaces human
annotation as the quality signal. No vendor holds the memory. No
curation is required. The system improves from the work.

The care and feeding of AI to do great things is not prompt engineering.
It is substrate engineering. This paper describes the substrate.

---

## 1. The Problem — Every Session Starts Cold

Every AI session starts cold. The model does not know what was built
last month. The engineer re-explains, re-establishes context,
rediscovers prior work. The cognitive overhead compounds across sessions.

This is the hidden cost of AI-assisted work that no benchmark measures.

Vendor memory features exist [51][52] but are black boxes — stored on
vendor infrastructure, formatted their way, subject to their retention
policy. The engineer does not own it, cannot query it, cannot combine
it with other tools. When the vendor changes the API, the memory is gone.

The substrate described here is different:

```
long-term memory = DB you own
                 + feeds from all your tools
                 + query layer you inspect
                 + signal detection from literature
                 + rendering via local AI
                 + growing from every session, automatically
```

---

## 2. The Substrate — Computed, Not Curated

The substrate is a SQLite database. The data does not exist as files.
It is computed and stored. Files are renderings — generated on demand,
discarded when done.

```sql
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,  -- SHA256 of cwd+timestamp
    cwd         TEXT,
    project     TEXT,
    started_at  TEXT,
    keywords    TEXT               -- JSON, extracted post-session
);

CREATE TABLE nodes (
    id          TEXT PRIMARY KEY,
    type        TEXT,  -- project | session | paper | concept | person
    label       TEXT,
    source      TEXT,  -- file path, arXiv URL, or 'unpublished'
    first_seen  TEXT,
    last_seen   TEXT,
    metadata    TEXT   -- JSON
);

CREATE TABLE edges (
    from_id     TEXT,
    to_id       TEXT,
    relation    TEXT,  -- matched | cited | evolved_from | session_referenced
    score       REAL,
    created_at  TEXT,
    session_id  TEXT
);

CREATE TABLE signals (
    keyword     TEXT,
    source_url  TEXT,
    title       TEXT,
    detected_at TEXT,
    is_new      INTEGER  -- 1 if first time seen — this IS the signal
);

CREATE VIRTUAL TABLE nodes_fts USING fts5(label, source, metadata);
```

Every tool in the knowledge stack is a feed. Same schema. No new
extraction — the tools already compute the labels.

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

The tools were always overlapping. The DB is where the overlap becomes
a capability instead of redundancy.

---

## 3. Self-Labeling — Why No Curation Is Required

Every PIM that becomes noise does so because the user must decide where
things go. Taxonomy imposed from outside the content always decays.

This system never asks. Labels emerge from the content:
- Keywords from TF-IDF and LDA — already computed by file_metadata
- Edges from keyword overlap — computed at write time
- Signal from external matches — computed on schedule

You cannot mis-file something because you never file anything. The
organization is emergent from the work, not imposed on it.

**The keyword layer is the durable signal.** Not embeddings — those
shift when models retrain. LDA topic keywords and TF-IDF weights are
stable: "knowledge graph," "LoRA," "deterministic gate" mean the same
thing across models and years. Google at scale remains keyword-grounded
for exactly this reason.

This was validated empirically in 2015: an internal HP system linked
markdown documents, annotated them monthly with search results using
LDA keyword extraction, and detected signal when new papers appeared
in the keyword neighborhood. The keyword layer was chosen deliberately
over embeddings. That choice is still correct.

---

## 4. The Search Bridge — Extending Outward

The substrate extends from internal work into the external literature
via three components:

**Idea signature extractor:**
Aggregate LDA + TF-IDF keywords across files in a project. Weight by
frequency across files, not just within one. Output: ranked keyword
list — the project's idea signature. No new extraction — `content_analysis`
table already has `lda_topics` and `tfidf_keywords` per file.

**Signal searcher:**
Query arXiv API and Semantic Scholar (both free, structured) using the
idea signature keywords. Keywords are the bridge — the common language
between internal LDA/TF-IDF and external search APIs. Returns papers
with date, abstract, match score.

**Signal annotator:**
Add returned papers as nodes. Edge: keyword_cluster → paper, with date
and score. Run on a schedule. `is_new = 1` on first detection.

**Signal detection:**
```sql
SELECT keyword, COUNT(*) as hits, MAX(detected_at) as latest
FROM signals WHERE is_new = 1
GROUP BY keyword ORDER BY hits DESC;
```

Absence of signal is also signal. A keyword cluster with no external
matches is either a gap in the literature (potentially novel) or a gap
in the keywords (calibration needed). Both are worth knowing.

---

## 5. The Autogrounding Hook — Carrying Forward

The hook is the mechanism that closes the cold-start problem.

```
session ends (Stop hook)
      ↓
query DB: what keywords defined this session?
      ↓
phi4 via aifilter — behavior: "summarize_prior_art"
      input:  raw KG matches (JSON)
      output: clean prior_art_notes.md — terse, file paths, one-liners
      ↓
written to cwd — available for next session
      ↓
next session: Claude reads prior_art_notes.md as normal project context
AI is grounded — no injection, no special handling
      ↓
grounding decision logged back to DB
DB grows
next session is better grounded
```

**Local AI as the rendering layer.** The DB holds the truth. Local AI
(phi4 via aifilter, single shot, zero cloud cost) generates the file
when needed. The file is a view over the DB, not the source of truth.

**The compounding pattern:**
> *Work on a project. The work annotates the DB. The DB grounds the
> next session. The next session does better work. That work annotates
> the DB further. The loop closes.*

Each session makes the next session smarter. Not because the model
changed. Because the substrate grew.

---

## 6. The Experiment — Three Falsifiable Claims

None of these require a GPU. All three run on a MacBook.

**Claim 1: Grounded prompts reduce re-explanation overhead.**
Measure: count of "as I mentioned" / "as we discussed" turns per
session, with hook vs. without. Grounded sessions should have fewer
context-restoration turns.

**Claim 2: Grounded prompts surface forgotten prior art.**
Measure: cases where the injected KG context referenced a project or
document the user did not mention in the prompt. Manual review of
session logs — did the surfaced context change the response?

**Claim 3: DB quality improves monotonically.**
Measure: node count and edge density over time. The marginal value of
each new node is measurable by retrieval precision on held-out prompts.

The hook is the experiment. The DB is the measurement instrument.
uaish provides the session corpus for measurement [companion paper].

---

## 7. Prior Work — What Exists and What Is Different

Long-term memory for LLMs is well-studied [51][52][53][54][55][56].

| This work | The literature |
|---|---|
| Self-labeling from behavioral exhaust | Requires curation or conversation input |
| Engineer-owned SQLite | Vendor-hosted or vendor-specific |
| Signal detection from literature | No outward-facing search loop |
| Deterministic gate as quality signal | Human annotation or model confidence |
| All tools as feeds (ghost, uaish, aifilter) | Single-source memory |
| Computed, not filed | Document-based storage |

The closest prior work is Memoria [51] — persistent memory via chat
summarization + weighted KG user persona. The difference: Memoria
derives memory from conversations. This derives memory from the
behavioral exhaust of real work — tool calls, file accesses, pass/fail
outcomes. The source is richer, more structured, and does not require
the user to say anything. The deterministic gate replaces the human
annotation step entirely.

The 2015 HP system (author's unpublished internal disclosure) is the
earliest direct prior art: markdown documents linked to each other,
monthly search annotations via LDA keyword extraction, signal detection
from new paper matches. The current work completes that system: the
manual annotation step is replaced by the hook, the monthly search is
replaced by the signal searcher, the file-based storage is replaced
by the queryable DB.

---

## 8. What Needs to Be Written

1. Implementation of `autoground_query.py` — the core DB query primitive
2. Implementation of `autoground.py` — the Stop hook script
3. Implementation of `signal_searcher.py` — arXiv + Semantic Scholar
4. Baseline measurement — session logs before hook, session logs after
5. Claim 1 measurement — re-explanation turn count
6. Claim 2 measurement — surfaced prior art review
7. Claim 3 measurement — node growth + retrieval precision over time

The companion paper (uaish / PITR) provides the session corpus and the
trajectory extraction methodology. This paper provides the substrate
and the grounding mechanism. Together they form a complete system.

---

## References (substrate paper)

[51] Memoria — arxiv 2512.12686
[52] LoCoMo — ACL 2024
[53] RAS survey — arxiv 2509.10697
[54] Context Engineering survey — arxiv 2507.13334
[55] Memory-Augmented Architecture — arxiv 2506.18271
[56] GraphRAG survey — arxiv 2501.13958

Full reference list with URLs and verification notes:
`~/src/universal_ai_shell_history/references.md` — refs [51]–[56]

Prior art (author's own):
- HP internal technical disclosure, ~2015 — LDA keyword bridge, monthly
  signal detection, markdown KG. Unpublished, vetted with IP counsel.
- `enhanced_aitools_with_KG_NLP_DPO`, Nov 2025 — KG + NLP + DPO concept
- `file_metadata_tool`, 2025 — LDA compression experiment
- `auto_knowledge_graph`, 2025 — KG from recorded work
- `file_metadata_and_embeddings`, 2025–2026 — this project
