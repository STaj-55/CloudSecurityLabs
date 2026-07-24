#!/usr/bin/env bash
set -euo pipefail

# teardown.sh — deletes the resource group created for this lab.
#
# Usage:
#   ./teardown.sh <resource-group-name>

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <resource-group-name>" >&2
  exit 1
fi

RG="$1"

read -r -p "This will delete resource group '${RG}' and everything in it. Continue? [y/N] " CONFIRM
if [[ ! "${CONFIRM}" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 1
fi

az group delete --name "${RG}" --yes --no-wait

echo "Delete requested for '${RG}'. Checking status..."
az group exists --name "${RG}"
