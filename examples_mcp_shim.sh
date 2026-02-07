#!/usr/bin/env bash
#
# Example usage of mcp_shim.py — the MCP protocol bridge.
#
# This script demonstrates all four shim commands and shows how
# any shell-capable process (Gemini CLI, scripts, Shortcuts, cron)
# can discover and use MCP tools without knowing the protocol.
#
# Prerequisites:
#   - ~/.mcp.json exists with server definitions
#   - The MCP server's dependencies are installed
#   - python3 is available
#

SHIM="$(dirname "$0")/mcp_shim.py"

echo "=============================================="
echo " MCP Shim Examples"
echo "=============================================="
echo ""

# ---------------------------------------------------
# 1. DISCOVER — What servers are configured?
# ---------------------------------------------------
echo "--- discover: what MCP servers are available? ---"
echo ""
python3 "$SHIM" discover
echo ""

# ---------------------------------------------------
# 2. LIST-TOOLS — What can a server do?
# ---------------------------------------------------
echo "--- list-tools: what tools does file-metadata offer? ---"
echo ""
python3 "$SHIM" list-tools file-metadata
echo ""

# ---------------------------------------------------
# 3. SCHEMA — Full details for a specific tool
# ---------------------------------------------------
echo "--- schema: full JSON schema for semantic_search ---"
echo ""
python3 "$SHIM" schema file-metadata semantic_search
echo ""

# ---------------------------------------------------
# 4. CALL — Invoke tools
# ---------------------------------------------------

# 4a. No arguments — get database stats
echo "--- call: get_stats (no arguments) ---"
echo ""
python3 "$SHIM" call file-metadata get_stats
echo ""

# 4b. Simple query — full-text search
echo "--- call: full_text_search for 'FAISS' ---"
echo ""
python3 "$SHIM" call file-metadata full_text_search '{"query": "FAISS", "limit": 5}'
echo ""

# 4c. Search by file type
echo "--- call: search_files for Python files ---"
echo ""
python3 "$SHIM" call file-metadata search_files '{"file_type": ".py", "limit": 5}'
echo ""

# 4d. Keyword search (TF-IDF)
echo "--- call: search_by_keywords for 'embedding' ---"
echo ""
python3 "$SHIM" call file-metadata search_by_keywords '{"keywords": ["embedding", "vector"], "limit": 5}'
echo ""

# 4e. List directories
echo "--- call: list_directories ---"
echo ""
python3 "$SHIM" call file-metadata list_directories '{"limit": 5}'
echo ""

# ---------------------------------------------------
# 5. COMPOSING CALLS — pipe results into other tools
# ---------------------------------------------------
echo "--- composing: search then get file info ---"
echo ""

# Find a Python file, extract its path, then get full info on it.
# This shows how the shim integrates with standard unix tools.
FIRST_FILE=$(python3 "$SHIM" call file-metadata search_files '{"file_type": ".py", "limit": 1}' \
    | grep "^•" | head -1 | sed 's/^• //')

if [ -n "$FIRST_FILE" ]; then
    echo "Found: $FIRST_FILE"
    echo "Getting full info..."
    echo ""
    python3 "$SHIM" call file-metadata get_file_info "{\"file_path\": \"$FIRST_FILE\"}"
else
    echo "(no file found to demonstrate composition)"
fi

echo ""
echo "=============================================="
echo " Done. All examples use stdio — no network."
echo "=============================================="
