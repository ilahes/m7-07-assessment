#!/usr/bin/env python3
"""
get_latest_candidate.py
-----------------------
Reads lifecycle/model-registry.yaml and prints the version string of the
latest entry whose state is 'candidate' or 'staging'.

If no candidate is found, falls back to the latest production entry.
Exits 0 on success, 1 if the registry file cannot be read or is empty.

Usage (CI):
    MODEL_VERSION=$(python scripts/get_latest_candidate.py)
"""

import sys
import os
import re

REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "lifecycle", "model-registry.yaml"
)

PREFERRED_STATES = ("candidate", "staging")
FALLBACK_STATES = ("production",)


def parse_registry(path):
    """
    Minimal parser: extract (version, state) pairs from top-level entries.
    Entry versions look like:   - version: "v1.3.0-20260601"
    (list item, indented, starting with `- version:`).
    Avoids a hard PyYAML dependency.
    """
    try:
        with open(path, "r") as f:
            content = f.read()
    except OSError as e:
        print(f"ERROR: Cannot read registry at {path}: {e}", file=sys.stderr)
        sys.exit(1)

    # Match only list-item version lines: `  - version: "..."`
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

    return entries


def main():
    registry_path = os.path.abspath(REGISTRY_PATH)
    entries = parse_registry(registry_path)

    if not entries:
        print("ERROR: No entries found in model registry.", file=sys.stderr)
        sys.exit(1)

    for preferred_state in PREFERRED_STATES:
        for version, state in entries:
            if state == preferred_state:
                print(version)
                return

    for fallback_state in FALLBACK_STATES:
        for version, state in entries:
            if state == fallback_state:
                print(
                    f"# WARN: No candidate found; using {fallback_state} version",
                    file=sys.stderr,
                )
                print(version)
                return

    print("ERROR: No usable model version found in registry.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
