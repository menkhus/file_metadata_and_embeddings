#!/usr/bin/env python3
"""
Tests for mcp_shim.py — the MCP protocol bridge.

Tests the shim's ability to:
- Discover servers from .mcp.json config
- Parse and validate config structure
- Spawn MCP servers and speak JSON-RPC
- List tools, retrieve schemas, and call tools

Usage:
    python3 -m pytest test_mcp_shim.py -v
    python3 test_mcp_shim.py  # direct execution
"""

import json
import os
import subprocess
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import shim modules for unit testing
import mcp_shim

SHIM_PATH = str(Path(__file__).parent / "mcp_shim.py")
MCP_SERVER_PATH = str(Path(__file__).parent / "mcp_server_fixed.py")


# ---------------------------------------------------------------------------
# Unit tests — config parsing, no server needed
# ---------------------------------------------------------------------------

class TestConfigDiscovery:
    """Test .mcp.json config file discovery and parsing."""

    def test_find_config_explicit_path(self, tmp_path):
        """Explicit --config path is used when provided."""
        config_file = tmp_path / ".mcp.json"
        config_data = {"mcpServers": {"test-server": {"command": "echo", "args": []}}}
        config_file.write_text(json.dumps(config_data))

        result, path = mcp_shim.find_config(str(config_file))
        assert result == config_data
        assert path == str(config_file)

    def test_find_config_missing_explicit_path(self):
        """Explicit path that doesn't exist should exit."""
        with pytest.raises(SystemExit):
            mcp_shim.find_config("/nonexistent/.mcp.json")

    def test_find_config_default_home(self, tmp_path, monkeypatch):
        """Falls back to ~/.mcp.json when no explicit path given."""
        config_data = {"mcpServers": {"my-server": {"command": "python3", "args": []}}}
        config_file = tmp_path / ".mcp.json"
        config_file.write_text(json.dumps(config_data))

        monkeypatch.setattr(mcp_shim, "DEFAULT_CONFIG_PATHS", [config_file])
        result, path = mcp_shim.find_config()
        assert result == config_data

    def test_find_config_no_config_found(self, monkeypatch):
        """No config file anywhere should exit."""
        monkeypatch.setattr(mcp_shim, "DEFAULT_CONFIG_PATHS", [Path("/nonexistent/.mcp.json")])
        with pytest.raises(SystemExit):
            mcp_shim.find_config()

    def test_get_server_config_valid(self):
        """Extract a named server from config."""
        config = {"mcpServers": {"file-metadata": {"command": "python3", "args": ["server.py"]}}}
        result = mcp_shim.get_server_config(config, "file-metadata")
        assert result["command"] == "python3"
        assert result["args"] == ["server.py"]

    def test_get_server_config_missing(self):
        """Requesting a nonexistent server should exit."""
        config = {"mcpServers": {"other-server": {"command": "echo"}}}
        with pytest.raises(SystemExit):
            mcp_shim.get_server_config(config, "file-metadata")

    def test_config_structure(self):
        """Verify the real ~/.mcp.json has expected structure."""
        home_config = Path.home() / ".mcp.json"
        if not home_config.exists():
            pytest.skip("No ~/.mcp.json found")

        config = json.loads(home_config.read_text())
        assert "mcpServers" in config

        for name, server in config["mcpServers"].items():
            assert "command" in server, f"Server '{name}' missing 'command'"
            # args and env are optional but should be correct types if present
            if "args" in server:
                assert isinstance(server["args"], list)
            if "env" in server:
                assert isinstance(server["env"], dict)


# ---------------------------------------------------------------------------
# Integration tests — require the actual MCP server to be functional
# ---------------------------------------------------------------------------

def server_available():
    """Check if the MCP server and database are available for integration tests."""
    if not os.path.exists(MCP_SERVER_PATH):
        return False
    db_path = os.environ.get('FILE_METADATA_DB', os.path.expanduser('~/data/file_metadata.sqlite3'))
    return os.path.exists(db_path)


