#!/usr/bin/env python3
"""
MCP Server for File Metadata Tool - PostgreSQL + pgvector Edition

Available tools:
- search_files: Search by metadata (name, type, date, size, directory)
- full_text_search: tsvector content search with snippets
- get_file_info: Full metadata + keywords + topics for a file
- get_file_chunks: Retrieve text chunks for a file
- list_directories: Browse indexed directories with stats
- search_by_keywords: Find files by TF-IDF keywords
- get_stats: Database statistics and overview
- semantic_search: pgvector cosine similarity search
- log_autograph: Log grounding choices to knowledge graph
- query_autographs: Query KG for patterns related to a context
- autograph_suggest: Get auto-suggestions based on learned patterns
- autograph_stats: View KG statistics and bootstrap phase
"""

import asyncio
import os
import sys
from typing import Any, Dict, List, Optional

import numpy as np
import psycopg2
import psycopg2.pool
import psycopg2.extras

# MCP imports
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.lowlevel import NotificationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    TextContent,
    Tool,
)

_PG_DSN = (
    "host=localhost dbname=file_metadata user=postgres "
    f"password={os.environ.get('DB_PASSWORD', '')}"
)

# Knowledge graph directory - for autograph learning
KG_PATH = os.environ.get('KG_PATH', os.path.join(os.path.dirname(__file__), 'knowledge_graph'))

# Try to load autograph manager for knowledge graph (optional)
try:
    from autograph_manager import AutographManager
    AUTOGRAPH_AVAILABLE = True
except ImportError:
    AUTOGRAPH_AVAILABLE = False
    AutographManager = None


