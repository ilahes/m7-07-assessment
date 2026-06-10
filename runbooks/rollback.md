# Rollback Runbook — Recommendation Inference Service

**Audience:** On-call engineer (any seniority)  
**Goal:** Roll back the recommendation model to the previous production version in < 5 minutes  
**Last updated:** 2026-06-01

---

## Rollback Triggers

Roll back immediately if ANY of the following alerts are firing in PagerDuty/Slack:

| Alert | Threshold |
|---|---|
| `RecAvailabilityBurnRateCritical` | 1h availability burn rate > 14.4× |
| `RecErrorRateHigh` | 5xx error rate > 0.5% sustained ≥ 2 min |
| `RecLatencyP95Breach` | p95 latency > 120 ms sustained ≥ 3 min |
| `RecABGuardrailAddToCartDrop` | Treatment add-to-cart rate > 5% below control ≥ 60 min |

Also roll back if the **product team or ML lead** requests it based on business metrics, even without a firing alert.

---

## Before You Start

**Confirm you need a rollback vs a hotfix:**
- If the issue is in the **serving code** (rec-api or rec-inference pods crashing) → this runbook applies to the model artifact only; you may also need to roll back the container image using `helm rollback`.
- If the issue is in the **feature pipeline** (Redis staleness) → contact Data Engineering on-call first; model rollback won't help.
- If the issue is a **downstream dependency** (product catalog cache, experiment service down) → follow those services' runbooks.

**Identify the previous production model version:**

```bash
# Check MLflow registry for the last 'production' or 'archived' model
python scripts/get_previous_production_version.py --model-name rec-two-tower-v1
# Expected output: v1.2.1-20260515
```

Or check `lifecycle/model-registry.yaml` in the Git repo — the most recent entry with `state: archived` is the previous production version.

---

## Rollback Steps

### Step 1 — Acknowledge the alert (PagerDuty)

```
pd ack <incident-id>
```

Post in `#incidents`: `🔴 Starting rollback of rec-inference to v1.2.1-20260515. ETA: 5 min.`

---

### Step 2 — Execute the rollback (ArgoCD preferred)

**Option A: ArgoCD UI (no terminal needed)**

1. Open https://argocd.retailco.internal
2. Find app `rec-inference-prod`
3. Click **App Details → Parameters**
4. Change `modelVersion` from `v1.3.0-20260601` → `v1.2.1-20260515`
5. Click **Sync → Force Sync**
6. Watch pods restart under **Pods** tab

**Option B: CLI (terminal)**

```bash
# Set context to production cluster
kubectl config use-context gke_retailco-prod_us-central1_retailco-gke-prod

# Patch the inference deployment env var
kubectl set env deployment/rec-inference \
  MODEL_VERSION=v1.2.1-20260515 \
  -n recommendations

# Watch rollout
kubectl rollout status deployment/rec-inference -n recommendations --timeout=300s
```

**Option C: Helm (if ArgoCD sync is disabled)**

```bash
helm upgrade rec-inference deploy/inference \
  --namespace recommendations \
  --reuse-values \
  --set modelVersion=v1.2.1-20260515 \
  --wait --timeout 5m
```

---

### Step 3 — Verify rollback

```bash
# All inference pods should show MODEL_VERSION=v1.2.1-20260515
kubectl get pods -n recommendations -l app=rec-inference \
  -o jsonpath='{.items[*].spec.containers[*].env}' | grep MODEL_VERSION

# Confirm readiness
kubectl get pods -n recommendations -l app=rec-inference
# All pods should be Running and Ready (2/2 or 1/1)

# Hit readiness endpoint on one pod
kubectl exec -n recommendations \
  $(kubectl get pod -n recommendations -l app=rec-inference -o jsonpath='{.items[0].metadata.name}') \
  -- curl -s http://localhost:8080/ready | jq .
# Expected: {"status":"ready","model_version":"v1.2.1-20260515","model_loaded":true,...}

# Confirm X-Model-Version header in a real request
curl -s -o /dev/null -D - \
  "https://api.retailco.com/rec/v1/recommendations" \
  -H "Authorization: Bearer ${PROD_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u_12345","context":"home_screen","limit":20}' \
  | grep X-Model-Version
# Expected: X-Model-Version: v1.2.1-20260515
```

---

### Step 4 — Verify metrics recovering

Check Grafana dashboard **Recommendations — SLO Overview**:

- [ ] p95 latency returning to < 120 ms
- [ ] Error rate (5xx) returning to < 0.5%
- [ ] `RecAvailabilityBurnRateCritical` alert resolving in PagerDuty (allow 2–3 min)

If metrics do NOT recover within 5 minutes of rollback completing:

→ The issue is likely **not the model**. Check: rec-api deployment, Redis connectivity, inference service pod logs.

---

### Step 5 — Update model registry

```bash
python scripts/update_registry_state.py \
  --model-name rec-two-tower-v1 \
  --version v1.3.0-20260601 \
  --state rolled-back \
  --rolled-back-by "$(git config user.email)" \
  --rollback-reason "RecErrorRateHigh: 5xx rate 2.3% at 14:32 UTC 2026-06-01"
```

---

### Step 6 — Communicate

Post in `#incidents` and `#ml-platform`:

```
✅ Rollback complete.
- Rolled back: v1.3.0-20260601 → v1.2.1-20260515
- Time to rollback: X min
- Current error rate: [paste value]
- Current p95 latency: [paste value]
- Incident post-mortem: [create JIRA ticket MLPLAT-XXX]
```

Resolve PagerDuty incident.

---

## Declaring Rollback Successful

All of the following must be true:

- [ ] All `rec-inference` pods are `Running` and `Ready`
- [ ] `kubectl get pods` shows only pods with `MODEL_VERSION=v1.2.1-20260515`
- [ ] `X-Model-Version: v1.2.1-20260515` returned in live API responses
- [ ] p95 latency ≤ 120 ms for ≥ 5 consecutive minutes in Grafana
- [ ] Error rate < 0.5% for ≥ 5 consecutive minutes in Grafana
- [ ] All rollback-trigger alerts resolved in PagerDuty
- [ ] Model registry updated to `state: rolled-back` for v1.3.0-20260601
- [ ] Incident update posted in `#incidents`

---

## Post-Rollback Actions (within 24 h)

- [ ] File post-mortem JIRA ticket (MLPLAT-XXX) with timeline, root cause, and follow-up items
- [ ] ML team investigates root cause of v1.3.0-20260601 regression before re-attempting promotion
- [ ] Do not re-promote v1.3.0-20260601 without fixing the root cause and re-running offline evaluation + load test
