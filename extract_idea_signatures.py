#!/usr/bin/env python3
"""
extract_idea_signatures.py — Populate the substrate DB with project nodes.

Reads from ~/data/file_metadata.sqlite3 (40K+ indexed files with TF-IDF
keywords). Groups files by project directory. Aggregates keywords across
all files in each project. Writes project nodes and top-file nodes to
~/data/substrate.sqlite3.

Key design: global IDF correction.
The indexer computed TF-IDF per-file using only that file's own chunks as the
corpus. This means "AI", "code", "function" score high locally even though they
appear in thousands of files. We fix this by computing global document-frequency
counts across all 32K analyzed files, then reweighting each term by
log(N / df) — the true IDF. Terms ubiquitous across the corpus drop to near
zero; terms rare but prominent in a specific project rise sharply.

Run once to bootstrap, then periodically as projects evolve.

Usage:
    python3 extract_idea_signatures.py [--db-path ~/data/file_metadata.sqlite3]
                                       [--substrate ~/data/substrate.sqlite3]
                                       [--min-files 2]
                                       [--top-files 5]
                                       [--dry-run]
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from math import log
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from substrate_db import SubstrateDB, DEFAULT_DB

DEFAULT_SOURCE_DB = Path.home() / "data" / "file_metadata.sqlite3"

# Roots that contain projects at depth 1 below the root
PROJECT_ROOTS = [
    Path.home() / "src",
    Path.home() / "Documents" / "src",
]


def _project_for_path(file_path: str) -> tuple[str, str] | None:
    """Return (project_name, project_dir) for a file path, or None."""
    p = Path(file_path)
    for root in PROJECT_ROOTS:
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if not parts:
            continue
        project_name = parts[0]
        project_dir = str(root / project_name)
        return project_name, project_dir
    return None


def _is_noise_keyword(term: str) -> bool:
    """Return True for terms that are filename fragments or structural noise."""
    if len(term) > 40:
        return True
    if any(term.endswith(ext) for ext in (".md", ".py", ".txt", ".json", ".csv")):
        return True
    if "/" in term:
        return True
    alpha_ratio = sum(c.isalpha() for c in term) / max(len(term), 1)
    if alpha_ratio < 0.5:
        return True
    return False


def _parse_tfidf(raw: str | None) -> list[tuple[str, float]]:
    """Parse tfidf_keywords JSON → list of (term, local_score), filtering noise."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            result = []
            for item in data:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    term = str(item[0]).strip()
                    if term and not _is_noise_keyword(term):
                        result.append((term, float(item[1])))
                elif isinstance(item, str):
                    term = item.strip()
                    if term and not _is_noise_keyword(term):
                        result.append((term, 1.0))
            return result
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return []


def build_global_idf(all_rows: list) -> tuple[dict[str, float], int]:
    """
    Compute global IDF from tfidf_keywords across all files.

    IDF(term) = log(N / df) where:
      N  = total number of files with any keywords
      df = number of files that include this term in their keywords

    Returns (idf_weights, total_doc_count).
    High IDF = rare across corpus = genuinely distinguishing.
    Low IDF  = appears everywhere = suppress it.
    """
    df_counts: dict[str, int] = defaultdict(int)
    total_docs = len(all_rows)

    for row in all_rows:
        terms = _parse_tfidf(row["tfidf_keywords"])
        # Count each term once per file (document frequency, not term frequency)
        for term, _ in set((t, 0) for t, _ in terms):
            df_counts[term] += 1

    idf: dict[str, float] = {}
    for term, df in df_counts.items():
        # +1 smoothing avoids div-by-zero for any edge cases
        idf[term] = log(total_docs / (df + 1))

    return idf, total_docs


