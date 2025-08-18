# Infrahub MCP Server

MCP server to interact with Infrahub

## Requirements

- Python 3.13+
- fastmcp
- infrahub_sdk


## Installation

1. **Clone the repo**

    ```bash
    git clone https://github.com/opsmill/infrahub-mcp-server.git
    cd infrahub-mcp-server
    ```

2. **Install dependencies**

    ```bash
    uv sync
    ```

3. **Run the server**

    ```bash
    uv run fastmcp run src/infrahub_mcp_server/server.py:mcp
    ```


## Configuration

Set the following environment variables as needed:

| Variable            | Description                         | Default                  |
|---------------------|-------------------------------------|--------------------------|
| `INFRAHUB_ADDRESS`  | URL of your Infrahub instance       | `http://localhost:8000`  |
| `INFRAHUB_API_TOKEN`| API token for Infrahub              | `placeholder UUID`       |
| `MCP_HOST`          | Host for the web server             | `0.0.0.0`                |
| `MCP_PORT`          | Port for the web server             | `8001`                   |


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

## MCP Methods

### infrahub_get_nodes
Retrieve nodes of a given kind.

Params:

- kind (string, required): node kind (e.g. "Router")
- branch (string): branch name
- filters (object): key/value filters
- simple keys → <key>__value
- list values → <key>__values
- use "any" to search across all attributes
- partial_match (boolean): true for substring matches
- infrahub_url (string): override via param
- infrahub_api_token (string): override via param

Response:

```json
{
  "success": true,
  "count": 5,
  "nodes": [ { ... }, ... ]
}
```

### infrahub_get_schema

Retrieve schema details.

Params:

- kind (string): kind name; omit to fetch all schemas
- branch (string)
- exclude_profiles (boolean)
- exclude_templates (boolean)
- infrahub_url (string)
- infrahub_api_token (string)

Response (single kind):

```json
{
  "success": true,
  "kind": "Tag",
  "namespace": "...",
  "name": "...",
  "attributes": [ { "name": "...", "type": "...", "description": "..." }, ... ],
  "relationships": [ { "name": "...", "rel_kind": "...", "cardinality": "...", "description": "..." }, ... ]
}
```

Response (all schemas):

```json
{
  "success": true,
  "count": 12,
  "schemas": [ { ... }, ... ]
}
```

