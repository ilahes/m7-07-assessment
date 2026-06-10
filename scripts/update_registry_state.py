#!/usr/bin/env python3
"""
update_registry_state.py
------------------------
Simulates promotion of a model version in lifecycle/model-registry.yaml
by printing what would be written. This is a dry-run script suitable for
an assessment dossier; in production it would write back to an MLflow or
GCS-backed registry via API.

Usage (CI):
    python scripts/update_registry_state.py \\
        --model-name rec-two-tower-v1 \\
        --version v1.3.0-20260601 \\
        --state staging \\
        --promoted-by github-actions

Exits 0 on success, 1 on argument or registry errors.
"""

import sys
import os
import re
import argparse
from datetime import datetime, timezone

REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "lifecycle", "model-registry.yaml"
)

VALID_STATES = ("candidate", "staging", "production", "archived", "rolled-back")


def read_registry(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError as e:
        print(f"ERROR: Cannot read registry at {path}: {e}", file=sys.stderr)
        sys.exit(1)


def find_entry_state(content, version):
    version_pattern = re.compile(
        rf'version:\s+"?{re.escape(version)}"?', re.MULTILINE
    )
    state_pattern = re.compile(r'^\s+state:\s+(\S+)', re.MULTILINE)

    m = version_pattern.search(content)
    if not m:
        return None
    rest = content[m.start():]
    sm = state_pattern.search(rest)
    return sm.group(1).rstrip() if sm else None


def main():
    parser = argparse.ArgumentParser(description="Promote model version in registry (dry-run).")
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--state", required=True, choices=VALID_STATES)
    parser.add_argument("--promoted-by", required=True)
    args = parser.parse_args()

    registry_path = os.path.abspath(REGISTRY_PATH)
    content = read_registry(registry_path)

    current_state = find_entry_state(content, args.version)
    if current_state is None:
        print(
            f"ERROR: Version '{args.version}' not found in registry.",
            file=sys.stderr,
        )
        sys.exit(1)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("=" * 60)
    print("DRY-RUN: Registry state update")
    print("=" * 60)
    print(f"  Registry:      {registry_path}")
    print(f"  Model name:    {args.model_name}")
    print(f"  Version:       {args.version}")
    print(f"  Current state: {current_state}")
    print(f"  New state:     {args.state}")
    print(f"  Promoted by:   {args.promoted_by}")
    print(f"  Timestamp:     {now}")
    print("=" * 60)
    print(
        "In production this script would call MLflow REST API:\n"
        f"  PATCH /api/2.0/mlflow/model-versions/update\n"
        f"  body: {{\"name\": \"{args.model_name}\", \"version\": \"{args.version}\","
        f" \"description\": \"state={args.state} promoted_by={args.promoted_by} at={now}\"}}"
    )
    print("✓ Dry-run complete. No registry was modified.")


if __name__ == "__main__":
    main()
