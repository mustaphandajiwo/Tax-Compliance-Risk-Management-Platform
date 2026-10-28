# NGSIRS CRM API / worker image. Build from the repository root:
#   docker build -f infra/docker/api.Dockerfile -t ngsirs-crm-api .
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api apps/api
COPY services services
RUN uv sync --frozen --no-dev

FROM python:3.13-slim
RUN groupadd --system ngsirs && useradd --system --gid ngsirs --home /app ngsirs
WORKDIR /app
COPY --from=build /app /app
COPY fixtures fixtures
COPY tools tools
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 NGSIRS_STORAGE_PATH=/data/objects
RUN mkdir -p /data/objects /data/keys && chown -R ngsirs:ngsirs /data
USER ngsirs
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1
CMD ["uvicorn", "ngsirs_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
