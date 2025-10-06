#!/usr/bin/env python3
"""
Test suite for AI-optimized chunking system
"""

import json
import tempfile
import os
from pathlib import Path

from chunking_refactor import AIOptimizedChunker, ChunkEnvelope


def test_code_chunking():
    """Test code file chunking"""
    print("=" * 60)
    print("TEST: Code Chunking")
    print("=" * 60)

    chunker = AIOptimizedChunker()

    # Multi-function Python code
    code = '''#!/usr/bin/env python3
"""Module docstring"""

import os
import sys

def function_one(arg1, arg2):
    """First function"""
    result = arg1 + arg2
    return result

def function_two(data):
    """Second function"""
    processed = []
    for item in data:
        if item > 0:
            processed.append(item * 2)
    return processed

class ExampleClass:
    """Example class"""

    def __init__(self, value):
        self.value = value

    def process(self):
        return self.value ** 2

if __name__ == "__main__":
    print("Running example")
'''

    envelopes = chunker.chunk_code(code, "test.py")

    print(f"\nCreated {len(envelopes)} chunks")
    for env in envelopes:
        print(f"\n--- Chunk {env.metadata.chunk_index} ---")
        print(f"Size: {env.metadata.chunk_size} chars")
        print(f"Strategy: {env.metadata.chunk_strategy}")
        print(f"Preview: {env.content[:100]}...")

    # Verify metadata
    assert all(env.metadata.chunk_strategy == "code_discrete" for env in envelopes)
    assert all(env.metadata.overlap_chars == 0 for env in envelopes)
    assert envelopes[0].metadata.total_chunks == len(envelopes)

    print("\n✓ Code chunking tests passed")
    return envelopes


def test_prose_chunking():
    """Test prose/markdown chunking"""
    print("\n" + "=" * 60)
    print("TEST: Prose Chunking")
    print("=" * 60)

    chunker = AIOptimizedChunker()

    # Longer prose document
    prose = '''# Introduction

This is the introduction paragraph. It sets the stage for what's to come in this document. We'll explore several key concepts throughout this text.

## First Section

The first section delves into the primary topic. It provides detailed explanations and examples that help illustrate the main points being discussed.

This paragraph continues the discussion with additional context. Multiple paragraphs within a section help organize the information logically.

## Second Section

Here we transition to a related but distinct topic. The relationship to the previous section becomes clear as we explore these ideas further.

Each paragraph builds upon the previous one, creating a coherent narrative that guides the reader through complex material.

## Conclusion

Finally, we wrap up with concluding thoughts that tie everything together. The conclusion reinforces the key takeaways from the entire document.'''

    envelopes = chunker.chunk_prose(prose, "test.md", use_overlap=False)

    print(f"\nCreated {len(envelopes)} discrete chunks")
    for env in envelopes:
        print(f"\n--- Chunk {env.metadata.chunk_index} ---")
        print(f"Size: {env.metadata.chunk_size} chars")
        print(f"Strategy: {env.metadata.chunk_strategy}")
        print(f"Paragraphs: {env.content.count(chr(10) + chr(10)) + 1}")

    # Verify metadata
    assert all(env.metadata.chunk_strategy == "prose_discrete" for env in envelopes)
    assert all(env.metadata.overlap_chars == 0 for env in envelopes)

    print("\n✓ Prose chunking tests passed")
    return envelopes


def test_chunk_envelope_serialization():
    """Test JSON serialization/deserialization"""
    print("\n" + "=" * 60)
    print("TEST: Chunk Envelope Serialization")
    print("=" * 60)

    chunker = AIOptimizedChunker()
    content = "Test content for serialization"
    envelopes = chunker.chunk_file("test.txt", content)

    # Serialize to JSON
    json_str = envelopes[0].to_json()
    print(f"\nSerialized envelope ({len(json_str)} bytes):")
    print(json_str[:200] + "..." if len(json_str) > 200 else json_str)

    # Deserialize
    restored = ChunkEnvelope.from_json(json_str)

    # Verify
    assert restored.metadata.filename == envelopes[0].metadata.filename
    assert restored.metadata.chunk_index == envelopes[0].metadata.chunk_index
    assert restored.content == envelopes[0].content

    print("\n✓ Serialization tests passed")


