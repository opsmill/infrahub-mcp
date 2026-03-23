# Remove main.md File Dependency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the deleted `main.md` file dependency by making `infrahub_agent()` generate its prompt dynamically, then clean up dead code.

**Architecture:** The `infrahub_agent()` MCP prompt in `server.py` currently calls `get_prompt("main")` which reads from a deleted file. We'll replace it with an inline dynamic prompt that summarizes the server's capabilities (matching what `main.md` contained). Then remove the now-unused `get_prompt()` utility and update the integration test fixture.

**Tech Stack:** Python 3.13, FastMCP, pytest

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/infrahub_mcp/server.py:50-53` | Replace `infrahub_agent()` with inline prompt |
| Modify | `src/infrahub_mcp/utils.py:45-49` | Remove `get_prompt()` function |
| Modify | `tests/integration/conftest.py:8,14-16` | Update `main_prompt` fixture |
| Create | `tests/unit/test_server_prompt.py` | Test for `infrahub_agent()` prompt |

---

### Task 1: Add test for `infrahub_agent()` prompt

**Files:**
- Create: `tests/unit/test_server_prompt.py`

- [ ] **Step 1: Write the failing test**

The test should verify that the `infrahub_agent` prompt is callable and returns sensible content. Since the server's `mcp` instance requires lifespan context (env vars, SDK client), test the prompt function directly rather than through `Client(mcp)`.

```python
from infrahub_mcp.server import infrahub_agent


async def test_infrahub_agent_prompt_returns_content() -> None:
    result = infrahub_agent()
    assert isinstance(result, str)
    assert len(result) > 100
    assert "infrahub://schema" in result
    assert "get_nodes" in result
    assert "node_upsert" in result
    assert "session branch" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_server_prompt.py -v`
Expected: FAIL — `get_prompt("main")` raises `FileNotFoundError`

- [ ] **Step 3: Commit failing test**

```bash
git add tests/unit/test_server_prompt.py
git commit -m "test: add failing test for infrahub_agent prompt"
```

---

### Task 2: Replace `infrahub_agent()` with dynamic prompt

**Files:**
- Modify: `src/infrahub_mcp/server.py:50-53`

- [ ] **Step 1: Replace `infrahub_agent()` in `server.py`**

Replace lines 50-53 in `src/infrahub_mcp/server.py`:

```python
@mcp.prompt()
def infrahub_agent() -> str:
    """System prompt for the Infrahub infrastructure agent."""
    return get_prompt("main")
