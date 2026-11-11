FROM python:3.12-slim

# uv is the package manager used by the monorepo
RUN pip install --no-cache-dir uv==0.13.7

# Use the image's own Python 3.12 (version pinned by .python-version). Recent uv
# releases default to uv-managed interpreters and, unpinned, downloaded the newest
# CPython (3.14, then 3.15), which has no psycopg2-binary wheels, so the build broke.
ENV UV_PYTHON_PREFERENCE=only-system

WORKDIR /app
COPY pyproject.toml uv.lock README.md .python-version ./
# formation-data depends on formation-sim (workspace), so its package dir must be
# present for `uv sync` to resolve the lockfile.
COPY packages/sim ./packages/sim
COPY packages/data ./packages/data
COPY packages/api ./packages/api

RUN uv sync --frozen --package formation-data

ENTRYPOINT ["uv", "run", "--package", "formation-data", "formation-data"]
CMD ["--help"]