def test_adjacent_chunk_retrieval():
    """Test getting adjacent chunks for context"""
    print("\n" + "=" * 60)
    print("TEST: Adjacent Chunk Retrieval")
    print("=" * 60)

    chunker = AIOptimizedChunker()

    # Create content with multiple chunks
    content = "\n\n".join([f"Paragraph {i}. " + ("Content. " * 50) for i in range(10)])
    envelopes = chunker.chunk_prose(content, "multi.md", use_overlap=False)

    print(f"\nTotal chunks: {len(envelopes)}")

    # Test adjacent retrieval
    target_idx = 5
    adjacent = chunker.get_adjacent_chunks(envelopes, target_idx, before=2, after=2)

    print(f"\nRetrieved {len(adjacent)} adjacent chunks around chunk {target_idx}:")
    for env in adjacent:
        marker = "  <-- TARGET" if env.metadata.chunk_index == target_idx else ""
        print(f"  Chunk {env.metadata.chunk_index}{marker}")

    # Verify
    assert len(adjacent) == 5  # 2 before + target + 2 after
    assert adjacent[2].metadata.chunk_index == target_idx

    # Edge case: beginning
    adjacent_start = chunker.get_adjacent_chunks(envelopes, 0, before=2, after=2)
    print(f"\nEdge case (start): {len(adjacent_start)} chunks")
    assert adjacent_start[0].metadata.chunk_index == 0

    # Edge case: end
    last_idx = len(envelopes) - 1
    adjacent_end = chunker.get_adjacent_chunks(envelopes, last_idx, before=2, after=2)
    print(f"Edge case (end): {len(adjacent_end)} chunks")
    assert adjacent_end[-1].metadata.chunk_index == last_idx

    print("\n✓ Adjacent chunk retrieval tests passed")


def test_file_type_detection():
    """Test automatic code vs prose detection"""
    print("\n" + "=" * 60)
    print("TEST: File Type Detection")
    print("=" * 60)

    chunker = AIOptimizedChunker()

    test_cases = [
        ("script.py", True),
        ("app.js", True),
        ("main.c", True),
        ("readme.md", False),
        ("document.txt", False),
        ("notes.org", False),
        ("config.json", False),
    ]

    for filename, expected_is_code in test_cases:
        is_code = chunker.is_code_file(filename)
        status = "✓" if is_code == expected_is_code else "✗"
        print(f"{status} {filename}: {'CODE' if is_code else 'PROSE'}")
        assert is_code == expected_is_code

    print("\n✓ File type detection tests passed")


def test_metadata_completeness():
    """Verify all required metadata fields are present"""
    print("\n" + "=" * 60)
    print("TEST: Metadata Completeness")
    print("=" * 60)

    chunker = AIOptimizedChunker()
    content = "Test content"
    envelopes = chunker.chunk_file("test.py", content)

    required_fields = [
        'filename',
        'chunk_index',
        'total_chunks',
        'chunk_size',
        'chunk_strategy',
        'overlap_chars',
        'file_type',
        'file_hash',
        'created_at'
    ]

    metadata_dict = envelopes[0].metadata.to_dict()

    print("\nMetadata fields:")
    for field in required_fields:
        present = field in metadata_dict
        status = "✓" if present else "✗"
        value = metadata_dict.get(field, "MISSING")
        print(f"{status} {field}: {value}")
        assert present, f"Missing required field: {field}"

    print("\n✓ Metadata completeness tests passed")


def demo_json_output():
    """Demonstrate JSON envelope format"""
    print("\n" + "=" * 60)
    print("DEMO: JSON Envelope Format for AI Consumption")
    print("=" * 60)

    chunker = AIOptimizedChunker()

    code_sample = '''def calculate(x, y):
    """Perform calculation"""
    return x * y + (x / y)

result = calculate(10, 5)
print(f"Result: {result}")'''

    envelopes = chunker.chunk_code(code_sample, "demo.py")

    print("\nComplete JSON envelope (ready for AI consumption):")
    print(envelopes[0].to_json())

    print("\nKey features:")
    print("  ✓ Complete metadata in envelope")
    print("  ✓ Chunk strategy clearly marked")
    print("  ✓ Adjacency info (chunk_index, total_chunks)")
    print("  ✓ File integrity (file_hash)")
    print("  ✓ Temporal tracking (created_at)")
    print("  ✓ Clean separation of content and metadata")


def main():
    """Run all tests"""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 10 + "AI-Optimized Chunking Test Suite" + " " * 15 + "║")
    print("╚" + "═" * 58 + "╝")

    try:
        test_code_chunking()
        test_prose_chunking()
        test_chunk_envelope_serialization()
        test_adjacent_chunk_retrieval()
        test_file_type_detection()
        test_metadata_completeness()
        demo_json_output()

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED ✓")
        print("=" * 60)
        print("\nNext steps:")
        print("  1. Run: python3 chunk_db_integration.py")
        print("  2. Initialize schema in your database")
        print("  3. Start chunking files with new system")
        print("=" * 60 + "\n")

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
