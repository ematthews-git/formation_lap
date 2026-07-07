FROM python:3.12-slim

# uv is the package manager used by the monorepo.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Workspace metadata + lockfile first so this layer is cached unless deps change.
COPY pyproject.toml uv.lock README.md ./

# All workspace members the API needs. formation-api depends on formation-data,
# which in turn depends on formation-sim — so all three must be present for
# `uv sync` to resolve the workspace and for imports to work at runtime.
COPY packages/sim ./packages/sim
COPY packages/data ./packages/data
COPY packages/api ./packages/api

# Frozen install of just the API package (+ its workspace deps) from the lockfile.
RUN uv sync --frozen --package formation-api

EXPOSE 8000

# Bind 0.0.0.0 inside the container; the host publishes it to 127.0.0.1 only and
# Caddy terminates TLS in front. --no-sync: the image is already synced above.
CMD ["uv", "run", "--no-sync", "--package", "formation-api", \
     "uvicorn", "formation_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
