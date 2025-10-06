#!/usr/bin/env python3
"""
file_query_tool_v2.py - JSONB-aware File Query Tool

Query files by metadata and retrieve chunks with complete JSONB envelopes.
Returns results in LLM-consumable JSON format.

Usage:
    python file_query_tool_v2.py --created-since 2024-01-01 --json
    python file_query_tool_v2.py --name "test" --type "py" --json
    python file_query_tool_v2.py --file-path "/path/to/file.py" --chunks --json

Features:
    - Query files by metadata (date, size, name, type)
    - Retrieve complete chunk envelopes with metadata
    - Optional context chunk retrieval
    - LLM-optimized JSON output format
"""

import argparse
import sqlite3
import json
import sys
from typing import List, Dict, Any, Optional
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from chunking_refactor import ChunkEnvelope


class FileQueryToolV2:
    """File and chunk querying with JSONB support"""

    def __init__(self, db_path: str = "file_metadata.db"):
        self.db_path = db_path

    def query_files(
        self,
        created_since: Optional[str] = None,
        created_before: Optional[str] = None,
        greater_than: Optional[int] = None,
        less_than: Optional[int] = None,
        name_pattern: Optional[str] = None,
        file_type: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Query files by metadata

        Args:
            created_since: Files created since YYYY-MM-DD
            created_before: Files created before YYYY-MM-DD
            greater_than: Files greater than SIZE bytes
            less_than: Files less than SIZE bytes
            name_pattern: Pattern to match in filename
            file_type: File type/extension to match
            limit: Maximum results to return

        Returns:
            List of file metadata dictionaries
        """
        clauses = []
        params = []

        if created_since:
            clauses.append('created_date >= ?')
            params.append(created_since)

        if created_before:
            clauses.append('created_date <= ?')
            params.append(created_before)

        if greater_than:
            clauses.append('file_size > ?')
            params.append(greater_than)

        if less_than:
            clauses.append('file_size < ?')
            params.append(less_than)

        if name_pattern:
            clauses.append('file_name LIKE ?')
            params.append(f'%{name_pattern}%')

        if file_type:
            clauses.append('(file_type LIKE ? OR mime_type LIKE ?)')
            params.append(f'%{file_type}%')
            params.append(f'%{file_type}%')

        where = ' AND '.join(clauses) if clauses else '1=1'
        query = f'SELECT * FROM file_metadata WHERE {where}'

        if limit:
            query += f' LIMIT {limit}'

        uri = f'file:{self.db_path}?mode=ro'
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(query, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            results.append(dict(row))

        conn.close()
        return results

    def get_file_chunks(
        self,
        file_path: str,
        chunk_index: Optional[int] = None,
        include_context: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get chunks for a file

        Args:
            file_path: Path to file
            chunk_index: Specific chunk index (None = all chunks)
            include_context: Number of adjacent chunks to include

        Returns:
            List of chunk envelopes with optional context
        """
        uri = f'file:{self.db_path}?mode=ro'
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if chunk_index is not None:
            # Get specific chunk
            cursor.execute('''
                SELECT chunk_envelope, chunk_index
                FROM text_chunks_v2
                WHERE file_path = ? AND chunk_index = ?
            ''', (file_path, chunk_index))

            row = cursor.fetchone()
            if not row:
                conn.close()
                return []

            result = {
                'chunk_index': row['chunk_index'],
                'chunk_envelope': json.loads(row['chunk_envelope'])
            }

            # Add context if requested
            if include_context > 0:
                result['context_chunks'] = self._get_adjacent_chunks(
                    conn, file_path, chunk_index, before=include_context, after=include_context
                )

            conn.close()
            return [result]
        else:
            # Get all chunks
            cursor.execute('''
                SELECT chunk_envelope, chunk_index
                FROM text_chunks_v2
                WHERE file_path = ?
                ORDER BY chunk_index
            ''', (file_path,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    'chunk_index': row['chunk_index'],
                    'chunk_envelope': json.loads(row['chunk_envelope'])
                })

            conn.close()
            return results

    def get_chunk_stats(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get chunking statistics for a file"""
        uri = f'file:{self.db_path}?mode=ro'
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                COUNT(*) as total_chunks,
                chunk_strategy,
                SUM(chunk_size) as total_size,
                AVG(chunk_size) as avg_size,
                MIN(chunk_size) as min_size,
                MAX(chunk_size) as max_size,
                file_hash,
                file_type
            FROM text_chunks_v2
            WHERE file_path = ?
            GROUP BY file_path
        ''', (file_path,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

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

    def format_for_llm(
        self,
        files: Optional[List[Dict[str, Any]]] = None,
        chunks: Optional[List[Dict[str, Any]]] = None,
        chunk_stats: Optional[Dict[str, Any]] = None,
        query_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Format results for LLM consumption"""
        output = {
            'status': 'success',
            'query_metadata': query_params or {},
            'database': self.db_path
        }

        if files is not None:
            output['files'] = {
                'total_count': len(files),
                'results': files
            }

        if chunks is not None:
            output['chunks'] = {
                'total_count': len(chunks),
                'results': chunks
            }

        if chunk_stats is not None:
            output['chunk_statistics'] = chunk_stats

        output['usage_hints'] = {
            'accessing_chunk_content': 'chunks.results[i].chunk_envelope.content',
            'accessing_metadata': 'chunks.results[i].chunk_envelope.metadata',
            'ai_metadata': 'chunks.results[i].chunk_envelope.metadata.ai_metadata',
            'context_chunks': 'chunks.results[i].context_chunks (if requested)',
            'file_metadata': 'files.results[i] for file-level metadata'
        }

        return output


def main():
    parser = argparse.ArgumentParser(
        description="File and chunk query tool with JSONB support (LLM-optimized output)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Query files by date
  python file_query_tool_v2.py --created-since 2024-01-01 --json

  # Query files by name and type
  python file_query_tool_v2.py --name "test" --type "py" --json

  # Get all chunks for a file
  python file_query_tool_v2.py --file-path "/path/to/file.py" --chunks --json

  # Get specific chunk with context
  python file_query_tool_v2.py --file-path "/path/to/file.py" --chunk-index 5 --context 1 --json

  # Get chunk statistics
  python file_query_tool_v2.py --file-path "/path/to/file.py" --stats --json
        """
    )

    # File query parameters
    parser.add_argument('--db', default='file_metadata.db', help='Path to SQLite database')
    parser.add_argument('--created-since', type=str, help='Files created since YYYY-MM-DD')
    parser.add_argument('--created-before', type=str, help='Files created before YYYY-MM-DD')
    parser.add_argument('--greater', type=int, help='Files greater than SIZE bytes')
    parser.add_argument('--less', type=int, help='Files less than SIZE bytes')
    parser.add_argument('--name', type=str, help='Pattern to match in filename')
    parser.add_argument('--type', type=str, help='File type or extension')
    parser.add_argument('--limit', type=int, help='Maximum file results')

    # Chunk query parameters
    parser.add_argument('--file-path', type=str, help='File path to query chunks for')
    parser.add_argument('--chunks', action='store_true', help='Retrieve chunks for file')
    parser.add_argument('--chunk-index', type=int, help='Specific chunk index')
    parser.add_argument('--context', type=int, default=0, help='Adjacent chunks to include')
    parser.add_argument('--stats', action='store_true', help='Show chunk statistics for file')

    # Output parameters
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON')

    args = parser.parse_args()

    tool = FileQueryToolV2(args.db)

    try:
        files_result = None
        chunks_result = None
        stats_result = None

        query_params = {
            'created_since': args.created_since,
            'created_before': args.created_before,
            'size_greater_than': args.greater,
            'size_less_than': args.less,
            'name_pattern': args.name,
            'file_type': args.type
        }

        # File query
        if any([args.created_since, args.created_before, args.greater, args.less, args.name, args.type]):
            files_result = tool.query_files(
                created_since=args.created_since,
                created_before=args.created_before,
                greater_than=args.greater,
                less_than=args.less,
                name_pattern=args.name,
                file_type=args.type,
                limit=args.limit
            )

        # Chunk query
        if args.file_path and (args.chunks or args.chunk_index is not None):
            chunks_result = tool.get_file_chunks(
                file_path=args.file_path,
                chunk_index=args.chunk_index,
                include_context=args.context
            )

        # Statistics query
        if args.file_path and args.stats:
            stats_result = tool.get_chunk_stats(args.file_path)

        if args.json:
            # LLM-consumable JSON output
            output = tool.format_for_llm(
                files=files_result,
                chunks=chunks_result,
                chunk_stats=stats_result,
                query_params=query_params
            )
            indent = 2 if args.pretty else None
            print(json.dumps(output, indent=indent, ensure_ascii=False))
        else:
            # Human-readable output
            if files_result:
                print(f"Found {len(files_result)} files:\n")
                for i, file in enumerate(files_result, 1):
                    print(f"{i}. {file['file_path']}")
                    print(f"   Size: {file['file_size']} bytes | Type: {file['file_type']}")
                    print(f"   Created: {file['created_date']} | Modified: {file['modified_date']}")
                    print()

            if chunks_result:
                print(f"Found {len(chunks_result)} chunks:\n")
                for chunk in chunks_result:
                    envelope = chunk['chunk_envelope']
                    metadata = envelope['metadata']
                    print(f"Chunk {metadata['chunk_index']}/{metadata['total_chunks'] - 1}")
                    print(f"  Strategy: {metadata['chunk_strategy']}")
                    print(f"  Size: {metadata['chunk_size']} chars")
                    print(f"  Content preview: {envelope['content'][:100]}...")
                    if 'context_chunks' in chunk:
                        print(f"  Context chunks: {len(chunk['context_chunks'])}")
                    print()

            if stats_result:
                print("Chunk Statistics:")
                for key, value in stats_result.items():
                    print(f"  {key}: {value}")

            if not any([files_result, chunks_result, stats_result]):
                print("No results found. Try --help for usage examples.")

    except sqlite3.OperationalError as e:
        if 'no such table' in str(e):
            print(json.dumps({
                'status': 'error',
                'error': 'Required tables not found',
                'message': 'Please run schema_refactor.sql to create the new tables',
                'hint': 'sqlite3 file_metadata.db < schema_refactor.sql'
            }, indent=2), file=sys.stderr)
        else:
            raise
    except Exception as e:
        print(json.dumps({
            'status': 'error',
            'error': str(e),
            'type': type(e).__name__
        }, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