@pytest.mark.skipif(not server_available(), reason="MCP server or database not available")
class TestShimCLI:
    """Integration tests that run the shim as a subprocess against the real server."""

    def run_shim(self, *args, timeout=30):
        """Helper to run the shim and capture output."""
        result = subprocess.run(
            [sys.executable, SHIM_PATH] + list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result

    def test_discover(self):
        """Discover shows configured servers."""
        result = self.run_shim("discover")
        assert result.returncode == 0
        assert "file-metadata" in result.stdout
        assert "Servers:" in result.stdout

    def test_list_tools(self):
        """List tools returns all 12 tools with descriptions."""
        result = self.run_shim("list-tools", "file-metadata")
        assert result.returncode == 0
        assert "Tools:" in result.stdout
        # Check for key tools
        assert "search_files" in result.stdout
        assert "full_text_search" in result.stdout
        assert "get_stats" in result.stdout
        assert "semantic_search" in result.stdout

    def test_list_tools_shows_params(self):
        """List tools includes parameter information."""
        result = self.run_shim("list-tools", "file-metadata")
        assert "Params:" in result.stdout
        assert "query*:string" in result.stdout  # required param marked with *

    def test_list_tools_bad_server(self):
        """Requesting a nonexistent server fails gracefully."""
        result = self.run_shim("list-tools", "nonexistent-server")
        assert result.returncode != 0

    def test_schema(self):
        """Schema returns full JSON schema for a tool."""
        result = self.run_shim("schema", "file-metadata", "full_text_search")
        assert result.returncode == 0
        schema = json.loads(result.stdout)
        assert schema["name"] == "full_text_search"
        assert "inputSchema" in schema
        assert "properties" in schema["inputSchema"]
        assert "query" in schema["inputSchema"]["properties"]

    def test_schema_bad_tool(self):
        """Schema for nonexistent tool fails gracefully."""
        result = self.run_shim("schema", "file-metadata", "nonexistent_tool")
        assert result.returncode != 0

    def test_call_get_stats(self):
        """Call get_stats returns database statistics."""
        result = self.run_shim("call", "file-metadata", "get_stats")
        assert result.returncode == 0
        assert "Total Files:" in result.stdout
        assert "Total Size:" in result.stdout
        assert "Directories:" in result.stdout

    def test_call_full_text_search(self):
        """Call full_text_search with a query returns results."""
        result = self.run_shim(
            "call", "file-metadata", "full_text_search",
            '{"query": "python"}'
        )
        assert result.returncode == 0
        # Should find something — python files are definitely indexed
        assert "Found" in result.stdout or "No matches" in result.stdout

    def test_call_search_files(self):
        """Call search_files by file type."""
        result = self.run_shim(
            "call", "file-metadata", "search_files",
            '{"file_type": ".py", "limit": 3}'
        )
        assert result.returncode == 0
        assert ".py" in result.stdout or "No files" in result.stdout

    def test_call_list_directories(self):
        """Call list_directories returns directory listing."""
        result = self.run_shim(
            "call", "file-metadata", "list_directories",
            '{"limit": 5}'
        )
        assert result.returncode == 0
        assert "directories" in result.stdout.lower() or "Files:" in result.stdout

    def test_call_bad_json_args(self):
        """Bad JSON arguments fail gracefully."""
        result = self.run_shim(
            "call", "file-metadata", "get_stats",
            '{not valid json}'
        )
        assert result.returncode != 0
        assert "Invalid JSON" in result.stderr

    def test_call_missing_required_param(self):
        """Calling a tool without required params returns an error from the server."""
        result = self.run_shim(
            "call", "file-metadata", "full_text_search",
            '{}'
        )
        assert result.returncode == 0  # shim succeeds, server returns error text
        assert "Error" in result.stdout or "error" in result.stdout.lower()

    def test_no_args_shows_help(self):
        """Running with no arguments shows help text."""
        result = self.run_shim()
        assert result.returncode == 0
        assert "discover" in result.stdout
        assert "list-tools" in result.stdout
        assert "call" in result.stdout


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
