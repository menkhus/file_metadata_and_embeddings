#!/usr/bin/env python3
"""
find_using_fts_v2.py - JSONB-aware Full-Text Search Tool

Full-text search using the new chunks_fts table with JSONB chunk envelopes.
Returns results in LLM-consumable JSON format.

Usage:
    python find_using_fts_v2.py --query "search phrase" --limit 10 --json
    python find_using_fts_v2.py --query "error handling" --context 1 --json

Features:
    - Searches new chunks_fts FTS5 table
    - Returns complete chunk envelopes with metadata
    - Optional adjacent chunk context retrieval
    - LLM-optimized JSON output format
"""

import argparse
import sqlite3
import json
import sys
from typing import List, Dict, Any
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from chunking_refactor import ChunkEnvelope


class FTSSearchV2:
    """Full-text search with JSONB chunk support"""

    def __init__(self, db_path: str = "file_metadata.db"):
        self.db_path = db_path

    def search(
        self,
        query: str,
        limit: int = 10,
        include_context: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Search chunks using FTS5

        Args:
            query: Search query string
            limit: Maximum results to return
            include_context: Number of adjacent chunks to include (0 = none)

        Returns:
            List of result dicts with chunk envelopes and metadata
        """
        uri = f'file:{self.db_path}?mode=ro'
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Search using FTS5
        cursor.execute('''
            SELECT
                t.id,
                t.file_path,
                t.chunk_index,
                t.chunk_envelope,
                t.chunk_strategy,
                f.rank,
                snippet(chunks_fts, 2, '**', '**', '...', 32) as snippet
            FROM chunks_fts f
            JOIN text_chunks_v2 t ON t.id = f.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY f.rank
            LIMIT ?
        ''', (query, limit))

        results = []
        for row in cursor.fetchall():
            # Parse chunk envelope
            envelope = ChunkEnvelope.from_json(row['chunk_envelope'])

            result = {
                'match_rank': row['rank'],
                'snippet': row['snippet'],
                'chunk_envelope': json.loads(row['chunk_envelope']),
                'search_metadata': {
                    'file_path': row['file_path'],
                    'chunk_index': row['chunk_index'],
                    'chunk_strategy': row['chunk_strategy'],
                    'query': query
                }
            }

            # Add context chunks if requested
            if include_context > 0:
                context_chunks = self._get_adjacent_chunks(
                    conn,
                    row['file_path'],
                    row['chunk_index'],
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

    def format_for_llm(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Format results for LLM consumption

        Returns structured JSON with:
        - Query metadata
        - Results with full chunk envelopes
        - Retrieval hints
        - Summary statistics
        """
        if not results:
            return {
                'status': 'no_results',
                'query_metadata': {
                    'total_results': 0,
                    'message': 'No matching chunks found'
                },
                'results': []
            }

        return {
            'status': 'success',
            'query_metadata': {
                'total_results': len(results),
                'query': results[0]['search_metadata']['query'],
                'search_type': 'full_text_search',
                'database': self.db_path
            },
            'results': results,
            'usage_hints': {
                'accessing_content': 'results[i].chunk_envelope.content',
                'accessing_metadata': 'results[i].chunk_envelope.metadata',
                'ai_metadata': 'results[i].chunk_envelope.metadata.ai_metadata',
                'context_chunks': 'results[i].context_chunks (if requested)',
                'retrieval_suggestion': 'Use ai_metadata.retrieval_context_suggestion for guidance'
            },
            'summary': {
                'files_matched': len(set(r['search_metadata']['file_path'] for r in results)),
                'strategies_used': list(set(r['search_metadata']['chunk_strategy'] for r in results)),
                'has_context': any('context_chunks' in r for r in results)
            }
        }


def main():
    parser = argparse.ArgumentParser(
        description="Full-text search with JSONB chunks (LLM-optimized output)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic search
  python find_using_fts_v2.py --query "error handling" --json

  # Search with context (±1 chunks)
  python find_using_fts_v2.py --query "function definition" --context 1 --json

  # Limit results
  python find_using_fts_v2.py --query "import" --limit 5 --json
        """
    )
    parser.add_argument('--db', default='file_metadata.db', help='Path to SQLite database')
    parser.add_argument('--query', required=True, help='Full-text search query')
    parser.add_argument('--limit', type=int, default=10, help='Maximum results to return')
    parser.add_argument('--context', type=int, default=0, help='Number of adjacent chunks to include as context')
    parser.add_argument('--json', action='store_true', help='Output as JSON (default: human-readable)')
    parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON output')

    args = parser.parse_args()

    searcher = FTSSearchV2(args.db)

    try:
        results = searcher.search(
            query=args.query,
            limit=args.limit,
            include_context=args.context
        )

        if args.json:
            # LLM-consumable JSON output
            output = searcher.format_for_llm(results)
            indent = 2 if args.pretty else None
            print(json.dumps(output, indent=indent, ensure_ascii=False))
        else:
            # Human-readable output
            if not results:
                print("No results found.")
                return

            print(f"Found {len(results)} matches for: '{args.query}'\n")
            for i, result in enumerate(results, 1):
                envelope = result['chunk_envelope']
                metadata = envelope['metadata']

                print(f"{'='*60}")
                print(f"Result {i} (rank: {result['match_rank']:.4f})")
                print(f"{'='*60}")
                print(f"File: {result['search_metadata']['file_path']}")
                print(f"Chunk: {metadata['chunk_index']}/{metadata['total_chunks'] - 1}")
                print(f"Strategy: {metadata['chunk_strategy']}")
                print(f"Size: {metadata['chunk_size']} chars")
                print(f"\nSnippet: {result['snippet']}")

                if 'context_chunks' in result and result['context_chunks']:
                    print(f"\nContext chunks: {len(result['context_chunks'])}")
                    for ctx in result['context_chunks']:
                        print(f"  - Chunk {ctx['chunk_index']}")

                print()

    except sqlite3.OperationalError as e:
        if 'no such table' in str(e):
            print(json.dumps({
                'status': 'error',
                'error': 'chunks_fts table not found',
                'message': 'Please run schema_refactor.sql to create the new tables',
                'hint': 'sqlite3 file_metadata.db < schema_refactor.sql'
            }, indent=2))
        else:
            raise
    except Exception as e:
        print(json.dumps({
            'status': 'error',
            'error': str(e),
            'type': type(e).__name__
        }, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
