#!/usr/bin/env python3
"""
find_most_similar_v2.py - JSONB-aware Semantic Search Tool

Semantic search using embeddings with JSONB chunk envelopes.
Returns results in LLM-consumable JSON format.

Usage:
    python find_most_similar_v2.py --query "error handling in python" --top_k 5 --json
    python find_most_similar_v2.py --query "authentication" --context 1 --json

Features:
    - Semantic search using sentence-transformers embeddings
    - Returns complete chunk envelopes with metadata
    - Optional adjacent chunk context retrieval
    - LLM-optimized JSON output format
"""

import argparse
import sqlite3
import json
import sys
from typing import List, Dict, Any, Optional
from pathlib import Path

try:
    import numpy as np
    import faiss
    from sentence_transformers import SentenceTransformer
    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from chunking_refactor import ChunkEnvelope


class SemanticSearchV2:
    """Semantic search with JSONB chunk support"""

    def __init__(self, db_path: str = "file_metadata.db", model_name: str = 'all-MiniLM-L6-v2'):
        if not DEPS_AVAILABLE:
            raise ImportError("Required packages not installed. Run: pip install faiss-cpu numpy sentence-transformers")

        self.db_path = db_path
        self.model_name = model_name
        self.model = None
        self.index = None
        self.metadata_cache = []

    def load_embeddings(self) -> bool:
        """Load embeddings from database and build FAISS index"""
        uri = f'file:{self.db_path}?mode=ro'
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Load from text_chunks_v2 table (embeddings stored as BLOB)
        cursor.execute('''
            SELECT
                id,
                file_path,
                chunk_index,
                chunk_envelope,
                embedding
            FROM text_chunks_v2
            WHERE embedding IS NOT NULL
            ORDER BY file_path, chunk_index
        ''')

        vectors = []
        self.metadata_cache = []

        for row in cursor.fetchall():
            # Deserialize embedding from BLOB
            embedding_blob = row['embedding']
            if embedding_blob:
                vector = np.frombuffer(embedding_blob, dtype='float32')
                vectors.append(vector)

                self.metadata_cache.append({
                    'id': row['id'],
                    'file_path': row['file_path'],
                    'chunk_index': row['chunk_index'],
                    'chunk_envelope': row['chunk_envelope']
                })

        conn.close()

        if not vectors:
            return False

        # Build FAISS index
        vectors_array = np.vstack(vectors).astype('float32')
        dim = vectors_array.shape[1]
        self.index = faiss.IndexFlatL2(dim)
        self.index.add(vectors_array)

        return True

    def search(
        self,
        query: str,
        top_k: int = 5,
        include_context: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Semantic search for similar chunks

        Args:
            query: Search query string
            top_k: Number of top results to return
            include_context: Number of adjacent chunks to include

        Returns:
            List of result dicts with chunk envelopes and similarity scores
        """
        if self.model is None:
            print(f"Loading model: {self.model_name} ...", file=sys.stderr)
            self.model = SentenceTransformer(self.model_name)

        if self.index is None:
            print("Loading embeddings from database ...", file=sys.stderr)
            if not self.load_embeddings():
                raise ValueError("No embeddings found in database. Run embedding generation first.")

        # Encode query
        query_vec = self.model.encode([query]).astype('float32')

        # Search FAISS index
        distances, indices = self.index.search(query_vec, top_k)

        results = []
        uri = f'file:{self.db_path}?mode=ro'
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row

        for rank, (idx, distance) in enumerate(zip(indices[0], distances[0]), 1):
            meta = self.metadata_cache[idx]

            # Parse chunk envelope
            envelope = ChunkEnvelope.from_json(meta['chunk_envelope'])

            result = {
                'rank': rank,
                'similarity_distance': float(distance),
                'similarity_score': float(1 / (1 + distance)),  # Convert distance to similarity
                'chunk_envelope': json.loads(meta['chunk_envelope']),
                'search_metadata': {
                    'file_path': meta['file_path'],
                    'chunk_index': meta['chunk_index'],
                    'query': query,
                    'search_method': 'semantic_embedding'
                }
            }

            # Add context chunks if requested
            if include_context > 0:
                context_chunks = self._get_adjacent_chunks(
                    conn,
                    meta['file_path'],
                    meta['chunk_index'],
                    before=include_context,
                    after=include_context
                )
                result['context_chunks'] = context_chunks

            results.append(result)

        conn.close()
        return results

    def _get_adjacent_chunks(
        self,
        conn: sqlite3.Connection,
        file_path: str,
        chunk_index: int,
        before: int = 1,
        after: int = 1
    ) -> List[Dict[str, Any]]:
        """Get adjacent chunks for context"""
        cursor = conn.cursor()

        start_idx = max(0, chunk_index - before)
        end_idx = chunk_index + after

        cursor.execute('''
            SELECT chunk_envelope, chunk_index
            FROM text_chunks_v2
            WHERE file_path = ?
              AND chunk_index BETWEEN ? AND ?
              AND chunk_index != ?
            ORDER BY chunk_index
        ''', (file_path, start_idx, end_idx, chunk_index))

        context = []
        for row in cursor.fetchall():
            context.append({
                'chunk_index': row['chunk_index'],
                'chunk_envelope': json.loads(row['chunk_envelope'])
            })

        return context

    def format_for_llm(self, results: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
        """Format results for LLM consumption"""
        if not results:
            return {
                'status': 'no_results',
                'query_metadata': {
                    'query': query,
                    'total_results': 0,
                    'message': 'No matching chunks found (embeddings may not be generated yet)'
                },
                'results': []
            }

        return {
            'status': 'success',
            'query_metadata': {
                'query': query,
                'total_results': len(results),
                'search_type': 'semantic_similarity',
                'model': self.model_name,
                'database': self.db_path,
                'index_size': len(self.metadata_cache)
            },
            'results': results,
            'usage_hints': {
                'accessing_content': 'results[i].chunk_envelope.content',
                'accessing_metadata': 'results[i].chunk_envelope.metadata',
                'similarity_score': 'results[i].similarity_score (0-1, higher is better)',
                'similarity_distance': 'results[i].similarity_distance (L2 distance, lower is better)',
                'context_chunks': 'results[i].context_chunks (if requested)',
                'note': 'Results are ordered by similarity (best match first)'
            },
            'summary': {
                'files_matched': len(set(r['search_metadata']['file_path'] for r in results)),
                'avg_similarity_score': sum(r['similarity_score'] for r in results) / len(results),
                'top_match_file': results[0]['search_metadata']['file_path'],
                'top_match_score': results[0]['similarity_score'],
                'has_context': any('context_chunks' in r for r in results)
            }
        }


def main():
    parser = argparse.ArgumentParser(
        description="Semantic search with JSONB chunks (LLM-optimized output)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic semantic search
  python find_most_similar_v2.py --query "error handling" --json

  # Search with context (±1 chunks)
  python find_most_similar_v2.py --query "authentication logic" --context 1 --json

  # Top 10 results
  python find_most_similar_v2.py --query "database connection" --top_k 10 --json

Requirements:
  pip install faiss-cpu numpy sentence-transformers
        """
    )
    parser.add_argument('--db', default='file_metadata.db', help='Path to SQLite database')
    parser.add_argument('--query', required=True, help='Semantic search query')
    parser.add_argument('--top_k', type=int, default=5, help='Number of top results')
    parser.add_argument('--context', type=int, default=0, help='Number of adjacent chunks to include')
    parser.add_argument('--model', default='all-MiniLM-L6-v2', help='Sentence transformer model')
    parser.add_argument('--json', action='store_true', help='Output as JSON (default: human-readable)')
    parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON output')

    args = parser.parse_args()

    if not DEPS_AVAILABLE:
        print(json.dumps({
            'status': 'error',
            'error': 'missing_dependencies',
            'message': 'Required packages not installed',
            'install': 'pip install faiss-cpu numpy sentence-transformers'
        }, indent=2), file=sys.stderr)
        sys.exit(1)

    searcher = SemanticSearchV2(args.db, args.model)

    try:
        results = searcher.search(
            query=args.query,
            top_k=args.top_k,
            include_context=args.context
        )

        if args.json:
            # LLM-consumable JSON output
            output = searcher.format_for_llm(results, args.query)
            indent = 2 if args.pretty else None
            print(json.dumps(output, indent=indent, ensure_ascii=False))
        else:
            # Human-readable output
            if not results:
                print("No results found.")
                return

            print(f"Semantic search for: '{args.query}'")
            print(f"Model: {args.model}")
            print(f"Index size: {len(searcher.metadata_cache)} chunks\n")

            for result in results:
                envelope = result['chunk_envelope']
                metadata = envelope['metadata']

                print(f"{'='*60}")
                print(f"Rank {result['rank']} (similarity: {result['similarity_score']:.4f})")
                print(f"{'='*60}")
                print(f"File: {result['search_metadata']['file_path']}")
                print(f"Chunk: {metadata['chunk_index']}/{metadata['total_chunks'] - 1}")
                print(f"Strategy: {metadata['chunk_strategy']}")
                print(f"Size: {metadata['chunk_size']} chars")
                print(f"\nContent preview:")
                content = envelope['content']
                preview = content[:200] + "..." if len(content) > 200 else content
                print(f"  {preview}")

                if 'context_chunks' in result and result['context_chunks']:
                    print(f"\nContext chunks: {len(result['context_chunks'])}")

                print()

    except ValueError as e:
        print(json.dumps({
            'status': 'error',
            'error': str(e),
            'hint': 'Generate embeddings first or check if text_chunks_v2 table exists'
        }, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            'status': 'error',
            'error': str(e),
            'type': type(e).__name__
        }, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
