FROM python:3.12-slim

# uv is the package manager used by the monorepo.
RUN pip install --no-cache-dir uv==0.13.7

# Use the image's own Python 3.12 (version pinned by .python-version). Recent uv
# releases default to uv-managed interpreters and, unpinned, downloaded the newest
# CPython (3.14, then 3.15), which has no psycopg2-binary wheels, so the build broke.
ENV UV_PYTHON_PREFERENCE=only-system

WORKDIR /app

# Workspace metadata + lockfile first so this layer is cached unless deps change.
COPY pyproject.toml uv.lock README.md .python-version ./

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
