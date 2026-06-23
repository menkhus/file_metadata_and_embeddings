#!/usr/bin/env python3
"""
Offline FAISS Index Builder with Two-Tier Architecture

Builds and manages FAISS vector indexes for semantic search.
Supports incremental updates via major/minor index architecture.

Output files:
- ~/data/file_search_major.faiss - Stable major index (bulk of vectors)
- ~/data/file_search_major_meta.json - Metadata for major index
- ~/data/file_search_minor.faiss - Incremental minor index (recent additions)
- ~/data/file_search_minor_meta.json - Metadata for minor index
- ~/data/file_search_index_state.json - State tracking (staleness, file hashes)

Usage:
    # Check index status
    python3 build_faiss_index.py --status

    # Add only new/changed files to minor index (fast)
    python3 build_faiss_index.py --add-only

    # Compact minor into major (periodic maintenance)
    python3 build_faiss_index.py --compact

    # Full rebuild of major index
    python3 build_faiss_index.py --rebuild-major --force

    # Legacy: full rebuild (same as --rebuild-major)
    python3 build_faiss_index.py
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from tqdm import tqdm

try:
    import faiss
    from sentence_transformers import SentenceTransformer
    DEPS_AVAILABLE = True
except ImportError as e:
    print(f"Warning: {e}", file=sys.stderr)
    print("Install with: pip install faiss-cpu sentence-transformers", file=sys.stderr)
    DEPS_AVAILABLE = False

from faiss_index_manager import TwoTierFAISSManager


# Default paths
DEFAULT_DB = os.path.expanduser("~/data/file_metadata.sqlite3")
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/data")
DEFAULT_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # Dimension for all-MiniLM-L6-v2


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Get database connection with row factory"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_chunks_with_metadata(db_path: str) -> List[Dict[str, Any]]:
    """
    Fetch all chunks with their associated metadata.
    Joins text_chunks with file_metadata and content_analysis.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    query = """
        SELECT
            tc.file_path,
            tc.chunk_index,
            tc.chunk_text,
            fm.file_name,
            fm.directory,
            fm.file_type,
            fm.file_size,
            fm.modified_date,
            ca.tfidf_keywords,
            ca.lda_topics,
            (SELECT COUNT(*) FROM text_chunks tc2 WHERE tc2.file_path = tc.file_path) as total_chunks
        FROM text_chunks tc
        LEFT JOIN file_metadata fm ON tc.file_path = fm.file_path
        LEFT JOIN content_analysis ca ON tc.file_path = ca.file_path
        ORDER BY tc.file_path, tc.chunk_index
    """

    cursor.execute(query)
    chunks = []

    for row in cursor:
        # Parse JSON fields
        tfidf_keywords = []
        if row['tfidf_keywords']:
            try:
                tfidf_raw = json.loads(row['tfidf_keywords'])
                # Extract just the keyword strings (might be tuples with scores)
                tfidf_keywords = [kw[0] if isinstance(kw, (list, tuple)) else kw
                                  for kw in tfidf_raw[:10]]
            except (json.JSONDecodeError, TypeError):
                pass

        lda_topics = []
        if row['lda_topics']:
            try:
                lda_raw = json.loads(row['lda_topics'])
                # Extract topic IDs
                lda_topics = [t[0] if isinstance(t, (list, tuple)) else t
                              for t in lda_raw[:5]]
            except (json.JSONDecodeError, TypeError):
                pass

        chunks.append({
            'file_path': row['file_path'],
            'file_name': row['file_name'],
            'directory': row['directory'],
            'file_type': row['file_type'],
            'file_size': row['file_size'],
            'modified_date': row['modified_date'],
            'chunk_index': row['chunk_index'],
            'total_chunks': row['total_chunks'],
            'chunk_text': row['chunk_text'],
            'tfidf_keywords': tfidf_keywords,
            'lda_topics': lda_topics,
        })

    conn.close()
    return chunks


