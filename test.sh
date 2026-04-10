#!/usr/bin/env bash
# Usage: ./test.sh [additional-args]
# Pass --skip-embeddings for faster processing (skips sentence transformer)
#
# For maximum speed (loads machine): ./test.sh --skip-embeddings --workers 24
# For background (low impact):       ./test.sh --skip-embeddings --workers 4

WORKERS=${WORKERS:-16}  # Default 16 workers, override with WORKERS=N ./test.sh

python3 file_metadata_content.py --db ~/data/file_metadata.sqlite3 ~/src --workers $WORKERS "$@"
python3 file_metadata_content.py --db ~/data/file_metadata.sqlite3 ~/writing --workers $WORKERS "$@"
#python3 file_metadata_content.py --db ~/data/file_metadata.sqlite3 ~/Documents --workers $WORKERS "$@"
