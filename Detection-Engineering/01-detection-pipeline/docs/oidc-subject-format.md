# Gotcha: GitHub OIDC subjects now use immutable IDs, not names

**Applies to:** federated credentials on the `gh-detection-pipeline` app registration
**Symptom:** `AADSTS700213: No matching federated identity record found for presented assertion subject`

## The problem

Microsoft's documentation for GitHub Actions federated credentials shows a **name-based**
subject:

```
repo:STaj-55/CloudSecurityLabs:ref:refs/heads/main
repo:STaj-55/CloudSecurityLabs:pull_request
```

GitHub now issues OIDC tokens whose `sub` claim uses an **immutable ID-based** format,
which embeds the numeric owner ID and repository ID:

```
repo:STaj-55@116413129/CloudSecurityLabs@1311461973:ref:refs/heads/main
repo:STaj-55@116413129/CloudSecurityLabs@1311461973:pull_request
```

Entra ID matches the federated credential subject as an **exact string**. There is no
wildcard, no normalisation, and no fallback between the two formats. A credential
registered with the documented name-based subject will reject a token carrying the
ID-based one, with `AADSTS700213`.

The IDs are stable and survive renames — which is the point of the change. A repo
rename no longer silently breaks OIDC, but the subject string is no longer
human-guessable.

## Getting the values

```bash
gh api users/STaj-55 --jq .id                      # 116413129   (owner ID)
gh api repos/STaj-55/CloudSecurityLabs --jq .id    # 1311461973  (repo ID)
```

## Diagnosing it

The `AADSTS700213` error text **contains the subject the runner actually presented**.
Read it out of the failed workflow log and compare it character-for-character against
what is registered:

```bash
az ad app federated-credential list --id <APP_OBJECT_ID> \
  --query "[].{name:name, subject:subject, issuer:issuer}" -o table
```

Do not guess at the correct value — copy the presented subject out of the error and
register exactly that.

## Two credentials are needed, not one

The subject differs per trigger, so a workflow that runs on both pull requests and
pushes to `main` needs **two** federated credentials:

| Trigger | Subject suffix |
|---|---|
| `push` to `main` | `:ref:refs/heads/main` |
| `pull_request` | `:pull_request` |

A common failure mode is registering only the `main` credential, watching the workflow
pass on merge, and then finding every PR-triggered run fails at the login step. In this
pipeline the `live-validation` and `fixture-execution` jobs run on PRs, so the
`:pull_request` credential is load-bearing.

## Note on forks

GitHub does not issue an OIDC token to a workflow triggered by a pull request from a
**fork**, regardless of federated credential configuration. The Azure jobs will fail on
fork PRs by design. That is not a misconfiguration, and it should not be "fixed" by
loosening the subject — a fork PR being unable to authenticate to your tenant is the
security boundary working correctly.
