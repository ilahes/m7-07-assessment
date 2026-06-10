# Load Test Plan — Recommendation Service

## Objectives

1. Validate that the system meets the p95 ≤ 120 ms latency SLO at 800 RPS sustained.
2. Confirm error rate ≤ 0.5% at peak load.
3. Verify autoscaling behaviour under ramp-up.
4. Identify the saturation point (max RPS before p95 > 120 ms).
5. Gate: load test must pass before any model version is promoted from staging to production (see CI/CD pipeline).

---

## Tool

**k6** (v0.51+), run from a GCP VM in the same region as the staging cluster (us-central1) to eliminate cross-region latency variance.

---

## Test Scenarios

### Scenario 1 — Steady-State Validation (Gate test, required for CI/CD pass)

```javascript
// k6/scenarios/steady_state.js
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'https://api-staging.retailco.com/rec/v1';
const TOKEN = __ENV.API_TOKEN;

// 90% returning users (have history), 10% cold-start
const USER_IDS = Array.from({length: 9000}, (_, i) => `u_${10000 + i}`)
  .concat(Array.from({length: 1000}, (_, i) => `u_cold_${i}`));

export const options = {
  scenarios: {
    steady_state: {
      executor: 'constant-arrival-rate',
      rate: 800,           // 800 RPS
      timeUnit: '1s',
      duration: '10m',     // 10 minutes sustained
      preAllocatedVUs: 200,
      maxVUs: 400,
    },
  },
  thresholds: {
    // Gate thresholds — test FAILS (and blocks CI/CD) if breached
    'http_req_duration{scenario:steady_state}': ['p(95)<120', 'p(99)<250'],  // p95 ≤ 120 ms, p99 ≤ 250 ms
    'http_req_failed{scenario:steady_state}': ['rate<0.005'],                 // error rate < 0.5%
  },
};

export default function () {
  const userId = USER_IDS[Math.floor(Math.random() * USER_IDS.length)];
  const payload = JSON.stringify({
    user_id: userId,
    context: 'home_screen',
    limit: 20,
    session_signals: { viewed_item_ids: [], cart_item_ids: [] },
  });
  const res = http.post(
    `${BASE_URL}/recommendations`,
    payload,
    {
      headers: {
        'Authorization': `Bearer ${TOKEN}`,
        'Content-Type': 'application/json',
        'X-Request-ID': `k6-${__VU}-${__ITER}`,
      },
      timeout: '500ms',  // fail fast; don't accumulate slow requests
    }
  );

  check(res, {
    'status is 200': (r) => r.status === 200,
    'has model version header': (r) => r.headers['X-Model-Version'] !== undefined,
    'has recommendations': (r) => {
      const body = JSON.parse(r.body);
      return body.recommendations && body.recommendations.length > 0;
    },
  });
  // No sleep — constant-arrival-rate executor manages pacing
}
```

**Pass criteria:**
- `p(95) < 120 ms` ✓
- Error rate `< 0.5%` ✓
- No pod OOMKills during test
- Redis CPU < 40%
- Inference pod GPU utilisation < 80%

---

### Scenario 2 — Ramp-Up / Autoscaling Test

```javascript
export const options = {
  scenarios: {
    ramp: {
      executor: 'ramping-arrival-rate',
      startRate: 50,
      timeUnit: '1s',
      stages: [
        { duration: '2m', target: 200 },   // ramp to 200 RPS
        { duration: '3m', target: 500 },   // ramp to 500 RPS
        { duration: '3m', target: 800 },   // ramp to 800 RPS (peak)
        { duration: '5m', target: 800 },   // hold at peak
        { duration: '2m', target: 1200 },  // spike to 1.5× (headroom test)
        { duration: '3m', target: 800 },   // return to peak
        { duration: '2m', target: 0 },     // ramp down
      ],
      preAllocatedVUs: 300,
      maxVUs: 600,
    },
  },
  thresholds: {
    // Only enforce during peak hold phase (800 RPS, 3–8 min mark)
    'http_req_duration{scenario:ramp}': ['p(95)<150'],  // slightly relaxed during ramp
    'http_req_failed{scenario:ramp}': ['rate<0.01'],
  },
};
```

**What to observe:**
- HPA scales Recommendation API from 3 → 6 pods as RPS climbs. Target: scale-up begins within 90 s of crossing 65% CPU.
- HPA scales Inference Service from 6 → 8 pods if GPU utilisation exceeds 70%. Target: scale-up begins within 60 s.
- p95 latency stays under 150 ms during the 1,200 RPS spike (temporary exceedance acceptable; SLO is measured over 30 days).

---

### Scenario 3 — Batch Endpoint Test

```javascript
// POST /v1/recommendations:batch, 50 users per request, 10 RPS
export const options = {
  scenarios: {
    batch: {
      executor: 'constant-arrival-rate',
      rate: 10,
      timeUnit: '1s',
      duration: '5m',
      preAllocatedVUs: 20,
    },
  },
  thresholds: {
    'http_req_duration{scenario:batch}': ['p(95)<500'],
    'http_req_failed{scenario:batch}': ['rate<0.005'],
  },
};
```

---

## Monitoring During Load Test

The following Grafana panels must be open during the test:

1. **Recommendation API** — RPS, p50/p95/p99 latency, error rate, pod count
2. **Inference Service** — GPU utilisation, inference latency p95, pod count
3. **Redis Feature Store** — ops/s, memory usage, CPU, evictions
4. **HPA** — current/desired replica count for both deployments

---

## Result Reporting

After each run, k6 outputs a summary. The CI/CD pipeline captures:

```bash
k6 run \
  --env BASE_URL=https://api-staging.retailco.com/rec/v1 \
  --env API_TOKEN=${STAGING_API_TOKEN} \
  --out json=results/k6-results.json \
  serving/k6/scenarios/steady_state.js

# Extract pass/fail for CI gate
k6_exit_code=$?
if [ $k6_exit_code -ne 0 ]; then
  echo "LOAD TEST FAILED — blocking production promotion"
  exit 1
fi
```

Results are uploaded to GCS (`gs://retailco-cicd-artifacts/load-tests/{run_id}/`) for audit trail.
