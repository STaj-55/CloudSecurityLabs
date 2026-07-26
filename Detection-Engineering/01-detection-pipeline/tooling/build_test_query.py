#!/usr/bin/env python3
"""Build a runnable KQL test query from a detection rule plus its fixture.

The technique: in KQL, a `let` binding shadows a real table name. So if a rule's
query starts with `AzureActivity`, prepending

    let AzureActivity = datatable(...)[ ...rows... ];

makes that same query read the fixture rows instead of the live table -- with the
rule's query text used completely verbatim. Nothing is rewritten, templated or
string-substituted, so what gets tested is exactly what gets deployed.

Usage:
    python3 tooling/build_test_query.py --rule <uuid>
    python3 tooling/build_test_query.py --all

This module is also imported by check_fixture_columns.py and tests/test_detections.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    sys.exit(f"Missing dependency: {exc}. Run: pip install -r requirements.txt")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DETECTIONS_DIR = PROJECT_ROOT / "detections"
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"

SUPPORTED_KQL_TYPES = {
    "string",
    "datetime",
    "int",
    "long",
    "real",
    "bool",
    "dynamic",
    "guid",
    "timespan",
}


class FixtureError(Exception):
    """Raised when a fixture is malformed. Always names the offending file."""


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_detections() -> dict[str, dict]:
    """Return {rule_id: detection_dict} for every rule under detections/."""
    detections: dict[str, dict] = {}
    for path in sorted(DETECTIONS_DIR.rglob("*")):
        if path.suffix not in (".yaml", ".yml") or not path.is_file():
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(document, dict) and "id" in document:
            document["_path"] = path
            detections[document["id"]] = document
    return detections


def fixture_path_for(rule_id: str) -> Path:
    return FIXTURES_DIR / f"{rule_id}.yaml"


def load_fixture(path: Path) -> dict:
    """Load and structurally validate a fixture file.

    Normalises the single-table shorthand (top-level `table` + `columns` + rows)
    into the same shape as the multi-table `tables:` form, so callers only ever
    deal with one representation.
    """
    if not path.is_file():
        raise FixtureError(f"fixture not found: {path}")

    fixture = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(fixture, dict):
        raise FixtureError(f"{path.name}: fixture is empty or not a YAML mapping")

    for key in ("rule_id", "expected_rows"):
        if key not in fixture:
            raise FixtureError(f"{path.name}: missing required key '{key}'")

    has_single = "table" in fixture
    has_multi = "tables" in fixture
    if has_single and has_multi:
        raise FixtureError(f"{path.name}: use either 'table' or 'tables', not both")
    if not has_single and not has_multi:
        raise FixtureError(f"{path.name}: must define 'table' or 'tables'")

    if has_single:
        blocks = [
            {
                "table": fixture["table"],
                "columns": fixture.get("columns"),
                "true_positives": fixture.get("true_positives") or [],
                "true_negatives": fixture.get("true_negatives") or [],
            }
        ]
    else:
        if not isinstance(fixture["tables"], list) or not fixture["tables"]:
            raise FixtureError(f"{path.name}: 'tables' must be a non-empty list")
        blocks = fixture["tables"]

    for block in blocks:
        _validate_block(path, block)

    fixture["_blocks"] = blocks
    fixture["_path"] = path
    return fixture


def _validate_block(path: Path, block: dict) -> None:
    """Check one table block: types are known, every row matches the schema exactly."""
    table = block.get("table")
    if not table:
        raise FixtureError(f"{path.name}: a table block is missing 'table'")

    columns = block.get("columns")
    if not isinstance(columns, dict) or not columns:
        raise FixtureError(f"{path.name}: table '{table}' needs a non-empty 'columns' map")

    for name, kql_type in columns.items():
        if kql_type not in SUPPORTED_KQL_TYPES:
            raise FixtureError(
                f"{path.name}: table '{table}' column '{name}' has unsupported KQL type "
                f"'{kql_type}' (supported: {', '.join(sorted(SUPPORTED_KQL_TYPES))})"
            )

    expected_keys = set(columns)
    for kind in ("true_positives", "true_negatives"):
        rows = block.get(kind) or []
        if not isinstance(rows, list):
            raise FixtureError(f"{path.name}: table '{table}' '{kind}' must be a list")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise FixtureError(
                    f"{path.name}: table '{table}' {kind}[{index}] is not a mapping"
                )
            missing = expected_keys - set(row)
            extra = set(row) - expected_keys
            if missing:
                raise FixtureError(
                    f"{path.name}: table '{table}' {kind}[{index}] is missing "
                    f"column(s): {', '.join(sorted(missing))}"
                )
            if extra:
                raise FixtureError(
                    f"{path.name}: table '{table}' {kind}[{index}] has column(s) not in "
                    f"the schema: {', '.join(sorted(extra))}"
                )


# --------------------------------------------------------------------------
# KQL literal rendering
# --------------------------------------------------------------------------


def render_value(value, kql_type: str, column: str, where: str) -> str:
    """Render one Python value as a KQL literal of the given type.

    Typed literals matter: a datetime column needs datetime(2026-01-01T00:00:00Z),
    not a bare quoted string, or the datatable() will not compile.
    """
    if value is None:
        return '""' if kql_type == "string" else f"{kql_type}(null)"

    if kql_type == "string":
        # json.dumps gives correct quoting and escaping for KQL string literals.
        return json.dumps(str(value))

    if kql_type == "datetime":
        if isinstance(value, dt.datetime):
            text = value.isoformat()
        elif isinstance(value, dt.date):
            text = value.isoformat()
        else:
            text = str(value)
        return f"datetime({text})"

    if kql_type in ("int", "long"):
        return str(int(value))

    if kql_type == "real":
        return str(float(value))

    if kql_type == "bool":
        return "true" if value else "false"

    if kql_type == "dynamic":
        # Dynamic columns must be wrapped in dynamic(), never emitted as a raw
        # string, or KQL types them as string and property access breaks.
        return f"dynamic({json.dumps(value)})"

    if kql_type == "guid":
        return f"guid({value})"

    if kql_type == "timespan":
        return str(value)

    raise FixtureError(f"{where}: column '{column}' has unsupported type '{kql_type}'")


def build_let_block(block: dict, fixture_name: str) -> str:
    """Render one `let <Table> = datatable(...)[...];` statement."""
    table = block["table"]
    columns: dict[str, str] = block["columns"]

    schema = ",\n".join(f"    {name}:{kql_type}" for name, kql_type in columns.items())

    # (label, row) pairs so each emitted row carries a comment explaining its role.
    labelled: list[tuple[str, dict]] = []
    for index, row in enumerate(block.get("true_positives") or [], start=1):
        labelled.append((f"true positive {index} — must match", row))
    for index, row in enumerate(block.get("true_negatives") or [], start=1):
        labelled.append((f"true negative {index} — must NOT match", row))

    if not labelled:
        raise FixtureError(f"{fixture_name}: table '{table}' has no rows")

    row_lines: list[str] = []
    for position, (label, row) in enumerate(labelled):
        values = ", ".join(
            render_value(row[name], kql_type, name, fixture_name)
            for name, kql_type in columns.items()
        )
        # No trailing comma after the final row.
        separator = "," if position < len(labelled) - 1 else ""
        row_lines.append(f"    // {label}")
        row_lines.append(f"    {values}{separator}")

    rows = "\n".join(row_lines)
    return f"let {table} = datatable(\n{schema}\n)[\n{rows}\n];"


def build_test_query(detection: dict, fixture: dict) -> str:
    """Assemble the full test query: header, let blocks, then the rule query verbatim."""
    blocks = fixture["_blocks"]
    total_tp = sum(len(b.get("true_positives") or []) for b in blocks)
    total_tn = sum(len(b.get("true_negatives") or []) for b in blocks)

    header = "\n".join(
        [
            "// " + "=" * 70,
            "// GENERATED TEST QUERY — do not edit by hand.",
            f"// rule          : {detection['title']}",
            f"// rule_id       : {detection['id']}",
            f"// fixture       : {fixture['_path'].relative_to(PROJECT_ROOT)}",
            f"// expected_rows : {fixture['expected_rows']} "
            f"({total_tp} true positive(s), {total_tn} true negative(s))",
            "// " + "=" * 70,
            "//",
            "// Each `let` below shadows the real table name, so the rule query at the",
            "// bottom runs completely unmodified against these fixture rows.",
            "",
        ]
    )

    # One let block per source table.
    lets = "\n\n".join(build_let_block(block, fixture["_path"].name) for block in blocks)

    return f"{header}\n{lets}\n\n// ---- rule query (verbatim) ----\n{detection['query']}\n"


# --------------------------------------------------------------------------
# Structural column check (used by check_fixture_columns.py)
# --------------------------------------------------------------------------

# Words that are KQL syntax, operators or common scalar-type names rather than
# column references. Function names are excluded separately by the "(" lookahead.
KQL_RESERVED = {
    "let", "datatable", "where", "project", "extend", "summarize", "by", "join",
    "on", "kind", "union", "order", "sort", "asc", "desc", "nulls", "first",
    "last", "take", "limit", "top", "distinct", "count", "parse", "evaluate",
    "render", "invoke", "and", "or", "not", "in", "has", "hasprefix", "hassuffix",
    "contains", "startswith", "endswith", "matches", "regex", "between",
    "has_any", "has_all", "true", "false", "null", "typeof", "string", "int",
    "long", "real", "bool", "boolean", "datetime", "timespan", "dynamic", "guid",
    "decimal", "materialize", "range", "step", "from", "to", "print", "as", "set",
    "declare", "pattern", "case", "when", "then", "else", "if", "default", "hint",
    "with", "inner", "outer", "leftouter", "rightouter", "fullouter", "leftsemi",
    "rightsemi", "leftanti", "rightanti", "anti", "semi",
    # Tail halves of hyphenated operators (project-away, mv-expand, ...), which
    # the identifier tokeniser sees as separate words.
    "away", "keep", "rename", "reorder", "expand", "apply", "mv",
}

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A single '=' that is not part of ==, =~, >=, <=, != — i.e. an assignment.
_ASSIGNMENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=(?![=~])")


def strip_literals_and_comments(query: str) -> str:
    """Blank out comments and string literals before tokenising.

    Without this, the contents of a string like
    "MICROSOFT.COMPUTE/VIRTUALMACHINES/RUNCOMMAND/ACTION" would be mistaken for
    column references.
    """
    query = re.sub(r"//[^\n]*", " ", query)
    query = re.sub(r'@"(?:[^"]|"")*"', " ", query)  # verbatim strings first
    query = re.sub(r"@'(?:[^']|'')*'", " ", query)
    query = re.sub(r'"(?:\\.|[^"\\])*"', " ", query)
    query = re.sub(r"'(?:\\.|[^'\\])*'", " ", query)
    return query


def extract_column_references(query: str, known_tables: set[str]) -> set[str]:
    """Best-effort set of column names a KQL query reads.

    Deliberately heuristic and deliberately simple. It excludes: KQL keywords,
    function calls, table names, numeric literals, dynamic-property access after
    a dot, and any name the query defines itself via `X = ...`.
    """
    stripped = strip_literals_and_comments(query)
    defined_in_query = set(_ASSIGNMENT.findall(stripped))

    references: set[str] = set()
    for match in _IDENTIFIER.finditer(stripped):
        name = match.group(0)

        if name.lower() in KQL_RESERVED:
            continue
        if name in known_tables or name in defined_in_query:
            continue
        # Unit suffix of a timespan literal (1h, 30m, 100ms): the tokeniser sees
        # the digits and the suffix as separate tokens, so a digit immediately
        # before the name means this is a literal, not a column.
        if match.start() > 0 and stripped[match.start() - 1].isdigit():
            continue
        # Function call: next non-space character is an opening paren.
        trailing = stripped[match.end():].lstrip()
        if trailing.startswith("("):
            continue
        # Property access on a dynamic column (foo.bar) — bar is not a column.
        preceding = stripped[: match.start()].rstrip()
        if preceding.endswith("."):
            continue

        references.add(name)

    return references


def fixture_columns(fixture: dict) -> set[str]:
    """Union of declared column names across every table block in a fixture."""
    columns: set[str] = set()
    for block in fixture["_blocks"]:
        columns.update(block["columns"])
    return columns


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a runnable KQL test query from a detection rule and its fixture."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--rule", metavar="UUID", help="rule id to build a test query for")
    group.add_argument("--all", action="store_true", help="build test queries for every fixture")
    args = parser.parse_args()

    detections = load_detections()
    if not detections:
        print("FATAL no detections found under detections/", file=sys.stderr)
        return 2

    if args.rule:
        rule_ids = [args.rule]
    else:
        rule_ids = sorted(p.stem for p in FIXTURES_DIR.glob("*.yaml"))
        if not rule_ids:
            print("FATAL no fixtures found under tests/fixtures/", file=sys.stderr)
            return 2

    for position, rule_id in enumerate(rule_ids):
        detection = detections.get(rule_id)
        if detection is None:
            print(f"FATAL no detection found with id {rule_id}", file=sys.stderr)
            return 2
        try:
            fixture = load_fixture(fixture_path_for(rule_id))
        except FixtureError as exc:
            print(f"FATAL {exc}", file=sys.stderr)
            return 2

        if position:
            print("\n")
        print(build_test_query(detection, fixture))

    return 0


if __name__ == "__main__":
    sys.exit(main())
