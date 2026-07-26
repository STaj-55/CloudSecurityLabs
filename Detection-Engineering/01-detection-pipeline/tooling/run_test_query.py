#!/usr/bin/env python3
"""Execute generated detection test queries against a local Kusto emulator.

This is the step that turns the fixture harness from a structural check into an
actual proof. build_test_query.py produces a self-contained query -- every table is
shadowed by a datatable() literal, so there is nothing to ingest and no workspace to
provision. This script POSTs that query to a local Kusto engine and checks:

  1. the row count equals expected_rows;
  2. every returned row corresponds to a declared true_positive;
  3. no returned row corresponds to a declared true_negative.

(2) and (3) are what make it a real negative-then-positive proof rather than a count
that happens to line up.

Start the engine first:  docker compose up -d

Usage:
    python3 tooling/run_test_query.py --all
    python3 tooling/run_test_query.py --rule <uuid>
    python3 tooling/run_test_query.py --all --wait 180
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

from build_test_query import (
    FixtureError,
    PROJECT_ROOT,
    build_test_query,
    fixture_path_for,
    load_detections,
    load_fixture,
)

# The emulator's default database. Overridable so the same script can later point at
# a real ADX cluster or a CI service container.
DEFAULT_ENDPOINT = os.environ.get("KUSTO_ENDPOINT", "http://127.0.0.1:8080")
DEFAULT_DATABASE = os.environ.get("KUSTO_DATABASE", "NetDefaultDB")

# Only these fixture types are used to match a returned row back to a fixture row.
# datetime and dynamic are excluded because Kusto reformats them on the way out
# (fractional-second precision, key ordering) and string equality would be unreliable.
COMPARABLE_TYPES = {"string", "int", "long", "bool"}


class KustoError(Exception):
    """Raised when the engine is unreachable or rejects a query."""


# --------------------------------------------------------------------------
# Kusto REST client (stdlib only — no new dependency for one HTTP POST)
# --------------------------------------------------------------------------


def execute(query: str, endpoint: str = DEFAULT_ENDPOINT, database: str = DEFAULT_DATABASE,
            timeout: int = 60) -> list[dict]:
    """Run a KQL query and return the primary result as a list of dicts.

    Uses the v2 REST API because its response frames are explicitly tagged with a
    TableKind, so the primary result can be identified unambiguously rather than by
    guessing an index.
    """
    url = f"{endpoint.rstrip('/')}/v2/rest/query"
    payload = json.dumps({"db": database, "csl": query}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            frames = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Kusto returns the actual syntax/semantic error in the body — surface it,
        # because "HTTP 400" on its own is useless when debugging generated KQL.
        detail = exc.read().decode("utf-8", errors="replace")
        raise KustoError(f"query rejected (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise KustoError(
            f"cannot reach Kusto at {endpoint}: {exc.reason}. Is it running? "
            "Start it with: docker compose up -d"
        ) from exc

    for frame in frames:
        if frame.get("FrameType") == "DataTable" and frame.get("TableKind") == "PrimaryResult":
            columns = [column["ColumnName"] for column in frame.get("Columns", [])]
            return [dict(zip(columns, row)) for row in frame.get("Rows", [])]

    raise KustoError("response contained no PrimaryResult frame")


def is_available(endpoint: str = DEFAULT_ENDPOINT, timeout: int = 3) -> bool:
    """Cheap liveness probe. Used to skip execution tests when the engine is down."""
    try:
        execute("print ping = 1", endpoint=endpoint, timeout=timeout)
        return True
    except KustoError:
        return False


def wait_until_ready(endpoint: str = DEFAULT_ENDPOINT, timeout: int = 180) -> bool:
    """Poll until the engine answers. Kustainer takes ~30-60s to become queryable."""
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        if is_available(endpoint):
            return True
        print(f"  waiting for Kusto at {endpoint} (attempt {attempt})...", flush=True)
        time.sleep(5)
    return False


# --------------------------------------------------------------------------
# Row classification
# --------------------------------------------------------------------------


def _rows_match(returned: dict, fixture_row: dict, columns: dict[str, str]) -> bool:
    """True if a returned row agrees with a fixture row on every comparable column."""
    shared = [
        name
        for name, kql_type in columns.items()
        if kql_type in COMPARABLE_TYPES and name in returned and name in fixture_row
    ]
    if not shared:
        return False
    return all(str(returned[name]) == str(fixture_row[name]) for name in shared)


def classify(returned: dict, blocks: list[dict]) -> str:
    """Label a returned row as a fixture true positive, true negative, or unknown."""
    for block in blocks:
        columns = block["columns"]
        for row in block.get("true_positives") or []:
            if _rows_match(returned, row, columns):
                return "true_positive"
        for row in block.get("true_negatives") or []:
            if _rows_match(returned, row, columns):
                return "true_negative"
    return "unknown"


def check_rule(detection: dict, fixture: dict, endpoint: str) -> tuple[bool, list[str]]:
    """Execute one rule's test query and evaluate the result. Returns (ok, messages)."""
    query = build_test_query(detection, fixture)
    rows = execute(query, endpoint=endpoint)

    blocks = fixture["_blocks"]
    expected = fixture["expected_rows"]
    total_tn = sum(len(b.get("true_negatives") or []) for b in blocks)

    problems: list[str] = []
    notes: list[str] = []

    if len(rows) != expected:
        problems.append(f"returned {len(rows)} row(s), expected {expected}")

    labels = [classify(row, blocks) for row in rows]
    leaked = labels.count("true_negative")
    matched = labels.count("true_positive")
    unknown = labels.count("unknown")

    if leaked:
        problems.append(
            f"{leaked} true_negative row(s) matched the query — the rule is too broad"
        )
    if unknown:
        problems.append(
            f"{unknown} returned row(s) matched no fixture row (check the fixture is current)"
        )

    if not problems:
        notes.append(
            f"{matched}/{expected} true positive(s) matched, "
            f"all {total_tn} true negative(s) correctly filtered out"
        )

    return not problems, problems + notes


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute detection test queries against a local Kusto emulator."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--rule", metavar="UUID", help="run one rule by id")
    group.add_argument("--all", action="store_true", help="run every rule that has a fixture")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help=f"default: {DEFAULT_ENDPOINT}")
    parser.add_argument(
        "--wait",
        type=int,
        metavar="SECONDS",
        help="poll for the engine to become ready before running (use after 'compose up')",
    )
    args = parser.parse_args()

    if args.wait:
        print(f"Waiting up to {args.wait}s for Kusto...")
        if not wait_until_ready(args.endpoint, args.wait):
            print(f"FATAL Kusto did not become ready within {args.wait}s", file=sys.stderr)
            return 2
        print("Kusto is ready.\n")
    elif not is_available(args.endpoint):
        print(
            f"FATAL cannot reach Kusto at {args.endpoint}.\n"
            "      Start it with:  docker compose up -d\n"
            "      Then retry with: --wait 180",
            file=sys.stderr,
        )
        return 2

    detections = load_detections()
    if args.rule:
        rule_ids = [args.rule]
    else:
        rule_ids = sorted(
            rule_id
            for rule_id, detection in detections.items()
            if (detection.get("validation") or {}).get("method") == "fixture-datatable"
        )
        if not rule_ids:
            print("FATAL no rules use fixture-datatable validation", file=sys.stderr)
            return 2

    failed = 0
    for rule_id in rule_ids:
        detection = detections.get(rule_id)
        if detection is None:
            print(f"FAIL no detection found with id {rule_id}")
            failed += 1
            continue

        rel = detection["_path"].relative_to(PROJECT_ROOT)
        try:
            fixture = load_fixture(fixture_path_for(rule_id))
            ok, messages = check_rule(detection, fixture, args.endpoint)
        except (FixtureError, KustoError) as exc:
            print(f"FAIL {rel}")
            print(f"       {exc}")
            failed += 1
            continue

        print(f"{'PASS' if ok else 'FAIL'} {rel}")
        for message in messages:
            print(f"       {message}")
        if not ok:
            failed += 1

    total = len(rule_ids)
    print()
    if failed:
        print(f"{total - failed}/{total} rules executed correctly — {failed} failure(s)")
        return 1

    print(f"{total}/{total} rules executed correctly against the Kusto emulator")
    return 0


if __name__ == "__main__":
    sys.exit(main())
