#!/usr/bin/env python3
"""
FastAPI Web Interface for File Metadata and Embeddings System

This provides a web-based interface to:
1. Process files with V1 system (file_metadata_content.py)
2. Search using V2 tools (FTS, semantic, file queries)
3. Manage database (view, delete, enable/disable components)
4. Display real-time logs and results
"""

from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional, List, Dict, Any
import sys
import os
import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
import asyncio
from queue import Queue
import threading

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Import V2 tools
from tools_v2.find_using_fts_v2 import FTSSearchV2
from tools_v2.find_most_similar_v2 import SemanticSearchV2
from tools_v2.file_query_tool_v2 import FileQueryToolV2

# Import V1 system components (we'll use them programmatically)
from file_metadata_content import FileMetadataExtractor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global log queue for real-time log streaming
log_queue = Queue()

class QueueHandler(logging.Handler):
    """Custom logging handler that puts logs into a queue"""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        log_entry = self.format(record)
        self.log_queue.put({
            'timestamp': datetime.now().isoformat(),
            'level': record.levelname,
            'message': log_entry
        })

# Add queue handler to root logger
queue_handler = QueueHandler(log_queue)
queue_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(queue_handler)

# Initialize FastAPI app
app = FastAPI(title="File Metadata & Embeddings Web Interface")

# Setup templates directory
templates = Jinja2Templates(directory="templates")

# Default database path
DEFAULT_DB_PATH = "/Users/mark/data/file_metadata.sqlite3"

# Global processing state
processing_state = {
    'running': False,
    'current_task': None,
    'progress': 0,
    'total': 0,
    'status': 'idle'
}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with navigation"""
    return templates.TemplateResponse("home.html", {"request": request})


@app.get("/process", response_class=HTMLResponse)
async def process_page(request: Request):
    """File processing interface"""
    return templates.TemplateResponse("process.html", {
        "request": request,
        "default_db": DEFAULT_DB_PATH
    })


@app.post("/api/process/start")
async def start_processing(
    background_tasks: BackgroundTasks,
    directory: str = Form(...),
    db_path: str = Form(DEFAULT_DB_PATH),
    workers: int = Form(4),
    force: bool = Form(False),
    verbose: bool = Form(False),
    debug: bool = Form(False)
):
    """Start file processing in background"""
    global processing_state

    if processing_state['running']:
        return JSONResponse({
            'status': 'error',
            'message': 'Processing already running'
        }, status_code=400)

    processing_state['running'] = True
    processing_state['status'] = 'starting'

    # Configure logging level
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
    elif verbose:
        logging.getLogger().setLevel(logging.INFO)

    logger.info(f"Starting file processing: directory={directory}, db={db_path}, workers={workers}, force={force}")

    # Run processing in background
    background_tasks.add_task(
        run_file_processing,
        directory, db_path, workers, force
    )

    return JSONResponse({
        'status': 'success',
        'message': 'Processing started'
    })


async def run_file_processing(directory: str, db_path: str, workers: int, force: bool):
    """Background task for file processing - uses existing V1 scan_directory method"""
    global processing_state

    try:
        processing_state['status'] = 'running'
        logger.info(f"Processing directory: {directory}")

        # Create extractor instance
        extractor = FileMetadataExtractor(db_path)

        # Process files using existing scan_directory method
        results = extractor.scan_directory(
            directory,
            max_workers=workers,
            force=force
        )

        processing_state['total'] = results.get('total_files', 0)
        processing_state['progress'] = results.get('successful_files', 0)
        processing_state['status'] = 'completed'
        processing_state['results'] = results

        logger.info("Processing completed successfully")
        logger.info(f"Results: {results}")

    except Exception as e:
        processing_state['status'] = 'error'
        logger.error(f"Processing error: {e}", exc_info=True)
    finally:
        processing_state['running'] = False


@app.get("/api/process/status")
async def get_processing_status():
    """Get current processing status"""
    return JSONResponse(processing_state)


@app.get("/api/logs")
async def get_logs():
    """Get recent logs from queue"""
    logs = []
    while not log_queue.empty():
        logs.append(log_queue.get())
    return JSONResponse({'logs': logs})


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    """Search interface"""
    return templates.TemplateResponse("search.html", {
        "request": request,
        "default_db": DEFAULT_DB_PATH
    })


@app.post("/api/search/fts")
async def search_fts(
    query: str = Form(...),
    limit: int = Form(10),
    context: int = Form(0),
    db_path: str = Form(DEFAULT_DB_PATH)
):
    """Full-text search"""
    try:
        searcher = FTSSearchV2(db_path)
        results = searcher.search(query, limit=limit, include_context=context)

        return JSONResponse({
            'status': 'success',
            'query': query,
            'count': len(results),
            'results': results
        })
    except Exception as e:
        logger.error(f"FTS search error: {e}", exc_info=True)
        return JSONResponse({
            'status': 'error',
            'message': str(e)
        }, status_code=500)


@app.post("/api/search/semantic")
async def search_semantic(
    query: str = Form(...),
    top_k: int = Form(5),
    context: int = Form(0),
    db_path: str = Form(DEFAULT_DB_PATH)
):
    """Semantic search"""
    try:
        searcher = SemanticSearchV2(db_path)

        # Load embeddings
        if not searcher.load_embeddings():
            return JSONResponse({
                'status': 'error',
                'message': 'No embeddings found in database'
            }, status_code=404)

        results = searcher.search(query, top_k=top_k, include_context=context)

        return JSONResponse({
            'status': 'success',
            'query': query,
            'count': len(results),
            'results': results
        })
    except Exception as e:
        logger.error(f"Semantic search error: {e}", exc_info=True)
        return JSONResponse({
            'status': 'error',
            'message': str(e)
        }, status_code=500)


@app.post("/api/search/files")
async def search_files(
    created_since: Optional[str] = Form(None),
    created_before: Optional[str] = Form(None),
    greater_than: Optional[int] = Form(None),
    less_than: Optional[int] = Form(None),
    name_pattern: Optional[str] = Form(None),
    file_type: Optional[str] = Form(None),
    limit: Optional[int] = Form(100),
    db_path: str = Form(DEFAULT_DB_PATH)
):
    """File query search"""
    try:
        query_tool = FileQueryToolV2(db_path)
        results = query_tool.query_files(
            created_since=created_since,
            created_before=created_before,
            greater_than=greater_than,
            less_than=less_than,
            name_pattern=name_pattern,
            file_type=file_type,
            limit=limit
        )

        return JSONResponse({
            'status': 'success',
            'count': len(results),
            'results': results
        })
    except Exception as e:
        logger.error(f"File query error: {e}", exc_info=True)
        return JSONResponse({
            'status': 'error',
            'message': str(e)
        }, status_code=500)


@app.get("/manage", response_class=HTMLResponse)
async def manage_page(request: Request):
    """Database management interface"""
    return templates.TemplateResponse("manage.html", {
        "request": request,
        "default_db": DEFAULT_DB_PATH
    })


@app.get("/api/db/stats")
async def get_db_stats(db_path: str = DEFAULT_DB_PATH):
    """Get database statistics"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        stats = {}

        # Count tables
        tables = [
            'file_metadata',
            'content_analysis',
            'text_chunks',
            'text_chunks_v2',
            'embeddings_index',
            'content_fts',
            'chunks_fts'
        ]

        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                stats[table] = 0  # Table doesn't exist

        # Database size
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        stats['db_size_mb'] = round(db_size / (1024 * 1024), 2)

        conn.close()

        return JSONResponse({
            'status': 'success',
            'stats': stats
        })
    except Exception as e:
        logger.error(f"Database stats error: {e}", exc_info=True)
        return JSONResponse({
            'status': 'error',
            'message': str(e)
        }, status_code=500)


