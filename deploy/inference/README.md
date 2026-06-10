# deploy/inference — Helm-style Deployment Placeholder

## Purpose

This directory is a **reviewable Helm-style deployment placeholder** included
in the Scenario X MLOps assessment dossier.

It exists because the CI/CD workflow (`cicd/.github/workflows/deploy-model.yml`)
references `deploy/inference/` at multiple points — for Helm installs, `yq`
patches, and feature-schema validation — and the repository must be coherent
for assessment review.

---

## Structure

```
deploy/inference/
├── Chart.yaml                  Helm chart metadata
├── values.yaml                 Default values (base)
├── values-staging.yaml         Staging overrides
├── values-prod.yaml            Production overrides
├── templates/
│   ├── deployment.yaml         Kubernetes Deployment
│   ├── service.yaml            ClusterIP Service
│   ├── hpa.yaml                HorizontalPodAutoscaler
│   └── configmap.yaml          Non-secret operational config
└── README.md                   This file
```

---

## Environment-specific values

| File                  | Purpose                                         |
|-----------------------|-------------------------------------------------|
| `values.yaml`         | Shared defaults; applied to all environments    |
| `values-staging.yaml` | Overrides for staging (lower replicas, DEBUG)   |
| `values-prod.yaml`    | Overrides for production (4+ replicas, WARNING) |

CI/CD applies the relevant override file via `--values`:

```bash
# Staging
helm upgrade --install rec-inference deploy/inference \
  --values deploy/inference/values-staging.yaml ...

# Production
helm upgrade --install rec-inference deploy/inference \
  --values deploy/inference/values-prod.yaml ...
```

---

## Model artifact strategy: mounted, not baked

The model artifact (~1.35 GB total: 462 MB ONNX + 890 MB FAISS index) is
**mounted at runtime**, not embedded in the container image.

An init container pulls the versioned artifacts from GCS
(`gs://retailco-models`) and places them at `/mnt/models` before the inference
server starts. This keeps image sizes small and allows model-only updates
without rebuilding or re-scanning the container image.

The mount path is controlled by `modelArtifact.mountPath` in `values.yaml`
(default: `/mnt/models`) and surfaced to the container as the `MODEL_ARTIFACT_PATH`
environment variable.

---

## Health and readiness endpoints

| Probe       | Path     | Notes                              |
|-------------|----------|------------------------------------|
| Liveness    | `/health` | Returns 200 when process is alive |
| Readiness   | `/ready`  | Returns 200 when model is loaded  |

Both probes use these exact paths everywhere: `values.yaml`, `values-staging.yaml`,
`values-prod.yaml`, `templates/deployment.yaml`, and `templates/configmap.yaml`.

Legacy health-check paths are intentionally not used in this chart.

---

## Secrets and credentials

Real cloud credentials (GCP service account keys, Redis passwords, API tokens)
are **intentionally not included** in any values file. They are injected at
deploy time via:

- GitHub Actions secrets (`${{ secrets.GCP_SA_KEY }}`, etc.)
- Kubernetes Secrets created out-of-band via Workload Identity or Secret Manager
- `--set` flags in the `helm upgrade` commands inside the workflow

---

## API endpoints (unchanged)

This chart serves the following endpoints (defined in `api/openapi.yaml`):

| Method | Path                                    | Description           |
|--------|-----------------------------------------|-----------------------|
| POST   | `/v1/recommendations`                   | Sync inference        |
| POST   | `/v1/recommendations:batch`             | Batch inference       |
| POST   | `/v1/recommendation-jobs`               | Async job submit      |
| GET    | `/v1/recommendation-jobs/{job_id}`      | Async job result      |
| GET    | `/health`                               | Liveness probe        |
| GET    | `/ready`                                | Readiness probe       |

---

## Related files

- `cicd/.github/workflows/deploy-model.yml` — CI/CD pipeline that references this directory
- `serving/capacity-plan.md` — replica sizing rationale (800 RPS, p95 ≤ 120 ms)
- `serving/slos.yaml` — SLO definitions
- `lifecycle/model-registry.yaml` — model registry state machine
