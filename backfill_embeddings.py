#!/usr/bin/env python3
"""
Backfill vector embeddings for all text_chunks rows using nomic-embed-text-v1.5.

Encodes chunk content in batches, writes embedding vectors to PostgreSQL.
Safe to interrupt and resume — skips rows where embedding IS NOT NULL.

Usage:
    python backfill_embeddings.py [--batch-size N] [--pg-dsn DSN]

Progress:
    SELECT COUNT(*) FILTER (WHERE embedding IS NULL) AS remaining,
           COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS done
    FROM text_chunks;
"""

import argparse
import logging
import os
import sys
import time

# Use only local cache — suppress all HuggingFace Hub network calls.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import psycopg2
import psycopg2.extras

log = logging.getLogger(__name__)

PG_DSN = (
    f"host=localhost dbname=file_metadata user=postgres "
    f"password={os.environ.get('DB_PASSWORD', '')}"
)
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
EMBED_DIM = 768
DEFAULT_BATCH = 128


def load_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        log.error("sentence-transformers not installed: uv add sentence-transformers")
        sys.exit(1)
    log.info("Loading model %s …", MODEL_NAME)
    import torch
    # Bulk backfill runs on CPU: MPS accumulates tensor memory across batches and
    # OOMs on variable-length real chunks. MPS is kept for single-query inference.
    # Use all physical cores for intra-op parallelism.
    torch.set_num_threads(8)
    log.info("Using device: cpu (8 threads)")
    model = SentenceTransformer(MODEL_NAME, trust_remote_code=True, device="cpu")
    assert model.get_embedding_dimension() == EMBED_DIM, \
        f"Expected {EMBED_DIM}-dim, got {model.get_embedding_dimension()}"
    log.info("Model ready (dim=%d)", EMBED_DIM)
    return model


def count_remaining(pg: psycopg2.extensions.connection) -> tuple[int, int]:
    with pg.cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE embedding IS NULL)     AS remaining,
                COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS done
            FROM text_chunks
        """)
        row = cur.fetchone()
        return (row[0], row[1]) if row else (0, 0)


def fetch_batch(pg: psycopg2.extensions.connection, batch_size: int) -> list[tuple[int, str]]:
    with pg.cursor() as cur:
        cur.execute("""
            SELECT id, content FROM text_chunks
            WHERE embedding IS NULL
            ORDER BY id
            LIMIT %s
        """, (batch_size,))
        return cur.fetchall()


def write_embeddings(pg: psycopg2.extensions.connection, rows: list[tuple]) -> None:
    sql = "UPDATE text_chunks SET embedding = %s::vector WHERE id = %s"
    with pg.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=100)
    pg.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH,
                        help=f"Chunks per encode batch (default {DEFAULT_BATCH})")
    parser.add_argument("--pg-dsn", default=PG_DSN)
    args = parser.parse_args()

    model = load_model()
    pg = psycopg2.connect(args.pg_dsn)

    remaining, done = count_remaining(pg)
    total = remaining + done
    log.info("Total chunks: %d | Already embedded: %d | Remaining: %d", total, done, remaining)

    if remaining == 0:
        log.info("All chunks already embedded. Nothing to do.")
        pg.close()
        return

    processed = 0
    t_start = time.monotonic()

    try:
        while True:
            batch = fetch_batch(pg, args.batch_size)
            if not batch:
                break

            ids = [r[0] for r in batch]
            texts = [r[1] or "" for r in batch]

            embeddings = model.encode(texts, prompt_name="document",
                                      show_progress_bar=False, batch_size=args.batch_size)

            # Format as PostgreSQL vector literal: '[0.1,0.2,...]'
            update_rows = [
                ("[" + ",".join(f"{v:.8f}" for v in emb) + "]", chunk_id)
                for chunk_id, emb in zip(ids, embeddings)
            ]
            write_embeddings(pg, update_rows)

            processed += len(batch)
            elapsed = time.monotonic() - t_start
            rate = processed / elapsed if elapsed > 0 else 0
            eta_s = (remaining - processed) / rate if rate > 0 else 0
            log.info(
                "  %d / %d (%.1f%%) — %.0f chunks/s — ETA %.0fm",
                done + processed, total,
                100 * (done + processed) / total,
                rate,
                eta_s / 60,
            )

    except KeyboardInterrupt:
        log.info("Interrupted — progress saved. Re-run to continue.")
    finally:
        pg.close()

    remaining_after, done_after = count_remaining(psycopg2.connect(args.pg_dsn))
    log.info("Done. Embedded: %d / %d | Still remaining: %d", done_after, total, remaining_after)

    if remaining_after == 0:
        log.info("All chunks embedded with %s. Run CREATE INDEX to rebuild HNSW.", MODEL_NAME)


if __name__ == "__main__":
    main()
