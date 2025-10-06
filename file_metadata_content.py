#!/usr/bin/env python3

"""
Cross-platform File Metadata and Content Analysis System with Enhanced Error Handling

This system provides:
1. File metadata extraction (cross-platform)
2. Content analysis with AI-powered features
3. SQLite database storage
4. Text processing and embeddings
5. Search capabilities foundation
6. Robust error handling and graceful degradation

Requirements:
pip install sqlite3 pathlib nltk scikit-learn sentence-transformers pandas numpy tqdm setproctitle
"""

import os
import sqlite3
import hashlib
import mimetypes
import platform
import json
import re
import time
import signal
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import logging
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from enum import Enum

# Third-party imports (install via pip)
try:
    import pandas as pd
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.decomposition import LatentDirichletAllocation
    from sentence_transformers import SentenceTransformer
    import nltk
    from nltk.corpus import stopwords
    from nltk.tokenize import word_tokenize, sent_tokenize
    from nltk.stem import WordNetLemmatizer
    from tqdm import tqdm
    import setproctitle
    # Download required NLTK data with error handling
    try:
        nltk.download('punkt', quiet=True)
        nltk.download('stopwords', quiet=True)
        nltk.download('wordnet', quiet=True)
        nltk.download('averaged_perceptron_tagger', quiet=True)
        NLTK_AVAILABLE = True
    except Exception as e:
        print(f"Warning: Could not download NLTK data: {e}")
        NLTK_AVAILABLE = False
    
except ImportError as e:
    print(f"Missing required package: {e}")
    print("Please install with: pip install pandas numpy scikit-learn sentence-transformers nltk tqdm")
    print("Continuing with reduced functionality...")
    NLTK_AVAILABLE = False

# Configure logging with improved chardet debug routing
# Create file handler for all debug messages
file_handler = logging.FileHandler('file_metadata_system.log')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))

# Create console handler for INFO and above only
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.handlers.clear()
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Configure chardet to only log to file (prevents debug spam on console)
chardet_logger = logging.getLogger('chardet')
chardet_logger.setLevel(logging.DEBUG)
chardet_logger.propagate = False  # Don't send to parent loggers
chardet_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

class ProcessingStatus(Enum):
    """Status codes for file processing"""
    SUCCESS = "success"
    SKIPPED = "skipped"
    PERMISSION_DENIED = "permission_denied"
    FILE_NOT_FOUND = "file_not_found"
    ENCODING_ERROR = "encoding_error"
    SIZE_LIMIT_EXCEEDED = "size_limit_exceeded"
    TIMEOUT = "timeout"
    UNKNOWN_ERROR = "unknown_error"

@dataclass
class FileMetadata:
    """File metadata structure"""
    file_path: str
    file_name: str
    directory: str
    file_size: int
    file_type: str
    mime_type: str
    created_date: str
    modified_date: str
    accessed_date: str
    permissions: str
    file_hash: str
    is_text_file: bool
    encoding: Optional[str] = None
    processing_status: str = ProcessingStatus.SUCCESS.value
    error_message: Optional[str] = None

@dataclass
class ContentAnalysis:
    """Content analysis results structure"""
    file_path: str
    file_hash: str
    word_count: int
    char_count: int
    language: str
    topic_summary: str
    keywords: List[str]
    tfidf_keywords: List[Tuple[str, float]]
    lda_topics: List[Tuple[int, List[Tuple[str, float]]]]
    chunks: List[str]
    embeddings: List[List[float]]
    sentiment_score: Optional[float] = None
    processing_status: str = ProcessingStatus.SUCCESS.value
    error_message: Optional[str] = None

class GracefulInterruptHandler:
    """Handle graceful shutdown on interrupt signals"""
    
    def __init__(self):
        self.shutdown_requested = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        logger.info(f"Shutdown signal received: {signum}")
        self.shutdown_requested = True
    
    def should_shutdown(self) -> bool:
        return self.shutdown_requested

