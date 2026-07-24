# AZ-500 Labs

Hands-on, reproducible labs mapped to the four AZ-500 (Microsoft Azure Security Technologies)
exam domains. Each lab implements a single security control four ways — Azure Portal, Azure
CLI/PowerShell, Bicep, and Terraform — with a validation step that proves the control actually
enforces access (negative test, then positive test).

See the repo-root [CLAUDE.md](../CLAUDE.md) for full lab conventions, and
[`_template/`](_template/) for the scaffold every lab is built from.

## Exam domains and lab status

| Domain | Weight | Lab status |
|---|---|---|
| D1 — Secure identity and access | 15–20% | planned |
| D2 — Secure networking | 20–25% | planned |
| D3 — Secure compute, storage, and databases | 20–25% | planned |
| D4 — Secure Azure with Defender for Cloud and Microsoft Sentinel | 30–35% | planned |

Labs live under [`labs/`](labs/), named `az500-d<domain#>-l<NN>-<slug>`.
