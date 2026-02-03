# Hybrid Search TODO

## Concept (2026-02-02)

Combine FTS5 (exact keyword matching) with FAISS semantic search (meaning similarity) to provide higher-quality search results than either alone.

**Why hybrid is valuable:**
- FTS finds exact matches semantic might miss ("config" finds "config" even if embeddings drift)
- Semantic finds conceptually related content FTS misses ("authentication" finds "login flow")
- Combined results surface documents that match both criteria → higher confidence

## Current State

**Separate tools exist:**
- `mcp__file-metadata__full_text_search` → FTS5 exact matches with snippets
- `mcp__file-metadata__semantic_search` → FAISS cosine similarity with scores

**Referenced in docs:**
- `tools_v2/README.md:462` - Listed as future enhancement
- `osx_support/ARCHITECTURE.md:357` - "Combine results when needed"

## Implementation Approach

### 1. Score Normalization

FTS5 and FAISS return incompatible score types:
- FTS5: BM25 rank (higher = better match, unbounded)
- FAISS: Cosine similarity (0.0 - 1.0, higher = more similar)

**Normalization options:**
```python
# Option A: Min-max normalize FTS scores to 0-1
fts_normalized = (score - min_score) / (max_score - min_score)

# Option B: Reciprocal rank (position-based, ignores raw scores)
rrf_score = 1 / (k + rank)  # k typically 60
```

### 2. Fusion Strategies

**Reciprocal Rank Fusion (RRF)** - Recommended for simplicity:
```python
def reciprocal_rank_fusion(fts_results, semantic_results, k=60):
    """Combine rankings using RRF. Position matters, not raw scores."""
    scores = defaultdict(float)

    for rank, result in enumerate(fts_results):
        scores[result.file_path] += 1 / (k + rank + 1)

    for rank, result in enumerate(semantic_results):
        scores[result.file_path] += 1 / (k + rank + 1)

    # Sort by combined score
    return sorted(scores.items(), key=lambda x: -x[1])
```

**Weighted Linear Combination** - When tuning matters:
```python
def weighted_fusion(fts_results, semantic_results, fts_weight=0.4, semantic_weight=0.6):
    """Combine normalized scores with weights."""
    # Normalize both to 0-1 range
    # Combine: final_score = fts_weight * fts_norm + semantic_weight * sem_norm
    pass
```

### 3. De-duplication

Same file may appear in both result sets:
```python
def merge_results(fts_results, semantic_results):
    """Merge by file_path, keeping best metadata from each."""
    seen = {}
    for r in fts_results + semantic_results:
        key = (r.file_path, r.chunk_index)
        if key not in seen:
            seen[key] = r
        else:
            # Merge: keep FTS snippet, semantic similarity score
            seen[key].snippet = r.snippet or seen[key].snippet
            seen[key].similarity = max(r.similarity, seen[key].similarity)
    return list(seen.values())
```

### 4. Implementation Location

**Option A: New MCP tool** (Recommended)
Add `hybrid_search` tool to `mcp_server_fixed.py`:
```python
@server.tool("hybrid_search")
async def hybrid_search(query: str, limit: int = 10, fts_weight: float = 0.4):
    """Combined FTS + semantic search with score fusion."""
    fts_results = await full_text_search(query, limit=limit*2)
    semantic_results = await semantic_search(query, limit=limit*2)
    fused = reciprocal_rank_fusion(fts_results, semantic_results)
    return fused[:limit]
```

**Option B: New V2 tool**
Create `tools_v2/find_hybrid_v2.py` following existing patterns.

### 5. Output Format

Follow existing JSON envelope pattern:
```json
{
  "status": "success",
  "query": "authentication flow",
  "method": "hybrid",
  "fusion_strategy": "rrf",
  "results": [
    {
      "file_path": "/path/to/auth.py",
      "chunk_index": 3,
      "hybrid_score": 0.0312,
      "fts_rank": 2,
      "semantic_rank": 1,
      "semantic_similarity": 0.72,
      "snippet": "def authenticate_user(..."
    }
  ],
  "hints": {
    "fts_matches": 8,
    "semantic_matches": 10,
    "overlap": 4
  }
}
```

## Testing Strategy

1. **Baseline comparison**: Same query against FTS-only, semantic-only, hybrid
2. **Edge cases**:
   - Query with no FTS matches (pure semantic)
   - Query with no semantic matches (pure keyword)
   - Exact filename match (FTS should dominate)
3. **Quality eval**: Manual review of top-10 for sample queries

## References

- Reciprocal Rank Fusion paper: Cormack et al., 2009
- `faiss_index_manager.py` - FAISS search implementation
- `mcp_server_fixed.py:full_text_search` - FTS implementation
