# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ---------- 运行阶段 ----------
FROM python:3.12-slim AS runtime

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:${PATH}" \
    PYTHONPATH=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r appgrp && useradd -r -g appgrp -d /app appusr

COPY --from=builder /install /install
COPY --chown=appusr:appgrp . /app

RUN mkdir -p /app/data /app/logs && chown -R appusr:appgrp /app
USER appusr

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["sh", "-c", "\
    if [ \"$RUN_MIGRATIONS\" = \"true\" ]; then alembic upgrade head; fi; \
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS:-1} \
    --proxy-headers --forwarded-allow-ips='*'"]
