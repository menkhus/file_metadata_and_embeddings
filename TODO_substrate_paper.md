# TODO — Substrate Engineering Paper + Implementation

*Filed April 2026. Two tracks: implementation and paper writing.*
*Paper outline: `PAPER_OUTLINE.md`*
*Enhancement details: `ENHANCEMENT_REQUEST_autogrounding_layer.md`*

---

## Track 1 — Core DB Infrastructure

- [ ] Design final schema — sessions, nodes, edges, signals, nodes_fts
      (draft in ENHANCEMENT_REQUEST_autogrounding_layer.md Enhancement 3)
- [ ] Create `substrate_db.py` — DB init, schema creation, connection manager
- [ ] Migrate autograph KG from CSV (nodes.csv, edges.csv) into SQLite
- [ ] Wire file_metadata content_analysis (LDA, TF-IDF) as first feed
      — on index run, write nodes to substrate DB
- [ ] Wire ghost as feed — on ghost archive, write file node to DB
- [ ] Wire uaish as feed — on session end, write session node + keywords
      (coordinate with `~/src/universal_ai_shell_history/`)

---

## Track 2 — Autogrounding Hook

- [ ] `autoground_query.py` — given keyword list, query DB, return top-N nodes
      (this is the core primitive everything else uses)
- [ ] `autoground.py` — Stop hook: extract session keywords, query DB,
      call phi4 via aifilter to render prior_art_notes.md
- [ ] Behavior file: `summarize_prior_art.txt` — terse, file paths + one-liners,
      max 20 lines, grouped by internal/external/unpublished
- [ ] Add `Stop` hook entry to `~/.claude/settings.json`
- [ ] Test: run a session, verify prior_art_notes.md written to cwd
- [ ] Test: start next session, verify Claude picks up prior_art_notes.md

---

## Track 3 — Search Bridge (Signal Detection)

- [ ] `extract_idea_signatures.py` — aggregate LDA + TF-IDF keywords
      per project directory from content_analysis table
- [ ] `signal_searcher.py` — query arXiv API + Semantic Scholar
      using idea signature keywords, return papers with date + abstract
- [ ] `signal_annotator.py` — write returned papers as nodes + edges to DB
      set is_new=1 on first detection
- [ ] Schedule via launchd — weekly, writes new signals to DB
- [ ] Test: run signal searcher on uaish project keywords, inspect results
- [ ] Test: run again after one week, verify is_new detection works

---

## Track 4 — MCP Tool

- [ ] Add `ground_prompt(text)` tool to `mcp_server_fixed.py`
      — extracts keywords from text, queries DB, returns top-N context nodes
      — makes grounding accessible to all AI sessions via MCP
- [ ] Add `get_signals(keyword)` tool — returns new external matches for a keyword
- [ ] Add `add_session_node(cwd, keywords, session_id)` tool — feed from uaish

---

## Track 5 — Paper Experiment (Measurement)

- [ ] Baseline: collect 20 sessions without hook — count re-explanation turns
- [ ] With hook: collect 20 sessions — count re-explanation turns
- [ ] Claim 1 measurement: compare turn counts (re-explanation overhead)
- [ ] Claim 2 measurement: log cases where prior_art surfaced forgotten work
      — manual review, did it change the response?
- [ ] Claim 3 measurement: node count + edge density over 30 days
      — plot growth curve, measure retrieval precision on held-out prompts
- [ ] Write results section from measurements

---

## Track 6 — Paper Writing

- [ ] Write Section 1 prose — The Problem (cold start)
- [ ] Write Section 2 prose — The Substrate (schema, feeds)
- [ ] Write Section 3 prose — Self-labeling (keyword stability, why not embeddings)
- [ ] Write Section 4 prose — Search bridge (arXiv, signal detection)
- [ ] Write Section 5 prose — Autogrounding hook (carrying forward)
- [ ] Write Section 6 prose — Experiment and results
- [ ] Write Section 7 prose — Prior work comparison table
- [ ] Find and verify all citations [51]–[56] — check URLs still live
- [ ] Add HP 2015 system citation — describe as unpublished internal disclosure
- [ ] Cross-reference Gleanings paper: `~/src/universal_ai_shell_history/aifilter_notes.dir/PAPER_OUTLINE.md`

---

## Implementation Order (minimum viable grounding)

Items 1–5 deliver value immediately, before any paper writing:

1. `substrate_db.py` — schema + connection
2. `autoground_query.py` — core query primitive  
3. `summarize_prior_art.txt` behavior file
4. `autoground.py` — Stop hook script
5. Wire Stop hook in `~/.claude/settings.json`

After these five: every Claude session ends by writing prior_art_notes.md.
The next session is grounded. The loop is running.

Everything else (signal searcher, MCP tool, paper measurement) builds on top.
