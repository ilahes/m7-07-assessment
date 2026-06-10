# ADR 0003 — Experiment Service: Dedicated vs Inline A/B Routing

**Status:** Accepted  
**Date:** 2026-05-28  
**Deciders:** Alice Chen (ML Lead), Sarah Kim (Product Lead), David Park (Platform Lead)  
**Scenario:** Scenario X — Personalized In-App Recommendations

---

## Context

The product team runs **continuous A/B experiments** against challenger recommendation models. At any point there may be 3–8 concurrent experiments, each routing a slice of traffic to a different model version. The system must:

1. Assign each user to a consistent experiment variant (same user → same variant across requests)
2. Route the recommendation request to the correct model version
3. Propagate the experiment assignment to downstream services and monitoring
4. Allow experiment configuration changes (new experiments, traffic splits, kill switches) **without code deploys**

Two architectural choices were evaluated:

**Option A — Inline routing:** Embed experiment assignment logic directly in the Recommendation API pods. Each pod loads experiment config from a shared ConfigMap or feature flag service at startup.

**Option B — Dedicated Experiment Service:** A thin, stateless gRPC service that owns experiment assignment. The Recommendation API calls it once per request to get the variant assignment, then routes accordingly.

---

## Decision

**Deploy a dedicated Experiment Service (Option B).**

The service exposes a single RPC: `GetVariant(user_id, experiment_namespace) → {variant_id, model_version, experiment_id}`. It is backed by a LaunchDarkly-compatible assignment store with consistent hashing for stable user-level assignment across horizontally scaled pods.

---

## Consequences

**Positive:**

- **Stateless API pods.** The Recommendation API carries no experiment state. Horizontal scaling, rolling restarts, and pod replacement do not risk inconsistent assignments.
- **Config changes without deploys.** Experiment traffic splits, kill switches, and new experiment registrations are pushed to the Experiment Service's config store without touching the Recommendation API image or Helm values.
- **Consistent user assignment.** Consistent hashing in the Experiment Service guarantees the same user always maps to the same variant, even across 6 API pods — critical for valid A/B test measurement.
- **Observability.** The `X-Experiment-ID` header returned by the Experiment Service is propagated to all downstream calls and emitted in traces. Grafana can filter latency and error metrics by experiment variant, making regression detection trivial.
- **Experiment Service is independently scalable.** If the number of concurrent experiments grows beyond 20, only the Experiment Service needs to scale — the Recommendation API is unaffected.

**Negative / Trade-offs:**

- **+3 ms per request.** The gRPC call to the Experiment Service adds ~3 ms p95 latency. This is accounted for in the capacity plan's latency breakdown and fits within the 120 ms end-to-end budget.
- **Additional operational surface.** One more service to deploy, monitor, and on-call for. Mitigated by the service's simplicity (stateless, no DB, thin gRPC wrapper) and a circuit breaker: if the Experiment Service is unreachable, the Recommendation API falls back to a default variant (control group) and logs a `RecExperimentServiceDegraded` metric.
- **gRPC dependency.** Requires gRPC client in the Recommendation API and a gRPC server for the Experiment Service. This is acceptable given the team's existing GKE/gRPC infrastructure.

## Alternatives Considered

### Option A: Inline routing (rejected)

| Criterion | Dedicated Service (chosen) | Inline in API (rejected) |
|---|---|---|
| Config change without deploy | ✅ Push to assignment store | ❌ ConfigMap update + rolling restart (~3 min) |
| Consistent user assignment at scale | ✅ Centralised consistent hashing | ❌ Requires shared store or drifts between pod restarts |
| Blast radius of experiment bugs | ✅ Isolated; API pods unaffected | ❌ Experiment state in API; harder to reason about |
| Operational overhead | ⚠ One extra service | ✅ No extra service |
| Request latency | ⚠ +3 ms gRPC call | ✅ ~0 ms (in-process) |
| Scale to >20 experiments | ✅ Only Experiment Service scales | ❌ All API pods must be resized |

Rejected because config-change-without-deploy and consistent user assignment are hard requirements from the product team. The +3 ms cost is explicitly accounted for in the capacity plan latency breakdown.

### Option C: LaunchDarkly SaaS (deferred)

Managed LaunchDarkly would eliminate operational overhead entirely. Deferred because: data residency requirements may prohibit sending user IDs to a US-based SaaS; the Experiment Service's LaunchDarkly-compatible protocol means migration is a config swap rather than a rewrite. Revisit at v2.0 after data residency policy is confirmed.

---

## Implementation Notes

- Experiment Service SLA: p99 < 5 ms (well within the 3 ms budget allocation, which is a conservative p95 figure).
- Circuit breaker threshold: 3 consecutive timeouts → fallback to control variant.
- `X-Experiment-ID` header format: `{experiment_slug}:{variant_id}` (e.g. `rec-model-v1.3-test:treatment`).
- Experiment config store: LaunchDarkly (managed SaaS) for launch; migrate to self-hosted Unleash if data residency requirements tighten.
- Scale limit: current design supports up to ~20 concurrent experiments before the assignment store needs sharding. Product alignment required if experiment count is expected to exceed this (see Open Questions in root README).
