# Retry Logging Refactor TODO

## Analysis (2026-02-01)

**Files to modify:** `file_metadata_content.py`

**Lines to change:**
- Line 901: `get_connection()` retry logging
- Line 929: `execute_with_retry()` retry logging

**Current behavior:** All retry attempts (1-5) log at WARNING level, creating noise with concurrent workers.

## Implementation Plan

### 1. Change retry logging levels
```python
# Replace logger.warning() at lines 901 and 929 with:
if attempt < 3:
    logger.debug(f"Database locked/busy, retrying in {wait_time:.1f} seconds... (attempt {attempt + 1}/{self.max_retries})")
else:
    logger.warning(f"Database locked/busy, retrying in {wait_time:.1f} seconds... (attempt {attempt + 1}/{self.max_retries})")
```

### 2. Add retry statistics tracking
Add to `DatabaseManager.__init__()`:
```python
self.retry_stats = {'total_retries': 0, 'max_attempts': 0}
self._retry_lock = threading.Lock()
```

Add helper method:
```python
def _record_retry(self, attempt: int):
    with self._retry_lock:
        self.retry_stats['total_retries'] += 1
        self.retry_stats['max_attempts'] = max(self.retry_stats['max_attempts'], attempt + 1)
```

### 3. Add summary at end of run
Add method to `DatabaseManager`:
```python
def get_retry_summary(self) -> str:
    if self.retry_stats['total_retries'] == 0:
        return "No database retries needed"
    return f"Total retries: {self.retry_stats['total_retries']}, max attempts needed: {self.retry_stats['max_attempts']}"
```

Call from `FileMetadataExtractor.process_directory()` at completion.

### 4. Optional: Add --verbose flag
In argument parser, add:
```python
parser.add_argument('--verbose-retries', action='store_true', help='Log all retry attempts at DEBUG level')
```

## Why This Matters
- With 32 concurrent workers, normal database contention causes many retries
- Attempts 1-3 are expected behavior under contention
- Attempts 4-5 indicate unusual contention worth investigating
- Summary stats help diagnose performance issues without log spam
