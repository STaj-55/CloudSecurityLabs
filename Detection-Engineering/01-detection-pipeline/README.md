# 01 — Detection Pipeline

A detection-as-code pipeline: detection rules live as version-controlled YAML, get validated
against a strict schema on every pull request, and are proven against fixture data with a
KQL unit-test harness that needs no Azure subscription to run.

**Tested on:** 2026-07-26 · **Region:** n/a (all tooling runs offline)
**Cost:** £0. Nothing here deploys Azure resources. The one detection targets `AzureActivity`,
which Log Analytics ingests free of charge, so validating it against a live workspace in a
later phase will also cost nothing.

## Why this exists

A detection rule that has never been tested is a hypothesis, not a control. The failure mode
is quiet: the KQL compiles, the rule deploys, the dashboard stays green, and nobody notices
it has been returning zero rows for six months because a column was renamed upstream.

This project makes that failure loud, using the same negative-then-positive proof the AZ-500
labs use for access controls:

- **Negative test** — rows that must *not* match (a routine VM start). If a query edit
  accidentally broadens the rule, one of these starts matching and the test fails.
- **Positive test** — rows that must match (Run Command by an unexpected identity). If a
  query edit accidentally narrows the rule, the row count drops and the test fails.

## Layout

```
01-detection-pipeline/
├── detections/            # rules as YAML, grouped by data source
│   ├── azure-resource/
│   ├── entra/
│   └── storage/
├── schema/
│   └── detection.schema.json    # JSON Schema (draft 2020-12) — the rule contract
├── tests/
│   ├── fixtures/          # <rule-id>.yaml — synthetic rows per rule
│   └── test_detections.py
├── tooling/
│   ├── validate_schema.py        # rules conform to the schema; IDs are unique
│   ├── check_fixture_columns.py  # every column the query reads exists in the fixture
│   └── build_test_query.py       # rule + fixture -> runnable KQL
├── docs/{adr,runbooks}/
└── requirements.txt       # pinned: jsonschema, PyYAML, pytest
```

CI lives at the repo root in [`.github/workflows/detection-pipeline-validate.yml`](../../.github/workflows/detection-pipeline-validate.yml),
because GitHub only reads workflows from there. It is path-filtered to this directory.

## The schema is deliberately strict

`schema/detection.schema.json` sets `"additionalProperties": false` at **every** object level.
An unrecognised key is a hard failure rather than a silently ignored one — so `trigger_treshold`
fails the build instead of leaving the rule quietly running on the schema default.

Required fields go beyond what a SIEM needs to execute a rule. `rationale`, `false_positives`
(non-empty), `validation` and `tuning_history` exist to force the thinking that separates a
rule you can operate from a rule you merely deployed. If you cannot name a single false
positive, you do not understand the rule well enough to ship it.

## The KQL test harness

KQL's `let` binding shadows a table name. So prepending

```kql
let AzureActivity = datatable(TimeGenerated:datetime, Caller:string, ...)[ ...rows... ];
```

makes the rule's query read fixture rows instead of the live table — with the query text used
**completely verbatim**. Nothing is templated or string-substituted, so what gets tested is
byte-for-byte what gets deployed.

Build one:

```bash
python3 tooling/build_test_query.py --rule 21cf9572-d108-491a-b3dd-d7b7877d736e
```

Paste the output into Log Analytics and it runs standalone.

### Fixture gotchas

- **Datetimes need typed literals** — `datetime(2026-07-20T14:32:11Z)`, not a quoted string.
  The builder handles this; quote the value in YAML so PyYAML hands over a string.
- **Dynamic columns need `dynamic(...)`** — a raw string gets typed as `string` and property
  access silently breaks.
- **`_ResourceId` has a leading underscore** — it is a Log Analytics system column, and it is
  easy to lose when hand-writing a schema.
- Every fixture row must supply **exactly** the declared columns. Missing or extra keys are
  errors, not defaults.

## Running it locally

```bash
cd Detection-Engineering/01-detection-pipeline
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

./.venv/bin/python tooling/validate_schema.py        # schema conformance + unique IDs
./.venv/bin/python tooling/check_fixture_columns.py  # fixture/query column agreement
./.venv/bin/python -m pytest tests/ -v               # full harness
```

All three run in CI on every PR touching this directory. Query-execution tests are collected
but skipped — they need a Log Analytics workspace, which is a later phase.

## Current detections

| Rule | Table | ATT&CK | Severity | Status |
|------|-------|--------|----------|--------|
| [Azure VM Run Command Execution](detections/azure-resource/azure-vm-run-command.yaml) | `AzureActivity` | [T1651](https://attack.mitre.org/techniques/T1651/) — Cloud Administration Command | medium | experimental |

Run Command is remote code execution on a VM that needs no inbound network path, no SSH or
RDP exposure, and no guest credentials — only the Azure control plane and a
`Virtual Machine Contributor` role assignment. It is a clean pivot from a compromised Azure
identity into the guest OS, and it bypasses every host-network control the VM sits behind.
