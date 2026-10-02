#!/usr/bin/env bash
set -euo pipefail

# Regenerate CAPABILITIES.md from the live MCP server definition.
# Requires: mcp-discovery, uv (with project deps installed).
# The server is launched with dummy credentials — it only needs to
# register tools/resources/prompts, not connect to Infrahub.

OUTFILE="${1:-CAPABILITIES.md}"

echo "Regenerating $OUTFILE ..."

INFRAHUB_ADDRESS=http://localhost:8080 \
INFRAHUB_API_TOKEN=dummy \
  mcp-discovery create \
    --filename "$OUTFILE" \
    --template md \
    -- uv run fastmcp run src/infrahub_mcp/server.py:mcp

echo "  Updated: $OUTFILE"
