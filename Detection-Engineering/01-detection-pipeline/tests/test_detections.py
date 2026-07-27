"""Pytest harness for detection fixtures.

Everything here runs offline. The tests that would need a real Log Analytics
workspace to execute the generated KQL are marked skipped, with the reason stated
explicitly rather than silently passing.

Run:  python3 -m pytest tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# tooling/ is a plain script directory, not an installed package, so it has to be
# put on the import path explicitly. Running the scripts directly works without
# this because Python adds the script's own directory to sys.path; pytest does not.
sys.path.insert(0, str(PROJECT_ROOT / "tooling"))

from build_test_query import (  # noqa: E402
    build_test_query,
    extract_column_references,
    fixture_columns,
    fixture_path_for,
    load_detections,
    load_fixture,
)

FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
DETECTIONS = load_detections()
FIXTURE_RULE_IDS = sorted(path.stem for path in FIXTURES_DIR.glob("*.yaml"))


def _load(rule_id: str):
    assert rule_id in DETECTIONS, f"fixture {rule_id}.yaml has no matching detection rule"
    return DETECTIONS[rule_id], load_fixture(fixture_path_for(rule_id))


def test_at_least_one_fixture_exists():
    assert FIXTURE_RULE_IDS, "no fixtures found under tests/fixtures/"


@pytest.mark.parametrize("rule_id", FIXTURE_RULE_IDS)
def test_fixture_declares_the_rules_tables(rule_id):
    detection, fixture = _load(rule_id)
    assert fixture["rule_id"] == rule_id
    declared = set(detection["data_source"]["tables"])
    in_fixture = {block["table"] for block in fixture["_blocks"]}
    assert in_fixture == declared


@pytest.mark.parametrize("rule_id", FIXTURE_RULE_IDS)
def test_expected_rows_equals_true_positive_count(rule_id):
    """The row-count contract: every true positive must survive the query.

    This is the assertion the (skipped) execution test will make against real
    results. Checking it here keeps the fixture internally consistent, so a
    mismatch is caught long before a workspace is involved.
    """
    _, fixture = _load(rule_id)
    total_tp = sum(len(block.get("true_positives") or []) for block in fixture["_blocks"])
    assert fixture["expected_rows"] == total_tp


@pytest.mark.parametrize("rule_id", FIXTURE_RULE_IDS)
def test_fixture_has_a_true_negative(rule_id):
    """Negative-then-positive: a fixture with no true negative proves nothing."""
    _, fixture = _load(rule_id)
    total_tn = sum(len(block.get("true_negatives") or []) for block in fixture["_blocks"])
    assert total_tn > 0, "fixture needs at least one row that must NOT match"


@pytest.mark.parametrize("rule_id", FIXTURE_RULE_IDS)
def test_test_query_builds(rule_id):
    detection, fixture = _load(rule_id)
    query = build_test_query(detection, fixture)

    for block in fixture["_blocks"]:
        assert f"let {block['table']} = datatable(" in query

    # The rule query must appear byte-for-byte. If this ever fails, the harness
    # is testing something other than what gets deployed.
    assert detection["query"] in query


@pytest.mark.parametrize("rule_id", FIXTURE_RULE_IDS)
def test_query_columns_are_declared_in_fixture(rule_id):
    detection, fixture = _load(rule_id)
    tables = {block["table"] for block in fixture["_blocks"]}
    referenced = extract_column_references(detection["query"], tables)
    missing = referenced - fixture_columns(fixture)
    assert not missing, f"query reads column(s) absent from the fixture: {sorted(missing)}"


import os  # noqa: E402

from run_test_query import (  # noqa: E402
    DEFAULT_ENDPOINT,
    check_rule,
    execute as execute_kusto,
    is_available,
)


def _log_analytics_executor():
    """Executor backed by the real Log Analytics workspace, or None if unavailable.

    The fixture queries shadow every table with `let <Table> = datatable(...)`, so
    they never read a single row of real workspace data — the workspace is being used
    purely as a KQL engine. timespan=None is passed explicitly: the implicit time
    filter does not apply to a let-bound table, but relying on that quietly would be
    a nasty surprise if it ever changed.
    """
    workspace = os.environ.get("LAW_CUSTOMER_ID")
    if not workspace:
        return None

    try:
        from azure.identity import DefaultAzureCredential
        from azure.monitor.query import LogsQueryClient
    except ImportError:
        return None

    try:
        client = LogsQueryClient(DefaultAzureCredential())
    except Exception:  # noqa: BLE001 - any credential problem means "not available"
        return None

    def execute(query: str) -> list[dict]:
        result = client.query_workspace(workspace, query, timespan=None)
        tables = getattr(result, "tables", None) or getattr(result, "partial_data", None) or []
        rows: list[dict] = []
        for table in tables:
            rows.extend(dict(zip(table.columns, row)) for row in table.rows)
        return rows

    # Confirm the credential actually works before committing to this backend,
    # rather than failing every test with an auth error.
    try:
        execute("print probe = 1")
    except Exception:  # noqa: BLE001
        return None
    return execute


def _select_backend():
    """Prefer the real workspace; fall back to the local emulator; else skip.

    Probed once at collection time — each probe is a real network round trip, and a
    backend is not going to appear halfway through a run.
    """
    executor = _log_analytics_executor()
    if executor is not None:
        return executor, f"Log Analytics workspace {os.environ['LAW_CUSTOMER_ID'][:8]}..."
    if is_available():
        return (lambda q: execute_kusto(q, endpoint=DEFAULT_ENDPOINT)), \
            f"local Kusto emulator at {DEFAULT_ENDPOINT}"
    return None, None


EXECUTOR, BACKEND = _select_backend()

# In CI the whole point of the Azure job is that these tests actually execute. Without
# this, a broken credential would make them skip and the job would still go green — a
# silent loss of coverage. Set REQUIRE_KQL_ENGINE=1 there to turn "no engine" into a
# hard failure, while local runs keep skipping politely.
REQUIRE_ENGINE = os.environ.get("REQUIRE_KQL_ENGINE") == "1"

requires_engine = pytest.mark.skipif(
    EXECUTOR is None and not REQUIRE_ENGINE,
    reason=(
        "No KQL engine available. These tests execute the generated queries for real. "
        "Either set LAW_CUSTOMER_ID with working Azure credentials (CI does this via "
        "OIDC), or start the local emulator with 'docker compose up -d'. Skipped "
        "rather than failed so the offline checks still pass on a machine with neither."
    ),
)


@requires_engine
@pytest.mark.parametrize("rule_id", FIXTURE_RULE_IDS)
def test_query_execution_proves_the_rule(rule_id):
    """The real negative-then-positive proof, executed by an actual KQL engine.

    Asserts the row count matches expected_rows, that every returned row is a
    declared true positive, and that no true negative leaked through.
    """
    assert EXECUTOR is not None, (
        "REQUIRE_KQL_ENGINE=1 but no KQL engine is reachable. In CI this means the "
        "Azure login or LAW_CUSTOMER_ID is broken — failing loudly rather than "
        "skipping and reporting a false green."
    )
    detection, fixture = _load(rule_id)
    ok, messages = check_rule(detection, fixture, EXECUTOR)
    assert ok, f"[{BACKEND}] " + "; ".join(messages)
