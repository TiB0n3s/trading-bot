FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-base.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-base.txt

COPY . .
RUN pip install --no-cache-dir --no-deps .

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]


FROM runtime AS research

COPY requirements-research.txt ./
RUN pip install --no-cache-dir -r requirements-research.txt

CMD ["python", "scripts/run_tests.py"]
