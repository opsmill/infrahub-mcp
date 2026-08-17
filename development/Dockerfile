# ****************************************************************
# STAGE 1: Builder — install dependencies with uv
# ****************************************************************
ARG PYTHON_VER=3.13
FROM ghcr.io/astral-sh/uv:0.7-python${PYTHON_VER}-bookworm-slim AS builder

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT="/opt/venv"
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-install-workspace

COPY README.md ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ****************************************************************
# STAGE 2: Runtime — minimal image
# ****************************************************************
ARG PYTHON_VER=3.13
FROM docker.io/python:${PYTHON_VER}-slim AS runtime

LABEL io.modelcontextprotocol.server.name="infrahub-mcp"

# curl backs the HEALTHCHECK below and the compose-level probes in downstream
# stacks (opsmill/infrahub-solution-ai-dc#70). Deliberately not version-pinned:
# Debian drops superseded versions from the archive (trixie is already at
# 8.14.1-2+deb13u4), so an exact pin breaks the build on the next security update.
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install --no-install-recommends -y curl && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8001

WORKDIR /app

# Copy only the virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Run as non-root user
RUN groupadd --system app && useradd --system --gid app --create-home app \
    && chown -R app:app /app
USER app

EXPOSE ${MCP_PORT}

# /health returns 503 until Infrahub is reachable, hence the generous start
# period. In shared-credential modes it makes a live get_version() round-trip,
# so the budget leaves room for a slow Infrahub. --max-time stays just under
# --timeout so a slow probe reports curl's exit 28 rather than an opaque kill.
# A compose-level healthcheck overrides this one where one is declared.
HEALTHCHECK --interval=15s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -fsSL --max-time 8 -o /dev/null -w '%{http_code}' http://localhost:${MCP_PORT}/health

CMD ["sh", "-c", "exec infrahub-mcp --transport streamable-http --host $MCP_HOST --port $MCP_PORT"]
