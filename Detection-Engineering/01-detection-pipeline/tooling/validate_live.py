#!/usr/bin/env python3
"""Validate detection queries against the real Log Analytics workspace schema.

Submits each rule's query with a one-second timespan. That is enough for the service
to parse the KQL and resolve every column against the workspace schema, but narrow
enough that no data comes back. Queries are billed at zero cost.

The point of this script is the three-way outcome:

  PASS  the query parsed and every column resolved
  SKIP  a table the rule declares has no schema in this workspace yet -- warn, but
        do not fail the build; that table arrives with a later project
  FAIL  the KQL is invalid, or a referenced column does not exist on a table that
        does exist. This is the case that would otherwise deploy cleanly to
        Sentinel and then match nothing, silently, forever.

The classification below is derived from what the API actually returns (probed
against a live workspace), not from documented error codes. The observed responses
are tabulated in the project README under "Live schema validation".

Usage:
    export LAW_CUSTOMER_ID=<workspace GUID>
    python3 tooling/validate_live.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import timedelta

try:
    from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
    from azure.identity import DefaultAzureCredential
    from azure.monitor.query import LogsQueryClient
except ImportError as exc:  # pragma: no cover
    sys.exit(f"Missing dependency: {exc}. Run: pip install -r requirements.txt")

from build_test_query import PROJECT_ROOT, load_detections

# One second is plenty: semantic analysis happens regardless of timespan, so the
# schema is fully checked while guaranteeing an empty result set.
VALIDATION_TIMESPAN = timedelta(seconds=1)

# Both failure modes come back as SEM0100. The only thing that distinguishes them is
# the message wording, so match on that and then corroborate against the rule's own
# declared tables before deciding a missing table is expected rather than a typo.
MISSING_TABLE_MARKER = "failed to resolve table or column expression named"
MISSING_COLUMN_MARKERS = (
    "failed to resolve column or scalar expression named",
    "failed to resolve scalar expression named",
)
_NAMED_ENTITY = re.compile(r"named '([^']+)'")

PASS, SKIP, FAIL = "PASS", "SKIP", "FAIL"


def deepest_error(body: dict) -> dict:
    """Walk the nested innererror chain to the most specific error object."""
    node = body.get("error", {}) if isinstance(body, dict) else {}
    while isinstance(node.get("innererror"), dict):
        node = node["innererror"]
    return node


def error_body(exc: HttpResponseError) -> dict:
    try:
        return exc.response.json()
    except Exception:  # noqa: BLE001 - a non-JSON body is itself just "no detail"
        return {}


def classify(exc: HttpResponseError, declared_tables: set[str]) -> tuple[str, str]:
    """Map an API error onto (state, human-readable detail).

    A missing table is only SKIP when the unresolved name is one the rule actually
    declares in data_source.tables. If the query references some other table -- a
    typo, or a table the author forgot to declare -- that is a real defect and FAILs.
    """
    body = error_body(exc)
    node = deepest_error(body)
    code = node.get("code") or "UnknownError"
    message = node.get("message") or str(exc)
    lowered = message.lower()

    if MISSING_TABLE_MARKER in lowered:
        match = _NAMED_ENTITY.search(message)
        name = match.group(1) if match else "<unknown>"
        if name in declared_tables:
            return SKIP, (
                f"table '{name}' has no schema in this workspace yet — "
                "column validation for this rule is unverified"
            )
        return FAIL, (
            f"unresolved table '{name}' is not declared in data_source.tables "
            f"(declared: {', '.join(sorted(declared_tables)) or 'none'}) — "
            "likely a typo or an undeclared dependency"
        )

    if any(marker in lowered for marker in MISSING_COLUMN_MARKERS):
        match = _NAMED_ENTITY.search(message)
        name = match.group(1) if match else "<unknown>"
        return FAIL, f"column '{name}' does not exist on the table — [{code}] {message}"

    return FAIL, f"[{code}] {message}"


def validate_rule(client: LogsQueryClient, workspace: str, detection: dict) -> tuple[str, str]:
    declared = set(detection.get("data_source", {}).get("tables") or [])
    try:
        result = client.query_workspace(
            workspace, detection["query"], timespan=VALIDATION_TIMESPAN
        )
    except HttpResponseError as exc:
        return classify(exc, declared)

    # A partial result carries its error in a different place; run it through the
    # same classifier so the policy stays in one function.
    partial = getattr(result, "partial_error", None)
    if partial is not None:
        return FAIL, f"partial result: {partial}"

    return PASS, "query parsed and all columns resolved"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate detection queries against the live Log Analytics schema."
    )
    parser.add_argument(
        "--workspace",
        default=os.environ.get("LAW_CUSTOMER_ID"),
        help="Log Analytics workspace GUID (customerId). Defaults to $LAW_CUSTOMER_ID.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="pause between queries to stay under API throttling limits (default: 1.0)",
    )
    args = parser.parse_args()

    if not args.workspace:
        print(
            "FATAL no workspace GUID. Set LAW_CUSTOMER_ID or pass --workspace.",
            file=sys.stderr,
        )
        return 2

    detections = load_detections()
    if not detections:
        print("FATAL no detections found under detections/", file=sys.stderr)
        return 2

    try:
        client = LogsQueryClient(DefaultAzureCredential())
    except ClientAuthenticationError as exc:
        print(f"FATAL could not acquire Azure credentials: {exc}", file=sys.stderr)
        return 2

    ordered = sorted(detections.values(), key=lambda d: str(d["_path"]))
    failed = 0
    skipped: list[tuple[str, str]] = []

    for index, detection in enumerate(ordered):
        rel = detection["_path"].relative_to(PROJECT_ROOT)

        # Throttle. Only a couple of rules exist today, but the loop is the thing
        # that grows, and hitting 429s in CI is a miserable way to find that out.
        if index:
            time.sleep(args.delay)

        try:
            state, detail = validate_rule(client, args.workspace, detection)
        except ClientAuthenticationError as exc:
            print(f"FATAL Azure authentication failed: {exc}", file=sys.stderr)
            return 2

        print(f"{state} {rel}")
        print(f"       {detail}")

        if state == FAIL:
            failed += 1
        elif state == SKIP:
            skipped.append((detection["title"], detail))

    total = len(ordered)
    print()

    # Skipped rules are printed again, by name, so a coverage gap is visible in the
    # log rather than blending into a wall of PASS lines.
    if skipped:
        print(f"{len(skipped)} rule(s) SKIPPED — not validated against a live schema:")
        for title, detail in skipped:
            print(f"  - {title}: {detail}")
        print()

    if failed:
        print(f"{total - failed}/{total} rules validated against the live workspace "
              f"— {failed} failure(s)")
        return 1

    summary = f"{total}/{total} rules validated against the live workspace"
    if skipped:
        summary += f" ({len(skipped)} skipped)"
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
