# File Metadata & Embeddings Web Interface

FastAPI-based web interface for the file metadata and embeddings system.

## Features

### 1. File Processing (V1 System)
- Configure and run file metadata extraction
- Set directory, database path, worker threads
- Force rescan option for reprocessing unchanged files
- Verbose/debug logging controls
- Real-time log display with color-coded levels
- Live processing status updates

### 2. Search (V2 Tools)
Three search modes with tabbed interface:

**Full-Text Search (FTS5):**
- Search chunks using SQLite FTS5
- Configure result limit and context chunks
- View matching snippets with highlighting

**Semantic Search (Embeddings):**
- Vector similarity search using sentence-transformers
- Configure top-k results and context
- Requires embeddings to be generated first

**File Query (Metadata):**
- Query files by creation date, size, name pattern, type
- Supports date ranges and size filters
- Returns file metadata in table format

### 3. Database Management
- View database statistics (table row counts, db size)
- Delete data from specific tables or files
- Vacuum database to reclaim space
- Component management info (V1 vs V2 systems)

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Or install just web interface dependencies
pip install fastapi uvicorn[standard] python-multipart jinja2 faiss-cpu
```

## Usage

### Quick Start

```bash
# Run the startup script
./run_web_interface.sh

# Or run directly
python3 web_interface.py
```

Then open your browser to: **http://localhost:8000**

### Command Line Options

The web interface uses existing CLI tools:

**V1 File Processing:**
- Wraps `file_metadata_content.py` `scan_directory()` method
- All CLI args exposed in web form (directory, db, workers, force, verbose, debug)

**V2 Search Tools:**
- FTS: `tools_v2/find_using_fts_v2.py`
- Semantic: `tools_v2/find_most_similar_v2.py`
- File Query: `tools_v2/file_query_tool_v2.py`

## API Endpoints

### Processing
- `POST /api/process/start` - Start file processing
- `GET /api/process/status` - Get processing status
- `GET /api/logs` - Get recent logs

### Search
- `POST /api/search/fts` - Full-text search
- `POST /api/search/semantic` - Semantic search
- `POST /api/search/files` - File query search

### Database Management
- `GET /api/db/stats` - Database statistics
- `POST /api/db/delete` - Delete data
- `POST /api/db/vacuum` - Vacuum database

## Architecture

```
web_interface.py (FastAPI)
    ↓
├── File Processing → file_metadata_content.py (V1)
│   └── FileMetadataExtractor.scan_directory()
│
├── Search Tools → tools_v2/ (V2)
│   ├── FTSSearchV2
│   ├── SemanticSearchV2
│   └── FileQueryToolV2
│
└── Database → SQLite
    └── /Users/mark/data/file_metadata.sqlite3
```

## Design Principles

1. **Reuse Existing Code:** Web interface wraps existing V1 and V2 tools
2. **Minimal UI:** Simple HTML forms, no heavy JavaScript frameworks
3. **Real-time Feedback:** Live logging and status updates
4. **Full Control:** All CLI options exposed in web forms
5. **Database Management:** View, delete, maintain database through GUI

## Notes

- Default database path: `/Users/mark/data/file_metadata.sqlite3`
- Processing runs in background using FastAPI BackgroundTasks
- Logs stream via polling (500ms interval)
- Status updates via polling (1s interval)
- All forms use standard HTML with minimal JavaScript for dynamic updates

## Troubleshooting

**Import errors:**
```bash
# Ensure all dependencies installed
pip install -r requirements.txt
```

**Database connection errors:**
- Check database path exists
- Verify permissions on database file

**Semantic search not working:**
- Embeddings must be generated first
- Run file processing with V1 system to generate embeddings
- Check that `embeddings_index` table has data

**Templates not found:**
- Ensure `templates/` directory exists in same location as `web_interface.py`
- Check all 4 HTML files are present: home.html, process.html, search.html, manage.html
