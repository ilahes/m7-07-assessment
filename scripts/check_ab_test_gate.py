#!/usr/bin/env python3
"""
check_ab_test_gate.py
---------------------
Validates that A/B test promotion gate requirements are documented in the
model registry and SLO files.

In production this would query the MLflow REST API for live A/B experiment
results (CTR lift > 0, p_value <= 0.05). For the assessment dossier it
verifies the gate requirements are present in the local config files.

Usage (CI):
    python scripts/check_ab_test_gate.py \
        --model-name rec-two-tower-v1 \
        --version v1.3.0-20260601

Exits 0 on success, 1 if gate requirements are not documented.
"""

import sys
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

REGISTRY_PATH = REPO_ROOT / "lifecycle" / "model-registry.yaml"
SLOS_PATH = REPO_ROOT / "serving" / "slos.yaml"

# Registry must document A/B gate conditions
REGISTRY_REQUIRED = [
    "ab_test",
    "p_value",
    "ctr_lift",
    "staging_to_production",
]

# SLO file must document latency and error-rate thresholds
SLOS_REQUIRED = [
    "p95",
    "error_rate",
    "availability",
]


def read_file(path: Path) -> str:
    if not path.exists():
        print(f"ERROR: Required file not found: {path}", file=sys.stderr)
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Validate A/B test gate requirements are documented."
    )
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    print(f"Checking A/B test gate for {args.model_name} version {args.version}")

    registry_content = read_file(REGISTRY_PATH)
    slos_content = read_file(SLOS_PATH)

    failed = False

    missing_registry = [s for s in REGISTRY_REQUIRED if s not in registry_content]
    if missing_registry:
        print(
            f"ERROR: model-registry.yaml missing A/B gate fields: {missing_registry}",
            file=sys.stderr,
        )
        failed = True
    else:
        print(f"✓ model-registry.yaml documents A/B gate conditions: {REGISTRY_REQUIRED}")

    missing_slos = [s for s in SLOS_REQUIRED if s not in slos_content]
    if missing_slos:
        print(
            f"ERROR: serving/slos.yaml missing threshold fields: {missing_slos}",
            file=sys.stderr,
        )
        failed = True
    else:
        print(f"✓ serving/slos.yaml documents latency and error-rate thresholds: {SLOS_REQUIRED}")

    if failed:
        sys.exit(1)

    print(
        "DRY RUN: In production, this step would also query MLflow for:\n"
        "  - ab_test_ctr_lift > 0\n"
        "  - ab_test_p_value <= 0.05\n"
        "  - ab_test_add_to_cart_lift > 0"
    )
    print("✓ A/B test gate documentation check passed.")


if __name__ == "__main__":
    main()
