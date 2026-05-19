#!/usr/bin/env python3
"""
file_query_tool_v2.py - PostgreSQL File Query Tool

Query files by metadata and retrieve chunks from PostgreSQL + pgvector.
Returns results in LLM-consumable JSON format.

Usage:
    python file_query_tool_v2.py --modified-since 2024-01-01 --json
    python file_query_tool_v2.py --name "test" --type "py" --json
    python file_query_tool_v2.py --file-path "/path/to/file.py" --chunks --json
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


def _get_conn():
    conn = psycopg2.connect(_PG_DSN)
    conn.autocommit = True
    return conn


def _build_envelope(row: Dict[str, Any]) -> Dict[str, Any]:
    """Build chunk-envelope-compatible dict from a text_chunks row."""
    meta = row.get('metadata') or {}
    return {
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


class FileQueryToolV2:
    """File and chunk querying against PostgreSQL"""

    def query_files(
        self,
        modified_since: Optional[str] = None,
        modified_before: Optional[str] = None,
        greater_than: Optional[int] = None,
        less_than: Optional[int] = None,
        name_pattern: Optional[str] = None,
        file_type: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []

        if modified_since:
            clauses.append('last_modified >= %s::timestamptz')
            params.append(modified_since)

        if modified_before:
            clauses.append('last_modified <= %s::timestamptz')
            params.append(modified_before)

        if greater_than:
            clauses.append('file_size > %s')
            params.append(greater_than)

        if less_than:
            clauses.append('file_size < %s')
            params.append(less_than)

        if name_pattern:
            clauses.append('file_path ILIKE %s')
            params.append(f'%{name_pattern}%')

        if file_type:
            clauses.append('(file_type ILIKE %s OR mime_type ILIKE %s)')
            params.extend([f'%{file_type}%', f'%{file_type}%'])

        where = ' AND '.join(clauses) if clauses else 'TRUE'
        query = f'SELECT * FROM file_metadata WHERE {where} ORDER BY last_modified DESC NULLS LAST'

        if limit:
            query += f' LIMIT {limit}'

        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        finally:
            conn.close()

        return [
            {
                **dict(row),
                'file_name': os.path.basename(row['file_path']),
                'directory': os.path.dirname(row['file_path']),
                'modified_date': str(row['last_modified'])[:19] if row['last_modified'] else '',
            }
            for row in rows
        ]

    def get_file_chunks(
        self,
        file_path: str,
        chunk_index: Optional[int] = None,
        include_context: int = 0
    ) -> List[Dict[str, Any]]:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if chunk_index is not None:
                    cur.execute("""
                        SELECT chunk_index, content, metadata, chunk_strategy,
                               chunk_size, total_chunks, file_hash, file_path
                        FROM text_chunks
                        WHERE file_path = %s AND chunk_index = %s
                    """, [file_path, chunk_index])
                    row = cur.fetchone()
                    if not row:
                        return []

                    result = {
                        'chunk_index': row['chunk_index'],
                        'chunk_envelope': _build_envelope(dict(row))
                    }

                    if include_context > 0:
                        result['context_chunks'] = self._get_adjacent_chunks(
                            conn, file_path, chunk_index,
                            before=include_context, after=include_context
                        )

                    return [result]
                else:
                    cur.execute("""
                        SELECT chunk_index, content, metadata, chunk_strategy,
                               chunk_size, total_chunks, file_hash, file_path
                        FROM text_chunks
                        WHERE file_path = %s
                        ORDER BY chunk_index
                    """, [file_path])
                    return [
                        {'chunk_index': r['chunk_index'], 'chunk_envelope': _build_envelope(dict(r))}
                        for r in cur.fetchall()
                    ]
        finally:
            conn.close()

    def get_chunk_stats(self, file_path: str) -> Optional[Dict[str, Any]]:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) AS total_chunks,
                        MAX(chunk_strategy) AS chunk_strategy,
                        SUM(chunk_size) AS total_size,
                        AVG(chunk_size) AS avg_size,
                        MIN(chunk_size) AS min_size,
                        MAX(chunk_size) AS max_size,
                        MAX(file_hash) AS file_hash,
                        MAX(fm.file_type) AS file_type
                    FROM text_chunks tc
                    JOIN file_metadata fm ON tc.file_path = fm.file_path
                    WHERE tc.file_path = %s
                    GROUP BY tc.file_path
                """, [file_path])
                row = cur.fetchone()
        finally:
            conn.close()

        if row:
            cols = ['total_chunks', 'chunk_strategy', 'total_size', 'avg_size',
                    'min_size', 'max_size', 'file_hash', 'file_type']
            return dict(zip(cols, row))
        return None

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
                {'chunk_index': r['chunk_index'], 'chunk_envelope': _build_envelope(dict(r))}
                for r in cur.fetchall()
            ]

    def format_for_llm(
        self,
        files: Optional[List[Dict[str, Any]]] = None,
        chunks: Optional[List[Dict[str, Any]]] = None,
        chunk_stats: Optional[Dict[str, Any]] = None,
        query_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        output: Dict[str, Any] = {
            'status': 'success',
            'query_metadata': query_params or {},
            'database': 'postgresql:file_metadata'
        }

        if files is not None:
            output['files'] = {'total_count': len(files), 'results': files}

        if chunks is not None:
            output['chunks'] = {'total_count': len(chunks), 'results': chunks}

        if chunk_stats is not None:
            output['chunk_statistics'] = chunk_stats

        output['usage_hints'] = {
            'accessing_chunk_content': 'chunks.results[i].chunk_envelope.content',
            'accessing_metadata': 'chunks.results[i].chunk_envelope.metadata',
            'context_chunks': 'chunks.results[i].context_chunks (if requested)',
            'file_metadata': 'files.results[i] for file-level metadata'
        }

        return output


def main():
    parser = argparse.ArgumentParser(
        description="File and chunk query tool — PostgreSQL edition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument('--modified-since', type=str, help='Files modified since YYYY-MM-DD')
    parser.add_argument('--modified-before', type=str, help='Files modified before YYYY-MM-DD')
    parser.add_argument('--greater', type=int, help='Files greater than SIZE bytes')
    parser.add_argument('--less', type=int, help='Files less than SIZE bytes')
    parser.add_argument('--name', type=str, help='Pattern to match in file path')
    parser.add_argument('--type', type=str, help='File type or extension')
    parser.add_argument('--limit', type=int, help='Maximum file results')

    parser.add_argument('--file-path', type=str, help='File path to query chunks for')
    parser.add_argument('--chunks', action='store_true', help='Retrieve chunks for file')
    parser.add_argument('--chunk-index', type=int, help='Specific chunk index')
    parser.add_argument('--context', type=int, default=0, help='Adjacent chunks to include')
    parser.add_argument('--stats', action='store_true', help='Show chunk statistics for file')

    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON')

    args = parser.parse_args()

    tool = FileQueryToolV2()

    try:
        files_result = None
        chunks_result = None
        stats_result = None

        query_params = {
            'modified_since': args.modified_since,
            'modified_before': args.modified_before,
            'size_greater_than': args.greater,
            'size_less_than': args.less,
            'name_pattern': args.name,
            'file_type': args.type
        }

        if any([args.modified_since, args.modified_before, args.greater, args.less, args.name, args.type]):
            files_result = tool.query_files(
                modified_since=args.modified_since,
                modified_before=args.modified_before,
                greater_than=args.greater,
                less_than=args.less,
                name_pattern=args.name,
                file_type=args.type,
                limit=args.limit
            )

        if args.file_path and (args.chunks or args.chunk_index is not None):
            chunks_result = tool.get_file_chunks(
                file_path=args.file_path,
                chunk_index=args.chunk_index,
                include_context=args.context
            )

        if args.file_path and args.stats:
            stats_result = tool.get_chunk_stats(args.file_path)

        if args.json:
            output = tool.format_for_llm(
                files=files_result,
                chunks=chunks_result,
                chunk_stats=stats_result,
                query_params=query_params
            )
            indent = 2 if args.pretty else None
            print(json.dumps(output, indent=indent, default=str, ensure_ascii=False))
        else:
            if files_result:
                print(f"Found {len(files_result)} files:\n")
                for i, f in enumerate(files_result, 1):
                    print(f"{i}. {f['file_path']}")
                    print(f"   Size: {f.get('file_size', 0)} bytes | Type: {f.get('file_type', '')}")
                    print(f"   Modified: {f['modified_date']}")
                    print()

            if chunks_result:
                print(f"Found {len(chunks_result)} chunks:\n")
                for chunk in chunks_result:
                    envelope = chunk['chunk_envelope']
                    meta = envelope['metadata']
                    print(f"Chunk {meta['chunk_index']}/{meta['total_chunks'] - 1}")
                    print(f"  Strategy: {meta['chunk_strategy']}")
                    print(f"  Size: {meta['chunk_size']} chars")
                    print(f"  Content preview: {envelope['content'][:100]}...")
                    print()

            if stats_result:
                print("Chunk Statistics:")
                for key, value in stats_result.items():
                    print(f"  {key}: {value}")

            if not any([files_result, chunks_result, stats_result]):
                print("No results found. Try --help for usage examples.")

    except Exception as e:
        print(json.dumps({
            'status': 'error',
            'error': str(e),
            'type': type(e).__name__
        }, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