class FileMetadataDB:
    """PostgreSQL + pgvector database interface for file metadata operations"""

    def __init__(self):
        self._pool = psycopg2.pool.ThreadedConnectionPool(1, 5, dsn=_PG_DSN)
        self._lsa = None
        self._model_load_attempted = False
        # Verify connection
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM file_metadata")
        finally:
            self._pool.putconn(conn)

    def _get_conn(self):
        return self._pool.getconn()

    def _put_conn(self, conn):
        self._pool.putconn(conn)

    def _load_model(self) -> bool:
        """Lazy-load LSA model (TF-IDF vectorizer + TruncatedSVD) for semantic search."""
        if self._model_load_attempted:
            return self._lsa is not None
        self._model_load_attempted = True
        try:
            import joblib
            model_path = os.path.join(os.path.dirname(__file__), "lsa_model.joblib")
            self._lsa = joblib.load(model_path)
            print("LSA model loaded.", file=sys.stderr)
            return True
        except Exception as e:
            print(f"Could not load LSA model: {e}", file=sys.stderr)
            return False

    def is_semantic_available(self) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM text_chunks WHERE lsa_vec IS NOT NULL LIMIT 1")
                return cur.fetchone() is not None
        finally:
            self._put_conn(conn)

    def semantic_search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Cosine similarity search using pgvector."""
        if not self._load_model() or self._lsa is None:
            return []
        tfidf = self._lsa["vectorizer"].transform([query])
        vec = self._lsa["svd"].transform(tfidf)[0]
        vec = vec / (np.linalg.norm(vec) or 1.0)
        vec_str = "[" + ",".join(str(v) for v in vec.tolist()) + "]"
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        tc.file_path,
                        tc.chunk_index,
                        tc.content,
                        1 - (tc.lsa_vec <=> %s::vector) AS similarity,
                        fm.file_type,
                        fm.last_modified
                    FROM text_chunks tc
                    JOIN file_metadata fm ON tc.file_path = fm.file_path
                    WHERE tc.lsa_vec IS NOT NULL
                    ORDER BY tc.lsa_vec <=> %s::vector
                    LIMIT %s
                """, [vec_str, vec_str, limit])
                rows = cur.fetchall()
        finally:
            self._put_conn(conn)

        return [
            {
                'file_path': row['file_path'],
                'file_name': os.path.basename(row['file_path']),
                'file_type': row['file_type'] or '',
                'modified_date': str(row['last_modified'])[:10] if row['last_modified'] else '',
                'chunk_index': row['chunk_index'],
                'chunk_text': (row['content'] or '')[:200],
                'similarity': float(row['similarity']),
            }
            for row in rows
        ]

    def recall(self, thought: str, k: int = 3, scope: str = '') -> str:
        """Semantic recall with adjacent-chunk context. 'scope' filters by path prefix."""
        if not self._load_model() or self._lsa is None:
            return "Semantic recall unavailable: model not loaded."
        tfidf = self._lsa["vectorizer"].transform([thought])
        vec = self._lsa["svd"].transform(tfidf)[0]
        vec = vec / (np.linalg.norm(vec) or 1.0)
        vec_str = "[" + ",".join(str(v) for v in vec.tolist()) + "]"
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if scope:
                    scope_filter = "AND tc.file_path LIKE %s"
                    params: List[Any] = [vec_str, scope.rstrip('/') + '/%', vec_str, k]
                else:
                    scope_filter = ""
                    params = [vec_str, vec_str, k]
                cur.execute(f"""
                    SELECT
                        tc.file_path,
                        tc.chunk_index,
                        tc.content,
                        1 - (tc.lsa_vec <=> %s::vector) AS similarity
                    FROM text_chunks tc
                    WHERE tc.lsa_vec IS NOT NULL
                    {scope_filter}
                    ORDER BY tc.lsa_vec <=> %s::vector
                    LIMIT %s
                """, params)
                hits = cur.fetchall()

                if not hits:
                    return "Nothing found."

                output: List[str] = []
                for row in hits:
                    # Fetch adjacent chunks for context
                    ci = row['chunk_index']
                    cur.execute("""
                        SELECT chunk_index, content FROM text_chunks
                        WHERE file_path = %s AND chunk_index = ANY(%s)
                        ORDER BY chunk_index
                    """, [row['file_path'], [ci - 1, ci, ci + 1]])
                    adj = cur.fetchall()
                    context = "\n".join((r['content'] or '') for r in adj)
                    output.append(
                        f"---\n[{row['similarity']:.2f}] {row['file_path']}\n\n{context[:600]}"
                    )
                return "\n\n".join(output)
        finally:
            self._put_conn(conn)

    def search_files_by_metadata(self, **kwargs) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = "SELECT * FROM file_metadata WHERE 1=1"
                params: List[Any] = []

                if kwargs.get('name_pattern'):
                    query += " AND file_path ILIKE %s"
                    params.append(f"%{kwargs['name_pattern']}%")

                if kwargs.get('file_type'):
                    query += " AND (file_type ILIKE %s OR mime_type ILIKE %s)"
                    params.extend([f"%{kwargs['file_type']}%", f"%{kwargs['file_type']}%"])

                if kwargs.get('directory'):
                    query += " AND file_path LIKE %s"
                    params.append(f"{kwargs['directory']}%")

                if kwargs.get('modified_since'):
                    query += " AND last_modified >= %s::timestamptz"
                    params.append(kwargs['modified_since'])

                if kwargs.get('min_size'):
                    query += " AND file_size >= %s"
                    params.append(kwargs['min_size'])

                if kwargs.get('max_size'):
                    query += " AND file_size <= %s"
                    params.append(kwargs['max_size'])

                query += " ORDER BY last_modified DESC NULLS LAST LIMIT %s"
                params.append(kwargs.get('limit', 20))

                cur.execute(query, params)
                rows = cur.fetchall()
        finally:
            self._put_conn(conn)

        return [
            {
                'file_path': row['file_path'],
                'file_name': os.path.basename(row['file_path']),
                'directory': os.path.dirname(row['file_path']),
                'file_size': row['file_size'] or 0,
                'file_type': row['file_type'] or '',
                'mime_type': row['mime_type'] or '',
                'modified_date': str(row['last_modified'])[:19] if row['last_modified'] else '',
            }
            for row in rows
        ]

    def full_text_search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Full-text search over chunk content using tsvector + websearch_to_tsquery."""
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    WITH ranked AS (
                        SELECT
                            tc.file_path, tc.content, fm.file_type, fm.last_modified,
                            ROW_NUMBER() OVER (
                                PARTITION BY tc.file_path ORDER BY tc.chunk_index
                            ) AS rn
                        FROM text_chunks tc
                        JOIN file_metadata fm ON tc.file_path = fm.file_path
                        WHERE to_tsvector('english', tc.content)
                              @@ websearch_to_tsquery('english', %s)
                    )
                    SELECT
                        file_path,
                        ts_headline('english', content,
                            websearch_to_tsquery('english', %s),
                            'MaxWords=20, MinWords=5, StartSel=>>>, StopSel=<<<'
                        ) AS snippet,
                        file_type,
                        last_modified
                    FROM ranked
                    WHERE rn = 1
                    ORDER BY last_modified DESC NULLS LAST
                    LIMIT %s
                """, [query, query, limit])
                rows = cur.fetchall()
        finally:
            self._put_conn(conn)

        return [
            {
                'file_path': row['file_path'],
                'file_name': os.path.basename(row['file_path']),
                'file_type': row['file_type'] or '',
                'modified_date': str(row['last_modified'])[:19] if row['last_modified'] else '',
                'snippet': row['snippet'],
            }
            for row in rows
        ]

    def get_file_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM file_metadata WHERE file_path = %s", [file_path])
                fm = cur.fetchone()
                if not fm:
                    return None

                result = dict(fm)
                result['file_name'] = os.path.basename(file_path)
                result['directory'] = os.path.dirname(file_path)
                result['modified_date'] = str(fm['last_modified'])[:19] if fm['last_modified'] else ''

                cur.execute("""
                    SELECT word_count, char_count, language, keywords, tfidf_keywords, lda_topics
                    FROM content_analysis WHERE file_path = %s
                """, [file_path])
                analysis = cur.fetchone()
                if analysis:
                    result['word_count'] = analysis['word_count']
                    result['char_count'] = analysis['char_count']
                    result['language'] = analysis['language']
                    result['keywords'] = analysis['keywords'] or []
                    result['tfidf_keywords'] = analysis['tfidf_keywords'] or []
                    result['lda_topics'] = analysis['lda_topics'] or []

            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM text_chunks WHERE file_path = %s", [file_path])
                result['chunk_count'] = cur.fetchone()[0]
        finally:
            self._put_conn(conn)
        return result

    def get_file_chunks(self, file_path: str, chunk_index: Optional[int] = None) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if chunk_index is not None:
                    cur.execute("""
                        SELECT chunk_index, content AS chunk_text
                        FROM text_chunks WHERE file_path = %s AND chunk_index = %s
                    """, [file_path, chunk_index])
                else:
                    cur.execute("""
                        SELECT chunk_index, content AS chunk_text
                        FROM text_chunks WHERE file_path = %s ORDER BY chunk_index
                    """, [file_path])
                rows = cur.fetchall()
        finally:
            self._put_conn(conn)
        return [{'chunk_index': r['chunk_index'], 'chunk_text': r['chunk_text']} for r in rows]

    def list_directories(self, parent: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if parent:
                    cur.execute("""
                        SELECT
                            regexp_replace(file_path, '/[^/]+$', '') AS directory,
                            COUNT(*) AS file_count,
                            SUM(file_size) AS total_size
                        FROM file_metadata
                        WHERE file_path LIKE %s
                        GROUP BY 1
                        ORDER BY file_count DESC
                        LIMIT %s
                    """, [f"{parent}%", limit])
                else:
                    cur.execute("""
                        SELECT
                            regexp_replace(file_path, '/[^/]+$', '') AS directory,
                            COUNT(*) AS file_count,
                            SUM(file_size) AS total_size
                        FROM file_metadata
                        GROUP BY 1
                        ORDER BY file_count DESC
                        LIMIT %s
                    """, [limit])
                rows = cur.fetchall()
        finally:
            self._put_conn(conn)
        return [
            {'directory': r['directory'], 'file_count': r['file_count'], 'total_size': r['total_size']}
            for r in rows
        ]

    def search_by_keywords(self, keywords: List[str], limit: int = 20) -> List[Dict[str, Any]]:
        """Find files by TF-IDF keywords stored as JSONB."""
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                conditions = []
                params: List[Any] = []
                for kw in keywords:
                    conditions.append("""(
                        ca.keywords @> jsonb_build_array(%s::text)
                        OR EXISTS (
                            SELECT 1 FROM jsonb_array_elements(ca.tfidf_keywords) pair
                            WHERE pair->>0 = %s
                        )
                    )""")
                    params.extend([kw, kw])

                where = ' OR '.join(conditions) if conditions else 'TRUE'
                cur.execute(f"""
                    SELECT fm.file_path, fm.file_type, fm.last_modified,
                           ca.keywords, ca.tfidf_keywords
                    FROM file_metadata fm
                    JOIN content_analysis ca ON fm.file_path = ca.file_path
                    WHERE {where}
                    ORDER BY fm.last_modified DESC NULLS LAST
                    LIMIT %s
                """, params + [limit])
                rows = cur.fetchall()
        finally:
            self._put_conn(conn)

        return [
            {
                'file_path': row['file_path'],
                'file_name': os.path.basename(row['file_path']),
                'file_type': row['file_type'] or '',
                'modified_date': str(row['last_modified'])[:19] if row['last_modified'] else '',
                'keywords': row['keywords'] or [],
                'tfidf_keywords': row['tfidf_keywords'] or [],
            }
            for row in rows
        ]

    def get_stats(self) -> Dict[str, Any]:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM file_metadata")
                total_files, total_bytes = cur.fetchone()

                cur.execute("""
                    SELECT file_type, COUNT(*) FROM file_metadata
                    GROUP BY file_type ORDER BY COUNT(*) DESC LIMIT 10
                """)
                top_types = [{'type': r[0] or '', 'count': r[1]} for r in cur.fetchall()]

                cur.execute("SELECT COUNT(*) FROM content_analysis")
                analyzed = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM text_chunks")
                total_chunks = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM text_chunks WHERE lsa_vec IS NOT NULL")
                embedded_chunks = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(DISTINCT regexp_replace(file_path, '/[^/]+$', ''))
                    FROM file_metadata
                """)
                total_dirs = cur.fetchone()[0]
        finally:
            self._put_conn(conn)

        return {
            'total_files': total_files,
            'total_size_bytes': int(total_bytes),
            'total_size_mb': round(int(total_bytes) / (1024 * 1024), 2),
            'top_file_types': top_types,
            'files_with_content_analysis': analyzed,
            'total_chunks': total_chunks,
            'embedded_chunks': embedded_chunks,
            'total_directories': total_dirs,
        }


# Initialize database interface
try:
    db = FileMetadataDB()
    print("✓ File metadata MCP server ready - PostgreSQL: file_metadata", flush=True, file=sys.stderr)
except Exception as e:
    print(f"Error connecting to PostgreSQL: {e}", flush=True, file=sys.stderr)
    exit(1)

# Initialize autograph manager for knowledge graph
autograph_mgr: Optional[Any] = None
if AUTOGRAPH_AVAILABLE and AutographManager is not None:
    try:
        os.makedirs(KG_PATH, exist_ok=True)
        autograph_mgr = AutographManager(KG_PATH)
        print(f"✓ Autograph knowledge graph ready - Path: {KG_PATH}", flush=True, file=sys.stderr)
    except Exception as e:
        print(f"Warning: Could not initialize autograph manager: {e}", flush=True, file=sys.stderr)

# Create MCP server
server = Server("file-metadata-mcp")


@server.list_tools()
async def handle_list_tools() -> List[Tool]:
    return [
        Tool(
            name="search_files",
            description="""Search files by metadata criteria. Like 'find' command but faster.

Examples:
- Find Python files: file_type=".py"
- Find in directory: directory="/Users/mark/src"
- Find recent files: modified_since="2024-01-01"
- Find large files: min_size=1000000 (bytes)
- Combine criteria for precise results""",
            inputSchema={
                "type": "object",
                "properties": {
                    "name_pattern": {
                        "type": "string",
                        "description": "Search files with this pattern in filename (e.g., 'test', 'config')"
                    },
                    "file_type": {
                        "type": "string",
                        "description": "File extension or MIME type (e.g., '.py', '.md', 'text/plain')"
                    },
                    "directory": {
                        "type": "string",
                        "description": "Filter to files in this directory path"
                    },
                    "modified_since": {
                        "type": "string",
                        "description": "Files modified since this date (YYYY-MM-DD)"
                    },
                    "min_size": {
                        "type": "integer",
                        "description": "Minimum file size in bytes"
                    },
                    "max_size": {
                        "type": "integer",
                        "description": "Maximum file size in bytes"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return (default: 20)",
                        "default": 20
                    }
                }
            }
        ),
        Tool(
            name="full_text_search",
            description="""Search inside file contents using full-text search (tsvector).

Returns matching files with text snippets showing where the match was found.
Supports phrases ("exact phrase"), OR, and exclusion (-term).

Examples:
- Find files mentioning: query="authentication"
- Exact phrase: query='"API endpoint"'
- Boolean: query="python async"
- Exclude: query="config -test" """,
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for in file content."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                        "default": 20
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_file_info",
            description="""Get complete information about a specific file.

Returns: full metadata, word count, extracted keywords, TF-IDF keywords,
LDA topics, and chunk count. Use this to understand a file's content and context.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Full path to the file"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="get_file_chunks",
            description="""Retrieve the text content chunks for a file.

Files are split into chunks for processing. Use this to read actual file content.
Optionally get a specific chunk by index, or all chunks for the file.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Full path to the file"
                    },
                    "chunk_index": {
                        "type": "integer",
                        "description": "Optional: specific chunk index to retrieve"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="list_directories",
            description="""Browse indexed directories with file counts and sizes.

Use this to explore the file structure and find where files are concentrated.
Optionally filter to subdirectories of a parent path.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "parent": {
                        "type": "string",
                        "description": "Optional: parent directory to filter (e.g., '/Users/mark/src')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum directories to return (default: 50)",
                        "default": 50
                    }
                }
            }
        ),
        Tool(
            name="search_by_keywords",
            description="""Find files by their extracted keywords (TF-IDF analysis).

Unlike full-text search, this finds files where terms are statistically important,
not just present. Good for finding files "about" a topic.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of keywords to search for (e.g., ['api', 'authentication'])"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                        "default": 20
                    }
                },
                "required": ["keywords"]
            }
        ),
        Tool(
            name="get_stats",
            description="""Get database statistics and overview.

Returns: total files, total size, top file types, directories count,
files with content analysis, total text chunks, embedded chunks.""",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="semantic_search",
            description="""Search files by meaning using LSA vectors (pgvector cosine similarity).

Unlike full-text search (exact matches), this finds semantically similar content.
"authentication flow" finds docs about "login process", "user credentials", etc.

Returns similarity scores and text previews.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query describing what you're looking for"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                        "default": 20
                    }
                },
                "required": ["query"]
            }
        ),
        # Knowledge Graph / Autograph tools
        Tool(
            name="log_autograph",
            description="""Log a grounding choice to the knowledge graph.

Called after user accepts/rejects sources during grounding. Creates autograph
entries that help future grounding suggestions. The system learns which sources
are useful for which contexts over time.

Bootstrap phases: Cold (0 edges) → Learning (<10) → Warm (10-50) → Hot (>50)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "context_summary": {
                        "type": "string",
                        "description": "Summary of what user was working on"
                    },
                    "command": {
                        "type": "string",
                        "description": "Which grounding command: ground, preground, postground, cite, research"
                    },
                    "sources_offered": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Files/sources offered to user"
                    },
                    "sources_accepted": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Files/sources user accepted"
                    },
                    "sources_rejected": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Files/sources user rejected"
                    }
                },
                "required": ["context_summary", "command", "sources_offered"]
            }
        ),
        Tool(
            name="query_autographs",
            description="""Query the autograph knowledge graph for patterns.

Find what sources are typically useful for a given context based on prior
grounding choices. Uses semantic similarity to find related contexts.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "context": {
                        "type": "string",
                        "description": "Context to find patterns for"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 10)",
                        "default": 10
                    }
                },
                "required": ["context"]
            }
        ),
        Tool(
            name="autograph_suggest",
            description="""Get auto-suggestions based on accumulated autographs.

Returns sources that were frequently accepted in similar contexts. Use this
to enable KG-assisted grounding - the system suggests files based on learned
patterns from past grounding decisions.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "context": {
                        "type": "string",
                        "description": "Current context to get suggestions for"
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Confidence threshold 0-1 (default: 0.5)"
                    }
                },
                "required": ["context"]
            }
        ),
        Tool(
            name="autograph_stats",
            description="""Get statistics about the autograph knowledge graph.

Shows total nodes, edges, bootstrap phase (Cold/Learning/Warm/Hot), node types,
edge types, and embedding status. Use to monitor KG health and learning progress.""",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="recall",
            description="""Semantic recall: "What have I worked on / written about X?"

Searches all indexed files using cosine similarity, then expands each hit to
include adjacent chunks for full context. Returns formatted text ready to read.

Use this to surface prior work, design decisions, or session notes relevant to
the current task. Prefer this over semantic_search when you want readable prose
output rather than a structured result list.

Optional scope parameter limits search to a directory prefix, e.g.
scope="/Users/mark/.claude" to search only AI session logs.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "thought": {
                        "type": "string",
                        "description": "What you're trying to recall — a concept, question, or topic"
                    },
                    "k": {
                        "type": "integer",
                        "description": "Number of results to return (default: 3)",
                        "default": 3
                    },
                    "scope": {
                        "type": "string",
                        "description": "Optional path prefix to scope the search (e.g. '/Users/mark/.claude')"
                    }
                },
                "required": ["thought"]
            }
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
    try:
        if name == "search_files":
            results = db.search_files_by_metadata(**arguments)

            if results:
                response = f"Found {len(results)} files:\n\n"
                for r in results:
                    size_kb = r['file_size'] / 1024
                    response += f"• {r['file_path']}\n"
                    response += f"  Type: {r['file_type']} | Size: {size_kb:.1f}KB | Modified: {r['modified_date']}\n"
            else:
                response = "No files found matching the criteria."

            return CallToolResult(content=[TextContent(type="text", text=response)])

        elif name == "full_text_search":
            query = arguments.get("query")
            if not query:
                return CallToolResult(
                    content=[TextContent(type="text", text="Error: query parameter is required")],
                    isError=True
                )

            results = db.full_text_search(query, arguments.get("limit", 20))

            if results:
                response = f"Found {len(results)} matches for '{query}':\n\n"
                for r in results:
                    response += f"• {r['file_path']}\n"
                    response += f"  Type: {r['file_type']} | Modified: {r['modified_date']}\n"
                    response += f"  Snippet: {r['snippet']}\n\n"
            else:
                response = f"No matches found for '{query}'."

            return CallToolResult(content=[TextContent(type="text", text=response)])

        elif name == "get_file_info":
            file_path = arguments.get("file_path")
            if not file_path:
                return CallToolResult(
                    content=[TextContent(type="text", text="Error: file_path is required")],
                    isError=True
                )

            result = db.get_file_info(file_path)

            if result:
                size_kb = (result.get('file_size') or 0) / 1024
                response = f"File: {result['file_name']}\n"
                response += f"Path: {result['file_path']}\n"
                response += f"Type: {result.get('file_type', '')} ({result.get('mime_type', '')})\n"
                response += f"Size: {size_kb:.1f}KB\n"
                response += f"Modified: {result['modified_date']}\n"

                if result.get('word_count'):
                    response += f"\nContent Analysis:\n"
                    response += f"  Words: {result['word_count']} | Chars: {result.get('char_count', 0)}\n"
                    response += f"  Chunks: {result['chunk_count']}\n"

                    if result.get('keywords'):
                        kws = result['keywords']
                        if isinstance(kws, list):
                            response += f"  Keywords: {', '.join(str(k) for k in kws[:10])}\n"

                    if result.get('tfidf_keywords'):
                        top_tfidf = result['tfidf_keywords'][:5]
                        top_words = [kw[0] if isinstance(kw, list) else kw for kw in top_tfidf]
                        response += f"  TF-IDF: {', '.join(str(k) for k in top_words)}\n"
            else:
                response = f"File not found in database: {file_path}"

            return CallToolResult(content=[TextContent(type="text", text=response)])

        elif name == "get_file_chunks":
            file_path = arguments.get("file_path")
            if not file_path:
                return CallToolResult(
                    content=[TextContent(type="text", text="Error: file_path is required")],
                    isError=True
                )

            chunks = db.get_file_chunks(file_path, arguments.get("chunk_index"))

            if chunks:
                response = f"File: {file_path}\n"
                response += f"Chunks: {len(chunks)}\n\n"
                for chunk in chunks:
                    response += f"--- Chunk {chunk['chunk_index']} ---\n"
                    response += f"{chunk['chunk_text']}\n\n"
            else:
                response = f"No chunks found for: {file_path}"

            return CallToolResult(content=[TextContent(type="text", text=response)])

        elif name == "list_directories":
            results = db.list_directories(
                arguments.get("parent"),
                arguments.get("limit", 50)
            )

            if results:
                response = "Indexed directories:\n\n"
                for r in results:
                    size_mb = (r['total_size'] or 0) / (1024 * 1024)
                    response += f"• {r['directory']}\n"
                    response += f"  Files: {r['file_count']} | Size: {size_mb:.1f}MB\n"
            else:
                response = "No directories found."

            return CallToolResult(content=[TextContent(type="text", text=response)])

        elif name == "search_by_keywords":
            keywords = arguments.get("keywords")
            if not keywords:
                return CallToolResult(
                    content=[TextContent(type="text", text="Error: keywords array is required")],
                    isError=True
                )

            results = db.search_by_keywords(keywords, arguments.get("limit", 20))

            if results:
                response = f"Found {len(results)} files matching keywords {keywords}:\n\n"
                for r in results:
                    response += f"• {r['file_path']}\n"
                    response += f"  Type: {r['file_type']} | Modified: {r['modified_date']}\n"
                    kws = r.get('keywords') or []
                    if kws:
                        response += f"  Keywords: {', '.join(str(k) for k in kws[:5])}\n"
                    response += "\n"
            else:
                response = f"No files found matching keywords: {keywords}"

            return CallToolResult(content=[TextContent(type="text", text=response)])

        elif name == "get_stats":
            stats = db.get_stats()

            response = "Database Statistics:\n\n"
            response += f"Total Files: {stats['total_files']:,}\n"
            response += f"Total Size: {stats['total_size_mb']:.1f} MB\n"
            response += f"Directories: {stats['total_directories']:,}\n"
            response += f"Files with Content Analysis: {stats['files_with_content_analysis']:,}\n"
            response += f"Total Text Chunks: {stats['total_chunks']:,}\n"
            response += f"\nVector Semantic Search (pgvector):\n"
            response += f"  Embedded chunks: {stats['embedded_chunks']:,} / {stats['total_chunks']:,}\n"

            response += f"\nTop File Types:\n"
            for ft in stats['top_file_types']:
                response += f"  {ft['type']}: {ft['count']:,}\n"

            return CallToolResult(content=[TextContent(type="text", text=response)])

        elif name == "semantic_search":
            query = arguments.get("query")
            if not query:
                return CallToolResult(
                    content=[TextContent(type="text", text="Error: query parameter is required")],
                    isError=True
                )

            if not db.is_semantic_available():
                return CallToolResult(
                    content=[TextContent(type="text", text="Semantic search not available: no embeddings in database.")],
                    isError=True
                )

            results = db.semantic_search(query, arguments.get("limit", 20))

            if results:
                response = f"Found {len(results)} semantically similar results for '{query}':\n\n"
                for r in results:
                    response += f"• {r['file_path']} (chunk {r['chunk_index']})\n"
                    response += f"  Similarity: {r['similarity']:.2%} | Type: {r['file_type']} | Modified: {r['modified_date']}\n"
                    response += f"  Preview: {r['chunk_text']}...\n\n"
            else:
                response = f"No semantically similar results found for '{query}'."

            return CallToolResult(content=[TextContent(type="text", text=response)])

        elif name == "recall":
            thought = arguments.get("thought")
            if not thought:
                return CallToolResult(
                    content=[TextContent(type="text", text="Error: thought parameter is required")],
                    isError=True
                )
            if not db.is_semantic_available():
                return CallToolResult(
                    content=[TextContent(type="text", text="Recall unavailable: no embeddings in database.")],
                    isError=True
                )
            result = db.recall(
                thought,
                k=arguments.get("k", 3),
                scope=arguments.get("scope", ""),
            )
            return CallToolResult(content=[TextContent(type="text", text=result)])

        # ====================================================================
        # Knowledge Graph / Autograph Tools
        # ====================================================================

        elif name == "log_autograph":
            if autograph_mgr is None:
                return CallToolResult(
                    content=[TextContent(type="text", text="Autograph manager not available. Check installation.")],
                    isError=True
                )

            context_summary = arguments.get("context_summary", "")
            command = arguments.get("command", "ground")
            sources_offered = arguments.get("sources_offered", [])
            sources_accepted = arguments.get("sources_accepted", [])
            sources_rejected = arguments.get("sources_rejected", [])

            result = autograph_mgr.log_autograph(
                context_summary=context_summary,
                command=command,
                sources_offered=sources_offered,
                sources_accepted=sources_accepted,
                sources_rejected=sources_rejected
            )

            response = f"Autograph logged successfully:\n"
            response += f"  Context node: {result['context_node']}\n"
            response += f"  Edges created: {result['edges_created']}\n"
            response += f"  Accepted: {result['accepted']}, Rejected: {result['rejected']}, Ignored: {result['ignored']}"

            return CallToolResult(content=[TextContent(type="text", text=response)])

        elif name == "query_autographs":
            if autograph_mgr is None:
                return CallToolResult(
                    content=[TextContent(type="text", text="Autograph manager not available. Check installation.")],
                    isError=True
                )

            context = arguments.get("context", "")
            limit = arguments.get("limit", 10)

            results = autograph_mgr.query_autographs(context, limit)

            if not results:
                response = f"No autographs found for context: '{context}'"
            else:
                response = f"Found {len(results)} autograph entries for '{context}':\n\n"
                for i, entry in enumerate(results, 1):
                    similarity = entry.get('context_similarity', 'N/A')
                    if isinstance(similarity, float):
                        similarity = f"{similarity:.2%}"
                    response += f"{i}. [{entry['edge_type']}] {entry['target_node']}\n"
                    response += f"   Weight: {entry['weight']}, Similarity: {similarity}\n"
                    ctx_preview = entry['context_summary'][:50]
                    response += f"   Context: {ctx_preview}...\n"
                    response += f"   Command: {entry['command']}\n\n"

            return CallToolResult(content=[TextContent(type="text", text=response)])

        elif name == "autograph_suggest":
            if autograph_mgr is None:
                return CallToolResult(
                    content=[TextContent(type="text", text="Autograph manager not available. Check installation.")],
                    isError=True
                )

            context = arguments.get("context", "")
            threshold = arguments.get("threshold", 0.5)

            suggestions = autograph_mgr.suggest_sources(context, threshold)

            if not suggestions:
                response = f"No suggestions available for context: '{context}'\n"
                response += "(Need more autographs or try lowering threshold)"
            else:
                response = f"Suggested sources for '{context}':\n\n"
                for i, suggestion in enumerate(suggestions, 1):
                    response += f"{i}. {suggestion['source']}\n"
                    response += f"   Confidence: {suggestion['confidence']:.1%}\n"
                    response += f"   Accept/Reject: {suggestion['accept_count']:.1f}/{suggestion['reject_count']:.1f}\n\n"

            return CallToolResult(content=[TextContent(type="text", text=response)])

        elif name == "autograph_stats":
            if autograph_mgr is None:
                return CallToolResult(
                    content=[TextContent(type="text", text="Autograph manager not available. Check installation.")],
                    isError=True
                )

            stats = autograph_mgr.get_stats()

            response = "Autograph Knowledge Graph Statistics:\n\n"
            response += f"Bootstrap Phase: {stats['bootstrap_phase']}\n"
            response += f"Total Nodes: {stats['total_nodes']}\n"
            response += f"Total Edges: {stats['total_edges']}\n"
            response += f"Embeddings Available: {stats['embeddings_available']}\n"
            response += f"Embeddings Count: {stats['embeddings_count']}\n"

            if stats['node_types']:
                response += "\nNode Types:\n"
                for ntype, count in stats['node_types'].items():
                    response += f"  • {ntype}: {count}\n"

            if stats['edge_types']:
                response += "\nEdge Types:\n"
                for etype, count in stats['edge_types'].items():
                    response += f"  • {etype}: {count}\n"

            response += "\nBootstrap Phases:\n"
            response += "  Cold: No autographs, manual grounding only\n"
            response += "  Learning: <10 edges, patterns emerging\n"
            response += "  Warm: 10-50 edges, auto-suggestions available\n"
            response += "  Hot: >50 edges, high-confidence suggestions\n"

            return CallToolResult(content=[TextContent(type="text", text=response)])

        else:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Unknown tool: {name}")],
                isError=True
            )

    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {str(e)}")],
            isError=True
        )


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="file-metadata-mcp",
                server_version="3.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={}
                )
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
