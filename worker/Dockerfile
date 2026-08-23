FROM ghcr.io/astral-sh/uv:0.8.22@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1 AS uv
FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY --from=uv /uv /uvx /bin/

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

# El contexto de construcción es worker/, por eso las rutas no llevan prefijo.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

COPY src ./src
RUN uv sync --frozen --no-dev --no-cache \
    && .venv/bin/playwright install --with-deps chromium \
    && chown -R app:app /app /ms-playwright

USER app

CMD ["/app/.venv/bin/restaurant-live-ops-worker", "sales"]
