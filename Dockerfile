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
    uv sync --frozen --no-dev

# ****************************************************************
# STAGE 2: Runtime — minimal image
# ****************************************************************
ARG PYTHON_VER=3.13
FROM docker.io/python:${PYTHON_VER}-slim AS runtime

LABEL io.modelcontextprotocol.server.name="infrahub-mcp"

ENV PYTHONUNBUFFERED=1
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8001

WORKDIR /app

# Copy only the virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Run as non-root user
RUN groupadd --system app && useradd --system --gid app app \
    && chown -R app:app /app
USER app

EXPOSE ${MCP_PORT}

ENTRYPOINT ["infrahub-mcp"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8001"]
