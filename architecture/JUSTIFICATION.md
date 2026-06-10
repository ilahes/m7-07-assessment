# Architecture Justification — Personalized In-App Recommendations

## Pattern Choice: Online Inference with Pre-computed Feature Vectors

### Why online (synchronous) inference?

The product requirement is a personalized ranked list on **every home-screen load**. The user's context at request time (current session, time of day, device) is a first-class personalization signal. Precomputed offline recommendations (e.g. nightly batch exports to a Redis list per user) would be simpler operationally, but they cannot react to within-session signals and would fail the 120 ms SLO during high traffic without a Redis lookup anyway. Online inference is the minimum viable architecture that satisfies both freshness and latency requirements.

The 120 ms end-to-end p95 budget is tight but achievable with the two-stage design: user feature vectors are pre-computed offline (updated hourly) and served from Redis in ≤20 ms, so the inference service only runs the forward pass on the pre-assembled vector rather than re-aggregating raw event data on each request.

### Why Redis (Memorystore) for the online feature store?

| Alternative | p99 read latency | Ops/s per cluster | Reasons rejected |
|---|---|---|---|
| Redis (Memorystore Standard) | ~3–6 ms | 200,000+ | **Chosen** |
| Cloud Bigtable | ~8–12 ms | 200,000+ | Higher latency; more operationally complex for simple key-value reads |
| Firestore | ~20–40 ms | 10,000 | Latency too high; threatens 120 ms budget |
| In-process cache (pod memory) | ~0.1 ms | unlimited | Cache invalidation complexity; 10M users × 2 KB = 20 GB does not fit in pod RAM; cache coherence across 6 pods is intractable |

Redis Cluster provides sub-6 ms p99 reads at 800 RPS trivially and scales to 1,200+ RPS without configuration changes. GCP Memorystore Standard removes operational burden (no manual cluster management, automated failover). The 26 GB cluster comfortably fits the 10M active user feature footprint (~20 GB raw + overhead).

A dedicated Redis cluster for the Product Catalog Cache (separate from the User Feature Store) isolates the two workloads so a catalog-heavy write burst does not contend with user feature reads and threaten the latency budget.

### Why mount the model artifact rather than bake it into the container image?

The model artifact (ONNX + FAISS index) totals **~1.35 GB**. Baking it into the container image would:
- Produce a ~1.7 GB image, extending pull time on new pods by 60–90 seconds
- Require a full image rebuild and new container tag for every model version update, coupling the model deployment lifecycle to the service deployment lifecycle
- Prevent rollback to a previous model version without a container redeployment

Mounting the model from GCS at pod startup (via an init container that downloads the artifact) decouples model versions from container image versions. A model rollback is a one-line patch to the `MODEL_VERSION` environment variable and a pod restart (~2 min). The container image is rebuilt only when the serving code changes, not when the model changes.

**Trade-off acknowledged:** Pod startup time increases by ~30–60 seconds (GCS download of 1.35 GB in us-central1 at ~20 MB/s). This is acceptable because the Recommendation API HPA maintains a minimum of 3 warm pods at all times; cold pod starts are infrequent and tolerated on scale-out events.

See [ADR 0001](adr/0001-model-artifact-mount-vs-bake.md) for the full decision record.

### Why a separate Experiment Service for A/B routing?

The product team runs **continuous A/B experiments** against challenger models. Embedding experiment assignment logic directly in the Recommendation API creates several problems:
- Experiment configuration changes (new experiments, traffic splits, kill switches) require code deploys
- Consistent user-level assignment (same user always sees the same variant) is hard to maintain across horizontally scaled pods without a shared assignment store
- Experiment state leaks into the inference service, making the two harder to reason about independently

A dedicated Experiment Service (thin gRPC wrapper, LaunchDarkly-compatible protocol) provides a stable API surface for assignment, keeps the Recommendation API stateless with respect to experiments, and adds only ~3 ms per request. The `X-Experiment-ID` header is propagated to all downstream services and emitted in traces, making experiment-correlated latency analysis straightforward in Grafana.

### Why a cold-start fallback path?

Approximately 5–10% of active users at any time have insufficient history (new installs, guest sessions, users who cleared app data). Without a fallback, their requests would either fail or receive empty recommendation lists, degrading the first-run experience.

The fallback uses a pre-computed global popularity embedding (top-500 items by rolling 7-day views and purchases), refreshed every 15 minutes by the batch pipeline and stored as a fixed key in Redis (`global:popularity:v{date}`). This key is always warm. The inference call proceeds identically; only the input vector differs. The fallback rate is monitored (see `RecColdStartSpike` alert) to detect Redis failures or feature pipeline outages that inflate cold-start beyond the expected baseline.

### Summary of Key Trade-offs

| Dimension | Choice | Alternative | Why this way |
|---|---|---|---|
| Inference mode | Online (synchronous) | Batch pre-compute | Session freshness; A/B test compatibility |
| Feature serving | Redis pre-computed vectors | Real-time aggregation | Latency budget (20 ms vs 80+ ms) |
| Model artifact | Mounted from GCS | Baked into image | Decoupled model versioning; faster rollback |
| A/B routing | Dedicated Experiment Service | Inline in API | Stateless API pods; experiment config independence |
| Cold-start | Popularity embedding | Return 503 | Better UX; measurable fallback rate |
| GPU type | T4 (ONNX + CUDA) | CPU-only | ONNX two-tower inference p95 56 ms on T4 vs 210 ms CPU-only |
| Infra platform | GKE + GCP managed services | Self-managed k8s | Operational simplicity; Memorystore/Dataflow/Vertex AI integration |
