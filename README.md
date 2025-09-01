# Infrahub MCP Server

MCP server to interact with Infrahub

## Requirements

- Python 3.13+
- fastmcp
- infrahub_sdk


## Usage

### HTTP API mode

```bash
poetry run python server.py --web
```

Send a POST request to the root endpoint (/):

```bash
curl -X POST http://localhost:8001/ \\
  -H "Content-Type: application/json" \\
  -d '{
    "tool": "infrahub_get_nodes",
    "params": {
      "kind": "Tag",
      "filters": { "any": "blue" },
      "partial_match": false
    }
  }'
```

### CLI / stdin-stdout mode

```bash
uv run fastmcp run src/infrahub_mcp_server/server.py:mcp
```

Then send JSON-RPC requests to stdin:

```bash
{"jsonrpc":"2.0","method":"tools/discover","params":{}}
{"jsonrpc":"2.0","method":"tools/call","params":{"name": "infrahub_get_nodes","arguments": {"kind":"Router","filters": {"location":"eu-west"}}}}
```

Process one-shot request with --oneshot:

```bash
echo '{"method":"tools/discover"}' | poetry run python server.py --oneshot
```
