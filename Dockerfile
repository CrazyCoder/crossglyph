# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.12.14

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bash ca-certificates coreutils curl gzip procps tar \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
COPY tools/uv.cmd tools/tool-wrapper.sh ./tools/
RUN chmod +x tools/uv.cmd tools/tool-wrapper.sh
RUN --mount=type=cache,target=/root/.cache \
    tools/uv.cmd sync --frozen --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache \
    tools/uv.cmd sync --frozen --no-dev --no-editable

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="CrossGlyph" \
      org.opencontainers.image.description="Build and tune CrossPoint .cpfont families" \
      org.opencontainers.image.source="https://github.com/CrazyCoder/crossglyph" \
      org.opencontainers.image.licenses="MIT"

ENV CROSSGLYPH_FONTS=/workspace \
    CROSSGLYPH_HOME=/app \
    CROSSGLYPH_HOST=0.0.0.0 \
    CROSSGLYPH_INSTALL_KIND=container \
    CROSSGLYPH_UPDATE_STATE=/tmp/crossglyph-update-state.json \
    HOME=/tmp \
    PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 1000 crossglyph \
    && useradd --uid 1000 --gid crossglyph --no-create-home \
        --home-dir /tmp --shell /usr/sbin/nologin crossglyph \
    && mkdir /workspace \
    && chown crossglyph:crossglyph /workspace

WORKDIR /app
COPY --from=builder --chown=crossglyph:crossglyph /app/.venv /app/.venv
COPY --chown=crossglyph:crossglyph LICENSE ./

USER crossglyph
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=2).read(1)"

ENTRYPOINT ["crossglyph"]
CMD ["preview", "--no-open"]
