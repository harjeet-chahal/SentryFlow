FROM python:3.11-slim

# The application is imported as the package `backend`, so the package must
# sit *inside* the import root rather than being unpacked over it -- copying
# the contents to /app is what made `import backend.main` fail before.
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY . /app/backend/

# Run unprivileged so the Kubernetes securityContext can enforce runAsNonRoot.
RUN useradd --create-home --uid 10001 sentryflow \
    && chown -R sentryflow:sentryflow /app
USER sentryflow

EXPOSE 8000

# Schema creation is idempotent and lives in its own init container in
# Kubernetes; this default keeps `docker compose up` a single step.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