class CrossPlatformFileScanner:
    """Cross-platform file system scanner with enhanced error handling"""
    
    def __init__(self):
        self.system = platform.system()
        self.supported_text_extensions = {
            '.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.yml', '.yaml',
            '.csv', '.tsv', '.log', '.cfg', '.ini', '.conf', '.sh', '.bat', '.ps1',
            '.c', '.cpp', '.h', '.hpp', '.java', '.cs', '.php', '.rb', '.go', '.rs',
            '.sql', '.r', '.m', '.swift', '.kt', '.dart', '.scala', '.clj', '.hs',
            '.tex', '.rtf', '.org', '.rst', '.wiki'
        }
        self.max_file_size = 100 * 1024 * 1024  # 100MB
        self.encoding_detection_sample_size = 10000
    
    def get_file_permissions(self, file_path: Path) -> Tuple[str, Optional[str]]:
        """Get file permissions in a cross-platform way"""
        try:
            stat = file_path.stat()
            if self.system == "Windows":
                perms = []
                try:
                    if os.access(file_path, os.R_OK):
                        perms.append('r')
                    if os.access(file_path, os.W_OK):
                        perms.append('w')
                    if os.access(file_path, os.X_OK):
                        perms.append('x')
                    return ''.join(perms), None
                except PermissionError as e:
                    return "denied", str(e)
            else:
                # Unix-like systems
                try:
                    return oct(stat.st_mode)[-3:], None
                except (OSError, ValueError) as e:
                    return "unknown", str(e)
        except PermissionError as e:
            logger.warning(f"Permission denied getting permissions for {file_path}: {e}")
            return "denied", str(e)
        except Exception as e:
            logger.warning(f"Could not get permissions for {file_path}: {e}")
            return "unknown", str(e)
    
    def get_file_hash(self, file_path: Path, max_read_size: int = 10 * 1024 * 1024) -> Tuple[str, Optional[str]]:
        """Generate MD5 hash of file content with size limits. Log if skipped due to size, but do not warn in stdout."""
        try:
            file_size = file_path.stat().st_size
            if file_size > max_read_size:
                logger.info(f"File {file_path} skipped for hashing (too large: {file_size} bytes)")
                return "too_large", None

            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                bytes_read = 0
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
                    bytes_read += len(chunk)
                    if bytes_read > max_read_size:
                        break
            return hash_md5.hexdigest(), None
        except PermissionError as e:
            logger.warning(f"Permission denied hashing file {file_path}: {e}")
            return "permission_denied", str(e)
        except FileNotFoundError as e:
            logger.warning(f"File not found for hashing {file_path}: {e}")
            return "file_not_found", str(e)
        except Exception as e:
            logger.warning(f"Could not hash file {file_path}: {e}")
            return "error", str(e)
    
    def detect_text_encoding(self, file_path: Path) -> Tuple[Optional[str], Optional[str]]:
        """Detect text file encoding with fallback methods"""
        try:
            # Try chardet first if available
            try:
                import chardet
                with open(file_path, 'rb') as f:
                    raw_data = f.read(self.encoding_detection_sample_size)
                result = chardet.detect(raw_data)
                if result and result.get('confidence', 0) > 0.7:
                    return result.get('encoding', 'utf-8'), None
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"Chardet failed for {file_path}: {e}")
            
            # Fallback to common encodings
            for encoding in ['utf-8', 'latin-1', 'cp1252', 'ascii']:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        f.read(1000)  # Try to read first 1000 characters
                    return encoding, None
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    logger.debug(f"Encoding test failed for {file_path} with {encoding}: {e}")
                    continue
            
            return None, "Could not detect encoding"
        except PermissionError as e:
            return None, f"Permission denied: {e}"
        except Exception as e:
            return None, str(e)
    
    def is_text_file(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        """Determine if file is a text file with enhanced error handling"""
        try:
            # Check by extension first
            if file_path.suffix.lower() in self.supported_text_extensions:
                return True, None
            
            # Check MIME type
            try:
                mime_type, _ = mimetypes.guess_type(str(file_path))
                if mime_type and mime_type.startswith('text/'):
                    return True, None
            except Exception as e:
                logger.debug(f"MIME type detection failed for {file_path}: {e}")
            
            # Check file content (sample first 1024 bytes)
            try:
                with open(file_path, 'rb') as f:
                    sample = f.read(1024)
                
                # Check for binary markers
                if b'\x00' in sample:
                    return False, None
                
                # Try to decode as text
                for encoding in ['utf-8', 'latin-1']:
                    try:
                        sample.decode(encoding)
                        return True, None
                    except UnicodeDecodeError:
                        continue
                
                return False, None
            except PermissionError as e:
                return False, f"Permission denied: {e}"
            except Exception as e:
                return False, str(e)
        except Exception as e:
            return False, str(e)
    
    def extract_file_metadata(self, file_path: Path) -> FileMetadata:
        """Extract comprehensive file metadata with error handling"""
        error_message = None
        processing_status = ProcessingStatus.SUCCESS.value
        
        try:
            # Check if file still exists
            if not file_path.exists():
                raise FileNotFoundError(f"File no longer exists: {file_path}")
            
            # Get file stats
            try:
                stat = file_path.stat()
            except PermissionError as e:
                processing_status = ProcessingStatus.PERMISSION_DENIED.value
                error_message = str(e)
                # Create minimal metadata with defaults
                return FileMetadata(
                    file_path=str(file_path.resolve()),
                    file_name=file_path.name,
                    directory=str(file_path.parent.resolve()),
                    file_size=0,
                    file_type=file_path.suffix.lower(),
                    mime_type="unknown",
                    created_date="unknown",
                    modified_date="unknown",
                    accessed_date="unknown",
                    permissions="denied",
                    file_hash="permission_denied",
                    is_text_file=False,
                    encoding=None,
                    processing_status=processing_status,
                    error_message=error_message
                )
            
            # Check file size limits
            if stat.st_size > self.max_file_size:
                processing_status = ProcessingStatus.SIZE_LIMIT_EXCEEDED.value
                error_message = f"File too large: {stat.st_size} bytes"
                return FileMetadata(
                    file_path=str(file_path.resolve()),
                    file_name=file_path.name,
                    directory=str(file_path.parent.resolve()),
                    file_size=stat.st_size,
                    file_type=file_path.suffix.lower(),
                    mime_type="unknown",
                    created_date="unknown",
                    modified_date="unknown",
                    accessed_date="unknown",
                    permissions="unknown",
                    file_hash="too_large",
                    is_text_file=False,
                    encoding=None,
                    processing_status=processing_status,
                    error_message=error_message
                )
            
            # Get MIME type
            try:
                mime_type, _ = mimetypes.guess_type(str(file_path))
                mime_type = mime_type or "unknown"
            except Exception as e:
                mime_type = "unknown"
                logger.debug(f"MIME type detection failed for {file_path}: {e}")
            
            # Get permissions
            permissions, perm_error = self.get_file_permissions(file_path)
            if perm_error and processing_status == ProcessingStatus.SUCCESS.value:
                processing_status = ProcessingStatus.PERMISSION_DENIED.value
                error_message = perm_error
            
            # Get file hash
            file_hash, hash_error = self.get_file_hash(file_path)
            if hash_error and processing_status == ProcessingStatus.SUCCESS.value:
                if "permission" in hash_error.lower():
                    processing_status = ProcessingStatus.PERMISSION_DENIED.value
                else:
                    processing_status = ProcessingStatus.UNKNOWN_ERROR.value
                error_message = hash_error
            
            # Check if text file
            is_text, text_error = self.is_text_file(file_path)
            if text_error and processing_status == ProcessingStatus.SUCCESS.value:
                if "permission" in text_error.lower():
                    processing_status = ProcessingStatus.PERMISSION_DENIED.value
                else:
                    processing_status = ProcessingStatus.UNKNOWN_ERROR.value
                error_message = text_error
            
            # Get encoding if text file
            encoding = None
            if is_text:
                encoding, enc_error = self.detect_text_encoding(file_path)
                if enc_error and processing_status == ProcessingStatus.SUCCESS.value:
                    processing_status = ProcessingStatus.ENCODING_ERROR.value
                    error_message = enc_error
            
            # Get timestamps
            try:
                created_date = datetime.fromtimestamp(stat.st_ctime).isoformat()
                modified_date = datetime.fromtimestamp(stat.st_mtime).isoformat()
                accessed_date = datetime.fromtimestamp(stat.st_atime).isoformat()
            except (OSError, ValueError) as e:
                created_date = modified_date = accessed_date = "unknown"
                if processing_status == ProcessingStatus.SUCCESS.value:
                    processing_status = ProcessingStatus.UNKNOWN_ERROR.value
                    error_message = f"Timestamp error: {e}"
            
            return FileMetadata(
                file_path=str(file_path.resolve()),
                file_name=file_path.name,
                directory=str(file_path.parent.resolve()),
                file_size=stat.st_size,
                file_type=file_path.suffix.lower(),
                mime_type=mime_type,
                created_date=created_date,
                modified_date=modified_date,
                accessed_date=accessed_date,
                permissions=permissions,
                file_hash=file_hash,
                is_text_file=is_text,
                encoding=encoding,
                processing_status=processing_status,
                error_message=error_message
            )
            
        except FileNotFoundError as e:
            logger.warning(f"File not found: {file_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error extracting metadata for {file_path}: {e}")
            raise

class TextProcessor:
    """Advanced text processing and analysis with enhanced error handling"""
    
    def __init__(self):
        self.stop_words = set()
        self.lemmatizer = None
        self.sentence_model = None
        self.nltk_available = NLTK_AVAILABLE
        
        # Initialize components with error handling
        self._initialize_nltk_components()
        self._initialize_sentence_transformer()
    
    def _initialize_nltk_components(self):
        """Initialize NLTK components with error handling"""
        if not self.nltk_available:
            logger.warning("NLTK not available, text processing will be limited")
            return
        
        try:
            from nltk.corpus import stopwords
            from nltk.stem import WordNetLemmatizer
            
            self.stop_words = set(stopwords.words('english'))
            self.lemmatizer = WordNetLemmatizer()
            logger.info("NLTK components initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize NLTK components: {e}")
            self.nltk_available = False
    
    def _initialize_sentence_transformer(self):
        """Initialize sentence transformer with error handling"""
        try:
            self.sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Sentence transformer initialized successfully")
        except Exception as e:
            logger.warning(f"Could not load sentence transformer: {e}")
            self.sentence_model = None
    
    def safe_read_file(self, file_path: str, encoding: Optional[str] = None, max_size: int = 10 * 1024 * 1024) -> Tuple[Optional[str], Optional[str]]:
        """Safely read file content with multiple fallback strategies"""
        try:
            file_path_obj = Path(file_path)
            
            # Check file size
            if file_path_obj.stat().st_size > max_size:
                return None, f"File too large: {file_path_obj.stat().st_size} bytes"
            
            # Try with specified encoding first
            if encoding:
                try:
                    with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
                        return f.read(), None
                except Exception as e:
                    logger.debug(f"Failed to read {file_path} with encoding {encoding}: {e}")
            
            # Try common encodings
            for enc in ['utf-8', 'latin-1', 'cp1252', 'ascii']:
                try:
                    with open(file_path, 'r', encoding=enc, errors='ignore') as f:
                        content = f.read()
                        if content:  # Only return if we got content
                            return content, None
                except Exception as e:
                    logger.debug(f"Failed to read {file_path} with encoding {enc}: {e}")
                    continue
            
            # Last resort: read as bytes and decode with errors ignored
            try:
                with open(file_path, 'rb') as f:
                    raw_content = f.read()
                content = raw_content.decode('utf-8', errors='ignore')
                return content, None
            except Exception as e:
                return None, f"Could not read file: {e}"
            
        except PermissionError as e:
            return None, f"Permission denied: {e}"
        except FileNotFoundError as e:
            return None, f"File not found: {e}"
        except Exception as e:
            return None, f"Unexpected error reading file: {e}"
    
    def clean_text(self, text: str) -> str:
        """Clean and normalize text with error handling"""
        try:
            if not text:
                return ""
            
            # Remove extra whitespace
            text = re.sub(r'\s+', ' ', text)
            # Remove special characters but keep alphanumeric and common punctuation
            text = re.sub(r'[^\w\s\.\!\?\,\;\:\-\(\)]', '', text)
            # Convert to lowercase
            text = text.lower().strip()
            return text
        except Exception as e:
            logger.warning(f"Error cleaning text: {e}")
            return text[:1000] if text else ""  # Return truncated version as fallback
    
    def extract_keywords(self, text: str, max_keywords: int = 10) -> List[str]:
        """Extract keywords using basic NLP with error handling"""
        try:
            if not text or not self.nltk_available:
                # Fallback: simple word frequency
                words = text.lower().split()
                words = [word for word in words if len(word) > 2 and word.isalpha()]
                from collections import Counter
                word_freq = Counter(words)
                return [word for word, freq in word_freq.most_common(max_keywords)]
            
            words = word_tokenize(text.lower())
            # Filter out stop words and short words
            keywords = []
            for word in words:
                if (word.isalpha() and len(word) > 2 and 
                    word not in self.stop_words and self.lemmatizer):
                    try:
                        keywords.append(self.lemmatizer.lemmatize(word))
                    except:
                        keywords.append(word)
            
            # Count frequency and return top keywords
            from collections import Counter
            word_freq = Counter(keywords)
            return [word for word, freq in word_freq.most_common(max_keywords)]
        except Exception as e:
            logger.warning(f"Error extracting keywords: {e}")
            return []
    
    def chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        """Split text into overlapping chunks with error handling"""
        try:
            if not text:
                return []
            
            if len(text) <= chunk_size:
                return [text]
            
            chunks = []
            start = 0
            
            while start < len(text):
                end = start + chunk_size
                
                # Try to end at sentence boundary
                if end < len(text):
                    # Look for sentence ending in the last 100 characters
                    last_period = text.rfind('.', max(0, end - 100), end)
                    if last_period != -1:
                        end = last_period + 1
                
                chunk = text[start:end].strip()
                if chunk:
                    chunks.append(chunk)
                
                start = end - overlap
                if start >= len(text):
                    break
            
            return chunks
        except Exception as e:
            logger.warning(f"Error chunking text: {e}")
            return [text[:chunk_size]] if text else []
    
    def generate_topic_summary(self, text: str, max_length: int = 200) -> str:
        """Generate a topic summary using simple extractive method"""
        try:
            if not text:
                return "No content to summarize"
            
            if self.nltk_available:
                sentences = sent_tokenize(text)
            else:
                # Fallback: split on periods
                sentences = [s.strip() for s in text.split('.') if s.strip()]
            
            if not sentences:
                return text[:max_length]
            
            # Simple extractive summary - take first few sentences
            summary_sentences = []
            current_length = 0
            
            for sentence in sentences:
                if current_length + len(sentence) > max_length:
                    break
                summary_sentences.append(sentence)
                current_length += len(sentence)
            
            return ' '.join(summary_sentences) if summary_sentences else sentences[0][:max_length]
        except Exception as e:
            logger.warning(f"Error generating summary: {e}")
            return text[:max_length] if text else "No content to summarize"
    
    def extract_tfidf_keywords(self, texts: List[str], max_features: int = 1000) -> List[Tuple[str, float]]:
        """Extract TF-IDF keywords from text corpus with error handling"""
        try:
            if not texts:
                return []
            
            # Filter out empty texts
            texts = [text.strip() for text in texts if text.strip()]
            if not texts:
                return []
            
            # Create a new TfidfVectorizer for this specific corpus
            # Adjust max_features based on corpus size
            actual_max_features = min(max_features, len(' '.join(texts).split()))
            
            tfidf_vectorizer = TfidfVectorizer(
                max_features=actual_max_features,
                stop_words='english',
                ngram_range=(1, 2),
                min_df=1,  # Minimum document frequency
                max_df=0.95  # Maximum document frequency
            )
            
            # Fit and transform the texts
            tfidf_matrix = tfidf_vectorizer.fit_transform(texts)
            feature_names = tfidf_vectorizer.get_feature_names_out()
            
            # Get mean TF-IDF scores across all documents
            mean_scores = np.mean(tfidf_matrix.toarray(), axis=0)
            
            # Get top keywords (limit to available features)
            num_top_keywords = min(20, len(feature_names))
            top_indices = np.argsort(mean_scores)[-num_top_keywords:][::-1]
            
            return [(feature_names[i], float(mean_scores[i])) for i in top_indices]
            
        except Exception as e:
            logger.warning(f"TF-IDF extraction failed: {e}")
            return []
    
    def extract_lda_topics(self, texts: List[str], n_topics: int = 5) -> List[Tuple[int, List[Tuple[str, float]]]]:
        """Extract LDA topics from text corpus with error handling"""
        try:
            if not texts:
                return []
            
            # Filter out empty texts
            texts = [text.strip() for text in texts if text.strip()]
            if len(texts) < 2:  # Need at least 2 documents for LDA
                return []
            
            # Adjust number of topics based on corpus size
            # Rule of thumb: don't have more topics than documents
            actual_n_topics = min(n_topics, len(texts))
            
            # Create a new TfidfVectorizer for this specific corpus
            # For LDA, we typically want more features and less aggressive filtering
            vocab_size = len(set(' '.join(texts).split()))
            max_features = min(1000, vocab_size)
            
            tfidf_vectorizer = TfidfVectorizer(
                max_features=max_features,
                stop_words='english',
                ngram_range=(1, 2),
                min_df=1,  # At least in 1 document
                max_df=0.95  # At most in 95% of documents
            )
            
            # Fit TF-IDF matrix
            tfidf_matrix = tfidf_vectorizer.fit_transform(texts)
            
            # Check if we have enough features
            if tfidf_matrix.shape[1] == 0:
                logger.warning("No features extracted for LDA")
                return []
            
            # Create and fit LDA model
            lda_model = LatentDirichletAllocation(
                n_components=actual_n_topics,
                random_state=42,
                max_iter=10,
                learning_method='batch'
            )
            
            lda_model.fit(tfidf_matrix)
            feature_names = tfidf_vectorizer.get_feature_names_out()
            
            # Extract topics
            topics = []
            for topic_idx, topic in enumerate(lda_model.components_):
                # Get top words for this topic
                num_top_words = min(10, len(feature_names))
                top_words_idx = topic.argsort()[-num_top_words:][::-1]
                
                # Ensure indices are within bounds
                top_words_idx = [idx for idx in top_words_idx if idx < len(feature_names)]
                
                top_words = [(feature_names[i], float(topic[i])) for i in top_words_idx]
                topics.append((topic_idx, top_words))
            
            return topics
            
        except Exception as e:
            logger.warning(f"LDA topic extraction failed: {e}")
            return []
    
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate sentence embeddings with error handling"""
        try:
            if not self.sentence_model or not texts:
                return []
            
            # Filter out empty texts
            texts = [text for text in texts if text.strip()]
            if not texts:
                return []
            
            embeddings = self.sentence_model.encode(texts)
            return embeddings.tolist()
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return []
    
    def analyze_content(self, file_path: str, content: str) -> ContentAnalysis:
        """Perform comprehensive content analysis with error handling"""
        processing_status = ProcessingStatus.SUCCESS.value
        error_message = None
        
        try:
            if not content:
                processing_status = ProcessingStatus.UNKNOWN_ERROR.value
                error_message = "No content to analyze"
                return ContentAnalysis(
                    file_path=file_path,
                    file_hash=hashlib.md5(b"").hexdigest(),
                    word_count=0,
                    char_count=0,
                    language='unknown',
                    topic_summary="No content to analyze",
                    keywords=[],
                    tfidf_keywords=[],
                    lda_topics=[],
                    chunks=[],
                    embeddings=[],
                    processing_status=processing_status,
                    error_message=error_message
                )
            
            # Basic statistics
            word_count = len(content.split())
            char_count = len(content)
            
            # Clean content
            try:
                clean_content = self.clean_text(content)
            except Exception as e:
                logger.warning(f"Error cleaning content for {file_path}: {e}")
                clean_content = content[:1000]  # Fallback
            
            # Extract features with error handling
            try:
                keywords = self.extract_keywords(clean_content)
            except Exception as e:
                logger.warning(f"Error extracting keywords for {file_path}: {e}")
                keywords = []
            
            try:
                topic_summary = self.generate_topic_summary(content)
            except Exception as e:
                logger.warning(f"Error generating summary for {file_path}: {e}")
                topic_summary = content[:200] if content else "No content"
            
            try:
                chunks = self.chunk_text(content)
            except Exception as e:
                logger.warning(f"Error chunking text for {file_path}: {e}")
                chunks = [content[:1000]] if content else []
            
            # Generate embeddings for chunks
            try:
                embeddings = self.generate_embeddings(chunks) if chunks else []
            except Exception as e:
                logger.warning(f"Error generating embeddings for {file_path}: {e}")
                embeddings = []
            
            # For TF-IDF and LDA, process the chunks as separate documents
            tfidf_keywords = []
            lda_topics = []
            
            if chunks and len(chunks) > 1:
                try:
                    # Extract TF-IDF keywords from chunks
                    tfidf_keywords = self.extract_tfidf_keywords(chunks)
                except Exception as e:
                    logger.warning(f"Error extracting TF-IDF keywords for {file_path}: {e}")
                    tfidf_keywords = []
                
                try:
                    # Extract LDA topics from chunks
                    lda_topics = self.extract_lda_topics(chunks)
                except Exception as e:
                    logger.warning(f"Error extracting LDA topics for {file_path}: {e}")
                    lda_topics = []
            
            return ContentAnalysis(
                file_path=file_path,
                file_hash=hashlib.md5(content.encode('utf-8', errors='ignore')).hexdigest(),
                word_count=word_count,
                char_count=char_count,
                language='en',  # Simple assumption - could be enhanced
                topic_summary=topic_summary,
                keywords=keywords,
                tfidf_keywords=tfidf_keywords,
                lda_topics=lda_topics,
                chunks=chunks,
                embeddings=embeddings,
                processing_status=processing_status,
                error_message=error_message
            )
        except Exception as e:
            logger.error(f"Unexpected error analyzing content for {file_path}: {e}")
            processing_status = ProcessingStatus.UNKNOWN_ERROR.value
            error_message = str(e)
            
            return ContentAnalysis(
                file_path=file_path,
                file_hash="error",
                word_count=0,
                char_count=0,
                language='unknown',
                topic_summary="Error during analysis",
                keywords=[],
                tfidf_keywords=[],
                lda_topics=[],
                chunks=[],
                embeddings=[],
                processing_status=processing_status,
                error_message=error_message
            )
class DatabaseManager:
    """SQLite database manager with enhanced error handling and connection pooling"""

    def __init__(self, db_path: str = "file_metadata.db"):
        self.db_path = db_path
        self.connection_timeout = 30  # seconds
        self.max_retries = 5  # Increased for better reliability
        self.retry_delay = 0.5  # Reduced delay for faster retries
        self._local = threading.local()  # Thread-local storage for connections
        self._connection_lock = threading.Lock()  # Lock for connection management

        # Create database directory if it doesn't exist
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self.init_database()
    
    def get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection with retry logic"""
        # Check if we already have a connection for this thread
        if hasattr(self._local, 'connection') and self._local.connection:
            try:
                # Test the connection
                self._local.connection.execute("SELECT 1")
                return self._local.connection
            except sqlite3.Error:
                # Connection is stale, remove it
                try:
                    self._local.connection.close()
                except:
                    pass
                self._local.connection = None

        # Create new connection for this thread
        for attempt in range(self.max_retries):
            try:
                with self._connection_lock:  # Serialize connection creation
                    conn = sqlite3.connect(
                        self.db_path,
                        timeout=self.connection_timeout,
                        check_same_thread=False
                    )
                    conn.execute("PRAGMA journal_mode=WAL")  # Enable WAL mode for better concurrency
                    conn.execute("PRAGMA synchronous=NORMAL")  # Balance between safety and performance
                    conn.execute("PRAGMA busy_timeout=5000")  # 5 second timeout for locks

                    # Store in thread-local storage
                    self._local.connection = conn
                    return conn

            except sqlite3.OperationalError as e:
                if ("database is locked" in str(e).lower() or "database is busy" in str(e).lower()) and attempt < self.max_retries - 1:
                    # Add exponential backoff
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(f"Database locked/busy, retrying in {wait_time:.1f} seconds... (attempt {attempt + 1}/{self.max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    raise
            except Exception as e:
                logger.error(f"Database connection error: {e}")
                raise

        raise sqlite3.OperationalError("Could not connect to database after retries")

    def close_connection(self):
        """Close the thread-local connection"""
        if hasattr(self._local, 'connection') and self._local.connection:
            try:
                self._local.connection.close()
            except:
                pass
            self._local.connection = None

    def execute_with_retry(self, operation_func, *args, **kwargs):
        """Execute database operation with retry logic for locked database"""
        for attempt in range(self.max_retries):
            try:
                return operation_func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                if ("database is locked" in str(e).lower() or "database is busy" in str(e).lower()) and attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(f"Database operation failed (locked/busy), retrying in {wait_time:.1f} seconds... (attempt {attempt + 1}/{self.max_retries})")
                    time.sleep(wait_time)
                    # Close and recreate connection on retry
                    self.close_connection()
                    continue
                else:
                    raise
            except Exception as e:
                logger.error(f"Database operation error: {e}")
                raise

        raise sqlite3.OperationalError("Database operation failed after retries")

    def init_database(self):
        """Initialize database tables with error handling"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # File metadata table (file_path as primary key, overwrite on conflict)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS file_metadata (
                        file_path TEXT PRIMARY KEY,
                        file_name TEXT NOT NULL,
                        directory TEXT NOT NULL,
                        file_size INTEGER NOT NULL,
                        file_type TEXT,
                        mime_type TEXT,
                        created_date TEXT,
                        modified_date TEXT,
                        accessed_date TEXT,
                        permissions TEXT,
                        file_hash TEXT,
                        is_text_file BOOLEAN,
                        encoding TEXT,
                        processing_status TEXT DEFAULT 'success',
                        error_message TEXT,
                        indexed_date TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                # ...existing code...
                # Directory structure table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS directory_structure (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        directory_path TEXT UNIQUE NOT NULL,
                        parent_directory TEXT,
                        file_count INTEGER DEFAULT 0,
                        total_size INTEGER DEFAULT 0,
                        last_updated TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Content analysis table (add processing_time_seconds for per-file timing)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS content_analysis (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_path TEXT NOT NULL,
                        file_hash TEXT NOT NULL,
                        word_count INTEGER,
                        char_count INTEGER,
                        language TEXT,
                        topic_summary TEXT,
                        keywords TEXT,  -- JSON array
                        tfidf_keywords TEXT,  -- JSON array
                        lda_topics TEXT,  -- JSON array
                        sentiment_score REAL,
                        processing_status TEXT DEFAULT 'success',
                        error_message TEXT,
                        analysis_date TEXT DEFAULT CURRENT_TIMESTAMP,
                        processing_time_seconds REAL,
                        FOREIGN KEY (file_path) REFERENCES file_metadata (file_path)
                    )
                ''')
                
                # Text chunks table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS text_chunks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_path TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        chunk_text TEXT NOT NULL,
                        chunk_embedding BLOB,  -- Store as binary
                        FOREIGN KEY (file_path) REFERENCES file_metadata (file_path)
                    )
                ''')
                
                # Embeddings index table for FAISS (self-documenting, stores chunk embeddings as JSON arrays)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS embeddings_index (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_path TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        embedding TEXT NOT NULL, -- JSON array of floats
                        metadata TEXT,
                        FOREIGN KEY (file_path) REFERENCES file_metadata (file_path)
                    )
                ''')
                # Processing statistics table (add missing columns for full status reporting)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS processing_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        total_files INTEGER,
                        successful_files INTEGER,
                        failed_files INTEGER,
                        permission_denied_files INTEGER,
                        size_limit_exceeded_files INTEGER,
                        encoding_error_files INTEGER,
                        file_not_found_files INTEGER,
                        timeout_files INTEGER,
                        unknown_error_files INTEGER,
                        start_time TEXT,
                        end_time TEXT,
                        duration_seconds REAL
                    )
                ''')
                
                # Create indexes for better search performance
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_path ON file_metadata(file_path)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_type ON file_metadata(file_type)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_directory ON file_metadata(directory)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_processing_status ON file_metadata(processing_status)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_content_file_path ON content_analysis(file_path)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON text_chunks(file_path)')
                
                # Enable FTS for full-text search
                cursor.execute('''
                    CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
                        file_path,
                        content,
                        content_id UNINDEXED
                    )
                ''')
                
                conn.commit()
                logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
    
    def insert_file_metadata(self, metadata: FileMetadata):
        """Insert file metadata into database with retry logic"""
        def _insert_operation():
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO file_metadata (
                        file_path, file_name, directory, file_size, file_type,
                        mime_type, created_date, modified_date, accessed_date,
                        permissions, file_hash, is_text_file, encoding,
                        processing_status, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    metadata.file_path, metadata.file_name, metadata.directory,
                    metadata.file_size, metadata.file_type, metadata.mime_type,
                    metadata.created_date, metadata.modified_date, metadata.accessed_date,
                    metadata.permissions, metadata.file_hash, metadata.is_text_file,
                    metadata.encoding, metadata.processing_status, metadata.error_message
                ))
                conn.commit()

        try:
            self.execute_with_retry(_insert_operation)
        except Exception as e:
            logger.error(f"Error inserting file metadata for {metadata.file_path}: {e}")
            raise RuntimeError(f"Failed to insert file metadata for {metadata.file_path}: {e}") from e

    def get_file_modified_date(self, file_path: str) -> str:
        """Get the modified_date for a file by file_path (returns '' if not found)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT modified_date FROM file_metadata WHERE file_path = ?', (file_path,))
                row = cursor.fetchone()
                if row and row[0]:
                    return row[0]
                return ''
        except Exception as e:
            logger.error(f"Error getting modified_date for {file_path}: {e}")
            return ''
    
    def insert_content_analysis(self, analysis: ContentAnalysis, processing_time_seconds: float = None):
        """Insert content analysis into database with retry logic"""
        def _insert_operation():
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Insert main content analysis
                cursor.execute('''
                    INSERT OR REPLACE INTO content_analysis (
                        file_path, file_hash, word_count, char_count, language,
                        topic_summary, keywords, tfidf_keywords, lda_topics,
                        sentiment_score, processing_status, error_message, processing_time_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    analysis.file_path, analysis.file_hash, analysis.word_count,
                    analysis.char_count, analysis.language, analysis.topic_summary,
                    json.dumps(analysis.keywords), json.dumps(analysis.tfidf_keywords),
                    json.dumps(analysis.lda_topics), analysis.sentiment_score,
                    analysis.processing_status, analysis.error_message,
                    processing_time_seconds
                ))
                # Insert text chunks
                cursor.execute('DELETE FROM text_chunks WHERE file_path = ?', (analysis.file_path,))
                cursor.execute('DELETE FROM embeddings_index WHERE file_path = ?', (analysis.file_path,))
                for i, chunk in enumerate(analysis.chunks):
                    embedding_blob = None
                    if i < len(analysis.embeddings):
                        try:
                            embedding_blob = np.array(analysis.embeddings[i]).tobytes()
                            # Also insert into embeddings_index as JSON array for FAISS
                            embedding_json = json.dumps(analysis.embeddings[i])
                            cursor.execute('''
                                INSERT INTO embeddings_index (file_path, chunk_index, embedding, metadata)
                                VALUES (?, ?, ?, ?)
                            ''', (analysis.file_path, i, embedding_json, None))
                        except Exception as e:
                            logger.warning(f"Error serializing embedding for chunk {i}: {e}")
                    cursor.execute('''
                        INSERT INTO text_chunks (file_path, chunk_index, chunk_text, chunk_embedding)
                        VALUES (?, ?, ?, ?)
                    ''', (analysis.file_path, i, chunk, embedding_blob))
                # Insert into FTS table
                cursor.execute('DELETE FROM content_fts WHERE file_path = ?', (analysis.file_path,))
                if analysis.chunks:
                    full_content = ' '.join(analysis.chunks)
                    cursor.execute('''
                        INSERT INTO content_fts (file_path, content, content_id)
                        VALUES (?, ?, ?)
                    ''', (analysis.file_path, full_content, analysis.file_hash))
                conn.commit()

        try:
            self.execute_with_retry(_insert_operation)
        except Exception as e:
            logger.error(f"Error inserting content analysis for {analysis.file_path}: {e}")
            raise RuntimeError(f"Failed to insert content analysis for {analysis.file_path}: {e}") from e
    
    def update_directory_stats(self, directory_path: str) -> bool:
        """Update directory statistics with error handling"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get file count and total size for directory
                cursor.execute('''
                    SELECT COUNT(*), COALESCE(SUM(file_size), 0)
                    FROM file_metadata
                    WHERE directory = ?
                ''', (directory_path,))
                
                result = cursor.fetchone()
                if result:
                    file_count, total_size = result
                    
                    cursor.execute('''
                        INSERT OR REPLACE INTO directory_structure (
                            directory_path, file_count, total_size, last_updated
                        ) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ''', (directory_path, file_count, total_size))
                    
                    conn.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"Error updating directory stats for {directory_path}: {e}")
            return False
    
    def record_processing_stats(self, session_id: str, stats: Dict[str, Any]) -> bool:
        """Record processing statistics"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO processing_stats (
                        session_id, total_files, successful_files, failed_files,
                        permission_denied_files, size_limit_exceeded_files,
                        encoding_error_files, file_not_found_files, timeout_files, unknown_error_files,
                        start_time, end_time, duration_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session_id, stats.get('total_files', 0), stats.get('successful_files', 0),
                    stats.get('failed_files', 0), stats.get('permission_denied_files', 0),
                    stats.get('size_limit_exceeded_files', 0), stats.get('encoding_error_files', 0),
                    stats.get('file_not_found_files', 0), stats.get('timeout_files', 0), stats.get('unknown_error_files', 0),
                    stats.get('start_time'), stats.get('end_time'), stats.get('duration_seconds', 0)
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error recording processing stats: {e}")
            return False

class FileMetadataExtractor:
    """Main file metadata extraction orchestrator with enhanced error handling"""

    def __init__(self, db_path: str = "file_metadata.db"):
        self.scanner = CrossPlatformFileScanner()
        self.text_processor = TextProcessor()
        self.db_manager = DatabaseManager(db_path)
        self.thread_lock = threading.Lock()
        self.interrupt_handler = GracefulInterruptHandler()

        # File descriptor management
        # Limit concurrent file operations to prevent EMFILE errors
        # Use a conservative limit to avoid overwhelming the system
        self.file_semaphore = threading.Semaphore(50)  # Max 50 concurrent file operations

        # Statistics tracking
        self.stats = {
            'total_files': 0,
            'successful_files': 0,
            'failed_files': 0,
            'permission_denied_files': 0,
            'size_limit_exceeded_files': 0,
            'encoding_error_files': 0,
            'file_not_found_files': 0,
            'timeout_files': 0,
            'unknown_error_files': 0
        }

    def _file_operation_context(self):
        """Context manager for file operations with semaphore"""
        return self.file_semaphore

    def is_hidden_path(self, path: Path) -> bool:
        """Check if a path (file or directory) is hidden"""
        try:
            # Check if any part of the path is hidden
            for part in path.parts:
                if part.startswith('.') and part not in {'.', '..'}:
                    return True
            
            # On Windows, also check file attributes
            if platform.system() == "Windows":
                try:
                    import stat
                    file_stat = path.stat()
                    # Check if hidden attribute is set (Windows FILE_ATTRIBUTE_HIDDEN = 2)
                    if hasattr(file_stat, 'st_file_attributes'):
                        return bool(file_stat.st_file_attributes & 2)
                except:
                    pass
            
            return False
        except Exception:
            # If we can't determine, assume it's not hidden
            return False
    
    def should_skip_directory(self, dir_path: Path) -> Tuple[bool, str]:
        """Determine if a directory should be skipped entirely"""
        try:
            # Skip hidden directories
            if self.is_hidden_path(dir_path):
                return True, "Hidden directory"
            
            # Skip system directories
            system_dirs = {
                '.git', '.svn', '.hg', '.bzr',  # Version control
                '__pycache__', '.pytest_cache', '.tox',  # Python
                'node_modules', '.npm', '.yarn',  # JavaScript
                '.vscode', '.idea', '.vs',  # IDEs
                'venv', '.venv', 'env', '.env',  # Python virtual environments
                'build', 'dist', '.build', '.dist',  # Build artifacts
                'target',  # Rust, Java build directory
                'bin', 'obj',  # C# build directories
                '.gradle', '.mvn',  # Java build tools
                'vendor',  # Various package managers
                'Thumbs.db', '.DS_Store'  # System files (though these are files, not dirs)
            }
            
            if dir_path.name in system_dirs:
                return True, "System directory"
            
            # Skip very deep nested directories (potential infinite recursion protection)
            if len(dir_path.parts) > 20:
                return True, "Directory too deep"
            
            return False, "OK"
        except Exception as e:
            return False, f"Error checking directory: {e}"
    
    def discover_files(self, directory_path: Path) -> List[Path]:
        """Discover all files in directory, excluding hidden and system files/directories."""
        all_files = []

        def _scan_directory(current_dir: Path, depth: int = 0) -> None:
            if depth > 20:
                return
            if self.interrupt_handler.should_shutdown():
                return
            try:
                should_skip, reason = self.should_skip_directory(current_dir)
                if should_skip:
                    logger.debug(f"Skipping directory {current_dir}: {reason}")
                    return
                try:
                    entries = list(current_dir.iterdir())
                except (OSError, PermissionError) as e:
                    logger.debug(f"Could not list directory {current_dir}: {e}")
                    return
                for entry in entries:
                    if self.interrupt_handler.should_shutdown():
                        return
                    try:
                        if self.is_hidden_path(entry):
                            logger.debug(f"Skipping hidden path: {entry}")
                            continue
                        if entry.is_file():
                            if not self.should_skip_file(entry):
                                all_files.append(entry)
                        elif entry.is_dir():
                            _scan_directory(entry, depth + 1)
                    except (OSError, PermissionError) as e:
                        logger.debug(f"Could not access {entry}: {e}")
                        continue
                    except Exception as e:
                        logger.debug(f"Unexpected error accessing {entry}: {e}")
                        continue
            except Exception as e:
                logger.warning(f"Error scanning directory {current_dir}: {e}")

        _scan_directory(directory_path)
        return all_files
    
    def should_skip_file(self, file_path: Path) -> bool:
        """Determine if a file should be skipped during discovery"""
        try:
            # Skip very large files (>100MB) early
            try:
                if file_path.stat().st_size > 100 * 1024 * 1024:
                    return True
            except (OSError, PermissionError):
                # If we can't get stats, we'll let the later processing handle it
                pass
            
            # Skip specific file types that are typically not useful
            skip_extensions = {
                '.exe', '.dll', '.so', '.dylib',  # Executables and libraries
                '.bin', '.dat', '.db', '.sqlite',  # Binary data files
                '.img', '.iso', '.dmg',  # Disk images
                '.zip', '.rar', '.7z', '.tar', '.gz',  # Archives
                '.mp4', '.avi', '.mkv', '.mov',  # Video files
                '.mp3', '.wav', '.flac', '.aac',  # Audio files
                '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff',  # Image files
                '.xls', '.xlsx', '.ppt', '.pptx',  # Office documents
                '.lock', '.tmp', '.temp', '.cache'  # Temporary files
            }
            
            if file_path.suffix.lower() in skip_extensions:
                return True
            
            # Skip files with certain patterns
            skip_patterns = {
                'thumbs.db', '.ds_store', 'desktop.ini',  # System files
                '.gitkeep', '.gitignore', '.gitmodules',  # Git files
                'package-lock.json', 'yarn.lock',  # Lock files
                '.env', '.env.local', '.env.production'  # Environment files
            }
            
            if file_path.name.lower() in skip_patterns:
                return True
            
            return False
        except Exception:
            return False
    
    def should_process_file(self, file_path: Path) -> Tuple[bool, str]:
        """Determine if file should be processed with detailed reasoning"""
        try:
            # Check for shutdown signal
            if self.interrupt_handler.should_shutdown():
                return False, "Shutdown requested"
            
            # At this point, hidden files should already be filtered out
            # But let's double-check as a safety measure
            if self.is_hidden_path(file_path):
                return False, "Hidden file"
            
            # Check if file exists
            if not file_path.exists():
                return False, "File does not exist"
            
            # Check if it's actually a file
            if not file_path.is_file():
                return False, "Not a file"
            
            # File-level skip checks (this was already done in discovery, but kept for safety)
            if self.should_skip_file(file_path):
                return False, "File type excluded"
            
            return True, "OK"
        except Exception as e:
            return False, f"Error checking file: {e}"
    
    def process_single_file(self, file_path: Path, force: bool = False) -> ProcessingStatus:
        try:
            import setproctitle
            setproctitle.setproctitle(f"file_metadata_content.py-worker-{file_path.name}")
        except Exception:
            pass
        """Process a single file with comprehensive error handling and file descriptor management"""

        # Use semaphore to limit concurrent file operations
        with self._file_operation_context():
            try:
                # Check if we should process this file
                should_process, reason = self.should_process_file(file_path)
                if not should_process:
                    logger.debug(f"Skipping {file_path}: {reason}")
                    return ProcessingStatus.SKIPPED

                # Check if file has changed (unless force)
                if not force:
                    db_mod = self.db_manager.get_file_modified_date(str(file_path.resolve()))
                    try:
                        fs_mod = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                    except Exception:
                        fs_mod = ''
                    if db_mod and fs_mod and db_mod == fs_mod:
                        logger.debug(f"Skipping unchanged file: {file_path}")
                        return ProcessingStatus.SKIPPED

                # Extract file metadata (file operations are protected by semaphore inside)
                try:
                    metadata = self.scanner.extract_file_metadata(file_path)
                except FileNotFoundError:
                    logger.warning(f"File not found during processing: {file_path}")
                    return ProcessingStatus.FILE_NOT_FOUND
                except PermissionError:
                    logger.warning(f"Permission denied accessing: {file_path}")
                    return ProcessingStatus.PERMISSION_DENIED
                except Exception as e:
                    logger.error(f"Error extracting metadata for {file_path}: {e}")
                    return ProcessingStatus.UNKNOWN_ERROR

                # Insert metadata (database operations have their own retry logic)
                self.db_manager.insert_file_metadata(metadata)

                # If file was too large, stop here so the status is counted correctly
                if metadata.processing_status == ProcessingStatus.SIZE_LIMIT_EXCEEDED.value:
                    return ProcessingStatus.SIZE_LIMIT_EXCEEDED

                # Process text content for text, PDF, and DOCX files
                try:
                    import time
                    start_time = time.time()
                    content = None
                    read_error = None
                    file_ext = file_path.suffix.lower()

                    # Use unpackers for PDF and DOCX
                    if file_ext == '.pdf':
                        try:
                            from file_unpackers.pdf_unpacker import extract_text_from_pdf
                            content = extract_text_from_pdf(file_path)
                        except Exception as e:
                            read_error = str(e)
                    elif file_ext == '.docx':
                        try:
                            from file_unpackers.docx_unpacker import extract_text_from_docx
                            content = extract_text_from_docx(file_path)
                        except Exception as e:
                            read_error = str(e)
                    elif metadata.is_text_file and metadata.processing_status == ProcessingStatus.SUCCESS.value:
                        # File reading is already protected by semaphore in safe_read_file
                        content, read_error = self.text_processor.safe_read_file(
                            str(file_path),
                            metadata.encoding
                        )

                    if read_error:
                        logger.warning(f"Could not read content for {file_path}: {read_error}")
                        if "permission" in read_error.lower():
                            return ProcessingStatus.PERMISSION_DENIED
                        elif "encoding" in read_error.lower():
                            return ProcessingStatus.ENCODING_ERROR
                        else:
                            return ProcessingStatus.UNKNOWN_ERROR

                    if content:
                        # Analyze content
                        analysis = self.text_processor.analyze_content(str(file_path), content)

                        # Insert content analysis with timing (database operations have their own retry logic)
                        processing_time = time.time() - start_time
                        self.db_manager.insert_content_analysis(analysis, processing_time_seconds=processing_time)

                except Exception as e:
                    logger.warning(f"Error processing content for {file_path}: {e}")
                    return ProcessingStatus.UNKNOWN_ERROR

                # Return the status from metadata processing
                return ProcessingStatus(metadata.processing_status)

            except Exception as e:
                logger.error(f"Unexpected error processing file {file_path}: {e}")
                return ProcessingStatus.UNKNOWN_ERROR
    
    def scan_directory(self, directory_path: str, max_workers: int = 4, force: bool = False) -> Dict[str, Any]:
        # Limit max workers to prevent resource exhaustion
        max_workers = min(max_workers, 8)  # Cap at 8 workers maximum
        try:
            import setproctitle
            setproctitle.setproctitle("file_metadata_content.py-thread-manager")
        except Exception:
            pass
        """Scan directory and extract metadata with comprehensive error handling, support --force and skip unchanged"""
        start_time = datetime.now()
        session_id = f"scan_{int(start_time.timestamp())}"

        try:
            directory_path = Path(directory_path).resolve()

            if not directory_path.exists():
                raise ValueError(f"Directory does not exist: {directory_path}")

            if not directory_path.is_dir():
                raise ValueError(f"Path is not a directory: {directory_path}")

            # Test database connectivity before starting any file processing
            logger.info("Testing database connectivity...")
            try:
                with self.db_manager.get_connection() as conn:
                    conn.execute("SELECT 1")
                logger.info("Database connectivity confirmed")
            except Exception as e:
                raise RuntimeError(f"Database connectivity failed: {e}")

            logger.info(f"Scanning directory: {directory_path}")

            # Discover files (this now excludes hidden files and directories)
            logger.info("Discovering files...")
            all_files = self.discover_files(directory_path)

            logger.info(f"Found {len(all_files)} files to process (hidden files/directories excluded)")

            # Reset statistics
            self.stats = {key: 0 for key in self.stats}
            self.stats['total_files'] = len(all_files)

            if len(all_files) == 0:
                logger.warning("No files found to process")
                return {
                    **self.stats,
                    'directories_updated': 0,
                    'session_id': session_id,
                    'duration_seconds': 0,
                    'interrupted': False
                }

            # Process files in parallel with robust shutdown handling
            import concurrent.futures
            executor = ThreadPoolExecutor(max_workers=max_workers)
            future_to_file = {
                executor.submit(self.process_single_file, file_path, force): file_path
                for file_path in all_files
            }
            try:
                for future in tqdm(as_completed(future_to_file), total=len(all_files), desc="Processing files"):
                    if self.interrupt_handler.should_shutdown():
                        logger.info("Shutdown requested, cancelling remaining tasks and shutting down executor")
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                    file_path = future_to_file[future]
                    try:
                        status = future.result()

                        # Update statistics
                        if status == ProcessingStatus.SUCCESS:
                            self.stats['successful_files'] += 1
                        elif status == ProcessingStatus.PERMISSION_DENIED:
                            self.stats['permission_denied_files'] += 1
                        elif status == ProcessingStatus.SIZE_LIMIT_EXCEEDED:
                            self.stats['size_limit_exceeded_files'] += 1
                        elif status == ProcessingStatus.ENCODING_ERROR:
                            self.stats['encoding_error_files'] += 1
                        elif status == ProcessingStatus.FILE_NOT_FOUND:
                            self.stats['file_not_found_files'] += 1
                        elif status == ProcessingStatus.TIMEOUT:
                            self.stats['timeout_files'] += 1
                        elif status == ProcessingStatus.SKIPPED:
                            # Don't count skipped files as failures
                            pass
                        else:
                            self.stats['unknown_error_files'] += 1

                        if status != ProcessingStatus.SUCCESS and status != ProcessingStatus.SKIPPED:
                            self.stats['failed_files'] += 1

                    except Exception as e:
                        logger.error(f"Error processing {file_path}: {e}")
                        self.stats['failed_files'] += 1
                        self.stats['unknown_error_files'] += 1
            except (KeyboardInterrupt, SystemExit):
                logger.info("Main process interrupted, shutting down executor and cancelling futures")
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
                # Clean up database connections
                self.db_manager.close_connection()

            # Update directory statistics (only for directories that contain processed files)
            directories = set()
            for file_path in all_files:
                try:
                    parent_dir = str(file_path.parent)
                    # Only include directories that aren't hidden
                    if not self.is_hidden_path(file_path.parent):
                        directories.add(parent_dir)
                except Exception as e:
                    logger.debug(f"Could not get parent directory for {file_path}: {e}")

            directories_updated = 0
            for directory in directories:
                if self.db_manager.update_directory_stats(directory):
                    directories_updated += 1

            # Record processing statistics
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            processing_stats = {
                **self.stats,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'duration_seconds': duration
            }

            self.db_manager.record_processing_stats(session_id, processing_stats)

            results = {
                **self.stats,
                'directories_updated': directories_updated,
                'session_id': session_id,
                'duration_seconds': duration,
                'interrupted': self.interrupt_handler.should_shutdown()
            }

            logger.info(f"Scan complete: {results}")
            return results

        except Exception as e:
            logger.error(f"Error during directory scan: {e}")
            raise

def main():
    try:
        import setproctitle
        setproctitle.setproctitle("file_metadata_content.py-main")
    except Exception:
        pass
    """Main function for CLI usage with enhanced error handling"""
    import argparse
    
    parser = argparse.ArgumentParser(description="File Metadata and Content Analysis System")
    parser.add_argument("directory", help="Directory to scan")
    parser.add_argument("--db", default="file_metadata.db", help="Database file path")
    parser.add_argument("--workers", type=int, default=4, help="Number of worker threads")
    parser.add_argument("--force", action="store_true", help="Force rescan all files even if unchanged/in database")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--debug", action="store_true", help="Debug logging")

    args = parser.parse_args()

    # Configure logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.verbose:
        logging.getLogger().setLevel(logging.INFO)
    else:
        logging.getLogger().setLevel(logging.WARNING)

    try:
        # Create extractor and scan directory
        extractor = FileMetadataExtractor(args.db)
        results = extractor.scan_directory(args.directory, args.workers, force=args.force)


        # Fetch processing stats for this session from the database
        extractor = FileMetadataExtractor(args.db)
        session_id = results['session_id']
        stats = None
        try:
            with extractor.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT total_files, successful_files, failed_files, permission_denied_files, size_limit_exceeded_files, encoding_error_files, file_not_found_files, timeout_files, unknown_error_files, start_time, end_time, duration_seconds
                    FROM processing_stats WHERE session_id = ? ORDER BY id DESC LIMIT 1
                ''', (session_id,))
                row = cursor.fetchone()
                if row:
                    stats = {
                        'total_files': row[0],
                        'successful_files': row[1],
                        'failed_files': row[2],
                        'permission_denied_files': row[3],
                        'size_limit_exceeded_files': row[4],
                        'encoding_error_files': row[5],
                        'file_not_found_files': row[6],
                        'timeout_files': row[7],
                        'unknown_error_files': row[8],
                        'start_time': row[9],
                        'end_time': row[10],
                        'duration_seconds': row[11],
                    }
        except Exception as e:
            print(f"Warning: Could not fetch processing stats from DB: {e}")

        # Use DB stats if available, else fallback to in-memory
        s = stats if stats else results

        print(f"\nScan Results:")
        print(f"Session ID: {session_id}")
        print(f"Total files: {s['total_files']}")
        print(f"Successful files: {s['successful_files']}")
        print(f"Failed files: {s['failed_files']}")
        print(f"  - Permission denied: {s['permission_denied_files']}")
        print(f"  - Size limit exceeded: {s['size_limit_exceeded_files']}")
        print(f"  - Encoding errors: {s['encoding_error_files']}")
        print(f"  - File not found: {s['file_not_found_files']}")
        print(f"  - Timeout: {s['timeout_files']}")
        print(f"  - Unknown errors: {s['unknown_error_files']}")
        print(f"Duration: {s['duration_seconds']:.2f} seconds")

        if results['interrupted']:
            print("⚠️  Scan was interrupted")
            sys.exit(1)

        # Only consider actually processed files (not skipped) for success rate
        processed_files = s['successful_files'] + s['failed_files']
        success_rate = (s['successful_files'] / processed_files * 100) if processed_files > 0 else 0
        print(f"Success rate (of processed files): {success_rate:.1f}%")

        if processed_files > 0 and success_rate < 50:
            print("⚠️  Low success rate for processed files - check permissions and file access")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n⚠️  Scan interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        logger.error(f"Main execution error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
