#!/usr/bin/env python3
"""Structural check: every column a rule query reads must exist in its fixture.

This runs with no Azure, no workspace and no credentials. It catches the single
most common fixture bug -- the query references a column the fixture never
declares, so the generated datatable() compiles but the rule silently returns
zero rows and the "test" passes for the wrong reason.

It is a heuristic parser, not a KQL compiler. It errs toward reporting a name it
is unsure about, on the grounds that a noisy failure you can read beats a silent
pass you cannot.

Run:  python3 tooling/check_fixture_columns.py
"""

from __future__ import annotations

import sys

from build_test_query import (
    FixtureError,
    PROJECT_ROOT,
    extract_column_references,
    fixture_columns,
    fixture_path_for,
    load_detections,
    load_fixture,
)


def main() -> int:
    detections = load_detections()
    if not detections:
        print("FATAL no detections found under detections/", file=sys.stderr)
        return 2

    failed = 0
    checked = 0
    skipped = 0

    for rule_id in sorted(detections, key=lambda r: str(detections[r]["_path"])):
        detection = detections[rule_id]
        rel = detection["_path"].relative_to(PROJECT_ROOT)
        validation = detection.get("validation") or {}

        # A rule may legitimately opt out of fixture-based validation.
        if validation.get("method") != "fixture-datatable" or not validation.get("fixture"):
            print(f"SKIP {rel}")
            print(f"       validation.method is '{validation.get('method')}' — no fixture expected")
            skipped += 1
            continue

        try:
            fixture = load_fixture(fixture_path_for(rule_id))
        except FixtureError as exc:
            print(f"FAIL {rel}")
            print(f"       {exc}")
            failed += 1
            continue

        checked += 1
        problems: list[str] = []

        # 1. The fixture must point back at this rule.
        if fixture.get("rule_id") != rule_id:
            problems.append(
                f"fixture rule_id '{fixture.get('rule_id')}' does not match rule id '{rule_id}'"
            )

        # 2. Fixture tables must be the tables the rule declares as its data source.
        declared = set(detection.get("data_source", {}).get("tables") or [])
        fixture_tables = {block["table"] for block in fixture["_blocks"]}
        if fixture_tables != declared:
            problems.append(
                f"fixture tables {sorted(fixture_tables)} do not match "
                f"data_source.tables {sorted(declared)}"
            )

        # 3. expected_rows must equal the true-positive count. If they diverge, the
        #    negative-then-positive proof is not actually being asserted.
        total_tp = sum(len(b.get("true_positives") or []) for b in fixture["_blocks"])
        if fixture.get("expected_rows") != total_tp:
            problems.append(
                f"expected_rows is {fixture.get('expected_rows')} but the fixture "
                f"declares {total_tp} true positive(s)"
            )

        # 4. The main event: every column the query reads must be declared.
        available = fixture_columns(fixture)
        referenced = extract_column_references(detection["query"], fixture_tables | declared)
        missing = referenced - available
        if missing:
            problems.append(
                "query references column(s) not declared in the fixture: "
                + ", ".join(sorted(missing))
            )

        if problems:
            print(f"FAIL {rel}")
            for problem in problems:
                print(f"       {problem}")
            failed += 1
        else:
            print(f"PASS {rel}")
            print(f"       {len(referenced)} column reference(s) all present in fixture")

    print()
    if failed:
        print(f"{checked - failed}/{checked} fixtures structurally valid — {failed} failure(s)")
        return 1

    summary = f"{checked}/{checked} fixtures structurally valid"
    if skipped:
        summary += f" ({skipped} rule(s) skipped — no fixture expected)"
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
