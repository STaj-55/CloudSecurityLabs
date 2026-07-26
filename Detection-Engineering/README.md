# Detection Engineering

Detection-as-code projects: building, validating and proving cloud detection logic with the
same discipline the [AZ-500 labs](../AZ-500-Labs/) apply to security controls.

## How this relates to the rest of the repo

`AZ-500-Labs/` builds a control several ways, then proves it enforces with an explicit
negative-then-positive access test. This series applies the identical idea to detection
rules: a rule is not "done" because the KQL looks right — it is done when it demonstrably
fires on the thing it should catch **and** demonstrably stays silent on the benign thing
next to it.

The difference is what gets built. These are tooling projects, not control labs, so they do
not follow the four-ways (Portal → CLI → Bicep → Terraform) structure or the
`AZ-500-Labs/_template/` layout.

## Projects

| # | Project | What it covers | Status |
|---|---------|----------------|--------|
| 01 | [detection-pipeline](01-detection-pipeline/) | Detection rule schema, CI validation on every PR, and an offline KQL unit-test harness | In progress |
| 02 | identity-lab | _planned_ | — |
| 03 | purple-team | _planned_ | — |

## Naming

Project folders are `NN-<slug>`, zero-padded and sequential. Numbering is series-wide, not
per-domain — these projects build on each other rather than mapping to exam domains.
