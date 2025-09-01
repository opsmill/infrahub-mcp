# LLM Context Guide for Infrahub MCP Server

Infrahub MCP Server connects your AI assistants to Infrahub using the open MCP standard—so agents can read and (optionally) change your infra state through a consistent, audited, human-approved interface.

## Key Directories

```
infrahub-mcp/
├── docs/                       # Documentation (UPDATE FOR CHANGES)
├── src/                        # Python Code
│   └── infrahub_mcp/
│       ├── __init__.py
|       ├── branch.py
|       ├── constants.py
|       ├── gql.py
|       ├── nodes.py
|       ├── prompts/
|       │   └── main.md
|       ├── schema.py
|       ├── server.py
|       └── utils.py
└── tests/                      # Python/integration tests
```

## Code Standards

### Python Backend

- **Type hints required** for all new code
- **MyPy compliant** - run `pre-commit run mypy`
- **Ruf compliant**- run `pre-commit run ruff`
- **pytest** for testing

## Documentation Requirements

- **docs/**: Update for any user-facing changes
- **Docstrings**: Required for new functions/classes

## Test Utilities

### Running Tests

## Platform-Specific Instructions

- **[CLAUDE.md](CLAUDE.md)** - For Claude/Anthropic tools
- **[.github/copilot-instructions.md](.github/copilot-instructions.md)** - For GitHub Copilot
- **[GEMINI.md](GEMINI.md)** - For Google Gemini tools
- **[GPT.md](GPT.md)** - For OpenAI/ChatGPT tools
- **[.cursor/rules/dev-standard.mdc](.cursor/rules/dev-standard.mdc)** - For Cursor editor
