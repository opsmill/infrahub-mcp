# ****************************************************************
# STAGE 1: Builder — install dependencies with uv
# ****************************************************************
ARG PYTHON_VER=3.13
FROM docker.io/python:${PYTHON_VER}-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT="/opt/venv"
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-install-workspace

COPY README.md ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ****************************************************************
# STAGE 2: Runtime — minimal image
# ****************************************************************
ARG PYTHON_VER=3.13
FROM docker.io/python:${PYTHON_VER}-slim AS runtime

ENV PYTHONUNBUFFERED=1
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8001

WORKDIR /app

# Copy only the virtual environment and source from builder
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src ./src/
COPY --from=builder /app/pyproject.toml ./

# Activate the virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Run as non-root user
RUN groupadd --system app && useradd --system --gid app app \
    && chown -R app:app /app
USER app

EXPOSE ${MCP_PORT}

# Exec form with explicit shell for $MCP_HOST / $MCP_PORT expansion at runtime
# (configurable via docker-compose env or `docker run -e`)
CMD ["/bin/sh", "-c", "fastmcp run src/infrahub_mcp/server.py:mcp --transport streamable-http --host \"$MCP_HOST\" --port \"$MCP_PORT\""]
