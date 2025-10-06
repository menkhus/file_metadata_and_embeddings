#!/usr/bin/env python3
"""
AI-Optimized Document Chunking with JSON Envelope Metadata

Implements chunking strategy optimized for AI consumption:
- Code: ~350 chars, discrete (no overlap)
- Prose: paragraph boundaries, discrete
- JSON envelope with comprehensive metadata
- Adjacency support via chunk_index
"""

import json
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib


@dataclass
class ChunkMetadata:
    """Metadata for a document chunk"""
    # Core metadata (mirrored in SQL columns)
    filename: str
    chunk_index: int
    total_chunks: int
    chunk_size: int
    chunk_strategy: str  # "code_discrete", "prose_discrete", "prose_overlap"
    overlap_chars: int
    file_type: str
    file_hash: str
    created_at: str

    # Extended AI-specific metadata (JSONB only)
    ai_metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Initialize AI metadata if not provided"""
        if self.ai_metadata is None:
            self.ai_metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def add_ai_metadata(self, key: str, value: Any):
        """Add AI-specific metadata"""
        if self.ai_metadata is None:
            self.ai_metadata = {}
        self.ai_metadata[key] = value


@dataclass
class ChunkEnvelope:
    """JSON envelope containing chunk and metadata"""
    metadata: ChunkMetadata
    content: str

    def to_json(self, indent: Optional[int] = 2) -> str:
        """Serialize to JSON string"""
        return json.dumps({
            'metadata': self.metadata.to_dict(),
            'content': self.content
        }, indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> 'ChunkEnvelope':
        """Deserialize from JSON string"""
        data = json.loads(json_str)
        metadata = ChunkMetadata(**data['metadata'])
        return cls(metadata=metadata, content=data['content'])


class AIOptimizedChunker:
    """Chunker optimized for AI consumption"""

    # Default chunk sizes
    CODE_CHUNK_SIZE = 350
    PROSE_CHUNK_SIZE = 800
    PROSE_OVERLAP_PERCENT = 0.15  # 15% overlap

    # File type classifications
    CODE_EXTENSIONS = {
        '.py', '.js', '.ts', '.java', '.c', '.cpp', '.h', '.hpp',
        '.rs', '.go', '.rb', '.php', '.swift', '.kt', '.scala',
        '.sh', '.bash', '.zsh', '.sql', '.r', '.m', '.cs'
    }

    def __init__(self):
        from datetime import datetime
        self.timestamp = datetime.utcnow().isoformat() + 'Z'

    def is_code_file(self, filename: str) -> bool:
        """Determine if file is code based on extension"""
        suffix = Path(filename).suffix.lower()
        return suffix in self.CODE_EXTENSIONS

    def calculate_file_hash(self, content: str) -> str:
        """Calculate SHA256 hash of content"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def chunk_code(self, content: str, filename: str) -> List[ChunkEnvelope]:
        """
        Chunk code files: ~350 chars, discrete (no overlap)
        Tries to break at logical boundaries (newlines, statement ends)
        """
        if not content:
            return []

        chunks = []
        lines = content.split('\n')
        current_chunk = []
        current_size = 0

        for line in lines:
            line_size = len(line) + 1  # +1 for newline

            # If adding this line exceeds chunk size, save current chunk
            if current_size + line_size > self.CODE_CHUNK_SIZE and current_chunk:
                chunks.append('\n'.join(current_chunk))
                current_chunk = [line]
                current_size = line_size
            else:
                current_chunk.append(line)
                current_size += line_size

        # Add remaining lines
        if current_chunk:
            chunks.append('\n'.join(current_chunk))

        return self._create_envelopes(
            chunks=chunks,
            filename=filename,
            content=content,
            strategy='code_discrete',
            overlap_chars=0
        )

    def chunk_prose(self, content: str, filename: str, use_overlap: bool = False) -> List[ChunkEnvelope]:
        """
        Chunk prose files at paragraph boundaries

        Args:
            content: Text content to chunk
            filename: Name of file
            use_overlap: If True, use 15% overlap; if False, discrete chunks
        """
        if not content:
            return []

        # Split on paragraph boundaries (double newline or multiple spaces)
        paragraphs = re.split(r'\n\s*\n', content)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        if not use_overlap:
            # Discrete chunking: group paragraphs until ~800 chars
            chunks = []
            current_chunk = []
            current_size = 0

            for para in paragraphs:
                para_size = len(para)

                # If single paragraph exceeds limit, split it
                if para_size > self.PROSE_CHUNK_SIZE:
                    if current_chunk:
                        chunks.append('\n\n'.join(current_chunk))
                        current_chunk = []
                        current_size = 0

                    # Split large paragraph at sentence boundaries
                    sentences = re.split(r'([.!?]+\s+)', para)
                    sent_chunk = []
                    sent_size = 0

                    for sent in sentences:
                        if sent_size + len(sent) > self.PROSE_CHUNK_SIZE and sent_chunk:
                            chunks.append(''.join(sent_chunk).strip())
                            sent_chunk = [sent]
                            sent_size = len(sent)
                        else:
                            sent_chunk.append(sent)
                            sent_size += len(sent)

                    if sent_chunk:
                        chunks.append(''.join(sent_chunk).strip())

                elif current_size + para_size > self.PROSE_CHUNK_SIZE and current_chunk:
                    chunks.append('\n\n'.join(current_chunk))
                    current_chunk = [para]
                    current_size = para_size
                else:
                    current_chunk.append(para)
                    current_size += para_size + 2  # +2 for \n\n

            if current_chunk:
                chunks.append('\n\n'.join(current_chunk))

            return self._create_envelopes(
                chunks=chunks,
                filename=filename,
                content=content,
                strategy='prose_discrete',
                overlap_chars=0
            )
        else:
            # Overlapping chunking for prose (if needed for retrieval)
            overlap_size = int(self.PROSE_CHUNK_SIZE * self.PROSE_OVERLAP_PERCENT)
            chunks = []
            start = 0

            while start < len(content):
                end = start + self.PROSE_CHUNK_SIZE

                # Find paragraph boundary near end
                if end < len(content):
                    para_break = content.find('\n\n', end - 100, end + 100)
                    if para_break != -1:
                        end = para_break

                chunk = content[start:end].strip()
                if chunk:
                    chunks.append(chunk)

                # Move start back by overlap amount
                start = end - overlap_size
                if start >= len(content):
                    break

            return self._create_envelopes(
                chunks=chunks,
                filename=filename,
                content=content,
                strategy='prose_overlap',
                overlap_chars=overlap_size
            )

    def chunk_file(self, filename: str, content: str, force_prose: bool = False) -> List[ChunkEnvelope]:
        """
        Main entry point: chunk file based on type

        Args:
            filename: Path or name of file
            content: File content
            force_prose: Force prose chunking even for code files
        """
        if force_prose or not self.is_code_file(filename):
            return self.chunk_prose(content, filename, use_overlap=False)
        else:
            return self.chunk_code(content, filename)

    def _create_envelopes(
        self,
        chunks: List[str],
        filename: str,
        content: str,
        strategy: str,
        overlap_chars: int
    ) -> List[ChunkEnvelope]:
        """Create ChunkEnvelope objects with metadata"""
        file_hash = self.calculate_file_hash(content)
        file_type = Path(filename).suffix.lstrip('.') or 'txt'
        total_chunks = len(chunks)

        # Calculate file-level stats for AI metadata
        file_size = len(content)
        avg_chunk_size = file_size / total_chunks if total_chunks > 0 else 0

        envelopes = []
        for i, chunk_content in enumerate(chunks):
            # Calculate chunk-specific AI metadata
            line_count = chunk_content.count('\n') + 1
            word_count = len(chunk_content.split())
            char_count = len(chunk_content)

            # Determine chunk position context
            position = "start" if i == 0 else ("end" if i == total_chunks - 1 else "middle")

            metadata = ChunkMetadata(
                filename=filename,
                chunk_index=i,
                total_chunks=total_chunks,
                chunk_size=char_count,
                chunk_strategy=strategy,
                overlap_chars=overlap_chars,
                file_type=file_type,
                file_hash=file_hash,
                created_at=self.timestamp,
                ai_metadata={
                    # Statistical metadata
                    'line_count': line_count,
                    'word_count': word_count,
                    'char_count': char_count,
                    'avg_chunk_size': round(avg_chunk_size, 2),
                    'file_total_size': file_size,

                    # Positional metadata
                    'chunk_position': position,
                    'has_previous': i > 0,
                    'has_next': i < total_chunks - 1,
                    'previous_chunk_index': i - 1 if i > 0 else None,
                    'next_chunk_index': i + 1 if i < total_chunks - 1 else None,

                    # Content hints for AI
                    'starts_with': chunk_content[:50] if len(chunk_content) > 50 else chunk_content,
                    'ends_with': chunk_content[-50:] if len(chunk_content) > 50 else chunk_content,

                    # Retrieval hints
                    'adjacent_chunk_indexes': list(range(max(0, i-2), min(total_chunks, i+3))),
                    'retrieval_context_suggestion': 'adjacent_1' if total_chunks > 3 else 'full_file',
                }
            )

            envelope = ChunkEnvelope(
                metadata=metadata,
                content=chunk_content
            )
            envelopes.append(envelope)

        return envelopes

    def get_adjacent_chunks(
        self,
        envelopes: List[ChunkEnvelope],
        chunk_index: int,
        before: int = 1,
        after: int = 1
    ) -> List[ChunkEnvelope]:
        """
        Retrieve adjacent chunks for context expansion

        Args:
            envelopes: List of all chunk envelopes
            chunk_index: Index of target chunk
            before: Number of chunks before to include
            after: Number of chunks after to include

        Returns:
            List of adjacent chunks including the target
        """
        start_idx = max(0, chunk_index - before)
        end_idx = min(len(envelopes), chunk_index + after + 1)
        return envelopes[start_idx:end_idx]


