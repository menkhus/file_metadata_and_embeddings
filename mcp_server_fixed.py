#!/usr/bin/env python3
"""
MCP Server for File Metadata Tool - Full Feature Version

This MCP server exposes the file metadata database to LLMs via standardized tools.
Provides comprehensive access to file metadata, content search, keywords, topics,
and knowledge graph learning from grounding decisions.

Available tools:
- search_files: Search by metadata (name, type, date, size, directory, permissions)
- full_text_search: FTS5 content search with snippets
- get_file_info: Full metadata + keywords + topics for a file
- get_file_chunks: Retrieve text chunks for a file
- list_directories: Browse indexed directories with stats
- search_by_keywords: Find files by TF-IDF keywords
- get_stats: Database statistics and overview
- semantic_search: FAISS vector similarity search (when index available)
- log_autograph: Log grounding choices to knowledge graph
- query_autographs: Query KG for patterns related to a context
- autograph_suggest: Get auto-suggestions based on learned patterns
- autograph_stats: View KG statistics and bootstrap phase
"""

import asyncio
import sqlite3
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np

# MCP imports
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.lowlevel import NotificationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    TextContent,
    Tool,
)

# Database path - can be overridden via environment variable
DB_PATH = os.environ.get('FILE_METADATA_DB', os.path.expanduser('~/data/file_metadata.sqlite3'))

# FAISS data directory - for two-tier index architecture
FAISS_DATA_DIR = os.environ.get('FAISS_DATA_DIR', os.path.expanduser('~/data'))

# Knowledge graph directory - for autograph learning
KG_PATH = os.environ.get('KG_PATH', os.path.join(os.path.dirname(__file__), 'knowledge_graph'))

# Try to load FAISS and sentence-transformers (optional)
try:
    import faiss
    from sentence_transformers import SentenceTransformer
    from faiss_index_manager import TwoTierFAISSManager
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    TwoTierFAISSManager = None

# Try to load autograph manager for knowledge graph (optional)
try:
    from autograph_manager import AutographManager
    AUTOGRAPH_AVAILABLE = True
except ImportError:
    AUTOGRAPH_AVAILABLE = False
    AutographManager = None


