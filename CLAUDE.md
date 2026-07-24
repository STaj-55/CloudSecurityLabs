# CLAUDE.md

Project conventions for **CloudSecurityLabs**. All future work in this repo — automated or
manual — must follow these rules.

## What this repo is

A public portfolio of reproducible cloud-security lab walkthroughs. The first series is
**AZ-500-Labs**, organized around the four Microsoft AZ-500 exam domains.

## Lab structure — the "four ways" rule

Each lab builds **one** security control **four** ways, in this order:

1. **Azure Portal (console)** — click-path steps.
2. **Azure CLI / PowerShell** — scripted equivalent.
3. **Bicep** — native IaC, authored first.
4. **Terraform (azurerm)** — a port that mirrors the Bicep result (same resources, same
   outcome, idiomatic Terraform).

## Lab naming and location

Lab folders live under `AZ-500-Labs/labs/` and are named:

```
az500-d<domain#>-l<NN>-<slug>
```

Example: `az500-d1-l01-managed-identity-keyvault`

Where `<domain#>` is 1–4 (matching the exam domains below) and `<NN>` is a zero-padded,
per-domain lab sequence number.

## Validation is mandatory

Every lab must include a validation step that proves the control actually enforces something:

1. **Negative test** — demonstrate access is denied *before* the control/role is correctly
   configured.
2. **Positive test** — demonstrate access works *after* the control/role is correctly
   configured.

A lab without both a negative and a positive test is incomplete.

## Every lab README must include

- Chirpy-compatible YAML frontmatter (so the README lifts cleanly into my Jekyll blog).
- An **"AZ-500 Exam Trap"** callout — a common exam gotcha related to the control.
- An **"AWS Equivalent"** callout — the closest AWS analog to the Azure control.
- A **"tested on"** date and Azure region.
- A cost estimate for the resources used.

## Secret hygiene

Never commit:

- Terraform state (`*.tfstate`, `*.tfstate.*`, `.terraform/`)
- `.env` files or `*.tfvars` (except `*.example.tfvars`, which is safe to commit)
- Keys, certs, or credential files (`*.pem`, `*.key`, `credentials.json`)
- Real tenant IDs or subscription IDs — redact these in all screenshots and sample output
  (use placeholders like `<TENANT_ID>` / `<SUBSCRIPTION_ID>`).

## Teardown and cost control

- Every lab has its own `teardown.sh` script (see `AZ-500-Labs/_template/teardown.sh` for the
  pattern).
- Expensive services — Azure Firewall, Bastion, Application Gateway, Defender paid plans,
  Sentinel ingestion — must be deallocated or deleted immediately after a lab is completed.

## Versioning and reproducibility

- Pin tool versions (Azure CLI, Bicep CLI, Terraform, azurerm provider) explicitly in each lab.
- Record a "tested on" date and Azure region in each lab README.

## Explicit non-goals for Claude Code in this repo

- **Do not** write lab walkthroughs or fill in the lab template content. Walkthrough READMEs
  and any file meant to hold lab narrative are authored separately by hand.
- **Do not** set up CI/CD pipelines unless explicitly asked.
- **Do not** make live Azure API/CLI calls against real cloud resources unless explicitly
  asked.
- When scaffolding, leave any README or template file meant for walkthrough content as an
  **empty placeholder** — no headings, no boilerplate, no examples.
