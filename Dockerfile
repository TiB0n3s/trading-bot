# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-base.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install -r requirements-base.txt

COPY . .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps .

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]


FROM runtime AS research

COPY requirements-research.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-research.txt

CMD ["python", "scripts/run_tests.py"]
