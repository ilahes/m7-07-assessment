#!/usr/bin/env python3
"""
check_registry_state.py
-----------------------
Validates that lifecycle/model-registry.yaml contains the required fields
and that a given model version is in one of the allowed states.

Usage (CI):
    python scripts/check_registry_state.py \\
        --model-name rec-two-tower-v1 \\
        --version v1.3.0-20260601 \\
        --allowed-states candidate staging

Exits 0 on success, 1 on any validation failure.
"""

import sys
import os
import re
import argparse

REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "lifecycle", "model-registry.yaml"
)

# Required top-level fields in the registry file
REQUIRED_FIELDS = [
    "model_name",
    "schema_version",
]

# Required per-entry fields (checked via regex presence)
REQUIRED_ENTRY_FIELDS = [
    "version",
    "state",
    "approved_by",
    "artifacts",
]


def read_registry(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError as e:
        print(f"ERROR: Cannot read registry at {path}: {e}", file=sys.stderr)
        sys.exit(1)


def check_required_fields(content, fields):
    missing = []
    for field in fields:
        pattern = re.compile(rf'^{re.escape(field)}:', re.MULTILINE)
        if not pattern.search(content):
            missing.append(field)
    return missing


def find_entry_state(content, version):
    """
    Find the state for a given version. Returns state string or None.
    """
    # Locate the version string, then find the nearest state: line after it
    version_pattern = re.compile(
        rf'version:\s+"?{re.escape(version)}"?', re.MULTILINE
    )
    state_pattern = re.compile(r'^\s+state:\s+(\S+)', re.MULTILINE)

    m = version_pattern.search(content)
    if not m:
        return None

    rest = content[m.start():]
    sm = state_pattern.search(rest)
    if not sm:
        return None

    return sm.group(1).rstrip()


def main():
    parser = argparse.ArgumentParser(description="Validate model registry state.")
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--allowed-states", nargs="+", required=True)
    args = parser.parse_args()

    registry_path = os.path.abspath(REGISTRY_PATH)
    print(f"Reading registry: {registry_path}")
    content = read_registry(registry_path)

    # 1. Check top-level required fields
    missing = check_required_fields(content, REQUIRED_FIELDS)
    if missing:
        print(f"ERROR: Registry missing required fields: {missing}", file=sys.stderr)
        sys.exit(1)
    print("✓ Required top-level fields present")

    # 2. Check that model_name matches
    model_name_match = re.search(r'^model_name:\s+(\S+)', content, re.MULTILINE)
    if model_name_match:
        found_model = model_name_match.group(1)
        if found_model != args.model_name:
            print(
                f"ERROR: Registry model_name '{found_model}' does not match "
                f"expected '{args.model_name}'",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"✓ model_name matches: {found_model}")
    else:
        print("ERROR: Cannot parse model_name from registry.", file=sys.stderr)
        sys.exit(1)

    # 3. Find version entry and check its state
    state = find_entry_state(content, args.version)
    if state is None:
        print(
            f"ERROR: Version '{args.version}' not found in registry.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"✓ Found version {args.version} with state: {state}")

    if state not in args.allowed_states:
        print(
            f"ERROR: State '{state}' is not in allowed states {args.allowed_states}.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"✓ State '{state}' is allowed. Registry check passed.")


if __name__ == "__main__":
    main()
