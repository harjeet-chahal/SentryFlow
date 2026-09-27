# Kubernetes

Helm chart for SentryFlow. Full instructions live in
[`docs/deployment.md`](../docs/deployment.md).

```
chart/
  Chart.yaml
  values.yaml               # defaults, suitable for a dev cluster
  values-production.yaml    # EKS: ECR images, managed services, IRSA, ALB
  templates/
    _helpers.tpl            # naming, labels, shared env block
    configmap.yaml          # non-secret configuration
    secret.yaml             # dev-only; production uses External Secrets
    serviceaccount.yaml     # IRSA annotation target
    backend-deployment.yaml # probes, securityContext, zone spread
    backend-service.yaml
    backend-hpa.yaml        # CPU-based, slow scale-down
    backend-pdb.yaml        # keeps 2 pods during node drains
    aggregator-deployment.yaml
    frontend.yaml           # Deployment + Service
    ingress.yaml            # path routing: /api,/auth,/health -> backend
    migration-job.yaml      # pre-install/pre-upgrade hook, idempotent
```

## Quick start

```bash
helm lint chart --set secrets.postgresPassword=placeholder

helm upgrade --install sentryflow ./chart \
  --namespace sentryflow --create-namespace \
  --set secrets.postgresPassword="$POSTGRES_PASSWORD"
```

## Validate before committing

```bash
helm template sentryflow ./chart \
  --set secrets.postgresPassword=placeholder --set ingress.enabled=true \
  | kubeconform -kubernetes-version 1.29.0 -strict -summary
```

CI runs both on every pull request.