def get_new_chunks_since(db_path: str, manager: TwoTierFAISSManager) -> List[Dict[str, Any]]:
    """
    Get chunks for files that are new or modified since last index build.
    Checks against the manager's file tracking to identify what's new.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # Get all unique files in the database
    cursor.execute("""
        SELECT DISTINCT tc.file_path, fm.modified_date
        FROM text_chunks tc
        LEFT JOIN file_metadata fm ON tc.file_path = fm.file_path
    """)

    new_file_paths = []
    for row in cursor:
        file_path = row['file_path']
        modified_date = row['modified_date'] or ''

        # Check if file is already indexed with same modification date
        if not manager.is_file_indexed(file_path, file_hash=modified_date):
            new_file_paths.append(file_path)

    if not new_file_paths:
        conn.close()
        return []

    # Fetch chunks for new/modified files
    placeholders = ','.join('?' * len(new_file_paths))
    query = f"""
        SELECT
            tc.file_path,
            tc.chunk_index,
            tc.chunk_text,
            fm.file_name,
            fm.directory,
            fm.file_type,
            fm.file_size,
            fm.modified_date,
            ca.tfidf_keywords,
            ca.lda_topics,
            (SELECT COUNT(*) FROM text_chunks tc2 WHERE tc2.file_path = tc.file_path) as total_chunks
        FROM text_chunks tc
        LEFT JOIN file_metadata fm ON tc.file_path = fm.file_path
        LEFT JOIN content_analysis ca ON tc.file_path = ca.file_path
        WHERE tc.file_path IN ({placeholders})
        ORDER BY tc.file_path, tc.chunk_index
    """

    cursor.execute(query, new_file_paths)
    chunks = []

    for row in cursor:
        tfidf_keywords = []
        if row['tfidf_keywords']:
            try:
                tfidf_raw = json.loads(row['tfidf_keywords'])
                tfidf_keywords = [kw[0] if isinstance(kw, (list, tuple)) else kw
                                  for kw in tfidf_raw[:10]]
            except (json.JSONDecodeError, TypeError):
                pass

        lda_topics = []
        if row['lda_topics']:
            try:
                lda_raw = json.loads(row['lda_topics'])
                lda_topics = [t[0] if isinstance(t, (list, tuple)) else t
                              for t in lda_raw[:5]]
            except (json.JSONDecodeError, TypeError):
                pass

        chunks.append({
            'file_path': row['file_path'],
            'file_name': row['file_name'],
            'directory': row['directory'],
            'file_type': row['file_type'],
            'file_size': row['file_size'],
            'modified_date': row['modified_date'],
            'chunk_index': row['chunk_index'],
            'total_chunks': row['total_chunks'],
            'chunk_text': row['chunk_text'],
            'tfidf_keywords': tfidf_keywords,
            'lda_topics': lda_topics,
        })

    conn.close()
    return chunks


def get_database_stats(db_path: str) -> Dict[str, Any]:
    """Get database statistics for staleness checking"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    stats = {}

    # Total chunks
    cursor.execute("SELECT COUNT(*) as count FROM text_chunks")
    stats['total_chunks'] = cursor.fetchone()['count']

    # Total files with chunks
    cursor.execute("SELECT COUNT(DISTINCT file_path) as count FROM text_chunks")
    stats['total_files'] = cursor.fetchone()['count']

    # Most recent file modification in database
    cursor.execute("SELECT MAX(modified_date) as latest FROM file_metadata")
    stats['latest_file_modified'] = cursor.fetchone()['latest']

    # Most recent indexed_date
    cursor.execute("SELECT MAX(indexed_date) as latest FROM file_metadata")
    stats['latest_indexed'] = cursor.fetchone()['latest']

    conn.close()
    return stats


def generate_embeddings(
    chunks: List[Dict[str, Any]],
    model: SentenceTransformer,
    batch_size: int = 64
) -> np.ndarray:
    """Generate embeddings for chunks"""
    texts = [chunk['chunk_text'] for chunk in chunks]

    print(f"Generating embeddings for {len(texts)} chunks...")
    all_embeddings = []

    for i in tqdm(range(0, len(texts), batch_size), desc="Embedding batches"):
        batch = texts[i:i + batch_size]
        embeddings = model.encode(batch, show_progress_bar=False)
        all_embeddings.extend(embeddings)

    return np.array(all_embeddings).astype('float32')


