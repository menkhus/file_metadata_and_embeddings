#!/usr/bin/env python3
"""
Unit tests for TwoTierFAISSManager

Tests the two-tier FAISS index architecture:
- Adding vectors to minor index
- Searching both indexes
- Staleness tracking and filtering
- Compaction (minor -> major merge)
- State file persistence
- Legacy migration

Run with: pytest test_faiss_index_manager.py -v
"""

import json
import os
import shutil
import tempfile
import pytest
import numpy as np

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

from faiss_index_manager import TwoTierFAISSManager, SearchResult, IndexState, EMBEDDING_DIM


# Skip all tests if FAISS not available
pytestmark = pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not installed")


@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for test indexes"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def manager(temp_data_dir):
    """Create a manager with temporary data directory"""
    return TwoTierFAISSManager(data_dir=temp_data_dir)


def make_chunks(n: int, file_path: str = "/test/file.py") -> list:
    """Create n test chunks"""
    return [
        {
            'file_path': file_path,
            'file_name': 'file.py',
            'directory': '/test',
            'file_type': 'py',
            'file_size': 1000,
            'modified_date': '2025-01-01',
            'chunk_index': i,
            'total_chunks': n,
            'chunk_text': f'Test chunk {i} content for semantic search',
            'tfidf_keywords': ['test', 'chunk'],
            'lda_topics': [0],
        }
        for i in range(n)
    ]


def make_embeddings(n: int) -> np.ndarray:
    """Create n random normalized embeddings"""
    embeddings = np.random.randn(n, EMBEDDING_DIM).astype('float32')
    faiss.normalize_L2(embeddings)
    return embeddings


class TestIndexState:
    """Tests for IndexState dataclass"""

    def test_default_state(self):
        state = IndexState()
        assert state.major_vector_count == 0
        assert state.minor_vector_count == 0
        assert state.stale_vector_ids == []
        assert state.indexed_file_hashes == {}

    def test_to_dict_roundtrip(self):
        state = IndexState(
            major_build_timestamp="2025-01-01T00:00:00",
            major_vector_count=100,
            minor_vector_count=10,
            indexed_file_hashes={"/test/file.py": {"tier": "major", "vector_ids": [0, 1]}},
            stale_vector_ids=[5, 6],
        )
        state_dict = state.to_dict()
        restored = IndexState.from_dict(state_dict)

        assert restored.major_build_timestamp == state.major_build_timestamp
        assert restored.major_vector_count == state.major_vector_count
        assert restored.minor_vector_count == state.minor_vector_count
        assert restored.indexed_file_hashes == state.indexed_file_hashes
        assert restored.stale_vector_ids == state.stale_vector_ids


