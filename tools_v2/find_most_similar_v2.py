#!/usr/bin/env python3
"""
find_most_similar_v2.py - Two-Tier Semantic Search Tool

Semantic search using two-tier FAISS index architecture.
Searches both major (stable) and minor (incremental) indexes.
Returns results in LLM-consumable JSON format.

Usage:
    python find_most_similar_v2.py --query "error handling in python" --top_k 5 --json
    python find_most_similar_v2.py --query "authentication" --context 1 --json
    python find_most_similar_v2.py --query "database" --status  # Show index status

Features:
    - Two-tier FAISS search (major + minor indexes)
    - Staleness filtering for modified/deleted files
    - Optional adjacent chunk context retrieval
    - LLM-optimized JSON output format
"""

import argparse
import sqlite3
import json
import sys
import os
from typing import List, Dict, Any, Optional
from pathlib import Path

try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from faiss_index_manager import TwoTierFAISSManager, SearchResult
    MANAGER_AVAILABLE = True
except ImportError:
    MANAGER_AVAILABLE = False


# Default paths
DEFAULT_DATA_DIR = os.path.expanduser("~/data")
DEFAULT_DB = os.path.expanduser("~/data/file_metadata.sqlite3")
DEFAULT_MODEL = "all-MiniLM-L6-v2"


