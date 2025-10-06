#!/usr/bin/env python3
"""
Database integration for AI-optimized chunking system with JSONB storage
"""

import sqlite3
import json
from typing import List, Optional, Dict, Any
from pathlib import Path
import logging

from chunking_refactor import ChunkEnvelope, AIOptimizedChunker

logger = logging.getLogger(__name__)


class ChunkDatabase:
    """Database operations for chunk storage and retrieval"""

    def __init__(self, db_path: str = "file_metadata.db"):
        self.db_path = db_path
        self.chunker = AIOptimizedChunker()

    def get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize_schema(self):
        """Initialize the v2 chunking schema"""
        schema_path = Path(__file__).parent / "schema_refactor.sql"

        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        with self.get_connection() as conn:
            # Execute schema (split on GO or execute as-is)
            conn.executescript(schema_sql)
            conn.commit()

        logger.info("Chunk database schema initialized")

    def store_chunks(
        self,
        file_path: str,
        envelopes: List[ChunkEnvelope],
        embeddings: Optional[List[bytes]] = None
    ) -> int:
        """
        Store chunk envelopes in database

        Args:
            file_path: Path to source file
            envelopes: List of chunk envelopes to store
            embeddings: Optional list of embedding blobs

        Returns:
            Number of chunks stored
        """
        if not envelopes:
            return 0

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Delete existing chunks for this file
            cursor.execute("DELETE FROM text_chunks_v2 WHERE file_path = ?", (file_path,))

            # Insert new chunks
            for i, envelope in enumerate(envelopes):
                embedding_blob = embeddings[i] if embeddings and i < len(embeddings) else None

                cursor.execute('''
                    INSERT INTO text_chunks_v2 (
                        file_path,
                        chunk_index,
                        chunk_envelope,
                        chunk_strategy,
                        chunk_size,
                        total_chunks,
                        file_hash,
                        file_type,
                        created_at,
                        embedding
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    file_path,
                    envelope.metadata.chunk_index,
                    envelope.to_json(indent=None),  # Store compact JSON
                    envelope.metadata.chunk_strategy,
                    envelope.metadata.chunk_size,
                    envelope.metadata.total_chunks,
                    envelope.metadata.file_hash,
                    envelope.metadata.file_type,
                    envelope.metadata.created_at,
                    embedding_blob
                ))

            conn.commit()

        logger.info(f"Stored {len(envelopes)} chunks for {file_path}")
        return len(envelopes)

    def get_chunk(
        self,
        file_path: str,
        chunk_index: int,
        return_envelope: bool = True
    ) -> Optional[ChunkEnvelope | Dict[str, Any]]:
        """
        Retrieve a specific chunk

        Args:
            file_path: Path to file
            chunk_index: Index of chunk
            return_envelope: If True, return ChunkEnvelope; if False, return dict

        Returns:
            ChunkEnvelope or dict, or None if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT chunk_envelope
                FROM text_chunks_v2
                WHERE file_path = ? AND chunk_index = ?
            ''', (file_path, chunk_index))

            row = cursor.fetchone()
            if not row:
                return None

            json_data = row['chunk_envelope']

            if return_envelope:
                return ChunkEnvelope.from_json(json_data)
            else:
                return json.loads(json_data)

    def get_adjacent_chunks(
        self,
        file_path: str,
        chunk_index: int,
        before: int = 1,
        after: int = 1,
        return_envelopes: bool = True
    ) -> List[ChunkEnvelope | Dict[str, Any]]:
        """
        Retrieve adjacent chunks for context expansion

        Args:
            file_path: Path to file
            chunk_index: Target chunk index
            before: Number of chunks before to include
            after: Number of chunks after to include
            return_envelopes: Return as ChunkEnvelope objects or dicts

        Returns:
            List of chunks in order
        """
        start_idx = max(0, chunk_index - before)
        end_idx = chunk_index + after

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT chunk_envelope, chunk_index
                FROM text_chunks_v2
                WHERE file_path = ?
                  AND chunk_index BETWEEN ? AND ?
                ORDER BY chunk_index
            ''', (file_path, start_idx, end_idx))

            results = []
            for row in cursor.fetchall():
                json_data = row['chunk_envelope']
                if return_envelopes:
                    results.append(ChunkEnvelope.from_json(json_data))
                else:
                    results.append(json.loads(json_data))

            return results

    def get_all_chunks(
        self,
        file_path: str,
        return_envelopes: bool = True
    ) -> List[ChunkEnvelope | Dict[str, Any]]:
        """
        Get all chunks for a file

        Args:
            file_path: Path to file
            return_envelopes: Return as ChunkEnvelope objects or dicts

        Returns:
            List of all chunks ordered by index
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT chunk_envelope
                FROM text_chunks_v2
                WHERE file_path = ?
                ORDER BY chunk_index
            ''', (file_path,))

            results = []
            for row in cursor.fetchall():
                json_data = row['chunk_envelope']
                if return_envelopes:
                    results.append(ChunkEnvelope.from_json(json_data))
                else:
                    results.append(json.loads(json_data))

            return results

    def search_chunks(
        self,
        query: str,
        limit: int = 10,
        return_envelopes: bool = True
    ) -> List[tuple[ChunkEnvelope | Dict[str, Any], float]]:
        """
        Full-text search across all chunks

        Args:
            query: Search query
            limit: Maximum results
            return_envelopes: Return as ChunkEnvelope objects or dicts

        Returns:
            List of (chunk, rank) tuples ordered by relevance
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    t.chunk_envelope,
                    f.rank
                FROM chunks_fts f
                JOIN text_chunks_v2 t ON t.id = f.rowid
                WHERE chunks_fts MATCH ?
                ORDER BY f.rank
                LIMIT ?
            ''', (query, limit))

            results = []
            for row in cursor.fetchall():
                json_data = row['chunk_envelope']
                rank = row['rank']

                if return_envelopes:
                    chunk = ChunkEnvelope.from_json(json_data)
                else:
                    chunk = json.loads(json_data)

                results.append((chunk, rank))

            return results

    def get_chunks_by_strategy(
        self,
        strategy: str,
        limit: Optional[int] = None,
        return_envelopes: bool = True
    ) -> List[ChunkEnvelope | Dict[str, Any]]:
        """
        Get chunks filtered by chunking strategy

        Args:
            strategy: Strategy name ('code_discrete', 'prose_discrete', etc)
            limit: Optional limit on results
            return_envelopes: Return as ChunkEnvelope objects or dicts

        Returns:
            List of matching chunks
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if limit:
                cursor.execute('''
                    SELECT chunk_envelope
                    FROM text_chunks_v2
                    WHERE chunk_strategy = ?
                    ORDER BY file_path, chunk_index
                    LIMIT ?
                ''', (strategy, limit))
            else:
                cursor.execute('''
                    SELECT chunk_envelope
                    FROM text_chunks_v2
                    WHERE chunk_strategy = ?
                    ORDER BY file_path, chunk_index
                ''', (strategy,))

            results = []
            for row in cursor.fetchall():
                json_data = row['chunk_envelope']
                if return_envelopes:
                    results.append(ChunkEnvelope.from_json(json_data))
                else:
                    results.append(json.loads(json_data))

            return results

    def process_and_store_file(
        self,
        file_path: str,
        content: Optional[str] = None,
        force_prose: bool = False
    ) -> int:
        """
        Process a file and store its chunks

        Args:
            file_path: Path to file
            content: File content (will read from disk if not provided)
            force_prose: Force prose chunking strategy

        Returns:
            Number of chunks created
        """
        # Read content if not provided
        if content is None:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

        # Chunk the file
        envelopes = self.chunker.chunk_file(file_path, content, force_prose=force_prose)

        # Store in database
        return self.store_chunks(file_path, envelopes)

    def get_file_stats(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Get statistics about chunks for a file

        Returns:
            Dict with stats or None if file not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COUNT(*) as chunk_count,
                    chunk_strategy,
                    total_chunks,
                    file_hash,
                    file_type,
                    SUM(chunk_size) as total_size,
                    AVG(chunk_size) as avg_size,
                    MIN(chunk_size) as min_size,
                    MAX(chunk_size) as max_size
                FROM text_chunks_v2
                WHERE file_path = ?
                GROUP BY file_path
            ''', (file_path,))

            row = cursor.fetchone()
            if not row:
                return None

            return dict(row)


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Initialize database
    db = ChunkDatabase()
    # db.initialize_schema()  # Run once to set up

    # Example: Process and store a file
    test_file = "/Users/mark/src/file_metadata_tool/chunking_refactor.py"

    print(f"Processing {test_file}...")
    chunk_count = db.process_and_store_file(test_file)
    print(f"Created {chunk_count} chunks")

    # Get stats
    stats = db.get_file_stats(test_file)
    print(f"\nFile stats: {json.dumps(stats, indent=2)}")

    # Retrieve a chunk
    chunk = db.get_chunk(test_file, 0)
    if chunk:
        print(f"\nFirst chunk metadata:")
        print(f"  Strategy: {chunk.metadata.chunk_strategy}")
        print(f"  Size: {chunk.metadata.chunk_size} chars")
        print(f"  Total chunks: {chunk.metadata.total_chunks}")

    # Get adjacent chunks for context
    adjacent = db.get_adjacent_chunks(test_file, chunk_index=1, before=1, after=1)
    print(f"\nAdjacent chunks around chunk 1: {len(adjacent)} chunks")

    # Search
    results = db.search_chunks("ChunkEnvelope", limit=5)
    print(f"\nSearch results: {len(results)} matches")
