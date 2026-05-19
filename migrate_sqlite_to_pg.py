#!/usr/bin/env python3
"""
Migrate file_metadata.sqlite3 → PostgreSQL file_metadata database.

Copies: file_metadata, content_analysis, text_chunks, directory_structure,
        processing_stats

Skips:  chunk embeddings (BLOBs in SQLite are raw numpy bytes; re-embed in Phase 3)
        FTS virtual tables (replaced by tsvector GIN indexes in PG)

Usage:
    python migrate_sqlite_to_pg.py [--dry-run] [--sqlite PATH] [--pg-dsn DSN]
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SQLITE_PATH = os.path.expanduser("~/data/file_metadata.sqlite3")
PG_DSN = (
    f"host=localhost dbname=file_metadata user=postgres "
    f"password={os.environ.get('DB_PASSWORD', '')}"
)
BATCH_SIZE = 500


def parse_ts(val: str | None) -> datetime | None:
    if not val:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_json(val: str | None):
    if not val:
        return None
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None


def migrate_file_metadata(sqlite: sqlite3.Connection, pg: psycopg2.extensions.connection, dry_run: bool) -> int:
    log.info("Migrating file_metadata …")
    rows = sqlite.execute("""
        SELECT file_path, file_hash, file_size, file_type, mime_type,
               is_text_file, encoding, processing_status, error_message,
               modified_date, indexed_date
        FROM file_metadata
    """).fetchall()

    sql = """
        INSERT INTO file_metadata
            (file_path, file_hash, file_size, file_type, mime_type,
             is_text_file, encoding, processing_status, error_message,
             last_modified, last_indexed)
        VALUES %s
        ON CONFLICT (file_path) DO NOTHING
    """
    records = [
        (
            r["file_path"], r["file_hash"], r["file_size"], r["file_type"],
            r["mime_type"], bool(r["is_text_file"]) if r["is_text_file"] is not None else None,
            r["encoding"], r["processing_status"], r["error_message"],
            parse_ts(r["modified_date"]), parse_ts(r["indexed_date"]),
        )
        for r in rows
    ]
    if not dry_run:
        with pg.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql, records, page_size=BATCH_SIZE)
        pg.commit()
    log.info("  %d rows", len(records))
    return len(records)


def migrate_content_analysis(sqlite: sqlite3.Connection, pg: psycopg2.extensions.connection, dry_run: bool) -> int:
    log.info("Migrating content_analysis …")
    # Only migrate rows whose file_path exists in file_metadata (FK safety)
    rows = sqlite.execute("""
        SELECT ca.file_path, ca.file_hash, ca.word_count, ca.char_count,
               ca.language, ca.topic_summary, ca.keywords, ca.tfidf_keywords,
               ca.lda_topics, ca.sentiment_score, ca.processing_status,
               ca.error_message, ca.analysis_date, ca.processing_time_seconds
        FROM content_analysis ca
        WHERE EXISTS (SELECT 1 FROM file_metadata fm WHERE fm.file_path = ca.file_path)
    """).fetchall()

    sql = """
        INSERT INTO content_analysis
            (file_path, file_hash, word_count, char_count, language,
             topic_summary, keywords, tfidf_keywords, lda_topics,
             sentiment_score, processing_status, error_message,
             analysis_date, processing_time_s)
        VALUES %s
        ON CONFLICT (file_path) DO NOTHING
    """
    records = [
        (
            r["file_path"], r["file_hash"], r["word_count"], r["char_count"],
            r["language"], r["topic_summary"],
            psycopg2.extras.Json(parse_json(r["keywords"])),
            psycopg2.extras.Json(parse_json(r["tfidf_keywords"])),
            psycopg2.extras.Json(parse_json(r["lda_topics"])),
            r["sentiment_score"], r["processing_status"], r["error_message"],
            parse_ts(r["analysis_date"]), r["processing_time_seconds"],
        )
        for r in rows
    ]
    if not dry_run:
        with pg.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql, records, page_size=BATCH_SIZE)
        pg.commit()
    log.info("  %d rows", len(records))
    return len(records)


def migrate_text_chunks(sqlite: sqlite3.Connection, pg: psycopg2.extensions.connection, dry_run: bool) -> int:
    log.info("Migrating text_chunks (embeddings skipped — re-embed in Phase 3) …")
    # Join to get file_hash; filter to valid file_paths; skip BLOB embeddings
    rows = sqlite.execute("""
        SELECT tc.file_path, tc.chunk_index, tc.chunk_text,
               fm.file_hash
        FROM text_chunks tc
        JOIN file_metadata fm ON fm.file_path = tc.file_path
        ORDER BY tc.file_path, tc.chunk_index
    """).fetchall()

    sql = """
        INSERT INTO text_chunks
            (file_path, chunk_index, file_hash, chunk_strategy,
             chunk_size, total_chunks, content, embedding)
        VALUES %s
        ON CONFLICT (file_path, chunk_index) DO NOTHING
    """
    # chunk_strategy/chunk_size/total_chunks unknown in old schema — use sentinel defaults
    # total_chunks computed per file below
    file_chunk_counts: dict[str, int] = {}
    for r in rows:
        file_chunk_counts[r["file_path"]] = file_chunk_counts.get(r["file_path"], 0) + 1

    records = [
        (
            r["file_path"],
            r["chunk_index"],
            r["file_hash"],
            "legacy",                               # chunk_strategy
            len(r["chunk_text"]) if r["chunk_text"] else 0,  # chunk_size (chars)
            file_chunk_counts.get(r["file_path"], 0),        # total_chunks
            r["chunk_text"],
            None,                                   # embedding — backfilled in Phase 3
        )
        for r in rows
    ]

    if not dry_run:
        with pg.cursor() as cur:
            for i in range(0, len(records), BATCH_SIZE):
                psycopg2.extras.execute_values(cur, sql, records[i:i+BATCH_SIZE], page_size=BATCH_SIZE)
                if i % 10000 == 0:
                    log.info("  … %d / %d chunks", i, len(records))
        pg.commit()
    log.info("  %d rows", len(records))
    return len(records)


def migrate_directory_structure(sqlite: sqlite3.Connection, pg: psycopg2.extensions.connection, dry_run: bool) -> int:
    log.info("Migrating directory_structure …")
    rows = sqlite.execute("""
        SELECT directory_path, parent_directory, file_count, total_size, last_updated
        FROM directory_structure
    """).fetchall()

    sql = """
        INSERT INTO directory_structure
            (directory_path, parent_path, file_count, total_size, last_scanned)
        VALUES %s
        ON CONFLICT (directory_path) DO NOTHING
    """
    records = [
        (r["directory_path"], r["parent_directory"], r["file_count"],
         r["total_size"], parse_ts(r["last_updated"]))
        for r in rows
    ]
    if not dry_run:
        with pg.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql, records, page_size=BATCH_SIZE)
        pg.commit()
    log.info("  %d rows", len(records))
    return len(records)


def migrate_processing_stats(sqlite: sqlite3.Connection, pg: psycopg2.extensions.connection, dry_run: bool) -> int:
    log.info("Migrating processing_stats …")
    rows = sqlite.execute("""
        SELECT session_id, start_time, end_time, successful_files,
               failed_files, interrupted,
               total_files, permission_denied_files, size_limit_exceeded_files,
               encoding_error_files, file_not_found_files, timeout_files,
               unknown_error_files, duration_seconds, directory, status
        FROM processing_stats
    """).fetchall()

    sql = """
        INSERT INTO processing_stats
            (session_id, start_time, end_time, files_processed,
             files_errored, interrupted, metadata)
        VALUES %s
    """
    records = [
        (
            r["session_id"],
            parse_ts(r["start_time"]),
            parse_ts(r["end_time"]),
            r["successful_files"] or 0,
            r["failed_files"] or 0,
            bool(r["interrupted"]) if r["interrupted"] is not None else False,
            psycopg2.extras.Json({
                "total_files": r["total_files"],
                "permission_denied": r["permission_denied_files"],
                "size_limit_exceeded": r["size_limit_exceeded_files"],
                "encoding_errors": r["encoding_error_files"],
                "file_not_found": r["file_not_found_files"],
                "timeouts": r["timeout_files"],
                "unknown_errors": r["unknown_error_files"],
                "duration_seconds": r["duration_seconds"],
                "directory": r["directory"],
                "status": r["status"],
            }),
        )
        for r in rows
    ]
    if not dry_run:
        with pg.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql, records, page_size=BATCH_SIZE)
        pg.commit()
    log.info("  %d rows", len(records))
    return len(records)


def verify(pg: psycopg2.extensions.connection) -> None:
    log.info("Verifying row counts …")
    tables = ["file_metadata", "content_analysis", "text_chunks",
              "directory_structure", "processing_stats"]
    with pg.cursor() as cur:
        for t in tables:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            row = cur.fetchone()
            count = row[0] if row else 0
            log.info("  %-25s %d rows", t, count)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and validate without writing to PostgreSQL")
    parser.add_argument("--sqlite", default=SQLITE_PATH)
    parser.add_argument("--pg-dsn", default=PG_DSN)
    args = parser.parse_args()

    if args.dry_run:
        log.info("DRY RUN — no data will be written")

    log.info("Opening SQLite: %s", args.sqlite)
    sqlite = sqlite3.connect(args.sqlite)
    sqlite.row_factory = sqlite3.Row

    log.info("Connecting to PostgreSQL …")
    pg = psycopg2.connect(args.pg_dsn)

    try:
        migrate_file_metadata(sqlite, pg, args.dry_run)
        migrate_content_analysis(sqlite, pg, args.dry_run)
        migrate_text_chunks(sqlite, pg, args.dry_run)
        migrate_directory_structure(sqlite, pg, args.dry_run)
        migrate_processing_stats(sqlite, pg, args.dry_run)

        if not args.dry_run:
            verify(pg)

        log.info("Migration complete.")
    except Exception:
        log.exception("Migration failed — rolling back")
        pg.rollback()
        sys.exit(1)
    finally:
        sqlite.close()
        pg.close()


if __name__ == "__main__":
    main()