# Example usage and testing
if __name__ == "__main__":
    chunker = AIOptimizedChunker()

    # Example 1: Code chunking
    code_content = '''def hello_world():
    """A simple function"""
    print("Hello, world!")
    return 0

def calculate_sum(a, b):
    """Calculate sum of two numbers"""
    result = a + b
    return result

class MyClass:
    def __init__(self):
        self.value = 42

    def get_value(self):
        return self.value
'''

    print("=== CODE CHUNKING ===")
    code_chunks = chunker.chunk_code(code_content, "example.py")
    for envelope in code_chunks:
        print(f"\n--- Chunk {envelope.metadata.chunk_index}/{envelope.metadata.total_chunks - 1} ---")
        print(envelope.to_json())

    # Example 2: Prose chunking
    prose_content = '''This is the first paragraph of a document. It contains some information about the topic.

This is the second paragraph. It provides additional context and details about the subject matter.

This is the third paragraph. It continues the discussion and adds more depth to the analysis.

This is the fourth paragraph with conclusions and final thoughts on the matter.'''

    print("\n\n=== PROSE CHUNKING ===")
    prose_chunks = chunker.chunk_prose(prose_content, "example.md")
    for envelope in prose_chunks:
        print(f"\n--- Chunk {envelope.metadata.chunk_index}/{envelope.metadata.total_chunks - 1} ---")
        print(envelope.to_json())

    # Example 3: Adjacent chunk retrieval
    print("\n\n=== ADJACENT CHUNKS ===")
    if len(code_chunks) > 1:
        adjacent = chunker.get_adjacent_chunks(code_chunks, chunk_index=0, before=0, after=1)
        print(f"Retrieved {len(adjacent)} adjacent chunks (current + 1 after)")
        for env in adjacent:
            print(f"  - Chunk {env.metadata.chunk_index}: {env.metadata.chunk_size} chars")
