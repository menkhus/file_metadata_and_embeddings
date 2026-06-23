#!/usr/bin/env python3
"""
Two-Tier FAISS Index Manager

Manages major (stable) and minor (incremental) FAISS indexes for efficient
semantic search. Enables fast incremental updates without full index rebuilds.

Architecture:
- Major index: Bulk of vectors, rebuilt infrequently
- Minor index: Recent additions, merged into major periodically
- Staleness tracking: Handles file modifications and deletions

Key insight: FAISS supports add() and merge_from() but NOT remove().
We track stale vectors and filter them at query time.

Usage:
    manager = TwoTierFAISSManager()
    manager.add_chunks(chunks, embeddings)  # Fast incremental add
    results = manager.search(query_vec, top_k=10)  # Searches both indexes
    manager.compact()  # Merge minor into major
"""

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False


# Default paths
DEFAULT_DATA_DIR = os.path.expanduser("~/data")
EMBEDDING_DIM = 384  # Dimension for all-MiniLM-L6-v2


@dataclass
class SearchResult:
    """Single search result from FAISS query"""
    vector_id: int
    file_path: str
    chunk_index: int
    chunk_text: str
    similarity_score: float
    tier: str  # 'major' or 'minor'
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IndexState:
    """Persistent state tracking for two-tier indexes"""
    major_build_timestamp: Optional[str] = None
    minor_build_timestamp: Optional[str] = None
    major_vector_count: int = 0
    minor_vector_count: int = 0
    indexed_file_hashes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    stale_vector_ids: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IndexState':
        return cls(
            major_build_timestamp=data.get('major_build_timestamp'),
            minor_build_timestamp=data.get('minor_build_timestamp'),
            major_vector_count=data.get('major_vector_count', 0),
            minor_vector_count=data.get('minor_vector_count', 0),
            indexed_file_hashes=data.get('indexed_file_hashes', {}),
            stale_vector_ids=data.get('stale_vector_ids', []),
        )


