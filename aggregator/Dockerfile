FROM python:3.11-slim

# Imported as the package `aggregator` (it shares nothing with the backend
# image, but the same layout keeps `python -m` and the tests identical).
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY requirements.txt /app/aggregator/requirements.txt
RUN pip install --no-cache-dir -r /app/aggregator/requirements.txt

COPY . /app/aggregator/

# Run unprivileged so the Kubernetes securityContext can enforce runAsNonRoot.
RUN useradd --create-home --uid 10001 sentryflow \
    && chown -R sentryflow:sentryflow /app
USER sentryflow

CMD ["python", "-m", "aggregator.batch_consumer"]
