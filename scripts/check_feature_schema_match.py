#!/usr/bin/env python3
"""
check_feature_schema_match.py
------------------------------
Validates that the feature contract expected by the serving system is
documented consistently across the model registry and OpenAPI spec.

Checks:
  - lifecycle/model-registry.yaml mentions core feature/response field names
  - api/openapi.yaml mentions the same field names and the X-Model-Version header

Usage (CI):
    python scripts/check_feature_schema_match.py \
        --model-version v1.3.0-20260601 \
        --serving-config deploy/inference/values.yaml

The --serving-config argument is accepted for CI compatibility but not
strictly required; validation is performed on the registry and OpenAPI files.

Exits 0 on success, 1 on any validation failure.
"""

import sys
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

REGISTRY_PATH = REPO_ROOT / "lifecycle" / "model-registry.yaml"
OPENAPI_PATH = REPO_ROOT / "api" / "openapi.yaml"

# Strings that must appear in the model registry
REGISTRY_REQUIRED = [
    "user_id",
    "feature_schema",
    "artifacts",
]

# Strings that must appear in the OpenAPI spec
OPENAPI_REQUIRED = [
    "user_id",
    "X-Model-Version",
    "recommendation",
    "score",
]


def read_file(path: Path) -> str:
    if not path.exists():
        print(f"ERROR: Required file not found: {path}", file=sys.stderr)
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def check_strings(content: str, required: list, source_label: str) -> list:
    missing = [s for s in required if s not in content]
    return missing


def main():
    parser = argparse.ArgumentParser(
        description="Validate feature schema consistency between registry and OpenAPI spec."
    )
    parser.add_argument("--model-version", required=False, help="Model version tag (informational)")
    parser.add_argument("--serving-config", required=False, help="Path to serving values YAML (accepted, not validated)")
    args = parser.parse_args()

    if args.model_version:
        print(f"Checking feature schema for model version: {args.model_version}")

    registry_content = read_file(REGISTRY_PATH)
    openapi_content = read_file(OPENAPI_PATH)

    missing_registry = check_strings(registry_content, REGISTRY_REQUIRED, "model-registry.yaml")
    missing_openapi = check_strings(openapi_content, OPENAPI_REQUIRED, "openapi.yaml")

    failed = False

    if missing_registry:
        print(
            f"ERROR: lifecycle/model-registry.yaml is missing required fields: {missing_registry}",
            file=sys.stderr,
        )
        failed = True
    else:
        print(f"✓ model-registry.yaml contains all required feature fields: {REGISTRY_REQUIRED}")

    if missing_openapi:
        print(
            f"ERROR: api/openapi.yaml is missing required contract fields: {missing_openapi}",
            file=sys.stderr,
        )
        failed = True
    else:
        print(f"✓ openapi.yaml contains all required contract fields: {OPENAPI_REQUIRED}")

    if failed:
        sys.exit(1)

    print("✓ Feature schema consistency check passed.")


if __name__ == "__main__":
    main()