class TestTwoTierFAISSManager:
    """Tests for TwoTierFAISSManager"""

    def test_init_creates_data_dir(self, temp_data_dir):
        subdir = os.path.join(temp_data_dir, "subdir")
        manager = TwoTierFAISSManager(data_dir=subdir)
        assert os.path.exists(subdir)

    def test_empty_stats(self, manager):
        stats = manager.get_stats()
        assert stats['total_vectors'] == 0
        assert stats['major']['exists'] is False
        assert stats['minor']['exists'] is False
        assert stats['indexed_files'] == 0
        assert stats['stale_vectors'] == 0
        assert stats['needs_compaction'] is False

    def test_add_chunks_to_minor(self, manager):
        chunks = make_chunks(5)
        embeddings = make_embeddings(5)

        added = manager.add_chunks(chunks, embeddings)

        assert added == 5
        stats = manager.get_stats()
        assert stats['minor']['vector_count'] == 5
        assert stats['minor']['exists'] is True
        assert stats['major']['exists'] is False
        assert stats['total_vectors'] == 5

    def test_add_chunks_validates_dimensions(self, manager):
        chunks = make_chunks(5)
        wrong_dim_embeddings = np.random.randn(5, 100).astype('float32')  # Wrong dim

        with pytest.raises(ValueError, match="Embedding dim mismatch"):
            manager.add_chunks(chunks, wrong_dim_embeddings)

    def test_add_chunks_validates_count(self, manager):
        chunks = make_chunks(5)
        too_few_embeddings = make_embeddings(3)

        with pytest.raises(ValueError, match="Mismatch"):
            manager.add_chunks(chunks, too_few_embeddings)

    def test_search_empty_index(self, manager):
        query = make_embeddings(1)[0]
        results = manager.search(query, top_k=5)
        assert results == []

    def test_search_minor_only(self, manager):
        # Add to minor index
        chunks = make_chunks(10)
        embeddings = make_embeddings(10)
        manager.add_chunks(chunks, embeddings)

        # Search with first embedding (should find itself as top match)
        results = manager.search(embeddings[0], top_k=3)

        assert len(results) <= 3
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].tier == 'minor'

    def test_search_major_only(self, manager):
        # Rebuild major index directly
        chunks = make_chunks(10)
        embeddings = make_embeddings(10)
        manager.rebuild_major(chunks, embeddings)

        # Search
        results = manager.search(embeddings[0], top_k=3)

        assert len(results) <= 3
        assert results[0].tier == 'major'

    def test_search_both_tiers(self, manager):
        # Build major with 10 chunks
        chunks1 = make_chunks(10, "/test/file1.py")
        embeddings1 = make_embeddings(10)
        manager.rebuild_major(chunks1, embeddings1)

        # Add to minor with 5 different chunks
        chunks2 = make_chunks(5, "/test/file2.py")
        embeddings2 = make_embeddings(5)
        manager.add_chunks(chunks2, embeddings2)

        # Search should potentially return results from both
        query = make_embeddings(1)[0]
        results = manager.search(query, top_k=15)

        assert len(results) <= 15
        # Results should be sorted by similarity
        scores = [r.similarity_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_deduplicates_by_file_chunk(self, manager):
        # Add same file/chunk twice (simulating re-indexing)
        chunks1 = make_chunks(3, "/test/file.py")
        embeddings1 = make_embeddings(3)
        manager.add_chunks(chunks1, embeddings1, file_hash="hash1")

        # Search should not have duplicates
        results = manager.search(embeddings1[0], top_k=10)

        # Check for unique (file_path, chunk_index) combinations
        keys = [(r.file_path, r.chunk_index) for r in results]
        assert len(keys) == len(set(keys))

    def test_staleness_tracking(self, manager):
        # Add chunks for a file
        chunks = make_chunks(3, "/test/file.py")
        embeddings = make_embeddings(3)
        manager.add_chunks(chunks, embeddings, file_hash="hash1")

        # Mark file as stale
        stale_ids = manager.mark_file_stale("/test/file.py")

        assert len(stale_ids) == 3
        assert manager.get_stale_vector_ids() == set(stale_ids)

    def test_search_filters_stale(self, manager):
        # Add chunks
        chunks = make_chunks(5, "/test/file.py")
        embeddings = make_embeddings(5)
        manager.add_chunks(chunks, embeddings)

        # Mark as stale
        manager.mark_file_stale("/test/file.py")

        # Search should return nothing (all stale)
        results = manager.search(embeddings[0], top_k=5, filter_stale=True)
        assert len(results) == 0

        # Search without filtering should still find them
        results = manager.search(embeddings[0], top_k=5, filter_stale=False)
        assert len(results) > 0

    def test_is_file_indexed(self, manager):
        assert manager.is_file_indexed("/test/file.py") is False

        chunks = make_chunks(3, "/test/file.py")
        embeddings = make_embeddings(3)
        manager.add_chunks(chunks, embeddings, file_hash="hash1")

        assert manager.is_file_indexed("/test/file.py") is True
        assert manager.is_file_indexed("/test/file.py", file_hash="hash1") is True
        assert manager.is_file_indexed("/test/file.py", file_hash="hash2") is False

    def test_needs_compaction_threshold(self, manager):
        assert manager.needs_compaction() is False

        # Add just below threshold
        chunks = make_chunks(500)
        embeddings = make_embeddings(500)
        manager.add_chunks(chunks, embeddings)
        assert manager.needs_compaction(threshold=1000) is False

        # Add to exceed threshold
        chunks2 = make_chunks(600, "/test/file2.py")
        embeddings2 = make_embeddings(600)
        manager.add_chunks(chunks2, embeddings2)
        assert manager.needs_compaction(threshold=1000) is True

    def test_compact_empty_minor(self, manager):
        result = manager.compact()
        assert result['status'] == 'no_action'

    def test_compact_merges_into_major(self, manager):
        # Add to minor
        chunks = make_chunks(10)
        embeddings = make_embeddings(10)
        manager.add_chunks(chunks, embeddings)

        stats_before = manager.get_stats()
        assert stats_before['minor']['vector_count'] == 10
        assert stats_before['major']['vector_count'] == 0

        # Compact
        result = manager.compact()

        assert result['status'] == 'success'
        assert result['pre_minor_vectors'] == 10
        assert result['post_major_vectors'] == 10

        stats_after = manager.get_stats()
        assert stats_after['minor']['vector_count'] == 0
        assert stats_after['major']['vector_count'] == 10
        assert stats_after['minor']['exists'] is False

    def test_compact_adds_to_existing_major(self, manager):
        # Build initial major
        chunks1 = make_chunks(5, "/test/file1.py")
        embeddings1 = make_embeddings(5)
        manager.rebuild_major(chunks1, embeddings1)

        # Add to minor
        chunks2 = make_chunks(3, "/test/file2.py")
        embeddings2 = make_embeddings(3)
        manager.add_chunks(chunks2, embeddings2)

        # Compact
        result = manager.compact()

        assert result['pre_major_vectors'] == 5
        assert result['pre_minor_vectors'] == 3
        assert result['post_major_vectors'] == 8

    def test_rebuild_major_clears_all(self, manager):
        # Add to minor first
        chunks1 = make_chunks(5)
        embeddings1 = make_embeddings(5)
        manager.add_chunks(chunks1, embeddings1)

        # Rebuild major (should clear minor too)
        chunks2 = make_chunks(10, "/test/newfile.py")
        embeddings2 = make_embeddings(10)
        result = manager.rebuild_major(chunks2, embeddings2)

        assert result['total_vectors'] == 10
        stats = manager.get_stats()
        assert stats['major']['vector_count'] == 10
        assert stats['minor']['vector_count'] == 0
        assert stats['stale_vectors'] == 0

    def test_state_persistence(self, temp_data_dir):
        # Create manager and add data
        manager1 = TwoTierFAISSManager(data_dir=temp_data_dir)
        chunks = make_chunks(5)
        embeddings = make_embeddings(5)
        manager1.add_chunks(chunks, embeddings, file_hash="test_hash")

        # Create new manager instance (simulating restart)
        manager2 = TwoTierFAISSManager(data_dir=temp_data_dir)
        stats = manager2.get_stats()

        assert stats['minor']['vector_count'] == 5
        assert manager2.is_file_indexed("/test/file.py", file_hash="test_hash")


class TestLegacyMigration:
    """Tests for legacy single-index migration"""

    def test_migrate_renames_files(self, temp_data_dir):
        # Create legacy index files
        legacy_index_path = os.path.join(temp_data_dir, "file_search.faiss")
        legacy_meta_path = os.path.join(temp_data_dir, "file_search_meta.json")

        # Create a simple FAISS index
        index = faiss.IndexFlatIP(EMBEDDING_DIM)
        embeddings = make_embeddings(5)
        index.add(embeddings)
        faiss.write_index(index, legacy_index_path)

        # Create metadata
        meta = {
            'build_info': {'total_vectors': 5},
            'vectors': [{'id': i, 'file_path': f'/test/file{i}.py', 'chunk_index': 0}
                       for i in range(5)]
        }
        with open(legacy_meta_path, 'w') as f:
            json.dump(meta, f)

        # Initialize manager (should trigger migration)
        manager = TwoTierFAISSManager(data_dir=temp_data_dir)
        migrated = manager.migrate_from_legacy()

        assert migrated is True
        assert not os.path.exists(legacy_index_path)
        assert not os.path.exists(legacy_meta_path)
        assert os.path.exists(os.path.join(temp_data_dir, "file_search_major.faiss"))
        assert os.path.exists(os.path.join(temp_data_dir, "file_search_major_meta.json"))

    def test_no_migration_if_already_migrated(self, temp_data_dir):
        # Create major index directly
        manager = TwoTierFAISSManager(data_dir=temp_data_dir)
        chunks = make_chunks(5)
        embeddings = make_embeddings(5)
        manager.rebuild_major(chunks, embeddings)

        # Migration should return False
        migrated = manager.migrate_from_legacy()
        assert migrated is False

    def test_no_migration_if_no_legacy(self, temp_data_dir):
        manager = TwoTierFAISSManager(data_dir=temp_data_dir)
        migrated = manager.migrate_from_legacy()
        assert migrated is False


class TestSearchResultMerging:
    """Tests for result merging and deduplication"""

    def test_results_sorted_by_similarity(self, manager):
        chunks = make_chunks(20)
        embeddings = make_embeddings(20)
        manager.add_chunks(chunks, embeddings)

        query = make_embeddings(1)[0]
        results = manager.search(query, top_k=10)

        scores = [r.similarity_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_limit_respected(self, manager):
        chunks = make_chunks(50)
        embeddings = make_embeddings(50)
        manager.add_chunks(chunks, embeddings)

        query = make_embeddings(1)[0]
        results = manager.search(query, top_k=5)

        assert len(results) == 5

    def test_deduplication_prefers_higher_score(self, manager):
        # Build major with some vectors
        chunks1 = make_chunks(3)
        embeddings1 = make_embeddings(3)
        manager.rebuild_major(chunks1, embeddings1)

        # Add same file to minor (simulating modified file)
        chunks2 = make_chunks(3)  # Same file path
        embeddings2 = make_embeddings(3)  # Different embeddings
        manager.add_chunks(chunks2, embeddings2)

        # Search - should only get unique (file_path, chunk_index) pairs
        query = make_embeddings(1)[0]
        results = manager.search(query, top_k=10)

        keys = [(r.file_path, r.chunk_index) for r in results]
        assert len(keys) == len(set(keys))
        assert len(results) <= 3  # Max 3 unique chunks


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
