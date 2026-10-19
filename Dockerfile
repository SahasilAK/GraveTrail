FROM ghcr.io/astral-sh/uv:0.12.5 AS uv
FROM python:3.11-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /build
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY ui/ ./ui/
COPY prompts/ ./prompts/
COPY app.py ./
COPY scripts/build/hatch_assets.py ./scripts/build/hatch_assets.py
COPY .streamlit/config.toml ./.streamlit/config.toml
RUN uv sync --locked --no-dev --no-editable --no-cache

FROM python:3.11-slim-bookworm AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --create-home gravetrail && mkdir /data && chown gravetrail:gravetrail /data
COPY --from=build /build/.venv /build/.venv
ENV PATH="/build/.venv/bin:$PATH" DATAFORGE_HOME=/data PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /data
USER 10001:10001
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')"
CMD ["gravetrail-ui", "--address", "0.0.0.0", "--no-browser"]
