# FlowMap on Railway — single-service image.
#
# Stage 1 builds the React SPA; stage 2 installs the Python server
# (deps pinned by server/uv.lock, market-data engine from the vendored
# wheel — no network VCS dependency) and serves the SPA from the same
# origin via flowmap_server.railway_main.
#
# Railway injects $PORT at runtime; the entrypoint binds 0.0.0.0:$PORT.

# ---------- frontend ----------
FROM node:22-slim AS client-build
WORKDIR /build
COPY client/package.json client/package-lock.json ./client/
RUN cd client && npm ci --no-audit --no-fund
COPY client/ ./client/
RUN cd client && npm run build

# ---------- backend ----------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
COPY server/vendor/ ./vendor/
RUN uv sync --frozen --no-dev --no-install-project

COPY server/src/ ./src/
ENV PYTHONPATH=/app/server/src \
    PATH="/app/server/.venv/bin:${PATH}"

COPY --from=client-build /build/client/dist/ /app/client-dist/
ENV FLOWMAP_CLIENT_DIST=/app/client-dist

EXPOSE 8720
CMD ["python", "-m", "flowmap_server.railway_main"]
