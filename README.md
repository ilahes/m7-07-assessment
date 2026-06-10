# MLOps Design Dossier — Scenario X: Personalized In-App Recommendations

## Executive Summary

This repository contains the complete MLOps design for a real-time personalized product recommendation system serving a B2C mobile retail application. On every home-screen load, the system retrieves the user's last 30 days of browsing and purchase history from a low-latency feature store, runs inference against a trained two-tower neural retrieval model, re-ranks the top candidates against live inventory and pricing signals, and returns a ranked list of up to 20 product recommendations — all within a 120 ms end-to-end p95 budget at 800 RPS peak load. Cold-start users (no purchase or browsing history) receive popularity-based fallback recommendations served from a pre-computed cache. The product team runs continuous A/B experiments against challenger models; the architecture separates the serving container image from the model artifact so that new model versions can be promoted, traffic-split, or rolled back in under five minutes without a container rebuild or redeployment.

## Architecture Diagram

See [`architecture/architecture.md`](architecture/architecture.md) for the full Mermaid diagram and request-flow walkthrough.

```
Mobile App → API Gateway → Recommendation API
                               ├── Feature Store (Redis)       ← user history
                               ├── Model Inference Service     ← two-tower model
                               ├── Product Catalog Cache       ← inventory/price
                               └── Experiment Service          ← A/B routing
```

## Key Numbers

| Metric | Value |
|---|---|
| Peak RPS | 800 |
| p95 end-to-end latency budget | 120 ms |
| Latency breakdown (gateway / feature / inference / ranking / serial.) | 5 / 20 / 60 / 20 / 5 ms |
| Availability SLO | 99.9% (43 min/month downtime budget) |
| p95 latency SLO | ≤ 120 ms (measured at API gateway) |
| Error rate SLO | ≤ 0.5% 5xx over any 5-minute window |
| Model artifact size | ~1.35 GB total — 462 MB ONNX + 890 MB FAISS index (mounted from GCS; not baked) |
| Serving hardware | Rec API: 6× `n2-standard-8`; Inference: 6× `n1-standard-8` + T4 GPU (GCP) |
| Recommendation API replicas (peak + headroom) | 6 pods |
| Inference service replicas (peak + burst headroom) | 6 pods |
| Estimated monthly serving cost | ~$3,360 USD |
| Model version format | `v{MAJOR}.{MINOR}.{PATCH}-{YYYYMMDD}` (e.g. `v1.3.0-20260601`) |
| Container image tag format | `{SERVICE}:{git-sha}-{YYYYMMDD}` (e.g. `rec-api:a3f9c12-20260601`) |

## Navigation

| Artifact | Path |
|---|---|
| Architecture diagram & flow | [`architecture/architecture.md`](architecture/architecture.md) |
| Pattern justification | [`architecture/JUSTIFICATION.md`](architecture/JUSTIFICATION.md) |
| ADR 0001 — Model artifact mount vs bake | [`architecture/adr/0001-model-artifact-mount-vs-bake.md`](architecture/adr/0001-model-artifact-mount-vs-bake.md) |
| ADR 0002 — Online feature store & cold-start | [`architecture/adr/0002-online-feature-store-and-cold-start.md`](architecture/adr/0002-online-feature-store-and-cold-start.md) |
| ADR 0003 — Experiment Service A/B routing | [`architecture/adr/0003-experiment-service-ab-routing.md`](architecture/adr/0003-experiment-service-ab-routing.md) |
| ML lifecycle diagram | [`lifecycle/lifecycle.md`](lifecycle/lifecycle.md) |
| Model registry spec | [`lifecycle/model-registry.yaml`](lifecycle/model-registry.yaml) |
| Dockerfile | [`container/Dockerfile`](container/Dockerfile) |
| Container image plan | [`container/README.md`](container/README.md) |
| OpenAPI 3.1 spec | [`api/openapi.yaml`](api/openapi.yaml) |
| API example payloads | [`api/examples/`](api/examples/) |
| Capacity plan | [`serving/capacity-plan.md`](serving/capacity-plan.md) |
| SLO definitions | [`serving/slos.yaml`](serving/slos.yaml) |
| Load test plan | [`serving/load-test-plan.md`](serving/load-test-plan.md) |
| CI/CD pipeline | [`cicd/.github/workflows/deploy-model.yml`](cicd/.github/workflows/deploy-model.yml) |
| Monitoring alerts | [`monitoring/alerts.yaml`](monitoring/alerts.yaml) |
| Rollback runbook | [`runbooks/rollback.md`](runbooks/rollback.md) |

## Open Questions

1. **Feature store SLA at 800 RPS.** The design specifies Redis Cluster for online features with a p99 read budget of 20 ms. This is achievable on GCP Memorystore at the right tier, but needs a formal load test at 1.5× peak (1,200 RPS) with the actual feature payload size (~2 KB per user). If p99 exceeds 25 ms under that test, the latency budget forces a trade-off: reduce recommendation list size, drop some feature fields, or move part of feature assembly client-side.

2. **A/B experiment traffic-split granularity.** The current design routes experiment assignments via the Experiment Service on every request, adding ~3 ms. If the product team scales to >20 concurrent experiments, consistent user-level assignment will require a sticky session layer or a distributed assignment store (e.g. LaunchDarkly or a Cassandra-backed service). This needs product alignment before the experiment service is built.

3. **Cold-start fallback freshness.** The popularity-based fallback cache is refreshed every 15 minutes by the batch pipeline. During a batch pipeline outage, users will receive stale fallback recommendations indefinitely. A maximum staleness threshold (e.g. 2 hours) should be agreed with the product team, after which the service should surface a curated editorial list rather than stale popularity data, or return a configurable HTTP 503 to the client.
