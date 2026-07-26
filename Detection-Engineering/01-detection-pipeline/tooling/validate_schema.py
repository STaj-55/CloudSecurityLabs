#!/usr/bin/env python3
"""Validate every detection YAML under detections/ against schema/detection.schema.json.

Prints PASS/FAIL per file with the exact failing field path, and exits non-zero if
anything fails. Also enforces global rule-ID uniqueness, which the JSON Schema cannot
see because a schema only ever looks at one document at a time.

Run from anywhere:  python3 tooling/validate_schema.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover - environment problem, not a rule problem
    sys.exit(f"Missing dependency: {exc}. Run: pip install -r requirements.txt")

# Anchor every path to the project directory (the parent of tooling/), NOT the
# process working directory. This is what lets CI invoke the script from the repo
# root while the script still finds detections/ and schema/ correctly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "schema" / "detection.schema.json"
DETECTIONS_DIR = PROJECT_ROOT / "detections"


def format_path(error) -> str:
    """Render a jsonschema error location as a readable field path.

    absolute_path is a deque of keys and list indices, e.g.
    ["entity_mappings", 0, "identifiers", 0, "column"] -> entity_mappings[0].identifiers[0].column
    An empty path means the error is on the document root.
    """
    parts: list[str] = []
    for token in error.absolute_path:
        if isinstance(token, int):
            parts.append(f"[{token}]")
        else:
            parts.append(f".{token}" if parts else str(token))
    return "".join(parts) or "<root>"


def load_yaml(path: Path):
    """Parse a YAML file, returning (document, error_message)."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle), None
    except yaml.YAMLError as exc:
        return None, f"YAML parse error: {exc}"
    except OSError as exc:
        return None, f"Could not read file: {exc}"


def main() -> int:
    if not SCHEMA_PATH.is_file():
        print(f"FATAL schema not found at {SCHEMA_PATH}", file=sys.stderr)
        return 2
    if not DETECTIONS_DIR.is_dir():
        print(f"FATAL detections directory not found at {DETECTIONS_DIR}", file=sys.stderr)
        return 2

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    detection_files = sorted(
        p for p in DETECTIONS_DIR.rglob("*") if p.suffix in (".yaml", ".yml") and p.is_file()
    )

    if not detection_files:
        print("FATAL no detection files found under detections/", file=sys.stderr)
        return 2

    failed = 0
    ids_seen: dict[str, list[str]] = defaultdict(list)

    for path in detection_files:
        rel = path.relative_to(PROJECT_ROOT)
        document, load_error = load_yaml(path)

        if load_error is not None:
            print(f"FAIL {rel}")
            print(f"       {load_error}")
            failed += 1
            continue

        if not isinstance(document, dict):
            print(f"FAIL {rel}")
            print("       file is empty or is not a YAML mapping")
            failed += 1
            continue

        # Track IDs even on files that fail other checks, so duplicates still surface.
        rule_id = document.get("id")
        if isinstance(rule_id, str):
            ids_seen[rule_id].append(str(rel))

        errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
        if errors:
            print(f"FAIL {rel}")
            for error in errors:
                print(f"       {format_path(error)}: {error.message}")
            failed += 1
        else:
            print(f"PASS {rel}")

    duplicates = {rid: files for rid, files in ids_seen.items() if len(files) > 1}
    if duplicates:
        print()
        for rule_id, files in sorted(duplicates.items()):
            print(f"FAIL duplicate rule id {rule_id} used by:")
            for file_path in files:
                print(f"       {file_path}")
        failed += len(duplicates)

    total = len(detection_files)
    print()
    if failed:
        print(f"{total - min(failed, total)}/{total} detections valid — {failed} failure(s)")
        return 1

    print(f"{total}/{total} detections valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