```

With a dynamic version that reproduces the essential content from the deleted `main.md`:

```python
@mcp.prompt()
def infrahub_agent() -> str:
    """System prompt for the Infrahub infrastructure agent."""
    return """You are an infrastructure specialist with read and write access to Infrahub — a graph-based infrastructure data management platform.

## Data formats

Structured arrays (schema details, node attribute results) are encoded in **TOON** (Token-Oriented Object Notation) to reduce token usage. TOON declares field names once in a header, then lists rows of values. Treat TOON exactly like a table: the header is the column spec, each indented row is one record.

## Available context (resources — read before tool calls)

| Resource | What it contains |
|---|---|
| `infrahub://schema` | All node kinds available in this instance |
| `infrahub://schema/{kind}` | Full schema + filter map for a specific kind |
| `infrahub://graphql-schema` | Complete GraphQL SDL for advanced queries |
| `infrahub://branches` | All branches, including your active session branch |

Read these resources first to avoid guessing kind names or filter keys.

## Available tools

### Read
- **`get_nodes`** — retrieve objects of a given kind, with optional filters. Pass `include_attributes=True` for full attribute data.
- **`search_nodes`** — find nodes by partial name match.
- **`query_graphql`** — execute any GraphQL query or mutation.

### Write
- **`node_upsert`** — create or update a node. Omit `id`/`hfid` to create; supply one to update.
- **`node_delete`** — delete a node by `id` or `hfid`.
- **`propose_changes`** — open a proposed change from your session branch to `main` for human review.

## Branch-per-session workflow

All writes are branch-isolated. On your first write, a session branch is automatically created (`mcp/session-YYYYMMDD-<hex>`). The default branch is never modified directly.

When changes are ready: call `propose_changes(title, description)` to open a proposed change for human review.

## Safety rules

- Never modify the default branch directly.
- Prefer `node_upsert` over raw GraphQL mutations for simple attribute changes.
- Always confirm with the user before deleting nodes."""
```

- [ ] **Step 2: Remove `get_prompt` import from `server.py`**

In `src/infrahub_mcp/server.py` line 15, change:

```python
from infrahub_mcp.utils import AppContext, get_prompt
```

to:

```python
from infrahub_mcp.utils import AppContext
```

- [ ] **Step 3: Run the test from Task 1 to verify it passes**

Run: `uv run pytest tests/unit/test_server_prompt.py -v`
Expected: PASS

- [ ] **Step 4: Run the full unit test suite**

Run: `uv run pytest tests/unit/ -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/infrahub_mcp/server.py tests/unit/test_server_prompt.py
git commit -m "fix: replace file-based infrahub_agent prompt with inline content"
```

---

### Task 3: Remove dead `get_prompt()` function

**Files:**
- Modify: `src/infrahub_mcp/utils.py:45-49`

- [ ] **Step 1: Verify `get_prompt` has no remaining callers**

Run: `grep -r "get_prompt" src/ tests/` — should only appear in `utils.py` definition and `tests/integration/conftest.py` (which we fix in Task 4).

- [ ] **Step 2: Remove `get_prompt()` from `utils.py`**

Delete lines 45-49 of `src/infrahub_mcp/utils.py`:

```python
def get_prompt(name: str) -> str:
    prompt_file = PROMPTS_DIRECTORY / f"{name}.md"
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file '{prompt_file}' does not exist.")
    return (PROMPTS_DIRECTORY / f"{name}.md").read_text()
```

Also remove the `PROMPTS_DIRECTORY` constant on line 16 if no other code references it:

```python
PROMPTS_DIRECTORY = CURRENT_DIRECTORY / "prompts"
```

- [ ] **Step 3: Run linter to check for unused import/variable warnings**

Run: `uv run pre-commit run ruff --all-files`
Expected: PASS (no new warnings)

- [ ] **Step 4: Commit**

```bash
git add src/infrahub_mcp/utils.py
git commit -m "refactor: remove unused get_prompt utility"
```

---

### Task 4: Fix integration test fixture

**Files:**
- Modify: `tests/integration/conftest.py:8,14-16`

- [ ] **Step 1: Update the `main_prompt` fixture**

Replace the fixture in `tests/integration/conftest.py` to import `infrahub_agent` directly instead of using the deleted file:

Change lines 8 and 14-16 from:

```python
from infrahub_mcp.utils import get_prompt

# ...

@pytest.fixture(scope="session")
def main_prompt() -> str:
    return get_prompt("main")
```

To:

```python
from infrahub_mcp.server import infrahub_agent

# ...

@pytest.fixture(scope="session")
def main_prompt() -> str:
    return infrahub_agent()
```

This calls the prompt function directly, which now returns an inline string. The test in `test_sandbox.py` continues to receive the same type (`str`) and doesn't need changes.

- [ ] **Step 2: Run linter**

Run: `uv run pre-commit run ruff --all-files`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/conftest.py
git commit -m "fix: update integration test fixture to use infrahub_agent directly"
```

---

### Task 5: Final verification

- [ ] **Step 1: Run full pre-commit suite**

Run: `uv run pre-commit run --all-files`
Expected: All hooks pass

- [ ] **Step 2: Run full test suite (unit)**

Run: `uv run pytest tests/unit/ -v`
Expected: All pass

- [ ] **Step 3: Run mypy**

Run: `uv run invoke lint-mypy`
Expected: Clean

- [ ] **Step 4: Verify no remaining references to `main.md` or old `get_prompt`**

Run: `grep -r "get_prompt\|main\.md" src/ tests/`
Expected: No matches (except possibly this plan file or comments)