def load_projects(source_db: Path, min_files: int,
                  verbose: bool = True) -> tuple[dict, dict[str, float], int]:
    """
    Query file_metadata.sqlite3, compute global IDF, group by project.

    Returns (projects_dict, global_idf, total_doc_count).
    """
    if not source_db.exists():
        print(f"Error: source DB not found: {source_db}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(source_db))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT fm.file_path, ca.tfidf_keywords, ca.topic_summary
        FROM content_analysis ca
        JOIN file_metadata fm ON fm.file_path = ca.file_path
        WHERE ca.tfidf_keywords IS NOT NULL
          AND ca.tfidf_keywords != '[]'
          AND ca.tfidf_keywords != ''
    """).fetchall()
    conn.close()

    if verbose:
        print(f"{len(rows)} files with keywords", end=" — ", flush=True)

    # Step 1: compute global IDF across ALL files before grouping
    global_idf, total_docs = build_global_idf(rows)
    if verbose:
        print(f"global IDF computed ({total_docs} docs, {len(global_idf)} terms)", flush=True)

    # Step 2: group files by project, reweight scores by global IDF
    projects: dict[str, dict] = {}

    for row in rows:
        file_path = row["file_path"]
        result = _project_for_path(file_path)
        if result is None:
            continue
        project_name, project_dir = result

        if project_dir not in projects:
            projects[project_dir] = {
                "name": project_name,
                "dir": project_dir,
                "files": [],
                "keyword_scores": defaultdict(float),
            }

        terms = _parse_tfidf(row["tfidf_keywords"])

        # Reweight each term: local_score × global_IDF
        # local_score captures how prominent the term is within this file.
        # global_IDF suppresses terms that are common across the whole corpus.
        corrected = [
            (term, local_score * global_idf.get(term, 0.0))
            for term, local_score in terms
        ]
        # Drop terms whose corrected score is near zero (corpus-wide noise)
        corrected = [(t, s) for t, s in corrected if s > 0.001]

        file_score = sum(s for _, s in corrected)

        projects[project_dir]["files"].append({
            "path": file_path,
            "keywords": corrected,
            "score": file_score,
            "summary": row["topic_summary"] or "",
        })

        for term, score in corrected:
            projects[project_dir]["keyword_scores"][term] += score

    return (
        {d: p for d, p in projects.items() if len(p["files"]) >= min_files},
        global_idf,
        total_docs,
    )


def write_to_substrate(projects: dict, substrate_db: SubstrateDB,
                       top_files: int, dry_run: bool,
                       corpus_size: int = 0) -> tuple[int, int]:
    """Write project and file nodes to substrate DB."""
    proj_count = 0
    file_count = 0

    for project_dir, proj in sorted(projects.items()):
        sorted_kws = sorted(
            proj["keyword_scores"].items(),
            key=lambda x: x[1],
            reverse=True,
        )
        top_keywords = [kw for kw, _ in sorted_kws[:25]]

        metadata = {
            "top_keywords": top_keywords,
            "file_count": len(proj["files"]),
            "total_keyword_score": round(sum(s for _, s in sorted_kws), 4),
            # IDF stability: record corpus size at write time.
            # If corpus grows > ~10% since this was written, re-run to
            # keep keywords representative. IDF = log(N/df) shifts as N grows.
            "idf_corpus_size": corpus_size,
        }

        if not dry_run:
            substrate_db.upsert_node(
                node_type="project",
                label=proj["name"],
                source=project_dir,
                metadata=metadata,
            )
        proj_count += 1

        # Top N files by globally-corrected score
        top_file_list = sorted(proj["files"], key=lambda f: f["score"], reverse=True)
        for fdata in top_file_list[:top_files]:
            file_keywords = [
                kw for kw, _ in
                sorted(fdata["keywords"], key=lambda x: x[1], reverse=True)[:10]
            ]
            file_meta = {
                "top_keywords": file_keywords,
                "project": proj["name"],
                "tfidf_score": round(fdata["score"], 4),
            }
            if fdata["summary"]:
                file_meta["summary"] = fdata["summary"][:200]
            file_meta["idf_corpus_size"] = corpus_size

            if not dry_run:
                substrate_db.upsert_node(
                    node_type="file",
                    label=Path(fdata["path"]).name,
                    source=fdata["path"],
                    metadata=file_meta,
                )
            file_count += 1

    return proj_count, file_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_SOURCE_DB,
                        help=f"Source file_metadata DB (default: {DEFAULT_SOURCE_DB})")
    parser.add_argument("--substrate", type=Path, default=DEFAULT_DB,
                        help=f"Substrate DB to populate (default: {DEFAULT_DB})")
    parser.add_argument("--min-files", type=int, default=2,
                        help="Minimum files per project to include (default: 2)")
    parser.add_argument("--top-files", type=int, default=5,
                        help="Top files per project to store as file nodes (default: 5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be written, don't write")
    args = parser.parse_args()

    print(f"Loading from: {args.db_path}")
    print(f"Writing to:   {args.substrate}")
    if args.dry_run:
        print("[dry-run mode — no writes]")

    print("Reading content_analysis... ", end="", flush=True)
    projects, _global_idf, total_docs = load_projects(
        args.db_path, args.min_files, verbose=True
    )
    print(f"{len(projects)} projects after global IDF correction")

    db = SubstrateDB(args.substrate)

    print("Writing nodes...", end=" ", flush=True)
    proj_count, file_count = write_to_substrate(
        projects, db, top_files=args.top_files, dry_run=args.dry_run,
        corpus_size=total_docs,
    )
    print("done")

    if not args.dry_run:
        stats = db.stats()
        print(f"\nSubstrate DB @ {db.db_path}")
        print(f"  project nodes: {proj_count}")
        print(f"  file nodes:    {file_count}")
        print(f"  total nodes:   {stats['nodes']}")
    else:
        print(f"\n[dry-run] would write {proj_count} project nodes, "
              f"{file_count} file nodes")

    # Show top 10 projects — now with globally-corrected keywords
    top = sorted(projects.values(), key=lambda p: len(p["files"]), reverse=True)[:10]
    print(f"\nTop 10 projects (global IDF, N={total_docs} docs):")
    for p in top:
        top_kws = sorted(p["keyword_scores"].items(), key=lambda x: x[1], reverse=True)
        kws = [k for k, _ in top_kws[:5]]
        print(f"  {len(p['files']):5d}  {p['name'][:40]:<40}  {', '.join(kws)}")

    print(f"\nNote: IDF is stable at this corpus size. Re-run when indexed")
    print(f"file count grows by ~10%+ (currently N={total_docs}).")


if __name__ == "__main__":
    main()
