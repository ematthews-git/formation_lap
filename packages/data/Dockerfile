FROM python:3.12-slim

# uv is the package manager used by the monorepo
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
# formation-data depends on formation-sim (workspace), so its package dir must be
# present for `uv sync` to resolve the lockfile.
COPY packages/sim ./packages/sim
COPY packages/data ./packages/data
COPY packages/api ./packages/api

RUN uv sync --frozen --package formation-data

ENTRYPOINT ["uv", "run", "--package", "formation-data", "formation-data"]
CMD ["--help"]
