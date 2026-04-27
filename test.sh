#!/usr/bin/env bash
# Usage: ./test.sh [additional-args]
# Pass --skip-embeddings for faster processing (skips sentence transformer)
#
# For maximum speed (loads machine): ./test.sh --skip-embeddings --workers 24
# For background (low impact):       ./test.sh --skip-embeddings --workers 4
#
# File types indexed:
#   Code:    .py .go .rs .ts .js .sh .bash
#   Docs:    .md .txt .rst
#   Config:  .toml .yaml .yml
#   Logs:    .jsonl (AI session logs, structured text)
#
# External corpora are denylisted to keep the index focused on active projects.
# vuln_source_data, dsl.ai, and linux-kernel data are large and not useful for
# session grounding (they contain CVEs and corpus text, not personal work).

WORKERS=${WORKERS:-16}  # Default 16 workers, override with WORKERS=N ./test.sh

EXTENSIONS=".md,.txt,.rst,.py,.go,.rs,.ts,.js,.sh,.bash,.toml,.yaml,.yml,.jsonl"

DENYLIST="linux-6.*,linux-6*,kernel-*,llvm-project*,chromium*,gecko-dev*,webkit*,vuln_source_data,vuln_source_data-*,dsl.ai,linux-kernel,linux-kernel-*"

uv run python3 file_metadata_content.py \
    --db ~/data/file_metadata.sqlite3 \
    --extensions "$EXTENSIONS" \
    --denylist "$DENYLIST" \
    --workers "$WORKERS" \
    "$@" \
    ~/Documents/src

uv run python3 file_metadata_content.py \
    --db ~/data/file_metadata.sqlite3 \
    --extensions "$EXTENSIONS" \
    --denylist "$DENYLIST" \
    --workers "$WORKERS" \
    "$@" \
    ~/Documents/writing

uv run python3 file_metadata_content.py \
    --db ~/data/file_metadata.sqlite3 \
    --extensions "$EXTENSIONS" \
    --denylist "$DENYLIST" \
    --workers "$WORKERS" \
    "$@" \
    ~/ai_shell_logs

# ~/.claude is hidden so needs explicit allowlist override
uv run python3 file_metadata_content.py \
    --db ~/data/file_metadata.sqlite3 \
    --extensions "$EXTENSIONS" \
    --denylist "$DENYLIST" \
    --allowlist "$HOME/.claude" \
    --workers "$WORKERS" \
    "$@" \
    ~/.claude