def cmd_status(manager: TwoTierFAISSManager, db_path: str) -> None:
    """Show detailed status of indexes"""
    stats = manager.get_stats()
    db_stats = get_database_stats(db_path)

    print("\n=== FAISS Index Status ===\n")

    # Major index
    print("Major Index:")
    if stats['major']['exists']:
        print(f"  Vectors: {stats['major']['vector_count']:,}")
        print(f"  File size: {stats['major']['file_size_mb']:.1f} MB")
        print(f"  Built: {stats['major']['build_timestamp'] or 'unknown'}")
    else:
        print("  Not built yet")

    # Minor index
    print("\nMinor Index:")
    if stats['minor']['exists']:
        print(f"  Vectors: {stats['minor']['vector_count']:,}")
        print(f"  File size: {stats['minor']['file_size_mb']:.1f} MB")
        print(f"  Built: {stats['minor']['build_timestamp'] or 'unknown'}")
    else:
        print("  Empty (no incremental additions)")

    # Combined stats
    print(f"\nTotal vectors: {stats['total_vectors']:,}")
    print(f"Indexed files: {stats['indexed_files']:,}")
    print(f"Stale vectors: {stats['stale_vectors']:,}")

    # Database comparison
    print(f"\nDatabase:")
    print(f"  Total chunks: {db_stats['total_chunks']:,}")
    print(f"  Total files: {db_stats['total_files']:,}")

    # Staleness check
    if stats['total_vectors'] < db_stats['total_chunks']:
        diff = db_stats['total_chunks'] - stats['total_vectors']
        print(f"\n[!] Index is behind database by ~{diff:,} chunks")
        print("    Run: python build_faiss_index.py --add-only")
    elif stats['needs_compaction']:
        print(f"\n[!] Compaction recommended (minor index getting large)")
        print("    Run: python build_faiss_index.py --compact")
    else:
        print("\n[OK] Index is up to date")


def cmd_add_only(
    manager: TwoTierFAISSManager,
    db_path: str,
    model: SentenceTransformer,
    batch_size: int
) -> None:
    """Add only new/changed files to minor index"""
    print("Checking for new/modified files...")

    chunks = get_new_chunks_since(db_path, manager)

    if not chunks:
        print("No new or modified files to index.")
        return

    # Group by file for reporting
    files = set(c['file_path'] for c in chunks)
    print(f"Found {len(chunks)} chunks from {len(files)} file(s)")

    # Generate embeddings
    embeddings = generate_embeddings(chunks, model, batch_size)

    # Add to minor index (grouping by file for hash tracking)
    current_file = None
    file_chunks = []
    file_embeddings = []

    for i, chunk in enumerate(chunks):
        if chunk['file_path'] != current_file:
            # Process previous file
            if file_chunks:
                file_hash = file_chunks[0].get('modified_date', '')
                manager.add_chunks(
                    file_chunks,
                    np.array(file_embeddings).astype('float32'),
                    file_hash=file_hash
                )

            # Start new file
            current_file = chunk['file_path']
            file_chunks = [chunk]
            file_embeddings = [embeddings[i]]
        else:
            file_chunks.append(chunk)
            file_embeddings.append(embeddings[i])

    # Process last file
    if file_chunks:
        file_hash = file_chunks[0].get('modified_date', '')
        manager.add_chunks(
            file_chunks,
            np.array(file_embeddings).astype('float32'),
            file_hash=file_hash
        )

    stats = manager.get_stats()
    print(f"\nAdded {len(chunks)} vectors to minor index")
    print(f"Minor index now has {stats['minor']['vector_count']} vectors")

    if stats['needs_compaction']:
        print("\n[Hint] Minor index is getting large. Consider running:")
        print("  python build_faiss_index.py --compact")


def cmd_compact(manager: TwoTierFAISSManager) -> None:
    """Merge minor index into major"""
    print("Compacting: merging minor index into major...")

    result = manager.compact()

    if result['status'] == 'no_action':
        print(result['message'])
    else:
        print(f"Merged {result['pre_minor_vectors']} vectors from minor into major")
        print(f"Major index now has {result['post_major_vectors']} vectors")
        print("Minor index cleared")


