# Deployment

SentryFlow ships three images — `backend`, `aggregator`, `frontend` — plus a
Helm chart. Local development runs everything in Docker Compose; production
runs on EKS with the stateful dependencies moved to managed AWS services.

## Contents

- [Local development](#local-development)
- [Container images](#container-images)
- [Kubernetes](#kubernetes)
- [AWS / EKS](#aws--eks)
- [Operations](#operations)

---

## Local development

Compose brings up the gateway, aggregator, dashboard and every dependency
(Postgres, Redis, Kafka in KRaft mode, ClickHouse):

```bash
SENTRYFLOW_ADMIN_PASSWORD=choose-one docker compose up -d --build
```

| Service | URL |
| --- | --- |
| Dashboard | http://localhost |
| Gateway | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Kafka UI | http://localhost:8080, with `--profile tools` |

Start-up is ordered by health checks. A one-shot `migrate` service runs
`python -m backend.setup_db` once Postgres is ready; the gateway starts after it
succeeds and Kafka is healthy. (The gateway would also start without Kafka and
connect once it arrives; waiting keeps the start-up log free of retries.)
`setup_db` is idempotent: it creates missing tables, applies additive
upgrades, creates the `admin` account if absent, and seeds a catch-all rate
limit. Without `SENTRYFLOW_ADMIN_PASSWORD` it generates a password and prints
it once: `docker compose logs migrate`.

The aggregator creates the ClickHouse table and the Kafka topics itself on
start-up, so a fresh stack needs no manual steps. Events from a request reach
the dashboard in about 2–3 seconds.

The dashboard image is built with `REACT_APP_API_URL=""`, so the browser calls
its own origin, and nginx proxies `/api`, `/auth`, `/health`, `/analytics` and
`/limits` to the gateway. The ingress routes the same paths in Kubernetes.

If a host port is taken, move it: `BACKEND_PORT`, `DASHBOARD_PORT`,
`POSTGRES_PORT`, `REDIS_PORT`, `KAFKA_PORT`, `CLICKHOUSE_HTTP_PORT`,
`CLICKHOUSE_NATIVE_PORT`, `KAFKA_UI_PORT`.

To run without containers, see the repository README. To load-test the stack,
see [load-testing.md](load-testing.md).

---

## Container images

The backend image installs the package at `/app/backend` and puts `/app` on
`PYTHONPATH`, because the code imports itself as `backend.*`. All three images
run as a non-root user so the Kubernetes `securityContext` can enforce
`runAsNonRoot`.

```bash
docker build -t sentryflow-backend:$(git rev-parse --short HEAD) ./backend
docker build -t sentryflow-aggregator:$(git rev-parse --short HEAD) ./aggregator
docker build -t sentryflow-frontend:$(git rev-parse --short HEAD) ./frontend
```

The frontend serves from `nginx-unprivileged` on port **8080**, not 80. Its
API base URL is baked in at build time (`--build-arg REACT_APP_API_URL=...`);
the default, empty, means same-origin behind the ingress.

---

## Kubernetes

The chart lives in [`kubernetes/chart`](../kubernetes/chart).

```bash
helm lint kubernetes/chart --set secrets.postgresPassword=placeholder

helm upgrade --install sentryflow ./kubernetes/chart \
  --namespace sentryflow --create-namespace \
  --set secrets.postgresPassword="$POSTGRES_PASSWORD" \
  --set image.tag="$(git rev-parse --short HEAD)"
```

What the chart renders: a backend Deployment + Service + HPA +
PodDisruptionBudget, an aggregator Deployment, a frontend Deployment +
Service, a ConfigMap, a Secret, a ServiceAccount, an optional Ingress, and a
pre-install/pre-upgrade Job that runs `setup_db`.

### Probes

The three health endpoints are deliberately different, and the chart wires
each to its matching probe:

| Endpoint | Probe | Checks |
| --- | --- | --- |
| `/health/live` | liveness, startup | nothing |
| `/health/ready` | readiness | Postgres, Redis |
| `/health` | none (operators) | Postgres, Redis, Kafka, with timings |

Liveness intentionally touches no dependency. A liveness probe that checked
Redis would restart every pod in the fleet during a Redis blip, converting a
degraded dependency into a full outage. Readiness checks only what is needed
to answer a request, so an affected pod leaves the Service endpoints and
rejoins on recovery without a restart.

Kafka is excluded from readiness because requests never wait on it: they
queue usage events for a background publisher, which reconnects on its own,
so restarting the pod would fix nothing. `/health` reports Kafka trouble as
`degraded`, with counts of queued, dropped and failed events.

### Validating changes

Rendered manifests are checked against the real Kubernetes schemas in CI:

```bash
helm template sentryflow kubernetes/chart \
  --set secrets.postgresPassword=placeholder --set ingress.enabled=true \
  | kubeconform -kubernetes-version 1.29.0 -strict -summary
```

---

## AWS / EKS

Production replaces the in-cluster stateful services with managed ones. The
cluster then runs only stateless workloads, which is what makes the node group
disposable.

| Component | AWS service |
| --- | --- |
| Postgres | RDS for PostgreSQL (Multi-AZ) |
| Redis | ElastiCache for Redis |
| Kafka | MSK |
| Images | ECR |
| Ingress | ALB via the AWS Load Balancer Controller |
| Secrets | Secrets Manager, projected by External Secrets Operator |
| ClickHouse | self-managed on EC2 or EBS-backed StatefulSet |

### 1. Push images to ECR

```bash
ACCOUNT=123456789012
REGION=us-east-1
REGISTRY=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com
TAG=$(git rev-parse --short HEAD)

aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin $REGISTRY

for svc in backend aggregator frontend; do
  docker build -t $REGISTRY/sentryflow-$svc:$TAG ./$svc
  docker push $REGISTRY/sentryflow-$svc:$TAG
done
```

Tag with the commit SHA rather than `latest`, so a rollback is a redeploy of a
known tag and the HPA never pulls a different image mid-scale-up.

### 2. Credentials via IRSA

Pods assume an IAM role instead of holding static keys. Annotate the
ServiceAccount (already templated in `values-production.yaml`):

```yaml
serviceAccount:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/sentryflow-app
```

### 3. Secrets

Nothing sensitive belongs in Git or in `--set`. Store the database password,
JWT signing key and ClickHouse credentials in Secrets Manager and let External
Secrets Operator project them into a Kubernetes Secret named
`sentryflow-secrets`; the chart then consumes it via `secrets.existingSecret`.
The gateway only reads ClickHouse, so give it a user with read access; the
aggregator needs insert and create on the `sentryflow` database.

#### Kafka topics on MSK

MSK disables topic auto-creation by default. The aggregator creates
`api-requests` and `rate-limited-events` on start-up if it is allowed to
(`aggregator.topicPartitions`, `aggregator.topicReplication`: 3 and 3 in
`values-production.yaml`). If your ACLs forbid that, create them beforehand;
the aggregator logs a warning and carries on when creation is refused.

The application refuses to start when `ENVIRONMENT=production` and
`JWT_SECRET` is unset, rather than falling back to a guessable default.

### 4. Deploy

```bash
aws eks update-kubeconfig --name sentryflow --region $REGION

helm upgrade --install sentryflow ./kubernetes/chart \
  --namespace sentryflow --create-namespace \
  -f ./kubernetes/chart/values-production.yaml \
  --set image.tag=$TAG \
  --wait --timeout 10m
```

`--wait` blocks until the new pods pass their readiness probes, so a failed
rollout surfaces in the pipeline rather than in production traffic.

### 5. Verify

```bash
kubectl -n sentryflow get pods -w
kubectl -n sentryflow exec deploy/sentryflow-backend -- \
  python -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://localhost:8000/health')))"
```

---

## Operations

### Rollback

```bash
helm rollback sentryflow --namespace sentryflow
```

The migration job only adds tables, columns and indexes and seeds absent
rows, so rolling the application back does not require a schema rollback.

### Administrators

The migration job creates `admin`. To promote another account:

```bash
kubectl -n sentryflow exec deploy/sentryflow-backend -- \
  python -m backend.setup_db --grant-admin alice
```

An existing account that happens to be named `admin` is never promoted
automatically: it could have come through public sign-up.

### Scaling

The backend is I/O bound — it awaits Redis and Postgres rather than burning
CPU — so it scales on CPU utilisation with a deliberately slow scale-down
(300s stabilisation) to avoid thrashing on spiky traffic.

The aggregator is a Kafka consumer group: replicas beyond the topic's
partition count sit idle. Scale partitions first, then replicas.

### Rate limiter behaviour during a Redis outage

`RATE_LIMIT_FAIL_OPEN` defaults to `true`: if Redis is unreachable, requests
are served without enforcement. Losing the limiter degrades enforcement rather
than causing an API outage. Set it to `false` where over-admission is worse
than unavailability.

### Logs

```bash
kubectl -n sentryflow logs -l app.kubernetes.io/component=backend --tail=100 -f
kubectl -n sentryflow logs -l app.kubernetes.io/component=aggregator --tail=100 -f
```
