# netstead self-hostable HTTP server image.
#
# What it ships:
#   - Python 3.13 slim base
#   - netstead + corral from PyPI (built from source until v1.0 GA)
#   - `[server]` extra (FastAPI + uvicorn + pydantic-settings + httpx)
#   - `[mcp]` extra (lets the same image also serve `netstead mcp serve`)
#   - `[clean]` extra (shapely + igraph + pyproj — many users want the
#     full surface; image stays under 1 GB even with these)
#
# What it does NOT ship:
#   - Your network data. Mount it at /data, point --config at it.
#   - TLS termination. Put this behind your own reverse proxy.
#   - Auth secrets. Pass via env or mounted config.
#
# Run:
#   docker run --rm -p 8000:8000 \
#       -v $(pwd)/config.yml:/etc/netstead/config.yml:ro \
#       -v $(pwd)/data:/data:ro \
#       ghcr.io/e-lo/netstead:latest
#
# Compose example: docker-compose.example.yml (next to this file).
#
# Build context: this file is in packages/netstead/ but the build needs
# both packages/corral and packages/netstead (workspace install). CI
# builds with `docker build -f packages/netstead/Dockerfile .` from the
# REPO ROOT so both subtrees are in scope.

FROM python:3.13-slim AS builder

# uv for fast workspace install. Pin to a stable release.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

# OS packages required by some of the optional-extra wheels (mostly
# the geo stack — shapely, pyproj — even though manylinux wheels are
# the norm, having geos + proj headers keeps us safe on arches where
# wheels aren't published).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgeos-c1v5 libproj25 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy the FULL workspace so uv can resolve corral as a local path
# dependency. (corral isn't on PyPI yet at v1.0; once it is, we
# can switch to `uv pip install netstead[server,mcp,clean]` here.)
COPY pyproject.toml uv.lock ./
COPY packages/ ./packages/

# Install BOTH packages with the extras we want shipped.
RUN uv venv /opt/netstead-venv \
    && uv pip install --python /opt/netstead-venv/bin/python \
        --no-cache \
        -e ./packages/corral \
        -e './packages/netstead[server,mcp,clean]'

# ---------------------------------------------------------------------------
# Runtime stage. Slim image, no build toolchain, just the venv + binaries.
# ---------------------------------------------------------------------------
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgeos-c1v5 libproj25 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash netstead

COPY --from=builder /opt/netstead-venv /opt/netstead-venv

# Workspace source — netstead[server] is installed as editable so it
# resolves back to these paths at import time. Strictly we could
# `--no-editable` the wheel install above; keeping editable matches
# what local devs see and makes hotfixing easier in a pinch.
COPY --from=builder /build /workspace
ENV PATH="/opt/netstead-venv/bin:${PATH}"

WORKDIR /workspace
USER netstead

# Standard server port. Override with --port at run time.
EXPOSE 8000

# Default config lives at /etc/netstead/config.yml — mount your own
# there. The `--bind 0.0.0.0` is required for the port to be
# reachable from outside the container; behind a reverse proxy this
# is fine. For direct exposure to the public internet, set up TLS
# at the proxy layer and configure bearer auth in your config.
CMD ["netstead", "server", "run", \
     "--config", "/etc/netstead/config.yml", \
     "--bind", "0.0.0.0", \
     "--port", "8000"]