class SemanticSearchV2:
    """Semantic search with two-tier FAISS index support"""

    def __init__(
        self,
        data_dir: str = DEFAULT_DATA_DIR,
        db_path: str = DEFAULT_DB,
        model_name: str = DEFAULT_MODEL
    ):
        if not DEPS_AVAILABLE:
            raise ImportError("Required packages not installed. Run: pip install faiss-cpu numpy sentence-transformers")
        if not MANAGER_AVAILABLE:
            raise ImportError("faiss_index_manager not found. Ensure it's in the parent directory.")

        self.data_dir = data_dir
        self.db_path = db_path
        self.model_name = model_name
        self.model = None
        self.manager = TwoTierFAISSManager(data_dir=data_dir)

    def search(
        self,
        query: str,
        top_k: int = 5,
        include_context: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Semantic search across both major and minor indexes

        Args:
            query: Search query string
            top_k: Number of top results to return
            include_context: Number of adjacent chunks to include

        Returns:
            List of result dicts with metadata and similarity scores
        """
        if self.model is None:
            print(f"Loading model: {self.model_name} ...", file=sys.stderr)
            self.model = SentenceTransformer(self.model_name)

        # Encode query
        query_embedding = self.model.encode([query])[0]
        query_vec = np.array(query_embedding).astype('float32')

        # Search both indexes
        search_results = self.manager.search(query_vec, top_k=top_k)

        if not search_results:
            return []

        # Convert SearchResult objects to dicts and add context if requested
        results = []
        conn = None
        if include_context > 0 and os.path.exists(self.db_path):
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row

        for rank, sr in enumerate(search_results, 1):
            result = {
                'rank': rank,
                'similarity_score': sr.similarity_score,
                'tier': sr.tier,
                'file_path': sr.file_path,
                'chunk_index': sr.chunk_index,
                'chunk_text': sr.chunk_text,
                'metadata': {
                    'file_name': sr.metadata.get('file_name', ''),
                    'file_type': sr.metadata.get('file_type', ''),
                    'file_size': sr.metadata.get('file_size', 0),
                    'modified_date': sr.metadata.get('modified_date', ''),
                    'total_chunks': sr.metadata.get('total_chunks', 1),
                    'tfidf_keywords': sr.metadata.get('tfidf_keywords', []),
                },
                'search_metadata': {
                    'query': query,
                    'search_method': 'two_tier_faiss',
                }
            }

            # Add context chunks if requested
            if include_context > 0 and conn:
                context_chunks = self._get_adjacent_chunks(
                    conn,
                    sr.file_path,
                    sr.chunk_index,
                    before=include_context,
                    after=include_context
                )
                result['context_chunks'] = context_chunks

            results.append(result)

        if conn:
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
            SELECT chunk_index, chunk_text
            FROM text_chunks
            WHERE file_path = ?
              AND chunk_index BETWEEN ? AND ?
              AND chunk_index != ?
            ORDER BY chunk_index
        ''', (file_path, start_idx, end_idx, chunk_index))

        context = []
        for row in cursor.fetchall():
            context.append({
                'chunk_index': row['chunk_index'],
                'chunk_text': row['chunk_text']
            })

        return context

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics"""
        return self.manager.get_stats()

    def format_for_llm(self, results: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
        """Format results for LLM consumption"""
        stats = self.get_stats()

        if not results:
            return {
                'status': 'no_results',
                'query_metadata': {
                    'query': query,
                    'total_results': 0,
                    'message': 'No matching chunks found'
                },
                'index_info': {
                    'major_vectors': stats['major']['vector_count'],
                    'minor_vectors': stats['minor']['vector_count'],
                    'total_vectors': stats['total_vectors'],
                },
                'results': []
            }

        # Count results by tier
        major_count = sum(1 for r in results if r['tier'] == 'major')
        minor_count = sum(1 for r in results if r['tier'] == 'minor')

        return {
            'status': 'success',
            'query_metadata': {
                'query': query,
                'total_results': len(results),
                'search_type': 'two_tier_semantic',
                'model': self.model_name,
            },
            'index_info': {
                'major_vectors': stats['major']['vector_count'],
                'minor_vectors': stats['minor']['vector_count'],
                'total_vectors': stats['total_vectors'],
                'stale_vectors': stats['stale_vectors'],
                'results_from_major': major_count,
                'results_from_minor': minor_count,
            },
            'results': results,
            'usage_hints': {
                'accessing_content': 'results[i].chunk_text',
                'accessing_metadata': 'results[i].metadata',
                'similarity_score': 'results[i].similarity_score (0-1, higher is better)',
                'tier': 'results[i].tier (major=stable, minor=recent)',
                'context_chunks': 'results[i].context_chunks (if requested)',
                'note': 'Results are ordered by similarity (best match first)'
            },
            'summary': {
                'files_matched': len(set(r['file_path'] for r in results)),
                'avg_similarity_score': sum(r['similarity_score'] for r in results) / len(results),
                'top_match_file': results[0]['file_path'],
                'top_match_score': results[0]['similarity_score'],
                'has_context': any('context_chunks' in r for r in results)
            }
        }


def print_status(searcher: SemanticSearchV2) -> None:
    """Print index status"""
    stats = searcher.get_stats()

    print("\n=== FAISS Index Status ===\n")

    print("Major Index:")
    if stats['major']['exists']:
        print(f"  Vectors: {stats['major']['vector_count']:,}")
        print(f"  File size: {stats['major']['file_size_mb']:.1f} MB")
        print(f"  Built: {stats['major']['build_timestamp'] or 'unknown'}")
    else:
        print("  Not built yet")

    print("\nMinor Index:")
    if stats['minor']['exists']:
        print(f"  Vectors: {stats['minor']['vector_count']:,}")
        print(f"  File size: {stats['minor']['file_size_mb']:.1f} MB")
        print(f"  Built: {stats['minor']['build_timestamp'] or 'unknown'}")
    else:
        print("  Empty (no incremental additions)")

    print(f"\nTotal vectors: {stats['total_vectors']:,}")
    print(f"Indexed files: {stats['indexed_files']:,}")
    print(f"Stale vectors: {stats['stale_vectors']:,}")

    if stats['needs_compaction']:
        print(f"\n[Hint] Compaction recommended. Run:")
        print("  python build_faiss_index.py --compact")


def main():
    parser = argparse.ArgumentParser(
        description="Semantic search with two-tier FAISS indexes (LLM-optimized output)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic semantic search
  python find_most_similar_v2.py --query "error handling" --json

  # Search with context (+-1 chunks)
  python find_most_similar_v2.py --query "authentication logic" --context 1 --json

  # Top 10 results
  python find_most_similar_v2.py --query "database connection" --top_k 10 --json

  # Show index status
  python find_most_similar_v2.py --status

Requirements:
  pip install faiss-cpu numpy sentence-transformers
        """
    )
    parser.add_argument('--data-dir', default=DEFAULT_DATA_DIR, help='FAISS data directory')
    parser.add_argument('--db', default=DEFAULT_DB, help='Path to SQLite database (for context retrieval)')
    parser.add_argument('--query', help='Semantic search query')
    parser.add_argument('--top_k', type=int, default=5, help='Number of top results')
    parser.add_argument('--context', type=int, default=0, help='Number of adjacent chunks to include')
    parser.add_argument('--model', default=DEFAULT_MODEL, help='Sentence transformer model')
    parser.add_argument('--json', action='store_true', help='Output as JSON (default: human-readable)')
    parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON output')
    parser.add_argument('--status', action='store_true', help='Show index status')

    args = parser.parse_args()

    if not DEPS_AVAILABLE:
        print(json.dumps({
            'status': 'error',
            'error': 'missing_dependencies',
            'message': 'Required packages not installed',
            'install': 'pip install faiss-cpu numpy sentence-transformers'
        }, indent=2), file=sys.stderr)
        sys.exit(1)

    if not MANAGER_AVAILABLE:
        print(json.dumps({
            'status': 'error',
            'error': 'missing_manager',
            'message': 'faiss_index_manager.py not found',
            'hint': 'Ensure faiss_index_manager.py is in the parent directory'
        }, indent=2), file=sys.stderr)
        sys.exit(1)

    try:
        searcher = SemanticSearchV2(args.data_dir, args.db, args.model)
    except Exception as e:
        print(json.dumps({
            'status': 'error',
            'error': str(e),
            'type': type(e).__name__
        }, indent=2), file=sys.stderr)
        sys.exit(1)

    # Status mode
    if args.status:
        print_status(searcher)
        sys.exit(0)

    # Search mode requires query
    if not args.query:
        parser.error("--query is required for search (or use --status)")

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
            stats = searcher.get_stats()

            if not results:
                print(f"No results found for: '{args.query}'")
                print(f"\nIndex has {stats['total_vectors']} total vectors")
                return

            print(f"Semantic search for: '{args.query}'")
            print(f"Model: {args.model}")
            print(f"Index: {stats['major']['vector_count']} major + {stats['minor']['vector_count']} minor vectors\n")

            for result in results:
                print(f"{'='*60}")
                print(f"Rank {result['rank']} (similarity: {result['similarity_score']:.4f}, tier: {result['tier']})")
                print(f"{'='*60}")
                print(f"File: {result['file_path']}")
                print(f"Chunk: {result['chunk_index']}/{result['metadata']['total_chunks'] - 1}")
                print(f"Type: {result['metadata']['file_type']}")

                if result['metadata'].get('tfidf_keywords'):
                    print(f"Keywords: {', '.join(result['metadata']['tfidf_keywords'][:5])}")

                print(f"\nContent preview:")
                content = result['chunk_text']
                preview = content[:300] + "..." if len(content) > 300 else content
                print(f"  {preview}")

                if 'context_chunks' in result and result['context_chunks']:
                    print(f"\nContext chunks: {len(result['context_chunks'])}")

                print()

    except ValueError as e:
        print(json.dumps({
            'status': 'error',
            'error': str(e),
            'hint': 'Build index first: python build_faiss_index.py'
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
