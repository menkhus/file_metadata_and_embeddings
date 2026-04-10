# Session Notes — 2026-04-10

## What was built

- `extract_idea_signatures.py` — bootstraps substrate DB from file_metadata index
- Global IDF correction — reweights per-file TF-IDF scores against full 32K-file corpus
- `corpus_size` stamped in node metadata — IDF staleness detectable
- `prompt-ground.py` — Python fallback for keyword extraction, session-level dedup
- Substrate DB populated: 393 nodes (62 projects, 273 files)

---

## The design conversation — what emerged

### The grounding system's actual purpose

Not retrieval. Not RAG. **Situating the model in a specific person's accumulated thought.**

RAG asserts: "this is relevant, read it." Heavy. Displaces reasoning.
This system hints: "these are adjacent, consider them." Shallow, broad, non-mandatory.
The hints are not for the user. They are fuel for B.

### A and B pools

**Pool A — prompt text.** The user's conscious intent. Declared signal. Already grounded — the user carries their own context. A doesn't need the hints.

**Pool B — generated text.** What the model activated in response. Interpreted signal. Starts cold every session. Impoverished without situating. **B is what the hints are for.**

Matching against B captures what actually got discussed, not just what was asked.
The model's elaboration expands the semantic scope of A — B contains concepts the user implied but didn't state.

### The A/B divergence signal

- **High A, low B** — user keeps asking about something responses don't engage with. Grounding failure or redirection.
- **High B, low A** — model keeps elaborating on something unprompted. Latent concept the session keeps activating without naming. Most interesting case.
- **Confirmed in both** — highest confidence. Intent and elaboration agree.

Watch for feedback loops: if grounding injects a node and B keeps mentioning it, that's the system talking to itself, not a genuine signal.

### Focus, not attention

Attention recomputes from scratch every forward pass. Doesn't commit.

What accumulates across session prompts is **focus** — an active set that narrows over time as terms are confirmed or fall out. Early turns: broad, exploratory. Late turns: 2-3 nodes that survived repeated confirmation from different keyword angles.

Weight = recency × cross-prompt frequency. Clip what the session stopped asking about.

### Working memory

The active set maintained by rehearsal, lost when rehearsal stops. Biological analogue is working memory, not attention.

A node that survives 30 turns of different keyword paths via both A and B is almost certainly central to the session's work — not because it was asserted, but because it kept surviving.

### Bias, discipline, and the honest critique

The system amplifies whatever intellectual pattern the user brings. Productive curiosity, genuine depth, but also bias and fixation. Structurally identical in this model.

The safeguard is user honesty — the ability to say "I wrote that, I don't believe it now" and deselect. Without that, the substrate DB becomes a monument to past thinking, not a tool for current thinking.

**Deliberate retention under uncertainty is not bias.** Holding an idea consciously, knowing you're holding it, until evidence is strong enough to justify release — that is intellectual integrity. The threshold is evidence, not comfort or consensus.

A concept held for years with high match frequency but low downstream connection is a flag: something in suspension. Not noise to clip — a thread being watched.

### The emergent case

Sometimes neither A nor B holds the new idea yet. It's forming in the gap between the two across the session. The substrate DB fires sparsely. The active set thins. The hints get left behind.

That's the right behavior. The system shouldn't try to ground what hasn't been thought before. Sparse matching late in a session that started rich means the session went somewhere genuinely new.

The model has depth and currency the user doesn't — training data never read, cross-domain patterns. The user has what the model doesn't — felt sense of wrongness, willingness to hold unresolved ideas, intuition from building things and watching them fail. The session is where they meet. The grounding system's job is to make that meeting start from a better position.

---

## TODO — A/B pool matching

Add to Track 5 in `TODO_substrate_paper.md`:

- [ ] **A/B pool matching** — currently only Pool A (prompt text) is extracted for
      keywords and matched against the substrate DB. Add Pool B (generated text /
      model response) as a second match source.
      - Capture model response text from the hook payload or transcript
      - Extract keywords from B independently
      - Track A-match count and B-match count separately per node per session
      - Weight: A+B match in same turn > A-only > B-only
      - B-only persistent matches are the most interesting signal — concept the
        model keeps activating unprompted. Surface these separately.
      - Watch for feedback loops: injected node appearing in B is self-referential,
        not genuine signal.

- [ ] **Session active set with recency decay** — change seen tracker from binary
      set to weighted counter: {node_id: (match_count, last_seen_turn)}.
      Weight = frequency × recency. Clip nodes whose recency-weighted score
      falls below threshold. Active set narrows naturally as session focuses.
      Early turns inject freely. Later turns inject only confirmed survivors.

- [ ] **Node states** — extend substrate DB nodes with an explicit state field:
      active | suspended | superseded | resolved. Suspended = held deliberately
      pending evidence. Superseded = explicitly replaced by newer thinking.
      Hints carry state into B: not just "you worked on this" but "you've been
      watching this unresolved for two years."
