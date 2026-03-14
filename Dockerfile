FROM python:3.13-slim

WORKDIR /app

# Install uv for fast, deterministic installs
RUN pip install --no-cache-dir uv

# Install dependencies first (layer-cached separately from source)
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

# Copy source
COPY src/ ./src/

EXPOSE 8001

ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8001

CMD ["uv", "run", "fastmcp", "run", "src/infrahub_mcp/server.py:mcp", \
     "--transport", "streamable-http", \
     "--host", "0.0.0.0", \
     "--port", "8001"]