def cmd_rebuild_major(
    manager: TwoTierFAISSManager,
    db_path: str,
    model: SentenceTransformer,
    batch_size: int
) -> None:
    """Full rebuild of major index"""
    db_stats = get_database_stats(db_path)
    print(f"\nDatabase has {db_stats['total_chunks']:,} chunks from {db_stats['total_files']:,} files")

    print("\nLoading chunks from database...")
    chunks = get_chunks_with_metadata(db_path)

    if not chunks:
        print("No chunks found in database. Run file_metadata_content.py first.")
        return

    print(f"Loaded {len(chunks):,} chunks")

    # Generate embeddings
    embeddings = generate_embeddings(chunks, model, batch_size)

    # Rebuild major index
    print("\nRebuilding major index...")
    result = manager.rebuild_major(chunks, embeddings)

    print(f"\nMajor index rebuilt with {result['total_vectors']:,} vectors")
    print(f"Indexed {result['indexed_files']} files")

    stats = manager.get_stats()
    print(f"\nIndex files:")
    print(f"  Major: {stats['major']['file_size_mb']:.1f} MB")
    print(f"\nSemantic search is now available via MCP server.")


def main():
    parser = argparse.ArgumentParser(
        description="Build and manage FAISS indexes for semantic search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check current index status
  python build_faiss_index.py --status

  # Add only new/changed files (fast, incremental)
  python build_faiss_index.py --add-only

  # Compact minor index into major (periodic maintenance)
  python build_faiss_index.py --compact

  # Full rebuild of major index
  python build_faiss_index.py --rebuild-major --force
        """
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=f"Database path (default: {DEFAULT_DB})"
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for index files (default: {DEFAULT_OUTPUT_DIR})"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Batch size for embedding generation (default: 64)"
    )

    # Command modes
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--status",
        action="store_true",
        help="Show detailed status of indexes"
    )
    mode_group.add_argument(
        "--add-only",
        action="store_true",
        help="Add only new/changed files to minor index (fast, incremental)"
    )
    mode_group.add_argument(
        "--compact",
        action="store_true",
        help="Merge minor index into major index"
    )
    mode_group.add_argument(
        "--rebuild-major",
        action="store_true",
        help="Full rebuild of major index from scratch"
    )
    mode_group.add_argument(
        "--check",
        action="store_true",
        help="[Legacy] Only check if index is stale"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild even if index exists"
    )

    args = parser.parse_args()

    # Verify database exists
    if not os.path.exists(args.db):
        print(f"Error: Database not found at {args.db}")
        sys.exit(1)

    # Initialize manager
    manager = TwoTierFAISSManager(data_dir=args.output_dir)

    # Check for legacy index and migrate if needed
    if manager.migrate_from_legacy():
        print("")  # Blank line after migration output

    # Status command doesn't need deps
    if args.status or args.check:
        cmd_status(manager, args.db)
        sys.exit(0)

    # Compact doesn't need deps either
    if args.compact:
        cmd_compact(manager)
        sys.exit(0)

    # Check dependencies for operations that need embedding
    if not DEPS_AVAILABLE:
        print("Error: Cannot build index without faiss and sentence-transformers.", file=sys.stderr)
        print("Install with: pip install faiss-cpu sentence-transformers", file=sys.stderr)
        sys.exit(1)

    # Load model
    print(f"Loading sentence transformer model: {DEFAULT_MODEL}")
    model = SentenceTransformer(DEFAULT_MODEL)

    if args.add_only:
        cmd_add_only(manager, args.db, model, args.batch_size)
    elif args.rebuild_major:
        if not args.force:
            stats = manager.get_stats()
            if stats['major']['exists']:
                print("Major index already exists. Use --force to rebuild.")
                sys.exit(0)
        cmd_rebuild_major(manager, args.db, model, args.batch_size)
    else:
        # Default behavior: smart mode
        stats = manager.get_stats()

        if not stats['major']['exists'] and not stats['minor']['exists']:
            # No index at all - do full build
            print("No existing index found. Building major index...")
            cmd_rebuild_major(manager, args.db, model, args.batch_size)
        elif args.force:
            # Forced rebuild
            print("Force rebuilding major index...")
            cmd_rebuild_major(manager, args.db, model, args.batch_size)
        else:
            # Check if incremental add is needed
            db_stats = get_database_stats(args.db)
            if stats['total_vectors'] < db_stats['total_chunks']:
                print("Index is behind database. Adding new chunks...")
                cmd_add_only(manager, args.db, model, args.batch_size)
            else:
                print("Index appears up to date.")
                cmd_status(manager, args.db)


if __name__ == "__main__":
    main()
