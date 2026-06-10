# scripts/

Utility scripts called by the CI/CD pipeline and runbooks.

| Script | Called by | Purpose |
|---|---|---|
| `get_latest_candidate.py` | CI/CD `validate-model-registry` job | Reads MLflow registry; returns latest version in `candidate` state |
| `check_registry_state.py` | CI/CD `validate-model-registry`, `promote-production` | Asserts a model version is in an allowed state; exits non-zero on failure |
| `check_feature_schema_match.py` | CI/CD `validate-model-registry` | Asserts model's `feature_schema_version` matches current serving schema |
| `update_registry_state.py` | CI/CD `deploy-production`, `promote-production`, rollback runbook | Transitions a model version to a new state and writes audit fields |
| `archive_previous_production.py` | CI/CD `promote-production` | Sets the outgoing production version to `archived` state |
| `check_ab_test_gate.py` | CI/CD `promote-production` | Asserts CTR lift > 0 and p-value ≤ 0.05 in MLflow experiment metrics |
| `get_previous_production_version.py` | Rollback runbook | Reads MLflow registry; returns most recent `archived` version |

All scripts accept `--help` and exit with a non-zero code on failure (CI-safe).
They assume `MLFLOW_TRACKING_URI` is set in the environment (injected as a GitHub Actions secret).
