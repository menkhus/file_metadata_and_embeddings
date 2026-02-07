#!/usr/bin/env python3
"""
MCP Shim — A standalone MCP client that discovers and talks to MCP servers.

Reads ~/.mcp.json (or a specified config) to find servers, spawns them,
and speaks JSON-RPC over their stdin/stdout. Any process that can call
this script can use MCP tools without knowing the protocol.

Usage:
    # Discover: what servers are configured?
    ./mcp_shim.py discover

    # List: what tools does a server offer?
    ./mcp_shim.py list-tools file-metadata

    # Call: invoke a tool
    ./mcp_shim.py call file-metadata get_stats
    ./mcp_shim.py call file-metadata full_text_search '{"query": "authentication"}'

    # Use a custom config location
    ./mcp_shim.py --config /path/to/.mcp.json discover

The semantic information flows from:
    ~/.mcp.json        → "what servers exist, how to launch them"
    tools/list         → "what can each server do" (names, descriptions, schemas)
    tools/call         → "do this" (name + arguments → result)

This script is the missing bridge between the MCP protocol and anything
that can run a shell command.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_CONFIG_PATHS = [
    Path.home() / ".mcp.json",                    # Global (Claude Code convention)
    Path.cwd() / ".mcp.json",                     # Project-local
]


def find_config(explicit_path=None):
    """Find the .mcp.json config file.

    Checks explicit path first, then the standard locations.
    Returns the parsed JSON and the path it was found at.
    """
    if explicit_path:
        p = Path(explicit_path)
        if p.exists():
            return json.loads(p.read_text()), str(p)
        print(f"Error: Config not found at {explicit_path}", file=sys.stderr)
        sys.exit(1)

    for p in DEFAULT_CONFIG_PATHS:
        if p.exists():
            return json.loads(p.read_text()), str(p)

    print("Error: No .mcp.json found.", file=sys.stderr)
    print(f"Searched: {', '.join(str(p) for p in DEFAULT_CONFIG_PATHS)}", file=sys.stderr)
    sys.exit(1)


def get_server_config(config, server_name):
    """Extract a named server's config from the parsed .mcp.json."""
    servers = config.get("mcpServers", {})
    if server_name not in servers:
        print(f"Error: Server '{server_name}' not found in config.", file=sys.stderr)
        print(f"Available servers: {', '.join(servers.keys())}", file=sys.stderr)
        sys.exit(1)
    return servers[server_name]


def send_jsonrpc(proc, method, params=None, request_id=1):
    """Send a JSON-RPC request to the server process and read the response.

    MCP over stdio uses newline-delimited JSON-RPC messages.
    We send a request, then read lines until we get a response
    with a matching id (skipping any notifications the server sends).
    """
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        request["params"] = params

    msg = json.dumps(request) + "\n"
    proc.stdin.write(msg)
    proc.stdin.flush()

    # Read lines until we get a response with our id.
    # MCP servers may send notifications (no id) that we skip.
    while True:
        line = proc.stdout.readline()
        if not line:
            print("Error: Server closed connection before responding.", file=sys.stderr)
            sys.exit(1)

        line = line.strip()
        if not line:
            continue

        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            # Skip non-JSON output (startup messages on stdout, etc.)
            continue

        # Skip notifications (no id field)
        if "id" not in response:
            continue

        if response["id"] == request_id:
            return response


def spawn_server(server_cfg):
    """Spawn an MCP server subprocess based on its config entry.

    Returns the Popen object with stdin/stdout pipes ready for JSON-RPC.
    """
    command = server_cfg["command"]
    args = server_cfg.get("args", [])
    env_overrides = server_cfg.get("env", {})

    # Build environment: inherit current env, overlay config env vars
    env = os.environ.copy()
    env.update(env_overrides)

    full_cmd = [command] + args

    try:
        proc = subprocess.Popen(
            full_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,  # Line-buffered
        )
    except FileNotFoundError:
        print(f"Error: Command not found: {command}", file=sys.stderr)
        sys.exit(1)

    return proc


def initialize_server(proc):
    """Send the MCP initialize handshake.

    MCP requires an initialize request before any tool calls.
    The server responds with its capabilities, then we send
    an initialized notification to complete the handshake.
    """
    init_response = send_jsonrpc(proc, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "mcp-shim", "version": "1.0.0"}
    }, request_id=0)

    if "error" in init_response:
        print(f"Error during initialize: {init_response['error']}", file=sys.stderr)
        sys.exit(1)

    # Send initialized notification (no id, no response expected)
    notification = json.dumps({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }) + "\n"
    proc.stdin.write(notification)
    proc.stdin.flush()

    return init_response.get("result", {})


