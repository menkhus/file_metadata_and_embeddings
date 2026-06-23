#!/usr/bin/env python3
"""
Build LSA (TF-IDF + TruncatedSVD) vectors for all text_chunks rows.

Writes 256-dim L2-normalized vectors to the lsa_vec column in PostgreSQL.
Saves the fitted model to lsa_model.joblib for use at query time (MCP server).

Modes:
  Full build (default): fits TfidfVectorizer + TruncatedSVD on all content,
    saves model, then encodes and writes every row.
  Incremental (--incremental): loads existing model, encodes only rows where
    lsa_vec IS NULL. Use this for hourly incremental runs after the initial build.

Usage:
    python build_lsa_index.py                   # full build (~30-60 min CPU)
    python build_lsa_index.py --incremental     # encode new chunks only
    python build_lsa_index.py --batch-size 4000 # tune batch size

Progress check:
    SELECT COUNT(*) FILTER (WHERE lsa_vec IS NULL)     AS remaining,
           COUNT(*) FILTER (WHERE lsa_vec IS NOT NULL) AS done
    FROM text_chunks;
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import psycopg2
import psycopg2.extras
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

log = logging.getLogger(__name__)

PG_DSN = (
    f"host=localhost dbname=file_metadata user=postgres "
    f"password={os.environ.get('DB_PASSWORD', '')}"
)
MODEL_PATH = Path(__file__).parent / "lsa_model.joblib"
LSA_DIMS = 256
DEFAULT_BATCH = 3000


def load_or_fit(pg: psycopg2.extensions.connection, incremental: bool) -> dict:
    if incremental and MODEL_PATH.exists():
        log.info("Incremental mode: loading existing model from %s", MODEL_PATH)
        return joblib.load(MODEL_PATH)

    if incremental:
        log.warning("--incremental requested but no model found at %s — running full fit", MODEL_PATH)

    log.info("Loading all chunk content for TF-IDF fit...")
    t0 = time.monotonic()
    with pg.cursor() as cur:
        cur.execute("SELECT content FROM text_chunks ORDER BY id")
        texts = [r[0] or "" for r in cur.fetchall()]
    log.info("Loaded %d chunks in %.1fs", len(texts), time.monotonic() - t0)

    log.info("Fitting TfidfVectorizer...")
    t0 = time.monotonic()
    vectorizer = TfidfVectorizer(
        max_features=100_000,
        sublinear_tf=True,
        min_df=2,
        strip_accents="unicode",
        analyzer="word",
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_]{2,}\b",
    )
    tfidf_matrix = vectorizer.fit_transform(texts)
    log.info("TF-IDF matrix: %d docs × %d terms in %.1fs",
             tfidf_matrix.shape[0], tfidf_matrix.shape[1], time.monotonic() - t0)  # type: ignore[union-attr]

    log.info("Fitting TruncatedSVD (dims=%d)...", LSA_DIMS)
    t0 = time.monotonic()
    svd = TruncatedSVD(n_components=LSA_DIMS, random_state=42, n_iter=5)
    svd.fit(tfidf_matrix)
    explained = float(svd.explained_variance_ratio_.sum())
    log.info("SVD fitted in %.1fs — explains %.1f%% variance", time.monotonic() - t0, 100 * explained)

    model = {"vectorizer": vectorizer, "svd": svd}
    joblib.dump(model, MODEL_PATH, compress=3)
    log.info("Model saved to %s", MODEL_PATH)

    return model


def count_remaining(pg: psycopg2.extensions.connection) -> tuple[int, int]:
    with pg.cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE lsa_vec IS NULL)     AS remaining,
                COUNT(*) FILTER (WHERE lsa_vec IS NOT NULL) AS done
            FROM text_chunks
        """)
        row = cur.fetchone()
        return (row[0], row[1]) if row else (0, 0)


def iter_batches(pg: psycopg2.extensions.connection, batch_size: int,
                 incremental: bool):
    """Yield (ids, texts) batches using cursor-based pagination on id."""
    last_id = 0
    null_clause = "AND lsa_vec IS NULL" if incremental else ""
    sql = f"""
        SELECT id, content FROM text_chunks
        WHERE id > %s {null_clause}
        ORDER BY id
        LIMIT %s
    """
    while True:
        with pg.cursor() as cur:
            cur.execute(sql, (last_id, batch_size))
            rows = cur.fetchall()
        if not rows:
            break
        ids = [r[0] for r in rows]
        texts = [r[1] or "" for r in rows]
        last_id = ids[-1]
        yield ids, texts


def encode_batch(model: dict, texts: list[str]) -> np.ndarray:
    tfidf = model["vectorizer"].transform(texts)
    vecs = model["svd"].transform(tfidf)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


def write_vecs(pg: psycopg2.extensions.connection, ids: list[int],
               vecs: np.ndarray) -> None:
    rows = [
        ("[" + ",".join(f"{v:.8f}" for v in vec) + "]", chunk_id)
        for chunk_id, vec in zip(ids, vecs)
    ]
    sql = "UPDATE text_chunks SET lsa_vec = %s::vector WHERE id = %s"
    with pg.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=200)
    pg.commit()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incremental", action="store_true",
                        help="Only encode rows where lsa_vec IS NULL (skip refit)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH,
                        help=f"Rows per encode batch (default {DEFAULT_BATCH})")
    parser.add_argument("--pg-dsn", default=PG_DSN)
    args = parser.parse_args()

    pg = psycopg2.connect(args.pg_dsn)

    remaining, done = count_remaining(pg)
    total = remaining + done
    log.info("Total chunks: %d | Already vectorized: %d | Remaining: %d", total, done, remaining)

    if remaining == 0:
        log.info("All chunks already have lsa_vec. Nothing to do.")
        pg.close()
        return

    model = load_or_fit(pg, args.incremental)

    processed = 0
    t_start = time.monotonic()

    try:
        for ids, texts in iter_batches(pg, args.batch_size, args.incremental):
            vecs = encode_batch(model, texts)
            write_vecs(pg, ids, vecs)

            processed += len(ids)
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
        log.info("Interrupted — progress saved. Re-run with --incremental to continue.")
    finally:
        pg.close()

    log.info("Done.")


if __name__ == "__main__":
    main()
