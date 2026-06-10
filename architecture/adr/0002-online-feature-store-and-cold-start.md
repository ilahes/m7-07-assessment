# ADR 0002 — Online Feature Store Selection and Cold-Start Strategy

**Status:** Accepted  
**Date:** 2026-05-28  
**Deciders:** Alice Chen (ML Lead), Elena Sousa (Data Engineering Lead), David Park (Platform Lead)  
**Scenario:** Scenario X — Personalized In-App Recommendations

---

## Context

The recommendation model requires a user feature vector (394 features, ~2 KB serialized) at inference time on every home-screen load. These features represent aggregated signals from the user's last 30 days of browsing and purchase events.

Two broad approaches exist:

1. **Pre-compute and cache:** An offline pipeline aggregates raw events periodically, writes feature vectors to a low-latency store, and the API reads them at request time.
2. **Real-time aggregation:** The API aggregates raw events from the event log on every request.

The feature freshness requirement is "last 30 days of browsing and purchases" — this is a rolling aggregate, not a real-time stream. Hourly updates are acceptable to the product team.

Additionally, new users (no purchase/browsing history) must receive "reasonable recommendations" — a cold-start solution is required.

---

## Decision

**Use Redis Cluster (GCP Memorystore Standard) as the online feature store, populated by an hourly Dataflow batch pipeline. Cold-start users are served via a pre-computed global popularity embedding stored as a fixed key in Redis.**

### Feature store architecture

- **Offline pipeline:** GCP Dataflow (Apache Beam) job runs hourly, reading last-30-day raw event data from BigQuery, aggregating per-user feature vectors, and writing them to Redis with key pattern `user:{user_id}:features:v{schema_version}`.
- **Online serving:** Recommendation API reads the user's feature vector from Redis in ≤20 ms p99. On a cache miss, the cold-start path is taken.
- **Expiry:** Redis keys are set with a 25-hour TTL. Users inactive for more than 25 hours will hit the cold-start path until the pipeline next writes their vector. This is intentional: stale vectors older than 25 hours are likely inaccurate enough to harm rather than help.

### Cold-start strategy

When `Redis GET user:{user_id}:features:v3` returns `nil`:
1. The Recommendation API sets `X-Fallback: popularity` in the downstream request context.
2. It reads the global popularity embedding from `global:popularity:v{date}` (always present; refreshed every 15 minutes by the batch pipeline).
3. Inference proceeds normally with the popularity embedding as the user vector.
4. The `rec_cold_start_total` counter increments.
5. The response includes `X-Fallback: popularity` header.

The global popularity embedding is updated every 15 minutes (not hourly) to provide a reasonably fresh trending signal even during the hourly pipeline's off-cycle window.

---

## Consequences

**Positive:**
- p99 Redis read latency of 3–6 ms leaves ample headroom in the 20 ms feature budget and the 120 ms end-to-end budget.
- Pre-computed vectors decouple feature complexity from inference latency. Complex 394-feature aggregations that would take 200+ ms to compute in real-time are fully absorbed into the hourly pipeline.
- Cold-start users receive relevant (popularity-based) recommendations immediately on first open, improving first-run experience.
- Cold-start rate is a measurable metric (`rec_cold_start_total`), enabling alerts that detect Redis failures masquerading as new-user traffic.
- Feature schema versioning (`v3` in key pattern) allows schema migrations without downtime: new schema written alongside old key until all pods have restarted.

**Negative:**
- Feature vectors are up to 1 hour stale. A user who purchases an item and reloads the app within the same hour may still see that item recommended. Product team has accepted this trade-off.
- Redis holds 10M users × 2 KB = ~20 GB of feature data. If the active user base grows beyond 13M, the 26 GB cluster will need to be resized. Mitigation: Memorystore cluster resize is online.
- The Dataflow pipeline is a dependency: if it fails for >4 hours, features become stale and the `RecFeaturePipelineDown` alert fires. During outages, the cold-start fallback absorbs all requests — this degrades personalization but does not cause errors.
- The popularity fallback cache (15-minute refresh) is populated by the same Dataflow pipeline. A complete pipeline outage means both personalized and fallback features degrade simultaneously. A secondary fallback (editorial curated list, configurable in Helm values) should be implemented in v1.1.

---

## Alternatives Considered

### Option A: Real-time feature aggregation (rejected)

Aggregate raw BigQuery events on each inference request via a streaming query.

Rejected because: BigQuery p99 query latency for a 30-day window aggregation is 200–400 ms, which alone exceeds the 120 ms end-to-end SLO. Cost would also be prohibitive at 800 RPS.

### Option B: Cloud Bigtable as feature store (rejected)

Use Bigtable instead of Redis for the online feature store.

Rejected because: Bigtable p99 read latency is 8–12 ms vs Redis 3–6 ms. At 800 RPS this is safe, but leaves less headroom for tail latency spikes. Bigtable is operationally heavier for a simple key-value read workload. Redis is the team's existing operational expertise. Bigtable would be preferred at 10B+ users where Redis memory cost becomes prohibitive.

### Option C: No cold-start fallback — return 503 for new users (rejected)

Return an error or empty list for users with no history.

Rejected because: New users represent 5–10% of daily active sessions during marketing campaigns. A 503 on the first app open creates a negative first impression. The product team's explicit requirement is "reasonable recommendations" for cold-start users.

### Option D: Item-based collaborative filtering for cold start (deferred)

Use item metadata (category, price range) to infer a cold-start embedding from device locale and app store category data.

Deferred to v1.2. More complex to implement and maintain; popularity fallback is sufficient for initial launch.

---

## References

- [Architecture Diagram](../architecture.md) — shows feature store in system context
- [Architecture Justification](../JUSTIFICATION.md) — Redis selection rationale with latency comparison table
- [Capacity Plan](../../serving/capacity-plan.md) — Redis cluster sizing
- [Monitoring Alerts](../../monitoring/alerts.yaml) — `RecColdStartSpike`, `RecFeatureStalenessHigh`, `RecFeaturePipelineDown`
- [SLOs](../../serving/slos.yaml) — `cold_start_fallback_rate` SLO
