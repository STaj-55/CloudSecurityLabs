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
└── AZ-500-Labs/
    ├── README.md
    ├── _template/
    │   ├── README.md
    │   ├── teardown.sh
    │   ├── bicep/
    │   ├── terraform/
    │   ├── cli/
    │   └── assets/
    └── labs/
```

See [AZ-500-Labs](AZ-500-Labs/) for the current lab series, mapped to the four AZ-500 exam
domains.
