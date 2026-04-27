# TODO — Substrate Engineering Paper + Implementation

*Filed April 2026. Two tracks: implementation and paper writing.*
*Paper outline: `PAPER_OUTLINE.md`*
*Enhancement details: `ENHANCEMENT_REQUEST_autogrounding_layer.md`*
*Last updated: 2026-04-27 — session-start-ground, dual-pool A+B, path fixes, uptake metric*

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
- [x] Test: run a session, verify prior_art_notes.md written to cwd
- [x] Test: start next session, verify Claude picks up prior_art_notes.md
- [x] **session-start-ground.py** (2026-04-27) — replace Stop hook approach with
      SessionStart hook. Reads previous session transcript directly. Dual-pool:
      Pool A = last 10 user prompts, Pool B = last 5 assistant responses.
      A+B confirmed keywords lead the merged query. More reliable than Stop hook
      (deterministic at session open, no dependency on prior session cleanup).
      Wired in ~/.claude/settings.json SessionStart hooks.
- [x] Retire autoground.py from Stop hooks — session-start-ground.py supersedes it.
      autoground.py kept on disk as reference.

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
- [x] **A/B pool matching (2026-04-10, completed 2026-04-27)** — Pool A (prompt)
      and Pool B (response) matched independently against substrate DB. A+B
      confirmed nodes weighted 3×, A-only 2×, B-only 1×. Staleness penalty
      prevents injection feedback loops. Implemented in prompt-ground.py (per-prompt)
      and session-start-ground.py (cross-session, previous transcript).
- [ ] **Uptake measurement (2026-04-27)** — does injected context actually influence
      the model? Add uptake_count field to session state in prompt-ground.py.
      Increment when a previously-injected node's label/path appears in Pool B
      keywords on a subsequent turn. Uptake rate = uptake_count / shown_count
      per session. Log to substrate DB sessions table. After 30 sessions, compare
      uptake rate distribution to determine if the machinery is live or inert.
      This is the minimum credible evidence that grounding is working.

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

- [x] **Rolling within-session dual-pool delta (2026-04-27, high impact)** —
      every 10 turns, inject a diff of the session node state as an additional
      context block. NOT a file rewrite — prior_art_notes.md stays as the stable
      cross-session anchor. The delta is ephemeral: injected in additionalContext
      at turn 10, 20, 30... visible to the model at that moment only.

      Scope separation:
        prior_art_notes.md = cross-session anchor (written at startup, read next session)
        ## Autoground Delta block = within-session signal (transient, not persisted)

      Delta categories (both pools, from live session state):
        - Newly confirmed A+B: both pools now agree, neither did at last snapshot
        - Promoted A→A+B: model started activating a prompt-declared concept
        - Persistent B-only: model keeps surfacing unprompted — highest interest signal
        - Faded: matched early, not seen in last 10 turns — session moved on

      Implementation: snapshot node state at turn 0 and every 10 turns. Diff
      current snapshot against previous. Session state dict already has a_count,
      b_count, last_turn per node — delta falls out naturally. Keep only last 2
      snapshots to bound state file size. Inject formatted delta block alongside
      existing ## Autoground Context block in prompt-ground.py main().

      Risk: may confuse the model if the delta is noisy or contradicts context.
      Monitor prompt-ground.log for turn % 10 entries. Easy to disable by setting
      DELTA_INTERVAL = 0.

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

- [ ] **Core thesis — document before writing sections (2026-04-27):**
      The context window is not misaligned — it is complete and correct for what
      it contains. The problem is not context quality, it is context *continuity*
      across session boundaries. What is lost at session close is train of thought:
      the accumulated vocabulary, the decisions made, the direction the reasoning
      was heading. The model cannot carry that forward because it has no persistence.
      This system externalizes train of thought into retrievable artifacts
      (prior_art_notes.md, session chain, dual-pool keyword state) and re-injects
      it at session open and at rolling intervals within a session. The context
      window then has what it needs to reason as if the session is continuous.
      The LLM is not pretending to remember — it is reasoning correctly from
      complete context. We are the ones responsible for making that context complete.
      Framing consequence: the evaluation question is not "does the model remember?"
      It is "is the re-injected train of thought sufficient for the model to reason
      continuously, and does that reduce friction for the user?" Those are measurable.
      This also cleanly separates the work from memory-augmented LLM research
      (which targets persistence inside the model) and positions it as external
      train-of-thought continuity infrastructure — a different and more tractable claim.

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
