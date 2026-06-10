# Container Image Plan — rec-inference

## Bake-vs-Mount Decision: **Mount**

The model artifact (ONNX + FAISS index, ~1.35 GB total) is **not** baked into the container image. It is downloaded from GCS at pod startup via an init container.

### Why Mount, Not Bake

**Image size.** Baking the 1.35 GB model artifact into the image produces a ~1.7 GB final image. At a GKE pull rate of ~150 MB/s, a cold pod takes ~90 s to pull the image before the process starts. The mount strategy keeps the image at ~340 MB (~15 s pull), which is critical for autoscaling responsiveness at 800 RPS peak.

**Decoupled release cadences.** The model is retrained and promoted weekly; the serving code changes far less frequently. Baking forces a full image rebuild on every model promotion — coupling two independent lifecycles. With mounting, a model rollback is a one-line patch to `MODEL_VERSION` in Helm values and a rolling pod restart (~2 min). No image rebuild, no CI run required.

**Rollback speed.** The rollback runbook (`runbooks/rollback.md`) targets <5 minutes end-to-end. A baked-image rollback requires a CI pipeline run (8–12 min minimum). Mounting makes rollback a kubectl/ArgoCD-only operation.

**Trade-off accepted.** Pod cold-start increases by ~30–60 s (GCS download of 1.35 GB at ~20 MB/s). This is acceptable because the HPA maintains a minimum of 3 warm pods at all times. The `/ready` probe's `initialDelaySeconds: 120` accounts for init container completion before traffic is routed.

**Alternative rejected: PVC volume snapshots.** A PVC pre-populated with the model would avoid the GCS download, but introduces stateful pod scheduling constraints and complicates multi-zone deployments. GCS download is simpler and sufficient at this scale.

> Full decision record: [ADR 0001 — Model Artifact Mount vs Bake](../architecture/adr/0001-model-artifact-mount-vs-bake.md)

## Base Image

`python:3.11-slim-bookworm`

- Bookworm (Debian 12) for long-term security support.
- `slim` variant strips documentation, locales, and extra packages; ~130 MB base.
- No Alpine: ONNX Runtime GPU wheels require glibc, which musl-based Alpine does not provide without significant workaround.

## Expected Image Size

| Layer | Approximate size |
|---|---|
| Base image (`python:3.11-slim-bookworm`) | 130 MB |
| ONNX Runtime 1.17 (CPU/GPU wheel) | 140 MB |
| FastAPI + uvicorn + pydantic | 25 MB |
| Other Python dependencies (redis, prometheus-client, etc.) | 30 MB |
| Application source code | 10 MB |
| **Total** | **~335 MB** |

Model artifact (not in image): 462 MB ONNX + 890 MB FAISS = **1.35 GB** at `/model/` via init container.

## Multi-Stage Build

Two stages:
1. **Builder:** `python:3.11-slim-bookworm` + `build-essential`. Creates a virtualenv and installs all dependencies. Build tools stay in this stage only.
2. **Runtime:** `python:3.11-slim-bookworm` (fresh copy). Copies only the virtualenv from the builder stage. No pip, no gcc, no build-essential in the final image.

## Security Choices

- **Non-root user:** `appuser` (UID 1001). The process never runs as root.
- **No unnecessary packages:** `apt-get install --no-install-recommends`; cache cleaned in the same `RUN` layer to avoid leaving stale package lists in image layers.
- **No secrets in image:** API keys, GCS credentials, and service account tokens are injected via Kubernetes Secrets / Workload Identity — never baked into the image or passed as build args.
- **Dependency pinning:** `requirements.txt` pins all packages to exact versions. Renovate bot opens PRs weekly for security updates.
- **Trivy scan:** Every image push is scanned by Trivy in CI/CD (see `cicd/.github/workflows/deploy-model.yml` step `Security Scan`). CRITICAL and HIGH CVEs with available fixes block the pipeline.
- **Read-only filesystem:** Kubernetes pod spec sets `readOnlyRootFilesystem: true` except for `/model` (init container writes here) and `/tmp`.

## Runtime Environment Variables

| Variable | Example value | Source |
|---|---|---|
| `MODEL_VERSION` | `v1.3.0-20260601` | Helm values (from model registry) |
| `FEATURE_SCHEMA_VERSION` | `v3` | Helm values (from model registry) |
| `MODEL_DIR` | `/model` | Default in Dockerfile |
| `SERVICE_PORT` | `8080` | Default in Dockerfile |
| `REDIS_HOST` | `10.100.0.5` | Kubernetes Secret |
| `REDIS_PORT` | `6379` | Kubernetes ConfigMap |
| `GCS_MODELS_BUCKET` | `gs://retailco-models` | Kubernetes ConfigMap |
| `WORKERS` | `1` | Default in Dockerfile |
| `LOG_LEVEL` | `info` | Kubernetes ConfigMap |

## Model Artifact Location

At runtime, the init container writes:
- `/model/rec-model-${MODEL_VERSION}.onnx` — the two-tower ONNX model
- `/model/rec-index-${MODEL_VERSION}.faiss` — the FAISS item index

The inference server loads these paths at startup. If either file is missing, the `/ready` endpoint returns `{"status": "not_ready", "reason": "model_not_loaded"}` and Kubernetes will not route traffic to the pod until the model is loaded.

## Healthcheck Behavior

Two endpoints:

| Endpoint | Type | Description |
|---|---|---|
| `GET /health` | Liveness | Returns 200 if the process is running and not deadlocked. No dependency on model state. |
| `GET /ready` | Readiness | Returns 200 only after the ONNX model is loaded, the FAISS index is loaded, and a warm-up inference pass has completed. Returns 503 otherwise. |

Kubernetes probe configuration (from Helm chart):
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 15
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 120   # Allow time for GCS download + model load
  periodSeconds: 10
  failureThreshold: 6
```

## Image Tag Format

`{SERVICE}:{git-sha}-{YYYYMMDD}` — e.g. `rec-inference:a3f9c12-20260601`

This format is consistent with:
- The CI/CD pipeline (`cicd/.github/workflows/deploy-model.yml` step `Compute image tag`)
- The model registry `serving.image_tag` field (`lifecycle/model-registry.yaml`)
- ArgoCD ApplicationSet `image.tag` parameter

The image tag is separate from the model version tag (`v1.3.0-20260601`). A single image tag can serve any model version.
