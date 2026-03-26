<!-- markdownlint-disable -->
![Infrahub Logo](https://assets-global.website-files.com/657aff4a26dd8afbab24944b/657b0e0678f7fd35ce130776_Logo%20INFRAHUB.svg)
<!-- markdownlint-restore -->

<!-- mcp-name: com.opsmill/infrahub-mcp -->

# Infrahub MCP Server

Infrahub MCP Server connects AI assistants and IDE agents to [Infrahub](https://github.com/opsmill/infrahub) using the open [Model Context Protocol](https://modelcontextprotocol.io) standard — so agents can query, create, update, and propose changes to your infrastructure data through a consistent, audited interface. It works with any MCP-compatible client (Claude Desktop, VS Code, Cursor, CLI agents, and more) with no custom glue code required.

All writes are branch-isolated and require human approval before merging — agents never modify your default branch directly.

## What You Can Do With It

- **Query your infrastructure data from natural language** — ask an AI assistant to find devices, interfaces, IP addresses, or any node kind defined in your Infrahub schema, with attribute filtering and partial-match search
- **Explore your schema without leaving the conversation** — the server exposes your full schema catalog, per-kind attribute and filter maps, and the GraphQL SDL as MCP resources that agents read automatically
- **Make changes on isolated branches** — all writes happen on an auto-created session branch (`mcp/session-YYYYMMDD-<hex>`), so the default branch is never modified directly
- **Submit changes for human review** — when edits are ready, call `propose_changes` to open a Proposed Change (the Infrahub equivalent of a pull request) for approval before merging
- **Run arbitrary GraphQL queries** — for advanced use cases, execute any GraphQL query or mutation directly against the Infrahub API

## Who This Is For

**An infrastructure or network team already using Infrahub** that wants their AI coding assistants to understand and interact with their source of truth. You get schema-aware querying, safe branch-isolated writes, and a human-in-the-loop review path — all from your IDE or chat assistant. Start with the [Installation guide](https://docs.infrahub.app/mcp/guides/installation).

**A developer building AI-powered infrastructure automation** who needs a standardized interface between agents and Infrahub. The MCP server handles authentication, schema discovery, and branch management so you can focus on the agent logic. Start with the [Docker deployment guide](https://docs.infrahub.app/mcp/guides/docker) for a production-ready setup.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- A running [Infrahub](https://github.com/opsmill/infrahub) instance
- An Infrahub API token or username/password credentials

## Quick Start

```bash
# Clone the repository
git clone https://github.com/opsmill/infrahub-mcp.git
cd infrahub-mcp

# Install dependencies
uv sync

# Set your Infrahub connection (token auth)
export INFRAHUB_ADDRESS="http://localhost:8000"
export INFRAHUB_API_TOKEN="your-api-token"

# Run the MCP server (stdio transport — ready for IDE clients)
uv run fastmcp run src/infrahub_mcp/server.py:mcp
```

Then add the server to your MCP client. See the [Installation guide](https://docs.infrahub.app/mcp/guides/installation) for Cursor, VS Code, and Claude Desktop configuration examples.

## Configuration

| Variable | Description | Default |
| --- | --- | --- |
| `INFRAHUB_ADDRESS` | URL of your Infrahub instance | **required** |
| `INFRAHUB_API_TOKEN` | API token *(or use username + password)* | — |
| `INFRAHUB_USERNAME` | Username for basic-auth login | — |
| `INFRAHUB_PASSWORD` | Password for basic-auth login | — |
| `INFRAHUB_TIMEOUT` | HTTP request timeout in seconds | `30` |
| `MCP_HOST` | Bind address for the HTTP server (Docker) | `0.0.0.0` |
| `MCP_PORT` | Port for the HTTP server (Docker) | `8001` |

## What's Included

- **Tools (read)** — `get_nodes` retrieves objects by kind with filters, `search_nodes` finds nodes by partial name match, `query_graphql` executes arbitrary GraphQL queries
- **Tools (write)** — `node_upsert` creates or updates nodes, `node_delete` removes nodes, `propose_changes` opens a Proposed Change for human review — all on an auto-created session branch
- **Resources** — `infrahub://schema` lists all available kinds, `infrahub://schema/{kind}` returns full attribute/filter details, `infrahub://graphql-schema` exposes the GraphQL SDL, `infrahub://branches` lists all branches
- **Prompts** — a built-in `infrahub_agent` system prompt that teaches agents the branch-per-session workflow and available tools
- **Infrastructure** — Dockerfile for container deployment, Docker Compose sidecar configuration, streamable HTTP transport support

| File | What it does |
| --- | --- |
| `src/infrahub_mcp/server.py` | Main server entry point — validates config, creates the Infrahub client, mounts all tools/resources/prompts |
| `src/infrahub_mcp/tools/nodes.py` | Read tools: `get_nodes`, `search_nodes` |
| `src/infrahub_mcp/tools/gql.py` | GraphQL tool: `query_graphql` |
| `src/infrahub_mcp/tools/write.py` | Write tools: `node_upsert`, `node_delete`, `propose_changes` |
| `src/infrahub_mcp/resources/schema.py` | Schema resources: catalog, kind detail, GraphQL SDL |
| `src/infrahub_mcp/resources/branches.py` | Branch listing resource |
| `src/infrahub_mcp/prompts/prompts.py` | Prompt templates for agent system prompts |
| `Dockerfile` | Container image for streamable HTTP deployment |
| `server.json` | MCP server manifest for registry discovery |

## Going Deeper

| | |
| --- | --- |
| **Install and configure your MCP client** | [Installation guide](https://docs.infrahub.app/mcp/guides/installation) — step-by-step setup for Cursor, VS Code, and Claude Desktop |
| **Deploy as a container** | [Docker guide](https://docs.infrahub.app/mcp/guides/docker) — standalone or as a sidecar alongside Infrahub |
| **See all available tools and resources** | [Methods reference](https://docs.infrahub.app/mcp/references/methods) — full list of tools, resources, and prompts with parameters |

## About Infrahub

[Infrahub](https://github.com/opsmill/infrahub) is an open source infrastructure data management and automation platform (AGPLv3), developed by [OpsMill](https://opsmill.com). It gives infrastructure and network teams a unified, schema-driven source of truth for all infrastructure data — devices, topology, IP space, configuration — with built-in version control, a generator framework for automation, and native integrations with Git, Ansible, Terraform, and CI/CD pipelines.
