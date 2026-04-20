# Infrahub MCP Server

Infrahub MCP Server connects AI assistants and IDE agents to [Infrahub](https://github.com/opsmill/infrahub) using the open [Model Context Protocol](https://modelcontextprotocol.io) standard — so agents can query, create, update, and propose changes to your infrastructure data through a consistent, audited interface. It works with any MCP-compatible client (Claude Desktop, VS Code, Cursor, CLI agents, and more) with no custom glue code required.

All writes are branch-isolated and require human approval before merging — agents never modify your default branch directly.

## Installation

```bash
pip install infrahub-mcp
# or
uv pip install infrahub-mcp
```

Docker:

```bash
docker pull registry.opsmill.io/opsmill/infrahub-mcp-server:latest
```

## Quickstart

Point the server at your Infrahub instance via environment variables, then run it over the transport your client expects.

**stdio** (default — for Claude Desktop, VS Code, Cursor):

```bash
export INFRAHUB_ADDRESS=http://localhost:8000
export INFRAHUB_API_TOKEN=<your-token>
infrahub-mcp
```

**Streamable HTTP** (for remote clients, sidecar deployments):

```bash
infrahub-mcp --transport streamable-http --host 0.0.0.0 --port 8001
```

## What you can do with it

- **Query your infrastructure data from natural language** — find devices, interfaces, IP addresses, or any kind in your schema, with attribute filtering and partial-match search.
- **Explore your schema without leaving the conversation** — the server exposes your catalog, per-kind attribute/filter maps, and the GraphQL SDL as MCP resources.
- **Make changes on isolated branches** — writes land on an auto-created session branch (`mcp/session-YYYYMMDD-<hex>`); the default branch is never touched directly.
- **Submit changes for human review** — call `propose_changes` to open a Proposed Change for approval before merging.
- **Run arbitrary GraphQL** — execute any query or mutation against the Infrahub API when you need full control.

## Documentation

Full documentation, including client configuration for Cursor, VS Code, Claude Desktop, and Claude Code, is available at the [Infrahub MCP Server docs site](https://opsmill.github.io/infrahub-mcp/).

- [Installation and client setup](https://opsmill.github.io/infrahub-mcp/guides/installation)
- [Docker / sidecar deployment](https://opsmill.github.io/infrahub-mcp/guides/docker)
- [Authentication modes](https://opsmill.github.io/infrahub-mcp/guides/authentication)
- [Configuration reference](https://opsmill.github.io/infrahub-mcp/references/configuration)
- [Methods reference — tools, resources, prompts](https://opsmill.github.io/infrahub-mcp/references/methods)

## About Infrahub

[Infrahub](https://github.com/opsmill/infrahub) is an open source infrastructure data management and automation platform (AGPLv3), developed by [OpsMill](https://opsmill.com). It gives infrastructure and network teams a unified, schema-driven source of truth — devices, topology, IP space, configuration — with built-in version control, a generator framework for automation, and native integrations with Git, Ansible, Terraform, and CI/CD pipelines.

## License

Apache 2.0 — see [LICENSE](./LICENSE).
