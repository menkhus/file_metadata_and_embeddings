# TODO Plan: Convert 'mcp_server_fixed.py' to FastAPI HTTP Server

## Goal

To enable global, decoupled access to the `file_metadata_and_embeddings` tools from any Gemini CLI session by exposing `mcp_server_fixed.py` as a persistent HTTP service. This replaces the `stdio_server` communication with a standard web API.

## Context

The `mcp_server_fixed.py` currently uses `mcp.server.stdio_server` for communication. This plan details how to integrate FastAPI to provide an HTTP interface for the existing `handle_list_tools` and `handle_call_tool` functions.

## Implementation Steps

### 1. Prerequisites

*   **Install necessary libraries:**
    ```bash
    pip install fastapi uvicorn pydantic
    ```
    (Note: `pydantic` is often installed with `fastapi`, but explicitly listing it helps.)

### 2. Modify `mcp_server_fixed.py`

The following modifications should be made to the `mcp_server_fixed.py` file.

*   **Add FastAPI Imports:**
    Locate the `import` section and add:
    ```python
    from fastapi import FastAPI, Request, HTTPException
    from pydantic import BaseModel # For request body validation
    import uvicorn
    import argparse # For command-line argument to choose server mode
    ```

*   **Define Request Models (Pydantic):**
    Before `server = Server("file-metadata-mcp")`, define Pydantic models for the `/call_tool` endpoint's request body:
    ```python
    class CallToolBody(BaseModel):
        name: str
        arguments: Dict[str, Any] = {}
    ```

*   **Initialize FastAPI App:**
    Immediately after `server = Server("file-metadata-mcp")`, add:
    ```python
    app = FastAPI(title="File Metadata MCP Server",
                  description="HTTP API for File Metadata tools, compatible with MCP concepts.",
                  version="2.1.0")
    ```

*   **Implement `/list_tools` HTTP Endpoint:**
    Add this function after the `@server.list_tools()` decorator block, but before the `handle_call_tool` block:
    ```python
    @app.get("/list_tools", response_model=List[Tool])
    async def http_list_tools():
        """List available tools for file metadata search and analysis via HTTP."""
        return await handle_list_tools()
    ```
    *(Note: You might need to adjust the return type `List[Tool]` or ensure `Tool` is Pydantic-compatible or convert to dicts.)*

*   **Implement `/call_tool` HTTP Endpoint:**
    Add this function after `http_list_tools` and before the `handle_call_tool` block:
    ```python
    @app.post("/call_tool", response_model=CallToolResult)
    async def http_call_tool(body: CallToolBody):
        """Handle tool calls via HTTP."""
        try:
            result = await handle_call_tool(body.name, body.arguments)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    ```
    *(Note: Similar to `List[Tool]`, `CallToolResult` might need adjustment for direct Pydantic compatibility or conversion to dicts if it's not already.)*

*   **Modify `if __name__ == "__main__":` block for Conditional Server Startup:**
    Locate the `if __name__ == "__main__":` block.
    1.  **Add Argument Parsing:**
        ```python
        parser = argparse.ArgumentParser(description="File Metadata MCP Server")
        parser.add_argument("--http", action="store_true", help="Run as HTTP server using FastAPI")
        args = parser.parse_args()
        ```
    2.  **Conditional Server Run:**
        Replace `asyncio.run(main())` with:
        ```python
        if args.http:
            print(f"Starting FastAPI HTTP server on http://0.0.0.0:8000 ...", flush=True)
            uvicorn.run(app, host="0.0.0.0", port=8000)
        else:
            print(f"Starting stdio_server ...", flush=True)
            asyncio.run(main()) # Your original stdio_server main
        ```

### 3. Deployment & Testing (User Action)

*   **Start the HTTP Server:**
    Navigate to your `~/src/file_metadata_and_embeddings` directory in a terminal and run:
    ```bash
    python3 mcp_server_fixed.py --http &
    ```
    (The `&` puts it in the background).
*   **Verify Server is Running:**
    Open another terminal and test the endpoints:
    ```bash
    curl http://localhost:8000/list_tools
    curl -X POST http://localhost:8000/call_tool -H "Content-Type: application/json" -d '{"name": "get_stats"}'
    ```
    You should receive JSON responses.

### 4. Gemini CLI Integration (Future Step)

Once the HTTP server is running, the Gemini CLI (from any project directory) can use `run_shell_command` with `curl` to interact with your tools, providing the global access desired.

---

This plan outlines the direct modifications needed to your `mcp_server_fixed.py` to achieve a fully HTTP-enabled MCP server.