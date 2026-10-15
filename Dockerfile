# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app


# Compilers and headers only live here: psycopg2 builds against libpq
FROM base AS builder

RUN apt-get update -y && \
    apt-get install -y --no-install-recommends build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements_dev.txt ./
RUN pip wheel --wheel-dir /wheels -r requirements_dev.txt


# Runtime dependencies installed from the builder's wheels, which stay out of the layers
FROM base AS runtime

RUN apt-get update -y && \
    apt-get install -y --no-install-recommends libpq5 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    pip install --no-index --find-links=/wheels -r requirements.txt


FROM runtime AS development

COPY requirements_dev.txt .
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    pip install --no-index --find-links=/wheels -r requirements_dev.txt

COPY . .

EXPOSE 3000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3000", "--reload"]


FROM runtime AS production

RUN groupadd --system --gid 10001 app && \
    useradd --system --uid 10001 --gid app --no-create-home --home-dir /app app

# Owned by root: the app user can read the code but not change it
COPY alembic.ini main.py ./
COPY alembic ./alembic
COPY config ./config
COPY src ./src

# uvicorn reads both: WEB_CONCURRENCY is the number of workers, and the API is
# only reachable through the reverse proxy on the internal network (ADR-0011),
# so its X-Forwarded-* headers are trusted
ENV WEB_CONCURRENCY=2 \
    FORWARDED_ALLOW_IPS="*"

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/live', timeout=4)"]

# With several workers uvicorn imports the app only in the children and restarts
# them forever if that fails, so check the settings first and exit with the error
CMD ["sh", "-c", "python -c 'import config' && exec uvicorn main:app --host 0.0.0.0 --port 8080 --proxy-headers"]
