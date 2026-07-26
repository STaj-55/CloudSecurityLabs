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


from run_test_query import (  # noqa: E402
    DEFAULT_ENDPOINT,
    check_rule,
    is_available,
)

# Probed once at collection time rather than per test — each probe is a real HTTP
# round trip, and the engine is not going to appear halfway through a run.
KUSTO_UP = is_available()

requires_kusto = pytest.mark.skipif(
    not KUSTO_UP,
    reason=(
        f"No Kusto engine reachable at {DEFAULT_ENDPOINT}. These tests execute the "
        "generated KQL for real; start the emulator with 'docker compose up -d' "
        "(allow ~60s to boot). Skipped rather than failed so the offline checks "
        "still run on a machine without Docker."
    ),
)


@requires_kusto
@pytest.mark.parametrize("rule_id", FIXTURE_RULE_IDS)
def test_query_execution_proves_the_rule(rule_id):
    """The real negative-then-positive proof, executed by an actual Kusto engine.

    Asserts the row count, that every returned row is a declared true positive, and
    that no true negative leaked through.
    """
    detection, fixture = _load(rule_id)
    ok, messages = check_rule(detection, fixture, DEFAULT_ENDPOINT)
    assert ok, "; ".join(messages)
