# Capacity Plan — Recommendation Service

## Traffic Assumptions

| Parameter | Value |
|---|---|
| Peak RPS | 800 |
| Sustained (avg day) RPS | 320 (40% of peak) |
| Burst headroom target | 1.5× peak = 1,200 RPS |
| p95 end-to-end latency budget | 120 ms |
| Request payload (inbound) | ~200 bytes |
| Response payload | ~4 KB (20 items × ~200 bytes) |

---

## Latency Budget Breakdown

End-to-end p95 = **120 ms**. Breakdown across components:

| Component | p95 budget | Notes |
|---|---|---|
| API Gateway (TLS + routing) | 5 ms | Cloud Load Balancing; measured at 99th pct < 8 ms |
| Feature fetch (Redis) | 20 ms | Redis Cluster p99 < 6 ms measured; 20 ms is conservative p95 under load |
| Model inference (ONNX + FAISS) | 60 ms | T4 GPU; benchmark: p50=42 ms, p95=56 ms at 200 RPS/pod |
| Ranking / post-processing | 20 ms | Catalog enrichment + re-rank; CPU-bound, 10–15 ms typical |
| Serialization + network | 5 ms | FastAPI JSON serialization ~2 ms; internal network ~3 ms |
| Headroom / jitter | 10 ms | Buffer for GC pauses, head-of-line blocking |
| **Total** | **120 ms** | |

---

## Component Sizing

### Recommendation API Service

- Handles request orchestration: feature fetch, inference call, catalog enrichment, re-rank, serialize.
- CPU-bound orchestration; no GPU needed.
- Benchmark: 1 pod (`n2-standard-8`, 8 vCPU, 32 GB RAM) handles **180 RPS** comfortably at p95 < 30 ms for its own processing.
- At 800 RPS peak: `800 / 180 = 4.4` pods needed → round up to **5 pods**.
- Add 1 pod headroom: **6 pods minimum** for 1,200 RPS burst capacity (`6 × 180 = 1,080 RPS`).
- HPA configured: min=3, max=8, scale-up on CPU > 65% sustained 90 s.

### Model Inference Service

- Runs ONNX Runtime with CUDA execution provider on T4 GPU.
- Benchmark on T4 (`n1-standard-8` + T4 GPU, 8 vCPU, 30 GB RAM):
  - p50 inference: 42 ms, p95: 56 ms
  - Maximum sustainable throughput: **220 RPS/pod** (p95 ≤ 60 ms)
- The Recommendation API fans out inference calls; effective inference RPS = same as API RPS = 800 peak.
- `800 / 220 = 3.6` → round up to **4 pods** for peak.
- Burst target is 1.5× peak = 1,200 RPS: `1200 / 220 = 5.5` → **6 pods minimum** to cover burst without relying on HPA reaction time.
- HPA configured: min=6, max=8, scale-up on GPU utilisation > 70% sustained 60 s.

### Online Feature Store (Redis Cluster)

- 6-node GCP Memorystore Standard cluster, 26 GB total (4.3 GB/node).
- Feature vector per user: ~2 KB. 10M active users × 2 KB = 20 GB raw; with overhead, fits in 26 GB cluster.
- Throughput: Memorystore Standard supports >200,000 ops/s per cluster; 800 RPS = 800 reads/s, trivially handled.
- Replicas: Memorystore HA handles this; no manual replica count needed.

### Product Catalog Cache (Redis)

- 3-node GCP Memorystore Standard, 6 GB total.
- ~2M SKUs × 500 bytes avg item metadata = 1 GB raw. Fits with margin.
- Separate cluster from feature store to isolate latency profiles.

---

## Hardware and Cost Estimate

| Component | Instance type | Count | Monthly cost (est.) |
|---|---|---|---|
| Recommendation API pods | `n2-standard-8` (8 vCPU / 32 GB) | 6 | $1,020 |
| Model Inference pods | `n1-standard-8` + T4 GPU | 6 | $1,680 |
| Redis Feature Store | Memorystore Standard 26 GB | 1 cluster | $380 |
| Redis Catalog Cache | Memorystore Standard 6 GB | 1 cluster | $115 |
| API Gateway + LB | Cloud Load Balancing | — | $90 |
| Misc (Cloud Trace, logging, egress) | — | — | ~$75 |
| **Total** | | | **~$3,360 / month** |

_Costs are GCP us-central1 on-demand, June 2026 pricing. Committed-use discounts (1-year CUD) would reduce compute ~30% to ~$2,100/month._

---

## Autoscaling Policy

```yaml
# Recommendation API HPA
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: rec-api-hpa
spec:
  minReplicas: 3
  maxReplicas: 8
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 65
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 90
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300

# Model Inference HPA
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: rec-inference-hpa
spec:
  minReplicas: 6
  maxReplicas: 8
  metrics:
    - type: External
      external:
        metric:
          name: custom.googleapis.com/gpu_utilization
        target:
          type: AverageValue
          averageValue: "70"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
```

---

## Load Test Validation

See [`load-test-plan.md`](load-test-plan.md). The capacity plan is considered validated when:
- k6 test at 800 RPS sustained for 10 minutes yields p95 ≤ 120 ms
- Error rate (5xx) ≤ 0.5%
- No pod OOMKills
- Redis CPU < 40% throughout
- Inference pod count stable at 6 (no unexpected HPA scale-out during sustained 800 RPS)