@app.post("/api/db/delete")
async def delete_data(
    table: str = Form(...),
    file_path: Optional[str] = Form(None),
    db_path: str = Form(DEFAULT_DB_PATH)
):
    """Delete data from database"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Allowed tables
        allowed_tables = [
            'file_metadata',
            'content_analysis',
            'text_chunks',
            'text_chunks_v2',
            'embeddings_index'
        ]

        if table not in allowed_tables:
            return JSONResponse({
                'status': 'error',
                'message': f'Invalid table: {table}'
            }, status_code=400)

        if file_path:
            # Delete specific file
            cursor.execute(f"DELETE FROM {table} WHERE file_path = ?", (file_path,))
            logger.info(f"Deleted {file_path} from {table}")
        else:
            # Delete all from table
            cursor.execute(f"DELETE FROM {table}")
            logger.info(f"Cleared table {table}")

        conn.commit()
        rows_deleted = cursor.rowcount
        conn.close()

        return JSONResponse({
            'status': 'success',
            'rows_deleted': rows_deleted
        })
    except Exception as e:
        logger.error(f"Delete error: {e}", exc_info=True)
        return JSONResponse({
            'status': 'error',
            'message': str(e)
        }, status_code=500)


@app.post("/api/db/vacuum")
async def vacuum_database(db_path: str = Form(DEFAULT_DB_PATH)):
    """Vacuum database to reclaim space"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("VACUUM")
        conn.close()

        logger.info("Database vacuumed successfully")

        return JSONResponse({
            'status': 'success',
            'message': 'Database vacuumed'
        })
    except Exception as e:
        logger.error(f"Vacuum error: {e}", exc_info=True)
        return JSONResponse({
            'status': 'error',
            'message': str(e)
        }, status_code=500)


if __name__ == "__main__":
    import uvicorn

    print("Starting File Metadata Web Interface...")
    print("Access at: http://localhost:8000")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
