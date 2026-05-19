#!/usr/bin/env python3
"""
find_most_similar_v2.py - pgvector Semantic Search Tool

Semantic search using pgvector cosine similarity over all-MiniLM-L6-v2 embeddings.
Returns results in LLM-consumable JSON format.

Usage:
    python find_most_similar_v2.py --query "error handling in python" --top_k 5 --json
    python find_most_similar_v2.py --query "authentication" --context 1 --json
    python find_most_similar_v2.py --status

Requirements:
    uv add sentence-transformers
"""

import argparse
import json
import os
import sys
from typing import List, Dict, Any, Optional

import psycopg2
import psycopg2.extras

_PG_DSN = (
    "host=localhost dbname=file_metadata user=postgres "
    f"password={os.environ.get('DB_PASSWORD', '')}"
)

DEFAULT_MODEL = "all-MiniLM-L6-v2"

try:
    from sentence_transformers import SentenceTransformer as _SentenceTransformer
    DEPS_AVAILABLE = True
except ImportError:
    _SentenceTransformer = None  # type: ignore[assignment, misc]
    DEPS_AVAILABLE = False


def _get_conn():
    conn = psycopg2.connect(_PG_DSN)
    conn.autocommit = True
    return conn


class SemanticSearchV2:
    """Semantic search using pgvector cosine similarity."""

    def __init__(self, model_name: str = DEFAULT_MODEL):
        if not DEPS_AVAILABLE or _SentenceTransformer is None:
            raise ImportError(
                "sentence-transformers not installed. Run: uv add sentence-transformers"
            )
        self.model_name = model_name
        self._model: Optional[Any] = None

    def _get_model(self) -> Any:
        if self._model is None:
            assert _SentenceTransformer is not None
            print(f"Loading model: {self.model_name} ...", file=sys.stderr)
            self._model = _SentenceTransformer(self.model_name)
        return self._model

    def search(
        self,
        query: str,
        top_k: int = 5,
        include_context: int = 0
    ) -> List[Dict[str, Any]]:
        model = self._get_model()
        embedding = model.encode([query])[0].tolist()
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"

        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        tc.file_path,
                        tc.chunk_index,
                        tc.content,
                        tc.metadata,
                        tc.chunk_strategy,
                        tc.chunk_size,
                        tc.total_chunks,
                        tc.file_hash,
                        fm.file_type,
                        fm.last_modified,
                        fm.file_size,
                        1 - (tc.embedding <=> %s::vector) AS similarity
                    FROM text_chunks tc
                    JOIN file_metadata fm ON tc.file_path = fm.file_path
                    WHERE tc.embedding IS NOT NULL
                    ORDER BY tc.embedding <=> %s::vector
                    LIMIT %s
                """, [vec_str, vec_str, top_k])
                rows = cur.fetchall()

            results = []
            for rank, row in enumerate(rows, 1):
                extra_meta = row.get('metadata') or {}
                result = {
                    'rank': rank,
                    'similarity_score': float(row['similarity']),
                    'file_path': row['file_path'],
                    'chunk_index': row['chunk_index'],
                    'chunk_text': row['content'],
                    'metadata': {
                        'file_name': os.path.basename(row['file_path']),
                        'file_type': row['file_type'] or '',
                        'file_size': row['file_size'] or 0,
                        'modified_date': str(row['last_modified'])[:10] if row['last_modified'] else '',
                        'total_chunks': row['total_chunks'],
                        'chunk_strategy': row['chunk_strategy'],
                        **extra_meta,
                    },
                    'search_metadata': {
                        'query': query,
                        'search_method': 'pgvector_cosine',
                        'model': self.model_name,
                    }
                }

                if include_context > 0:
                    result['context_chunks'] = self._get_adjacent_chunks(
                        conn, row['file_path'], row['chunk_index'],
                        before=include_context, after=include_context
                    )

                results.append(result)
        finally:
            conn.close()

        return results

    def _get_adjacent_chunks(
        self,
        conn: psycopg2.extensions.connection,
        file_path: str,
        chunk_index: int,
        before: int = 1,
        after: int = 1
    ) -> List[Dict[str, Any]]:
        start_idx = max(0, chunk_index - before)
        end_idx = chunk_index + after

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT chunk_index, content
                FROM text_chunks
                WHERE file_path = %s
                  AND chunk_index BETWEEN %s AND %s
                  AND chunk_index != %s
                ORDER BY chunk_index
            """, [file_path, start_idx, end_idx, chunk_index])
            return [
                {'chunk_index': r['chunk_index'], 'chunk_text': r['content']}
                for r in cur.fetchall()
            ]

    def get_stats(self) -> Dict[str, Any]:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM text_chunks WHERE embedding IS NOT NULL")
                embedded = (cur.fetchone() or (0,))[0]
                cur.execute("SELECT COUNT(*) FROM text_chunks")
                total = (cur.fetchone() or (0,))[0]
        finally:
            conn.close()
        return {'embedded_chunks': embedded, 'total_chunks': total}

    def format_for_llm(self, results: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
        stats = self.get_stats()

        if not results:
            return {
                'status': 'no_results',
                'query_metadata': {
                    'query': query,
                    'total_results': 0,
                    'message': 'No matching chunks found'
                },
                'index_info': stats,
                'results': []
            }

        return {
            'status': 'success',
            'query_metadata': {
                'query': query,
                'total_results': len(results),
                'search_type': 'pgvector_cosine',
                'model': self.model_name,
            },
            'index_info': stats,
            'results': results,
            'usage_hints': {
                'accessing_content': 'results[i].chunk_text',
                'accessing_metadata': 'results[i].metadata',
                'similarity_score': 'results[i].similarity_score (0-1, higher is better)',
                'context_chunks': 'results[i].context_chunks (if requested)',
                'note': 'Results are ordered by cosine similarity (best match first)'
            },
            'summary': {
                'files_matched': len(set(r['file_path'] for r in results)),
                'avg_similarity_score': sum(r['similarity_score'] for r in results) / len(results),
                'top_match_file': results[0]['file_path'],
                'top_match_score': results[0]['similarity_score'],
                'has_context': any('context_chunks' in r for r in results)
            }
        }


def main():
    parser = argparse.ArgumentParser(
        description="Semantic search with pgvector (LLM-optimized output)",
    )
    parser.add_argument('--query', help='Semantic search query')
    parser.add_argument('--top_k', type=int, default=5, help='Number of top results')
    parser.add_argument('--context', type=int, default=0, help='Number of adjacent chunks to include')
    parser.add_argument('--model', default=DEFAULT_MODEL, help='Sentence transformer model')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON output')
    parser.add_argument('--status', action='store_true', help='Show embedding status')

    args = parser.parse_args()

    if not DEPS_AVAILABLE:
        print(json.dumps({
            'status': 'error',
            'error': 'sentence-transformers not installed',
            'install': 'uv add sentence-transformers'
        }, indent=2), file=sys.stderr)
        sys.exit(1)

    try:
        searcher = SemanticSearchV2(args.model)
    except Exception as e:
        print(json.dumps({'status': 'error', 'error': str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)

    if args.status:
        stats = searcher.get_stats()
        print(f"pgvector Embedding Status:")
        print(f"  Embedded chunks: {stats['embedded_chunks']:,} / {stats['total_chunks']:,}")
        sys.exit(0)

    if not args.query:
        parser.error("--query is required for search (or use --status)")

    try:
        results = searcher.search(
            query=args.query,
            top_k=args.top_k,
            include_context=args.context
        )

        if args.json:
            output = searcher.format_for_llm(results, args.query)
            indent = 2 if args.pretty else None
            print(json.dumps(output, indent=indent, default=str, ensure_ascii=False))
        else:
            if not results:
                print(f"No results found for: '{args.query}'")
                return

            print(f"Semantic search for: '{args.query}'")
            print(f"Model: {args.model}\n")

            for result in results:
                print(f"{'='*60}")
                print(f"Rank {result['rank']} (similarity: {result['similarity_score']:.4f})")
                print(f"File: {result['file_path']}")
                print(f"Chunk: {result['chunk_index']}/{result['metadata']['total_chunks'] - 1}")
                print(f"Type: {result['metadata']['file_type']}")
                content = result['chunk_text']
                preview = content[:300] + "..." if len(content) > 300 else content
                print(f"\nContent preview:\n  {preview}")
                if result.get('context_chunks'):
                    print(f"\nContext chunks: {len(result['context_chunks'])}")
                print()

    except Exception as e:
        print(json.dumps({
            'status': 'error',
            'error': str(e),
            'type': type(e).__name__
        }, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
