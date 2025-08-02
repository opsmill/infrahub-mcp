# Infrahub MCP Server

MCP server to interact with Infrahub

## Installation

1. **Clone the repo**

```bash
git clone https://github.com/opsmill/infrahub-mcp-server.git
cd infrahub-mcp-server
uv sync
uv run fastmcp run src/infrahub_mcp/server.py:mcp
```

## Configuration

Set the following environment variables as needed:

| Variable            | Description                         | Default                  |
|---------------------|-------------------------------------|--------------------------|
| `INFRAHUB_ADDRESS`  | URL of your Infrahub instance       | `http://localhost:8000`  |
| `INFRAHUB_API_TOKEN`| API token for Infrahub              | `placeholder UUID`       |
| `MCP_HOST`          | Host for the web server             | `0.0.0.0`                |
| `MCP_PORT`          | Port for the web server             | `8001`                   |

