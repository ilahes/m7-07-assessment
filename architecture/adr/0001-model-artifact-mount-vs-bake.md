# ADR 0001 — Model Artifact: Mount from GCS vs Bake into Container Image

**Status:** Accepted  
**Date:** 2026-05-28  
**Deciders:** Alice Chen (ML Lead), David Park (Platform Lead)  
**Scenario:** Scenario X — Personalized In-App Recommendations

---

## Context

The recommendation model (ONNX two-tower + FAISS item index) is ~1.35 GB total (462 MB ONNX + 890 MB FAISS). The model is retrained weekly and promoted via a registry-gated pipeline. The serving container (`rec-inference`) needs access to the model at runtime.

Two strategies are possible:

1. **Bake** the model artifact into the container image at build time (COPY during Docker build).
2. **Mount** the model artifact at pod startup, downloading from GCS via an init container.

This is the most consequential infrastructure decision for the inference service because it determines:
- Container image size and pull latency
- Coupling between model lifecycle and container lifecycle
- Rollback speed and procedure

---

## Decision

**Mount the model artifact from GCS at pod startup via an init container.**

The init container runs `gsutil cp gs://retailco-models/rec-model-${MODEL_VERSION}.onnx /model/` and `gsutil cp gs://retailco-models/rec-index-${MODEL_VERSION}.faiss /model/` before the inference server starts. The `MODEL_VERSION` value is injected as an environment variable by the Helm chart, controlled by the `modelVersion` parameter in `values.yaml`.

---

## Consequences

**Positive:**
- Container image remains ~350 MB (Python slim + ONNX Runtime + dependencies), not ~1.7 GB.
- Image pull time on new pods: ~15 s vs ~90 s for a baked image, improving autoscaling responsiveness.
- Model rollback = patch `MODEL_VERSION` env var + rolling restart. No image rebuild, no CI/CD pipeline run required. Target rollback time: <5 minutes.
- The same container image can serve any model version; model and code have independent release cadences.
- Container layer cache is not invalidated on every weekly model retrain.

**Negative:**
- Pod cold-start time increases by ~30–60 s (GCS download of 1.35 GB at ~20 MB/s within us-central1). Acceptable because HPA maintains min=6 warm pods; scale-out events are infrequent and gradual.
- Dependency on GCS availability at pod startup. Mitigation: GCS has 99.9% availability SLA; an init container retry loop (3 attempts, 10 s backoff) handles transient errors. If GCS is unavailable, pods will not start — this is safer than serving a stale model.
- Model artifact must be in GCS before deployment. Enforced by the CI/CD `validate-model-registry` job, which fails if the artifact is missing.

---

## Alternatives Considered

### Option A: Bake into image (rejected)

| Criterion | Score |
|---|---|
| Image size | ❌ ~1.7 GB — slow pulls, expensive registry storage |
| Rollback speed | ❌ Requires new image build + push + deploy (~15 min pipeline) |
| Release coupling | ❌ Every model retrain requires a new image tag and container deploy |
| Startup latency | ✅ No init container overhead |

Rejected because the rollback speed requirement (<5 min) cannot be met with a baked image.

### Option B: Persistent Volume (NFS / Cloud Filestore) (rejected)

Pre-populate a PVC with the model artifact and mount it into the inference pod.

Rejected because: Cloud Filestore NFS latency is higher than GCS for bulk reads; multi-zone PVC availability is complex on GKE; operationally heavier than GCS for a weekly-updated artifact.

### Option C: Model server with dynamic model loading (e.g., Triton Serving) (deferred)

Triton supports loading models from GCS dynamically without pod restart. This is the preferred long-term architecture but adds operational complexity (Triton configuration, model repository layout, grpc protocol) that is out of scope for the initial deployment. ADR deferred to v2.0.

---

## References

- [Container README](../../container/README.md) — image size estimate and bake-vs-mount detail
- [Capacity Plan](../../serving/capacity-plan.md) — pod startup latency impact on autoscaling
- [Rollback Runbook](../../runbooks/rollback.md) — rollback procedure enabled by this decision
