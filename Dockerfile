# syntax=docker/dockerfile:1.7

FROM python:3.13-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /uvx /bin/


# =========================
# 1. DEPENDENCIES LAYER
# =========================
FROM base AS deps

COPY pyproject.toml uv.lock ./

# создаём venv + ставим зависимости
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"


# =========================
# 2. APP LAYER
# =========================
FROM base AS build

COPY app/ ./app/


# =========================
# 3. RUNTIME (MINIMAL)
# =========================
FROM base AS runtime

RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

# перенос готового venv
COPY --from=deps /app/.venv /app/.venv

# код отдельно
COPY --from=build /app/app /app/app

ENV PATH="/app/.venv/bin:$PATH"

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; \
urllib.request.urlopen('http://localhost:8000/ready')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
