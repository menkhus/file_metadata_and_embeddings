#!/usr/bin/env python3
"""
MCP Server for File Metadata Tool - Full Feature Version

This MCP server exposes the file metadata database to LLMs via standardized tools.
Provides comprehensive access to file metadata, content search, keywords, and topics.

Available tools:
- search_files: Search by metadata (name, type, date, size, directory, permissions)
- full_text_search: FTS5 content search with snippets
- get_file_info: Full metadata + keywords + topics for a file
- get_file_chunks: Retrieve text chunks for a file
- list_directories: Browse indexed directories with stats
- search_by_keywords: Find files by TF-IDF keywords
- get_stats: Database statistics and overview
- semantic_search: FAISS vector similarity search (when index available)
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

# FAISS index paths - optional, for semantic search
FAISS_INDEX_PATH = os.environ.get('FAISS_INDEX', os.path.expanduser('~/data/file_search.faiss'))
FAISS_META_PATH = os.environ.get('FAISS_META', os.path.expanduser('~/data/file_search_meta.json'))

# Try to load FAISS and sentence-transformers (optional)
try:
    import faiss
    from sentence_transformers import SentenceTransformer
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False


class FileMetadataDB:
    """Database interface for file metadata operations"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database not found at {db_path}")

        # FAISS index (loaded lazily)
        self.faiss_index = None
        self.faiss_metadata = None
        self.sentence_model = None

    def _load_faiss_index(self):
        """Load FAISS index and metadata if available"""
        if not FAISS_AVAILABLE:
            return False

        if self.faiss_index is not None:
            return True

        if os.path.exists(FAISS_INDEX_PATH) and os.path.exists(FAISS_META_PATH):
            try:
                self.faiss_index = faiss.read_index(FAISS_INDEX_PATH)
                with open(FAISS_META_PATH, 'r') as f:
                    data = json.load(f)

                # Handle both old format (list) and new format (dict with build_info)
                if isinstance(data, dict) and 'vectors' in data:
                    self.faiss_metadata = data['vectors']
                    build_info = data.get('build_info', {})

                    # Check staleness
                    index_chunks = build_info.get('db_chunks_at_build', 0)
                    if index_chunks > 0:
                        with self.get_connection() as conn:
                            cursor = conn.execute("SELECT COUNT(*) as count FROM text_chunks")
                            current_chunks = cursor.fetchone()['count']
                            if current_chunks > index_chunks:
                                print(f"Note: FAISS index may be stale ({index_chunks:,} vectors, but DB has {current_chunks:,} chunks). "
                                      f"Run build_faiss_index.py to update.", file=sys.stderr)
                else:
                    # Old format - just a list of metadata
                    self.faiss_metadata = data

                self.sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
                return True
            except Exception as e:
                print(f"Error loading FAISS index: {e}", file=sys.stderr)
                return False
        return False

    def semantic_search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Perform semantic similarity search using FAISS"""
        if not self._load_faiss_index():
            return []

        try:
            # Encode query
            query_embedding = self.sentence_model.encode([query])[0]
            query_embedding = np.array([query_embedding]).astype('float32')

            # Search FAISS index
            distances, indices = self.faiss_index.search(query_embedding, limit)

            results = []
            for i, idx in enumerate(indices[0]):
                if idx < 0 or idx >= len(self.faiss_metadata):
                    continue

                meta = self.faiss_metadata[idx]
                results.append({
                    'file_path': meta.get('file_path'),
                    'file_name': meta.get('file_name'),
                    'file_type': meta.get('file_type'),
                    'chunk_index': meta.get('chunk_index'),
                    'chunk_text': meta.get('chunk_text', '')[:200],  # Preview
                    'similarity': float(1 / (1 + distances[0][i])),  # Convert distance to similarity
                    'tfidf_keywords': meta.get('tfidf_keywords', [])[:5]
                })

            return results
        except Exception as e:
            print(f"Semantic search error: {e}")
            return []

    def is_faiss_available(self) -> bool:
        """Check if FAISS index is available"""
        return self._load_faiss_index()

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
            response += f"FAISS Semantic Search: {'Available' if db.is_faiss_available() else 'Not available (index not built)'}\n"
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
                server_version="2.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={}
                )
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
