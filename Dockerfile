# OpenEPW hosted image: the chat UI built with Node, served by the Python API on one port.
# Data (catalog, chat sessions, jobs, downloads) lives on a mounted disk at /var/data.

FROM node:22-slim AS web
WORKDIR /web
COPY web/chat-ui/package.json web/chat-ui/package-lock.json ./
RUN npm ci
COPY web/chat-ui/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OPENEPW_DATA_ROOT=/var/data/openepw \
    OPENEPW_WEB_ROOT=/app/web
# glibc gives each thread its own memory arena, and a threaded server then grows by free memory
# it never returns; two arenas bound that (the server is one process with worker threads).
ENV MALLOC_ARENA_MAX=2
WORKDIR /app
COPY pyproject.toml README.md LICENSE* ./
COPY src ./src
# api: the web server; harness: the model parser for chat; cds: Copernicus downloads.
RUN pip install ".[api,harness,cds]" && useradd --system --create-home --uid 10001 app
COPY --from=web /web/dist /app/web
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod 0755 /app/entrypoint.sh
EXPOSE 10000
ENTRYPOINT ["/app/entrypoint.sh"]
