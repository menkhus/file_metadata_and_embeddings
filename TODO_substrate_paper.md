# TODO — Substrate Engineering Paper + Implementation

*Filed April 2026. Two tracks: implementation and paper writing.*
*Paper outline: `PAPER_OUTLINE.md`*
*Enhancement details: `ENHANCEMENT_REQUEST_autogrounding_layer.md`*
*Last updated: 2026-04-09 — evening session*

---

## NOW — Minimum Viable Grounding (do these five, in order)

- [x] 1. `substrate_db.py` — schema + connection manager
- [x] 2. `autoground_query.py` — core query primitive (keywords in, matching nodes out)
- [x] 3. `summarize_prior_art.txt` — aifilter behavior file (renders DB results as terse notes)
- [x] 4. `autoground.py` — Stop hook script (queries DB, calls phi4, writes prior_art_notes.md)
- [x] 5. Wire Stop hook in `~/.claude/settings.json`

After these five: every session ends by writing prior_art_notes.md. The loop is running.

---

## DONE (2026-04-09 evening session)

- [x] `extract_idea_signatures.py` — reads file_metadata.sqlite3, aggregates TF-IDF
      keywords per project, writes 346 nodes (62 projects + 273 files) to substrate DB.
      Substrate DB now populated for the first time. Grounding is live.
- [x] `prompt-ground.py` — UserPromptSubmit hook: extracts keywords, queries substrate DB,
      injects matching prior-work nodes as additionalContext before each prompt.
      Wired in `~/.claude/settings.json`.
- [x] Python fallback for keyword extraction — `prompt-ground.py` no longer requires
      Ollama/phi4 to be running; falls back to stopword-filtered token extraction.
- [x] Session-level dedup — `prompt-ground.py` tracks seen node IDs per session
      (in `~/.claude/logs/prompt-ground-seen/`). Same references won't repeat within
      a session. Over-fetches then filters.
- [x] Noise keyword filter — `extract_idea_signatures.py` drops filename-fragment
      keywords (length > 40, ends with extension, low alpha ratio).

---

## Track 1 — Core DB Infrastructure

- [x] Design final schema — sessions, nodes, edges, signals, nodes_fts
      (draft in ENHANCEMENT_REQUEST_autogrounding_layer.md Enhancement 3)
- [x] Create `substrate_db.py` — DB init, schema creation, connection manager
- [ ] Migrate autograph KG from CSV (nodes.csv, edges.csv) into SQLite
- [ ] Wire file_metadata content_analysis (LDA, TF-IDF) as first feed
      — on index run, write nodes to substrate DB
- [ ] Wire ghost as feed — on ghost archive, write file node to DB
- [ ] Wire uaish as feed — on session end, write session node + keywords
      (coordinate with `~/src/universal_ai_shell_history/`)

---

## Track 2 — Prompt Micro-Processing Behaviors

- [x] `keyword_extract.txt` — behavior: extract intent keywords from short prompt
      phi4, single shot, returns noun/verb keyword list, no LDA needed
- [x] `ground_prompt.txt` — behavior: receive prompt + DB context nodes,
      prepend prior work as structured grounding context
- [x] `clean_and_tighten.txt` — behavior: fix spelling, grammar, tighten intent
      absorbs spell-check — phi4 does it better in one pass than aspell separately
- [x] `summarize_prior_art.txt` — behavior: render DB query results as terse
      prior_art_notes.md — file paths, one-liners, max 20 lines
- [ ] Test pipe: `echo "prompt" | aifilter -b keyword_extract | autoground_query
      | aifilter -b ground_prompt | aifilter -b clean_and_tighten`
- [ ] Verify: raw prompt in → clean grounded prompt out

---

## Track 3 — Autogrounding Hook

- [x] `autoground_query.py` — given keyword list, query DB, return top-N nodes
      (this is the core primitive everything else uses)
- [x] `autoground.py` — Stop hook: extract session keywords, query DB,
      call phi4 via aifilter to render prior_art_notes.md
- [x] Behavior file: `summarize_prior_art.txt` — terse, file paths + one-liners,
      max 20 lines, grouped by internal/external/unpublished
- [x] Add `Stop` hook entry to `~/.claude/settings.json`
- [ ] Test: run a session, verify prior_art_notes.md written to cwd
- [ ] Test: start next session, verify Claude picks up prior_art_notes.md

---

## Track 3 — Search Bridge (Signal Detection)

- [x] `extract_idea_signatures.py` — aggregate LDA + TF-IDF keywords
      per project directory from content_analysis table
- [ ] Schedule `extract_idea_signatures.py` via launchd — weekly re-population
      so new indexed projects get picked up automatically
- [ ] `signal_searcher.py` — query arXiv API + Semantic Scholar
      using idea signature keywords, return papers with date + abstract
- [ ] `signal_annotator.py` — write returned papers as nodes + edges to DB
      set is_new=1 on first detection
- [ ] Schedule via launchd — weekly, writes new signals to DB
- [ ] Test: run signal searcher on uaish project keywords, inspect results
- [ ] Test: run again after one week, verify is_new detection works

---

## Track 4 — Shell/Script Tools (NOT MCP — hooks and scripts preferred)

MCP is overkill for per-prompt grounding: it eats tokens unnecessarily.
Grounding stays in hooked scripts. Track 4 is standalone CLI tools only.

