# CloudSecurityLabs

A public portfolio of reproducible cloud-security lab walkthroughs. Each lab builds one
security control multiple ways (console, CLI, and IaC), then proves it works with an explicit
negative-then-positive access test — the goal is repeatable, auditable, exam-relevant proof of
how a control actually enforces, not just a screenshot.

## Structure

```
CloudSecurityLabs/
├── README.md
├── CLAUDE.md
├── .gitignore
├── .pre-commit-config.yaml
├── .github/workflows/          # CI — GitHub only reads workflows from the repo root
├── AZ-500-Labs/
│   ├── README.md
│   ├── _template/
│   │   ├── README.md
│   │   ├── teardown.sh
│   │   ├── bicep/
│   │   ├── terraform/
│   │   ├── cli/
│   │   └── assets/
│   └── labs/
└── Detection-Engineering/
    └── 01-detection-pipeline/
```

## Series

- **[AZ-500-Labs](AZ-500-Labs/)** — control labs mapped to the four AZ-500 exam domains. Each
  lab builds one control four ways (Portal → CLI → Bicep → Terraform), then proves it enforces
  with a negative-then-positive access test.
- **[Detection-Engineering](Detection-Engineering/)** — detection-as-code projects. Same proof
  discipline, applied to detection logic: a rule must demonstrably fire on the malicious case
  and stay silent on the benign one next to it.
