# ADR 0001 — Use the Kusto emulator for local detection query execution

**Status:** Accepted
**Date:** 2026-07-26

## Context

The fixture harness generates a self-contained KQL query per rule: a `datatable()`
literal shadows each source table, so the rule's query text runs verbatim against
synthetic rows. Up to this point nothing ever *ran* that query. The checks were
structural — schema conformance, and column references matching the fixture — which
catch typos and drift but cannot catch a logic error. A `where` clause with inverted
logic passes every structural check and returns the wrong rows.

To execute the query for real, the options were:

1. A live Log Analytics workspace in Azure.
2. A real Azure Data Explorer cluster.
3. Kustainer, Microsoft's free ADX emulator container.

## Decision

Execute test queries against **Kustainer** (`mcr.microsoft.com/azuredataexplorer/kustainer-linux`)
running locally via `docker compose`.

Because every table is shadowed by a `datatable()` literal, the queries never touch a
real table. That means the engine needs no ingestion, no schema provisioning, no data
connectors and no authentication — it only has to parse and evaluate KQL. Any KQL
engine will do, so the cheapest and fastest one wins.

## Consequences

**Good:**

- No Azure subscription, credentials or network access needed to prove a rule works.
- Fast: a query runs in milliseconds once the container is up, so the whole suite is a
  practical pre-commit check rather than a nightly job.
- Zero cost, and no risk of a test polluting a real workspace.
- The same `run_test_query.py` can later point at a real ADX cluster or a CI service
  container by setting `KUSTO_ENDPOINT` — no code change required.

**Bad / limits:**

- **Kustainer is an ADX engine, not Log Analytics.** Core KQL is identical, but
  Log Analytics-only surface does not exist: `workspace()`, `resource()`, Sentinel
  helper functions, and the built-in schemas of tables like `AzureActivity`. A rule
  relying on those cannot be validated this way and should set
  `validation.method` to something other than `fixture-datatable`.
- It proves the **query logic** is right. It does not prove the rule works in Sentinel
  end to end — connector health, DCR configuration, entity mapping and incident
  creation are all still untested. Those need a real workspace.
- Startup is slow (~30-60s) and the image is large (~1-2 GB), so it is opt-in rather
  than part of the default test run. Execution tests skip cleanly when the engine is
  not reachable.
- The image is currently tracked at `:latest`, which conflicts with the repo's
  version-pinning convention. It should be pinned to a digest once verified.

## Alternatives rejected

- **Live Log Analytics workspace** — highest fidelity, but needs a subscription,
  credentials in CI, and ingestion latency of several minutes before a written row is
  queryable. That latency alone makes it unusable as a fast feedback loop. Worth doing
  later as a separate, slower validation tier.
- **Real ADX cluster** — same KQL fidelity as the emulator but costs money and needs
  auth, with no compensating benefit for this use case.
- **Writing a KQL parser/evaluator** — not remotely worth it, and a reimplementation
  would not share the engine's semantics, which is the entire point of executing.
