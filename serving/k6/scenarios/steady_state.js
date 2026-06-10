// k6/scenarios/steady_state.js
// Gate test — must pass before any model version is promoted from staging to production.
// Run by CI/CD pipeline (cicd/.github/workflows/deploy-model.yml, job: load-test).
// Also documented in serving/load-test-plan.md (Scenario 1).

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
    // Gate thresholds — test FAILS (and blocks CI/CD promotion) if breached
    'http_req_duration{scenario:steady_state}': ['p(95)<120', 'p(99)<250'],
    'http_req_failed{scenario:steady_state}': ['rate<0.005'],
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
      timeout: '500ms',
    }
  );

  check(res, {
    'status is 200': (r) => r.status === 200,
    'has model version header': (r) => r.headers['X-Model-Version'] !== undefined,
    'has recommendations': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.recommendations && body.recommendations.length > 0;
      } catch {
        return false;
      }
    },
  });
  // No sleep — constant-arrival-rate executor manages pacing
}
