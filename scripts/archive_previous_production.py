#!/usr/bin/env python3
"""
archive_previous_production.py
-------------------------------
Dry-run: simulates archiving the previous production model version before
a new version is promoted to production.

In production this would call the MLflow REST API to transition the previous
production version's state to 'archived'. For the assessment dossier it reads
the registry, identifies the current production version, and prints what would
be archived.

Usage (CI):
    python scripts/archive_previous_production.py \
        --model-name rec-two-tower-v1 \
        --superseded-by v1.3.0-20260601

Exits 0 safely in all cases (archival failure should not block a rollforward).
"""

import sys
import re
import argparse
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).parent.parent
REGISTRY_PATH = REPO_ROOT / "lifecycle" / "model-registry.yaml"


def read_registry(path: Path) -> str:
    if not path.exists():
        print(f"ERROR: Registry not found at {path}", file=sys.stderr)
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def find_production_versions(content: str) -> list:
    """
    Find all (version, state) pairs where state == production.
    Uses the same list-item version pattern as get_latest_candidate.py.
    """
    version_pattern = re.compile(r'^\s+-\s+version:\s+"([^"]+)"', re.MULTILINE)
    state_pattern = re.compile(r'^\s+state:\s+(\w[\w-]*)', re.MULTILINE)

    entries = []
    version_matches = [(m.start(), m.group(1)) for m in version_pattern.finditer(content)]
    state_matches = [(m.start(), m.group(1)) for m in state_pattern.finditer(content)]

    for v_pos, version in version_matches:
        for s_pos, state in state_matches:
            if s_pos > v_pos:
                entries.append((version, state.rstrip()))
                break

    return [(v, s) for v, s in entries if s == "production"]


def main():
    parser = argparse.ArgumentParser(
        description="Dry-run archive of previous production model (assessment dossier)."
    )
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--superseded-by", required=True, help="New production version being promoted")
    args = parser.parse_args()

    content = read_registry(REGISTRY_PATH)
    production_versions = find_production_versions(content)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("=" * 60)
    print("DRY RUN: Archive previous production model")
    print("=" * 60)
    print(f"  Model:        {args.model_name}")
    print(f"  Superseded by: {args.superseded_by}")
    print(f"  Timestamp:    {now}")

    if not production_versions:
        print("  No current production version found in registry — nothing to archive.")
    else:
        for version, state in production_versions:
            if version != args.superseded_by:
                print(f"\n  Would archive: {version} (current state: {state})")
                print(
                    f"  MLflow API call (production):\n"
                    f"    PATCH /api/2.0/mlflow/model-versions/update\n"
                    f"    body: {{\"name\": \"{args.model_name}\", \"version\": \"{version}\","
                    f" \"description\": \"state=archived superseded_by={args.superseded_by} at={now}\"}}"
                )

    print("=" * 60)
    print("✓ Dry-run complete. No registry was modified.")


if __name__ == "__main__":
    main()