class FileMetadataDB:
    """Database interface for file metadata operations"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database not found at {db_path}")

        # Two-tier FAISS index manager (loaded lazily)
        self.faiss_manager: Optional[TwoTierFAISSManager] = None
        self.sentence_model = None
        self._faiss_load_attempted = False

    def _load_faiss_index(self) -> bool:
        """Load two-tier FAISS index manager if available"""
        if not FAISS_AVAILABLE:
            return False

        if self.faiss_manager is not None:
            return True

        if self._faiss_load_attempted:
            return False

        self._faiss_load_attempted = True

        try:
            self.faiss_manager = TwoTierFAISSManager(data_dir=FAISS_DATA_DIR)

            # Check for legacy index and migrate if needed
            self.faiss_manager.migrate_from_legacy()

            stats = self.faiss_manager.get_stats()
            if stats['total_vectors'] == 0:
                print("Note: FAISS indexes are empty. Run build_faiss_index.py to build.", file=sys.stderr)
                return False

            # Check staleness
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) as count FROM text_chunks")
                current_chunks = cursor.fetchone()['count']
                if current_chunks > stats['total_vectors']:
                    print(f"Note: FAISS index may be stale ({stats['total_vectors']:,} vectors, but DB has {current_chunks:,} chunks). "
                          f"Run build_faiss_index.py --add-only to update.", file=sys.stderr)

            self.sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
            return True
        except Exception as e:
            print(f"Error loading FAISS index: {e}", file=sys.stderr)
            self.faiss_manager = None
            return False

    def semantic_search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Perform semantic similarity search using two-tier FAISS indexes"""
        if not self._load_faiss_index():
            return []

        try:
            # Encode query
            query_embedding = self.sentence_model.encode([query])[0]
            query_embedding = np.array(query_embedding).astype('float32')

            # Search both indexes via manager
            search_results = self.faiss_manager.search(query_embedding, top_k=limit)

            results = []
            for r in search_results:
                results.append({
                    'file_path': r.file_path,
                    'file_name': r.metadata.get('file_name', ''),
                    'file_type': r.metadata.get('file_type', ''),
                    'chunk_index': r.chunk_index,
                    'chunk_text': r.chunk_text[:200] if r.chunk_text else '',  # Preview
                    'similarity': r.similarity_score,
                    'tier': r.tier,  # 'major' or 'minor'
                    'tfidf_keywords': r.metadata.get('tfidf_keywords', [])[:5]
                })

            return results
        except Exception as e:
            print(f"Semantic search error: {e}", file=sys.stderr)
            return []

    def is_faiss_available(self) -> bool:
        """Check if FAISS index is available"""
        return self._load_faiss_index()

    def get_faiss_stats(self) -> Optional[Dict[str, Any]]:
        """Get FAISS index statistics"""
        if not self._load_faiss_index():
            return None
        return self.faiss_manager.get_stats()

    def get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def search_files_by_metadata(self, **kwargs) -> List[Dict[str, Any]]:
        """Search files by metadata criteria"""

        with self.get_connection() as conn:
            query = "SELECT * FROM file_metadata WHERE 1=1"
            params = []

            if kwargs.get('name_pattern'):
                query += " AND file_name LIKE ?"
                params.append(f"%{kwargs['name_pattern']}%")

            if kwargs.get('file_type'):
                query += " AND (file_type LIKE ? OR mime_type LIKE ?)"
                params.extend([f"%{kwargs['file_type']}%", f"%{kwargs['file_type']}%"])

            if kwargs.get('directory'):
                query += " AND directory LIKE ?"
                params.append(f"%{kwargs['directory']}%")

            if kwargs.get('created_since'):
                query += " AND created_date >= ?"
                params.append(kwargs['created_since'])

            if kwargs.get('modified_since'):
                query += " AND modified_date >= ?"
                params.append(kwargs['modified_since'])

            if kwargs.get('min_size'):
                query += " AND file_size >= ?"
                params.append(kwargs['min_size'])

            if kwargs.get('max_size'):
                query += " AND file_size <= ?"
                params.append(kwargs['max_size'])

            if kwargs.get('permissions'):
                query += " AND permissions = ?"
                params.append(kwargs['permissions'])

            query += " ORDER BY modified_date DESC LIMIT ?"
            params.append(kwargs.get('limit', 20))

            cursor = conn.execute(query, params)
            results = []

            for row in cursor:
                results.append({
                    "file_path": row['file_path'],
                    "file_name": row['file_name'],
                    "directory": row['directory'],
                    "file_size": row['file_size'],
                    "file_type": row['file_type'],
                    "mime_type": row['mime_type'],
                    "created_date": row['created_date'],
                    "modified_date": row['modified_date'],
                    "permissions": row['permissions']
                })

            return results

    def full_text_search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Perform full-text search using FTS5"""

        with self.get_connection() as conn:
            sql = """
            SELECT
                fts.file_path,
                snippet(content_fts, 1, '>>>', '<<<', '...', 64) as snippet,
                fm.file_name,
                fm.file_type,
                fm.modified_date
            FROM content_fts fts
            LEFT JOIN file_metadata fm ON fts.file_path = fm.file_path
            WHERE content_fts MATCH ?
            LIMIT ?
            """

            cursor = conn.execute(sql, [query, limit])
            results = []

            for row in cursor:
                results.append({
                    'file_path': row['file_path'],
                    'file_name': row['file_name'],
                    'file_type': row['file_type'],
                    'modified_date': row['modified_date'],
                    'snippet': row['snippet']
                })

            return results

    def get_file_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get full metadata, keywords, and topics for a specific file"""

        with self.get_connection() as conn:
            # Get file metadata
            cursor = conn.execute(
                "SELECT * FROM file_metadata WHERE file_path = ?",
                [file_path]
            )
            row = cursor.fetchone()

            if not row:
                return None

            result = dict(row)

            # Get content analysis (keywords, topics)
            cursor = conn.execute(
                """SELECT word_count, char_count, language, keywords,
                          tfidf_keywords, lda_topics
                   FROM content_analysis WHERE file_path = ?""",
                [file_path]
            )
            analysis = cursor.fetchone()

            if analysis:
                result['word_count'] = analysis['word_count']
                result['char_count'] = analysis['char_count']
                result['language'] = analysis['language']
                result['keywords'] = json.loads(analysis['keywords']) if analysis['keywords'] else []
                result['tfidf_keywords'] = json.loads(analysis['tfidf_keywords']) if analysis['tfidf_keywords'] else []
                result['lda_topics'] = json.loads(analysis['lda_topics']) if analysis['lda_topics'] else []

            # Get chunk count
            cursor = conn.execute(
                "SELECT COUNT(*) as chunk_count FROM text_chunks WHERE file_path = ?",
                [file_path]
            )
            result['chunk_count'] = cursor.fetchone()['chunk_count']

            return result

    def get_file_chunks(self, file_path: str, chunk_index: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get text chunks for a file"""

        with self.get_connection() as conn:
            if chunk_index is not None:
                cursor = conn.execute(
                    """SELECT chunk_index, chunk_text
                       FROM text_chunks WHERE file_path = ? AND chunk_index = ?""",
                    [file_path, chunk_index]
                )
            else:
                cursor = conn.execute(
                    """SELECT chunk_index, chunk_text
                       FROM text_chunks WHERE file_path = ? ORDER BY chunk_index""",
                    [file_path]
                )

            return [{'chunk_index': row['chunk_index'], 'chunk_text': row['chunk_text']}
                    for row in cursor]

    def list_directories(self, parent: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List indexed directories with file counts"""

        with self.get_connection() as conn:
            if parent:
                cursor = conn.execute(
                    """SELECT directory, COUNT(*) as file_count,
                              SUM(file_size) as total_size
                       FROM file_metadata
                       WHERE directory LIKE ?
                       GROUP BY directory
                       ORDER BY file_count DESC LIMIT ?""",
                    [f"{parent}%", limit]
                )
            else:
                cursor = conn.execute(
                    """SELECT directory, COUNT(*) as file_count,
                              SUM(file_size) as total_size
                       FROM file_metadata
                       GROUP BY directory
                       ORDER BY file_count DESC LIMIT ?""",
                    [limit]
                )

            return [{'directory': row['directory'],
                     'file_count': row['file_count'],
                     'total_size': row['total_size']}
                    for row in cursor]

    def search_by_keywords(self, keywords: List[str], limit: int = 20) -> List[Dict[str, Any]]:
        """Find files matching TF-IDF keywords"""

        with self.get_connection() as conn:
            # Build query to search in keywords JSON
            conditions = []
            params = []
            for kw in keywords:
                conditions.append("(ca.keywords LIKE ? OR ca.tfidf_keywords LIKE ?)")
                params.extend([f'%"{kw}"%', f'%"{kw}"%'])

            query = f"""
                SELECT fm.file_path, fm.file_name, fm.file_type, fm.modified_date,
                       ca.keywords, ca.tfidf_keywords
                FROM file_metadata fm
                JOIN content_analysis ca ON fm.file_path = ca.file_path
                WHERE {' OR '.join(conditions)}
                ORDER BY fm.modified_date DESC
                LIMIT ?
            """
            params.append(limit)

            cursor = conn.execute(query, params)
            results = []

            for row in cursor:
                results.append({
                    'file_path': row['file_path'],
                    'file_name': row['file_name'],
                    'file_type': row['file_type'],
                    'modified_date': row['modified_date'],
                    'keywords': json.loads(row['keywords']) if row['keywords'] else [],
                    'tfidf_keywords': json.loads(row['tfidf_keywords']) if row['tfidf_keywords'] else []
                })

            return results

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics"""

        with self.get_connection() as conn:
            stats = {}

            # Total files
            cursor = conn.execute("SELECT COUNT(*) as count FROM file_metadata")
            stats['total_files'] = cursor.fetchone()['count']

            # Total size
            cursor = conn.execute("SELECT SUM(file_size) as total FROM file_metadata")
            stats['total_size_bytes'] = cursor.fetchone()['total'] or 0
            stats['total_size_mb'] = round(stats['total_size_bytes'] / (1024*1024), 2)

            # Files by type (top 10)
            cursor = conn.execute(
                """SELECT file_type, COUNT(*) as count
                   FROM file_metadata
                   GROUP BY file_type
                   ORDER BY count DESC LIMIT 10"""
            )
            stats['top_file_types'] = [{'type': row['file_type'], 'count': row['count']}
                                        for row in cursor]

            # Text files with content analysis
            cursor = conn.execute("SELECT COUNT(*) as count FROM content_analysis")
            stats['files_with_content_analysis'] = cursor.fetchone()['count']

            # Total chunks
            cursor = conn.execute("SELECT COUNT(*) as count FROM text_chunks")
            stats['total_chunks'] = cursor.fetchone()['count']

            # Directory count
            cursor = conn.execute("SELECT COUNT(DISTINCT directory) as count FROM file_metadata")
            stats['total_directories'] = cursor.fetchone()['count']

            return stats


# Initialize database interface
try:
    db = FileMetadataDB(DB_PATH)
    print(f"✓ File metadata MCP server ready - Database: {DB_PATH}", flush=True)
except FileNotFoundError as e:
    print(f"Error: {e}", flush=True)
    exit(1)

# Initialize autograph manager for knowledge graph
autograph_mgr: Optional[AutographManager] = None
if AUTOGRAPH_AVAILABLE:
    try:
        # Create knowledge_graph directory if it doesn't exist
        os.makedirs(KG_PATH, exist_ok=True)
        autograph_mgr = AutographManager(KG_PATH)
        print(f"✓ Autograph knowledge graph ready - Path: {KG_PATH}", flush=True)
    except Exception as e:
        print(f"Warning: Could not initialize autograph manager: {e}", flush=True)

# Create MCP server
server = Server("file-metadata-mcp")


@server.list_tools()
async def handle_list_tools() -> List[Tool]:
    """List available tools for file metadata search and analysis"""
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
                    "created_since": {
                        "type": "string",
                        "description": "Files created since this date (YYYY-MM-DD)"
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
                    "permissions": {
                        "type": "string",
                        "description": "Unix permissions (e.g., '644', '755')"
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
            description="""Search inside file contents using full-text search (FTS5).

Returns matching files with text snippets showing where the match was found.
Supports phrases ("exact phrase") and boolean operators (AND, OR, NOT).

Examples:
- Find files mentioning: query="authentication"
- Exact phrase: query='"API endpoint"'
- Boolean: query="python AND async"
- Exclude: query="config NOT test" """,
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for in file content. Supports FTS5 syntax."
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
files with content analysis, total text chunks. Use to understand the indexed corpus.""",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="semantic_search",
            description="""Search files by meaning using AI embeddings (FAISS vector search).

Unlike full-text search (exact matches), this finds semantically similar content.
"authentication flow" finds docs about "login process", "user credentials", etc.

Requires FAISS index to be built. Returns similarity scores and text previews.""",
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
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
    """Handle tool calls"""

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
                size_kb = result['file_size'] / 1024
                response = f"File: {result['file_name']}\n"
                response += f"Path: {result['file_path']}\n"
                response += f"Type: {result['file_type']} ({result['mime_type']})\n"
                response += f"Size: {size_kb:.1f}KB\n"
                response += f"Permissions: {result['permissions']}\n"
                response += f"Created: {result['created_date']}\n"
                response += f"Modified: {result['modified_date']}\n"

                if result.get('word_count'):
                    response += f"\nContent Analysis:\n"
                    response += f"  Words: {result['word_count']} | Chars: {result['char_count']}\n"
                    response += f"  Chunks: {result['chunk_count']}\n"

                    if result.get('keywords'):
                        response += f"  Keywords: {', '.join(result['keywords'][:10])}\n"

                    if result.get('tfidf_keywords'):
                        top_tfidf = [kw[0] if isinstance(kw, list) else kw for kw in result['tfidf_keywords'][:5]]
                        response += f"  TF-IDF: {', '.join(str(k) for k in top_tfidf)}\n"
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
                    size_mb = (r['total_size'] or 0) / (1024*1024)
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
                    if r.get('keywords'):
                        response += f"  Keywords: {', '.join(r['keywords'][:5])}\n"
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

            # FAISS index status
            faiss_stats = db.get_faiss_stats()
            if faiss_stats:
                response += f"\nFAISS Semantic Search: Available\n"
                response += f"  Major index: {faiss_stats['major']['vector_count']:,} vectors"
                if faiss_stats['major']['build_timestamp']:
                    response += f" (built: {faiss_stats['major']['build_timestamp'][:10]})"
                response += "\n"
                if faiss_stats['minor']['vector_count'] > 0:
                    response += f"  Minor index: {faiss_stats['minor']['vector_count']:,} vectors (incremental)\n"
                response += f"  Total vectors: {faiss_stats['total_vectors']:,}\n"
                if faiss_stats['stale_vectors'] > 0:
                    response += f"  Stale vectors: {faiss_stats['stale_vectors']:,}\n"
            else:
                response += f"FAISS Semantic Search: Not available (index not built)\n"

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

            if not db.is_faiss_available():
                return CallToolResult(
                    content=[TextContent(type="text", text="Semantic search not available. FAISS index not built.\nRun: python3 build_faiss_index.py")],
                    isError=True
                )

            results = db.semantic_search(query, arguments.get("limit", 20))

            if results:
                response = f"Found {len(results)} semantically similar results for '{query}':\n\n"
                for r in results:
                    response += f"• {r['file_path']} (chunk {r['chunk_index']})\n"
                    response += f"  Similarity: {r['similarity']:.2%} | Type: {r['file_type']}\n"
                    response += f"  Preview: {r['chunk_text']}...\n"
                    if r.get('tfidf_keywords'):
                        response += f"  Keywords: {', '.join(r['tfidf_keywords'])}\n"
                    response += "\n"
            else:
                response = f"No semantically similar results found for '{query}'."

            return CallToolResult(content=[TextContent(type="text", text=response)])

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
    """Main server entry point"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="file-metadata-mcp",
                server_version="2.1.0",  # Added autograph/KG tools
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={}
                )
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