- [ ] `autoground` CLI — thin wrapper calling autoground_query.py for use in
      aifilter pipes: `echo "prompt" | aifilter -b keyword_extract | autoground`
- [ ] `get_signals` CLI — query substrate DB for new_signals, stdout for review
- [ ] Wire `uaish` session-end → write session node to substrate DB
      (coordinate with `~/src/universal_ai_shell_history/`)

---

## Track 5 — Operational Maturity (from operational_problems.md, 2026-04-09)

- [ ] Store indexer configuration in the database — which directories are watched,
      which file types are indexed, which processing stages have run and when.
      Currently implicit (hardcoded paths, no record of what was done).
- [ ] Document all DB schemas — file_metadata.sqlite3 and substrate.sqlite3 —
      in a single SCHEMA.md with column-level descriptions. Make them self-describing.
- [ ] Self-throttle during indexing — index runs should never be disruptive.
      Implement sleep-between-batch with CPU/IO load detection.
- [x] Noise keyword filter — drop filename fragments, long terms, low alpha ratio.
- [x] **TF-IDF global IDF fix (hard-fought finding, 2026-04-09):**
      The indexer fits TfidfVectorizer per-file on that file's own chunks.
      IDF is computed within one document, not across the corpus.
      Result: "AI", "code", "function" score high because they're distinctive
      within a single file — but they appear in thousands of files and should
      score near zero. The total linguistic space (all 40K files) must be the
      IDF reference denominator.
      Fixed in extract_idea_signatures.py: build_global_idf() computes
      document-frequency counts across all 32K files, then reweights each
      project's term scores by global IDF = log(N / df).
      corpus_size stamped into every node's metadata so staleness is detectable.
- [ ] **IDF corpus drift (known property, not a bug):**
      As more files are indexed, N grows and all IDF values shift. Terms rare
      today become less distinctive as the corpus expands. This is how IDF works.
      Mitigation: corpus_size stored in node metadata. Re-run extract_idea_signatures.py
      when indexed file count grows by ~10% (currently N=32,152 → re-run at ~35,400).
      The scheduled launchd job (Track 3) handles this automatically.
      Longer-term: consider normalizing IDF by log(N) to make scores comparable
      across corpus sizes, or switch to BM25 which has better large-corpus behavior.
- [ ] **A/B pool matching (2026-04-10)** — currently only Pool A (prompt text) is
      matched against the substrate DB. Add Pool B (generated/response text) as
      a second independent source. Track A-match and B-match counts separately
      per node per session. Weight: A+B same turn > A-only > B-only.
      B-only persistent matches are the most interesting signal — concept the
      model keeps activating unprompted. Watch for feedback loops (injected node
      reappearing in B is self-referential noise, not genuine signal).
      See SESSION_NOTES_2026-04-10.md for full design rationale.

- [ ] **Session active set with recency decay** — change seen tracker from binary
      set to weighted counter {node_id: (match_count, last_seen_turn)}.
      Weight = frequency × recency. Clip what the session stopped asking about.
      Active set narrows naturally as work focuses. Early turns: inject broadly.
      Later turns: inject only confirmed survivors from both A and B pools.

- [ ] **Session active set as LoRA proxy (2026-04-10, high value idea):**
      The converged active set at session end is a low-dimensional semantic
      fingerprint of the session's domain. This is structurally what a LoRA
      adapter encodes — a low-rank delta that shifts the model toward a domain.
      The converged keyword distribution could serve as:
        a. A session label — write to substrate DB as the session node's keywords.
           "This session was about: [autograph, grounding, focus, dual-pool]"
        b. A LoRA training signal — session keyword fingerprints across many
           sessions on the same topic aggregate into a training distribution
           for a lightweight domain adapter (session-conditioned LoRA).
        c. A steering vector proxy — the keyword set as a sparse activation
           pattern that could inform inference-time steering without full LoRA.
      References: LoRA (Hu et al 2021), QLoRA, personalized LoRA literature,
      session-conditioned adaptation. This is an open research direction.
      Start simple: write converged active set to substrate DB session node.
      The LoRA connection is the long-term research direction.

- [ ] **Node states in substrate DB** — add state field: active | suspended |
      superseded | resolved. Suspended = held deliberately, pending evidence.
      Superseded = explicitly replaced by newer thinking. Hints carry state
      into B: not just "you worked on this" but "watched unresolved, 2 years."

- [ ] Test the full prompt pipeline end-to-end with phi4 running:
      `echo "prompt" | aifilter -b keyword_extract | autoground_query.py
       | aifilter -b ground_prompt | aifilter -b clean_and_tighten`
- [ ] Verify autoground.py Stop hook writes prior_art_notes.md on real session end
- [ ] Verify prompt-ground.py injects context Claude actually uses (check logs)

---

## Track 6 — Paper Experiment (Measurement)

- [ ] Baseline: collect 20 sessions without hook — count re-explanation turns
- [ ] With hook: collect 20 sessions — count re-explanation turns
- [ ] Claim 1 measurement: compare turn counts (re-explanation overhead)
- [ ] Claim 2 measurement: log cases where prior_art surfaced forgotten work
      — manual review, did it change the response?
- [ ] Claim 3 measurement: node count + edge density over 30 days
      — plot growth curve, measure retrieval precision on held-out prompts
- [ ] Write results section from measurements

---

## Track 7 — Paper Writing

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
