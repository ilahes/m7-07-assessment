# rec-inference: FastAPI application entry point.
# This is a placeholder for the implementation repository.
# The CI/CD pipeline expects: uvicorn src.main:app
#
# Expected routes (see api/openapi.yaml for full contract):
#   POST /v1/recommendations          — sync inference
#   POST /v1/recommendations:batch    — batch inference
#   POST /v1/recommendation-jobs      — async job submission
#   GET  /v1/recommendation-jobs/{job_id} — async job status
#   GET  /health                      — liveness probe
#   GET  /ready                       — readiness probe (checks model loaded)
#   GET  /metrics                     — Prometheus scrape endpoint

from src import __version__

app_metadata = {
    "title": "rec-inference",
    "version": __version__,
    "description": "Personalized product recommendation inference service.",
}