def cmd_discover(config, config_path):
    """Discover: show what servers are configured and how they launch."""
    servers = config.get("mcpServers", {})
    print(f"Config: {config_path}")
    print(f"Servers: {len(servers)}\n")

    for name, cfg in servers.items():
        cmd = cfg["command"]
        args = " ".join(cfg.get("args", []))
        env = cfg.get("env", {})
        print(f"  {name}")
        print(f"    Launch: {cmd} {args}")
        if env:
            for k, v in env.items():
                print(f"    Env:    {k}={v}")
        print()


def cmd_list_tools(config, server_name):
    """List tools: spawn the server, initialize, ask for tools, print them."""
    server_cfg = get_server_config(config, server_name)
    proc = spawn_server(server_cfg)

    try:
        initialize_server(proc)
        response = send_jsonrpc(proc, "tools/list", {}, request_id=1)

        if "error" in response:
            print(f"Error: {response['error']}", file=sys.stderr)
            sys.exit(1)

        tools = response.get("result", {}).get("tools", [])
        print(f"Server: {server_name}")
        print(f"Tools:  {len(tools)}\n")

        for tool in tools:
            print(f"  {tool['name']}")
            # Print first line of description
            desc = tool.get("description", "").strip()
            first_line = desc.split("\n")[0] if desc else "(no description)"
            print(f"    {first_line}")

            # Print required params
            schema = tool.get("inputSchema", {})
            props = schema.get("properties", {})
            required = schema.get("required", [])
            if props:
                param_parts = []
                for pname, pinfo in props.items():
                    marker = "*" if pname in required else ""
                    ptype = pinfo.get("type", "any")
                    param_parts.append(f"{pname}{marker}:{ptype}")
                print(f"    Params: {', '.join(param_parts)}")
            print()

    finally:
        proc.terminate()
        proc.wait()


def cmd_call(config, server_name, tool_name, arguments):
    """Call a tool: spawn, initialize, call, print result."""
    server_cfg = get_server_config(config, server_name)
    proc = spawn_server(server_cfg)

    try:
        initialize_server(proc)
        response = send_jsonrpc(proc, "tools/call", {
            "name": tool_name,
            "arguments": arguments,
        }, request_id=1)

        if "error" in response:
            print(json.dumps(response["error"], indent=2))
            sys.exit(1)

        result = response.get("result", {})
        content_list = result.get("content", [])

        # Print each content block
        for content in content_list:
            if content.get("type") == "text":
                print(content["text"])
            else:
                print(json.dumps(content, indent=2))

    finally:
        proc.terminate()
        proc.wait()


def cmd_schema(config, server_name, tool_name):
    """Schema: print the full JSON Schema for a specific tool's input."""
    server_cfg = get_server_config(config, server_name)
    proc = spawn_server(server_cfg)

    try:
        initialize_server(proc)
        response = send_jsonrpc(proc, "tools/list", {}, request_id=1)

        tools = response.get("result", {}).get("tools", [])
        for tool in tools:
            if tool["name"] == tool_name:
                print(json.dumps(tool, indent=2))
                return

        print(f"Error: Tool '{tool_name}' not found on server '{server_name}'.", file=sys.stderr)
        available = [t["name"] for t in tools]
        print(f"Available: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)

    finally:
        proc.terminate()
        proc.wait()


def main():
    parser = argparse.ArgumentParser(
        description="MCP Shim — discover and call MCP servers from any process.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s discover                                      Show configured servers
  %(prog)s list-tools file-metadata                      List tools on a server
  %(prog)s schema file-metadata full_text_search         Full schema for a tool
  %(prog)s call file-metadata get_stats                  Call a tool (no args)
  %(prog)s call file-metadata full_text_search '{"query": "auth"}'
        """,
    )
    parser.add_argument("--config", help="Path to .mcp.json (default: ~/.mcp.json)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON responses")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # discover
    subparsers.add_parser("discover", help="Show configured MCP servers")

    # list-tools
    lt = subparsers.add_parser("list-tools", help="List tools available on a server")
    lt.add_argument("server", help="Server name from .mcp.json")

    # schema
    sc = subparsers.add_parser("schema", help="Show full JSON schema for a tool")
    sc.add_argument("server", help="Server name from .mcp.json")
    sc.add_argument("tool", help="Tool name")

    # call
    ca = subparsers.add_parser("call", help="Call a tool on a server")
    ca.add_argument("server", help="Server name from .mcp.json")
    ca.add_argument("tool", help="Tool name")
    ca.add_argument("arguments", nargs="?", default="{}", help="JSON arguments (default: {})")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    config, config_path = find_config(args.config)

    if args.command == "discover":
        cmd_discover(config, config_path)

    elif args.command == "list-tools":
        cmd_list_tools(config, args.server)

    elif args.command == "schema":
        cmd_schema(config, args.server, args.tool)

    elif args.command == "call":
        try:
            arguments = json.loads(args.arguments)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON arguments: {e}", file=sys.stderr)
            sys.exit(1)
        cmd_call(config, args.server, args.tool, arguments)


if __name__ == "__main__":
    main()
