#!/usr/bin/env python3
"""
find_using_fts_v2.py - PostgreSQL Full-Text Search Tool

Full-text search over text_chunks using tsvector + websearch_to_tsquery.
Returns results in LLM-consumable JSON format.

Usage:
    python find_using_fts_v2.py --query "search phrase" --limit 10 --json
    python find_using_fts_v2.py --query "error handling" --context 1 --json
"""

import argparse
import json
import os
import sys
from typing import List, Dict, Any

import psycopg2
import psycopg2.extras

_PG_DSN = (
    "host=localhost dbname=file_metadata user=postgres "
    f"password={os.environ.get('DB_PASSWORD', '')}"
)


def _get_conn():
    conn = psycopg2.connect(_PG_DSN)
    conn.autocommit = True
    return conn


class FTSSearchV2:
    """Full-text search using PostgreSQL tsvector."""

    def search(
        self,
        query: str,
        limit: int = 10,
        include_context: int = 0
    ) -> List[Dict[str, Any]]:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        tc.id,
                        tc.file_path,
                        tc.chunk_index,
                        tc.content,
                        tc.metadata,
                        tc.chunk_strategy,
                        tc.chunk_size,
                        tc.total_chunks,
                        tc.file_hash,
                        ts_rank_cd(
                            to_tsvector('english', tc.content),
                            websearch_to_tsquery('english', %s)
                        ) AS rank,
                        ts_headline(
                            'english', tc.content,
                            websearch_to_tsquery('english', %s),
                            'MaxWords=20, MinWords=5, StartSel=**, StopSel=**'
                        ) AS snippet
                    FROM text_chunks tc
                    WHERE to_tsvector('english', tc.content)
                          @@ websearch_to_tsquery('english', %s)
                    ORDER BY rank DESC
                    LIMIT %s
                """, [query, query, query, limit])
                rows = cur.fetchall()

            results = []
            for row in rows:
                meta = row.get('metadata') or {}
                envelope = {
                    'content': row['content'],
                    'metadata': {
                        'file_path': row['file_path'],
                        'chunk_index': row['chunk_index'],
                        'total_chunks': row['total_chunks'],
                        'chunk_strategy': row['chunk_strategy'],
                        'chunk_size': row['chunk_size'],
                        'file_hash': row['file_hash'],
                        **meta,
                    }
                }
                result = {
                    'match_rank': float(row['rank']),
                    'snippet': row['snippet'],
                    'chunk_envelope': envelope,
                    'search_metadata': {
                        'file_path': row['file_path'],
                        'chunk_index': row['chunk_index'],
                        'chunk_strategy': row['chunk_strategy'],
                        'query': query
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
                SELECT chunk_index, content, metadata, chunk_strategy,
                       chunk_size, total_chunks, file_hash, file_path
                FROM text_chunks
                WHERE file_path = %s
                  AND chunk_index BETWEEN %s AND %s
                  AND chunk_index != %s
                ORDER BY chunk_index
            """, [file_path, start_idx, end_idx, chunk_index])
            return [
                {
                    'chunk_index': r['chunk_index'],
                    'chunk_envelope': {
                        'content': r['content'],
                        'metadata': {
                            'file_path': r['file_path'],
                            'chunk_index': r['chunk_index'],
                            'total_chunks': r['total_chunks'],
                            'chunk_strategy': r['chunk_strategy'],
                            **(r.get('metadata') or {}),
                        }
                    }
                }
                for r in cur.fetchall()
            ]

    def format_for_llm(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not results:
            return {
                'status': 'no_results',
                'query_metadata': {'total_results': 0, 'message': 'No matching chunks found'},
                'results': []
            }

        return {
            'status': 'success',
            'query_metadata': {
                'total_results': len(results),
                'query': results[0]['search_metadata']['query'],
                'search_type': 'postgresql_tsvector',
                'database': 'postgresql:file_metadata'
            },
            'results': results,
            'usage_hints': {
                'accessing_content': 'results[i].chunk_envelope.content',
                'accessing_metadata': 'results[i].chunk_envelope.metadata',
                'context_chunks': 'results[i].context_chunks (if requested)',
            },
            'summary': {
                'files_matched': len(set(r['search_metadata']['file_path'] for r in results)),
                'strategies_used': list(set(r['search_metadata']['chunk_strategy'] for r in results)),
                'has_context': any('context_chunks' in r for r in results)
            }
        }


def main():
    parser = argparse.ArgumentParser(
        description="Full-text search with PostgreSQL tsvector (LLM-optimized output)",
    )
    parser.add_argument('--query', required=True, help='Full-text search query')
    parser.add_argument('--limit', type=int, default=10, help='Maximum results to return')
    parser.add_argument('--context', type=int, default=0, help='Adjacent chunks to include as context')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON output')

    args = parser.parse_args()
    searcher = FTSSearchV2()

    try:
        results = searcher.search(
            query=args.query,
            limit=args.limit,
            include_context=args.context
        )

        if args.json:
            output = searcher.format_for_llm(results)
            indent = 2 if args.pretty else None
            print(json.dumps(output, indent=indent, default=str, ensure_ascii=False))
        else:
            if not results:
                print("No results found.")
                return

            print(f"Found {len(results)} matches for: '{args.query}'\n")
            for i, result in enumerate(results, 1):
                envelope = result['chunk_envelope']
                meta = envelope['metadata']
                print(f"{'='*60}")
                print(f"Result {i} (rank: {result['match_rank']:.4f})")
                print(f"File: {result['search_metadata']['file_path']}")
                print(f"Chunk: {meta['chunk_index']}/{meta['total_chunks'] - 1}")
                print(f"Strategy: {meta['chunk_strategy']}")
                print(f"\nSnippet: {result['snippet']}")

                if result.get('context_chunks'):
                    print(f"Context chunks: {len(result['context_chunks'])}")
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