class TwoTierFAISSManager:
    """
    Manages two-tier FAISS index architecture for incremental updates.

    Major index: Large, stable index rebuilt infrequently
    Minor index: Small, incremental index for recent additions

    On search, queries both indexes and merges results.
    On compact, merges minor into major and clears minor.
    """

    def __init__(self, data_dir: str = DEFAULT_DATA_DIR, embedding_dim: int = EMBEDDING_DIM):
        if not FAISS_AVAILABLE:
            raise ImportError("FAISS not available. Install with: pip install faiss-cpu")

        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_dim = embedding_dim

        # File paths
        self.major_index_path = self.data_dir / "file_search_major.faiss"
        self.major_meta_path = self.data_dir / "file_search_major_meta.json"
        self.minor_index_path = self.data_dir / "file_search_minor.faiss"
        self.minor_meta_path = self.data_dir / "file_search_minor_meta.json"
        self.state_path = self.data_dir / "file_search_index_state.json"

        # Legacy paths (for migration)
        self.legacy_index_path = self.data_dir / "file_search.faiss"
        self.legacy_meta_path = self.data_dir / "file_search_meta.json"

        # In-memory state (loaded lazily)
        self._major_index: Optional[faiss.Index] = None
        self._major_metadata: Optional[List[Dict[str, Any]]] = None
        self._minor_index: Optional[faiss.Index] = None
        self._minor_metadata: Optional[List[Dict[str, Any]]] = None
        self._state: Optional[IndexState] = None

    # -------------------------------------------------------------------------
    # State Management
    # -------------------------------------------------------------------------

    def _load_state(self) -> IndexState:
        """Load or initialize index state"""
        if self._state is not None:
            return self._state

        if self.state_path.exists():
            try:
                with open(self.state_path, 'r') as f:
                    data = json.load(f)
                self._state = IndexState.from_dict(data)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load state file: {e}", file=sys.stderr)
                self._state = IndexState()
        else:
            self._state = IndexState()

        return self._state

    def _save_state(self) -> None:
        """Persist index state to disk"""
        state = self._load_state()
        with open(self.state_path, 'w') as f:
            json.dump(state.to_dict(), f, indent=2)

    # -------------------------------------------------------------------------
    # Index Loading
    # -------------------------------------------------------------------------

    def _load_major_index(self) -> Tuple[Optional[faiss.Index], Optional[List[Dict[str, Any]]]]:
        """Load major index and metadata"""
        if self._major_index is not None:
            return self._major_index, self._major_metadata

        if not self.major_index_path.exists():
            return None, None

        try:
            self._major_index = faiss.read_index(str(self.major_index_path))

            if self.major_meta_path.exists():
                with open(self.major_meta_path, 'r') as f:
                    data = json.load(f)
                    # Handle both formats: list or dict with 'vectors' key
                    if isinstance(data, dict) and 'vectors' in data:
                        self._major_metadata = data['vectors']
                    else:
                        self._major_metadata = data
            else:
                self._major_metadata = []

            return self._major_index, self._major_metadata
        except Exception as e:
            print(f"Error loading major index: {e}", file=sys.stderr)
            return None, None

    def _load_minor_index(self) -> Tuple[Optional[faiss.Index], Optional[List[Dict[str, Any]]]]:
        """Load minor index and metadata"""
        if self._minor_index is not None:
            return self._minor_index, self._minor_metadata

        if not self.minor_index_path.exists():
            return None, None

        try:
            self._minor_index = faiss.read_index(str(self.minor_index_path))

            if self.minor_meta_path.exists():
                with open(self.minor_meta_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and 'vectors' in data:
                        self._minor_metadata = data['vectors']
                    else:
                        self._minor_metadata = data
            else:
                self._minor_metadata = []

            return self._minor_index, self._minor_metadata
        except Exception as e:
            print(f"Error loading minor index: {e}", file=sys.stderr)
            return None, None

    def _create_empty_index(self) -> faiss.Index:
        """Create empty FAISS index for inner product (cosine after normalization)"""
        return faiss.IndexFlatIP(self.embedding_dim)

    # -------------------------------------------------------------------------
    # Migration from Legacy Format
    # -------------------------------------------------------------------------

    def migrate_from_legacy(self) -> bool:
        """
        Migrate legacy single-index format to two-tier format.
        Renames file_search.faiss → file_search_major.faiss

        Returns True if migration occurred, False if already migrated or no legacy.
        """
        if self.major_index_path.exists():
            # Already have major index, no migration needed
            return False

        if not self.legacy_index_path.exists():
            # No legacy index to migrate
            return False

        print(f"Migrating legacy index to two-tier format...")

        # Rename index file
        os.rename(self.legacy_index_path, self.major_index_path)
        print(f"  Renamed {self.legacy_index_path.name} → {self.major_index_path.name}")

        # Rename metadata file
        if self.legacy_meta_path.exists():
            os.rename(self.legacy_meta_path, self.major_meta_path)
            print(f"  Renamed {self.legacy_meta_path.name} → {self.major_meta_path.name}")

        # Initialize state
        state = self._load_state()
        state.major_build_timestamp = datetime.now().isoformat()

        # Count vectors in migrated index
        major_index, major_meta = self._load_major_index()
        if major_index:
            state.major_vector_count = major_index.ntotal
        if major_meta:
            # Build file hash index from existing metadata
            for i, meta in enumerate(major_meta):
                file_path = meta.get('file_path', '')
                if file_path and file_path not in state.indexed_file_hashes:
                    state.indexed_file_hashes[file_path] = {
                        'tier': 'major',
                        'vector_ids': []
                    }
                if file_path:
                    state.indexed_file_hashes[file_path]['vector_ids'].append(i)

        self._save_state()
        print(f"  Migration complete. Major index has {state.major_vector_count} vectors.")
        return True

    # -------------------------------------------------------------------------
    # Adding Vectors (Incremental)
    # -------------------------------------------------------------------------

    def add_chunks(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: np.ndarray,
        file_hash: Optional[str] = None
    ) -> int:
        """
        Add chunks to minor index for fast incremental updates.

        Args:
            chunks: List of chunk metadata dicts (must include file_path, chunk_index, chunk_text)
            embeddings: Numpy array of embeddings, shape (n_chunks, embedding_dim)
            file_hash: Optional file hash for staleness tracking

        Returns:
            Number of vectors added
        """
        if len(chunks) == 0:
            return 0

        if embeddings.shape[0] != len(chunks):
            raise ValueError(f"Mismatch: {len(chunks)} chunks but {embeddings.shape[0]} embeddings")

        if embeddings.shape[1] != self.embedding_dim:
            raise ValueError(f"Embedding dim mismatch: got {embeddings.shape[1]}, expected {self.embedding_dim}")

        # Normalize embeddings for cosine similarity
        embeddings = embeddings.astype('float32')
        faiss.normalize_L2(embeddings)

        # Load or create minor index
        minor_index, minor_metadata = self._load_minor_index()
        if minor_index is None:
            minor_index = self._create_empty_index()
            minor_metadata = []
            self._minor_index = minor_index
            self._minor_metadata = minor_metadata

        # Get current vector count (for ID assignment)
        state = self._load_state()
        base_id = state.major_vector_count + state.minor_vector_count

        # Add to FAISS index
        minor_index.add(embeddings)

        # Add metadata
        new_ids = []
        for i, chunk in enumerate(chunks):
            vector_id = base_id + i
            new_ids.append(vector_id)

            meta = {
                'id': vector_id,
                'file_path': chunk.get('file_path', ''),
                'file_name': chunk.get('file_name', ''),
                'directory': chunk.get('directory', ''),
                'file_type': chunk.get('file_type', ''),
                'file_size': chunk.get('file_size', 0),
                'modified_date': chunk.get('modified_date', ''),
                'chunk_index': chunk.get('chunk_index', 0),
                'total_chunks': chunk.get('total_chunks', 1),
                'chunk_text': chunk.get('chunk_text', ''),
                'tfidf_keywords': chunk.get('tfidf_keywords', []),
                'lda_topics': chunk.get('lda_topics', []),
            }
            minor_metadata.append(meta)

        # Update state
        state.minor_vector_count = minor_index.ntotal
        state.minor_build_timestamp = datetime.now().isoformat()

        # Track file → vector mapping
        file_path = chunks[0].get('file_path', '') if chunks else ''
        if file_path:
            if file_path in state.indexed_file_hashes:
                # File was re-indexed - mark old vectors as stale
                old_info = state.indexed_file_hashes[file_path]
                state.stale_vector_ids.extend(old_info.get('vector_ids', []))

            state.indexed_file_hashes[file_path] = {
                'hash': file_hash or '',
                'tier': 'minor',
                'vector_ids': new_ids
            }

        # Save index and state
        self._save_minor_index()
        self._save_state()

        return len(chunks)

    def _save_minor_index(self) -> None:
        """Save minor index and metadata to disk"""
        if self._minor_index is None:
            return

        faiss.write_index(self._minor_index, str(self.minor_index_path))

        output_data = {
            'build_info': {
                'build_timestamp': datetime.now().isoformat(),
                'total_vectors': self._minor_index.ntotal,
                'tier': 'minor',
            },
            'vectors': self._minor_metadata or [],
        }

        with open(self.minor_meta_path, 'w') as f:
            json.dump(output_data, f)

    # -------------------------------------------------------------------------
    # Searching
    # -------------------------------------------------------------------------

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        filter_stale: bool = True
    ) -> List[SearchResult]:
        """
        Search both major and minor indexes, merge and deduplicate results.

        Args:
            query_embedding: Query vector, shape (embedding_dim,) or (1, embedding_dim)
            top_k: Number of results to return
            filter_stale: Whether to filter out stale vectors

        Returns:
            List of SearchResult objects, sorted by similarity (descending)
        """
        # Normalize query
        query = query_embedding.reshape(1, -1).astype('float32')
        faiss.normalize_L2(query)

        # Load state for staleness
        state = self._load_state()
        stale_ids = set(state.stale_vector_ids) if filter_stale else set()

        all_results: List[SearchResult] = []

        # Search major index
        major_index, major_metadata = self._load_major_index()
        if major_index is not None and major_index.ntotal > 0:
            # Request more than top_k to account for filtering
            search_k = min(top_k * 2, major_index.ntotal)
            scores, indices = major_index.search(query, search_k)

            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(major_metadata or []):
                    continue

                meta = major_metadata[idx]
                vector_id = meta.get('id', idx)

                if vector_id in stale_ids:
                    continue

                all_results.append(SearchResult(
                    vector_id=vector_id,
                    file_path=meta.get('file_path', ''),
                    chunk_index=meta.get('chunk_index', 0),
                    chunk_text=meta.get('chunk_text', ''),
                    similarity_score=float(score),
                    tier='major',
                    metadata=meta,
                ))

        # Search minor index
        minor_index, minor_metadata = self._load_minor_index()
        if minor_index is not None and minor_index.ntotal > 0:
            search_k = min(top_k * 2, minor_index.ntotal)
            scores, indices = minor_index.search(query, search_k)

            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(minor_metadata or []):
                    continue

                meta = minor_metadata[idx]
                vector_id = meta.get('id', idx)

                if vector_id in stale_ids:
                    continue

                all_results.append(SearchResult(
                    vector_id=vector_id,
                    file_path=meta.get('file_path', ''),
                    chunk_index=meta.get('chunk_index', 0),
                    chunk_text=meta.get('chunk_text', ''),
                    similarity_score=float(score),
                    tier='minor',
                    metadata=meta,
                ))

        # Merge and deduplicate
        return self._merge_results(all_results, top_k)

    def _merge_results(
        self,
        results: List[SearchResult],
        top_k: int
    ) -> List[SearchResult]:
        """
        Merge results from both indexes, deduplicate, and return top-k.

        Deduplication: If same (file_path, chunk_index) appears in both,
        keep the one with higher similarity score.
        """
        # Sort by similarity score (descending)
        results.sort(key=lambda r: r.similarity_score, reverse=True)

        # Deduplicate by (file_path, chunk_index)
        seen: Set[Tuple[str, int]] = set()
        unique_results: List[SearchResult] = []

        for result in results:
            key = (result.file_path, result.chunk_index)
            if key not in seen:
                seen.add(key)
                unique_results.append(result)

        return unique_results[:top_k]

    # -------------------------------------------------------------------------
    # Staleness Management
    # -------------------------------------------------------------------------

    def mark_file_stale(self, file_path: str) -> List[int]:
        """
        Mark all vectors from a file as stale (e.g., file was modified or deleted).

        Returns list of vector IDs marked as stale.
        """
        state = self._load_state()

        if file_path not in state.indexed_file_hashes:
            return []

        file_info = state.indexed_file_hashes[file_path]
        vector_ids = file_info.get('vector_ids', [])

        # Add to stale list
        state.stale_vector_ids.extend(vector_ids)

        # Remove from index tracking
        del state.indexed_file_hashes[file_path]

        self._save_state()
        return vector_ids

    def get_stale_vector_ids(self) -> Set[int]:
        """Get set of stale vector IDs"""
        state = self._load_state()
        return set(state.stale_vector_ids)

    def is_file_indexed(self, file_path: str, file_hash: Optional[str] = None) -> bool:
        """
        Check if a file is already indexed.
        If file_hash is provided, also checks if it matches (i.e., file unchanged).
        """
        state = self._load_state()

        if file_path not in state.indexed_file_hashes:
            return False

        if file_hash is not None:
            stored_hash = state.indexed_file_hashes[file_path].get('hash', '')
            return stored_hash == file_hash

        return True

    # -------------------------------------------------------------------------
    # Compaction
    # -------------------------------------------------------------------------

    def needs_compaction(self, threshold: int = 1000) -> bool:
        """
        Check if compaction is recommended.

        Triggers when:
        - Minor index exceeds threshold vectors, OR
        - Minor index > 10% of major index size
        """
        state = self._load_state()

        if state.minor_vector_count >= threshold:
            return True

        if state.major_vector_count > 0:
            ratio = state.minor_vector_count / state.major_vector_count
            if ratio > 0.1:
                return True

        return False

    def compact(self) -> Dict[str, Any]:
        """
        Merge minor index into major index and clear minor.

        Returns dict with compaction stats.
        """
        state = self._load_state()

        minor_index, minor_metadata = self._load_minor_index()

        if minor_index is None or minor_index.ntotal == 0:
            return {
                'status': 'no_action',
                'message': 'Minor index is empty, nothing to compact',
                'minor_vectors': 0,
                'major_vectors': state.major_vector_count,
            }

        # Load major index (or create if needed)
        major_index, major_metadata = self._load_major_index()
        if major_index is None:
            major_index = self._create_empty_index()
            major_metadata = []

        # Record pre-compaction stats
        pre_major = major_index.ntotal
        pre_minor = minor_index.ntotal

        # Merge minor into major
        major_index.merge_from(minor_index)

        # Merge metadata
        major_metadata = (major_metadata or []) + (minor_metadata or [])

        # Update state
        state.major_vector_count = major_index.ntotal
        state.major_build_timestamp = datetime.now().isoformat()
        state.minor_vector_count = 0
        state.minor_build_timestamp = None

        # Update tier tracking in indexed_file_hashes
        for file_path, info in state.indexed_file_hashes.items():
            if info.get('tier') == 'minor':
                info['tier'] = 'major'

        # Save major index
        self._major_index = major_index
        self._major_metadata = major_metadata
        faiss.write_index(major_index, str(self.major_index_path))

        output_data = {
            'build_info': {
                'build_timestamp': datetime.now().isoformat(),
                'total_vectors': major_index.ntotal,
                'tier': 'major',
            },
            'vectors': major_metadata,
        }
        with open(self.major_meta_path, 'w') as f:
            json.dump(output_data, f)

        # Remove minor index files
        if self.minor_index_path.exists():
            os.remove(self.minor_index_path)
        if self.minor_meta_path.exists():
            os.remove(self.minor_meta_path)

        # Clear in-memory minor index
        self._minor_index = None
        self._minor_metadata = None

        self._save_state()

        return {
            'status': 'success',
            'message': f'Merged {pre_minor} vectors from minor into major',
            'pre_major_vectors': pre_major,
            'pre_minor_vectors': pre_minor,
            'post_major_vectors': major_index.ntotal,
            'stale_vectors': len(state.stale_vector_ids),
        }

    # -------------------------------------------------------------------------
    # Status and Stats
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive stats about both indexes"""
        state = self._load_state()

        major_index, _ = self._load_major_index()
        minor_index, _ = self._load_minor_index()

        stats = {
            'major': {
                'exists': self.major_index_path.exists(),
                'vector_count': major_index.ntotal if major_index else 0,
                'build_timestamp': state.major_build_timestamp,
                'file_size_mb': self._get_file_size_mb(self.major_index_path),
            },
            'minor': {
                'exists': self.minor_index_path.exists(),
                'vector_count': minor_index.ntotal if minor_index else 0,
                'build_timestamp': state.minor_build_timestamp,
                'file_size_mb': self._get_file_size_mb(self.minor_index_path),
            },
            'total_vectors': (major_index.ntotal if major_index else 0) +
                            (minor_index.ntotal if minor_index else 0),
            'indexed_files': len(state.indexed_file_hashes),
            'stale_vectors': len(state.stale_vector_ids),
            'needs_compaction': self.needs_compaction(),
        }

        return stats

    def _get_file_size_mb(self, path: Path) -> float:
        """Get file size in MB, or 0 if file doesn't exist"""
        if path.exists():
            return path.stat().st_size / (1024 * 1024)
        return 0.0

    # -------------------------------------------------------------------------
    # Full Rebuild
    # -------------------------------------------------------------------------

    def rebuild_major(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: np.ndarray
    ) -> Dict[str, Any]:
        """
        Full rebuild of major index from scratch.
        Clears minor index and resets staleness tracking.

        Args:
            chunks: All chunk metadata
            embeddings: All embeddings, shape (n_chunks, embedding_dim)

        Returns:
            Build stats
        """
        if len(chunks) == 0:
            return {'status': 'error', 'message': 'No chunks provided'}

        if embeddings.shape[0] != len(chunks):
            raise ValueError(f"Mismatch: {len(chunks)} chunks but {embeddings.shape[0]} embeddings")

        # Normalize embeddings
        embeddings = embeddings.astype('float32')
        faiss.normalize_L2(embeddings)

        # Create new index
        new_index = self._create_empty_index()
        new_index.add(embeddings)

        # Build metadata
        new_metadata = []
        file_hashes: Dict[str, Dict[str, Any]] = {}

        for i, chunk in enumerate(chunks):
            meta = {
                'id': i,
                'file_path': chunk.get('file_path', ''),
                'file_name': chunk.get('file_name', ''),
                'directory': chunk.get('directory', ''),
                'file_type': chunk.get('file_type', ''),
                'file_size': chunk.get('file_size', 0),
                'modified_date': chunk.get('modified_date', ''),
                'chunk_index': chunk.get('chunk_index', 0),
                'total_chunks': chunk.get('total_chunks', 1),
                'chunk_text': chunk.get('chunk_text', ''),
                'tfidf_keywords': chunk.get('tfidf_keywords', []),
                'lda_topics': chunk.get('lda_topics', []),
            }
            new_metadata.append(meta)

            # Track file → vector mapping
            file_path = chunk.get('file_path', '')
            if file_path:
                if file_path not in file_hashes:
                    file_hashes[file_path] = {
                        'tier': 'major',
                        'vector_ids': []
                    }
                file_hashes[file_path]['vector_ids'].append(i)

        # Save major index
        self._major_index = new_index
        self._major_metadata = new_metadata
        faiss.write_index(new_index, str(self.major_index_path))

        output_data = {
            'build_info': {
                'build_timestamp': datetime.now().isoformat(),
                'total_vectors': new_index.ntotal,
                'tier': 'major',
            },
            'vectors': new_metadata,
        }
        with open(self.major_meta_path, 'w') as f:
            json.dump(output_data, f)

        # Clear minor index
        if self.minor_index_path.exists():
            os.remove(self.minor_index_path)
        if self.minor_meta_path.exists():
            os.remove(self.minor_meta_path)
        self._minor_index = None
        self._minor_metadata = None

        # Reset state
        self._state = IndexState(
            major_build_timestamp=datetime.now().isoformat(),
            major_vector_count=new_index.ntotal,
            minor_vector_count=0,
            indexed_file_hashes=file_hashes,
            stale_vector_ids=[],
        )
        self._save_state()

        return {
            'status': 'success',
            'message': f'Rebuilt major index with {new_index.ntotal} vectors',
            'total_vectors': new_index.ntotal,
            'indexed_files': len(file_hashes),
        }
