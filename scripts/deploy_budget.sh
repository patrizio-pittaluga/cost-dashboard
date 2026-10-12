#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -ne 1 ]]; then
  echo 'Uso: ./scripts/deploy_budget.sh tua-email@example.com' >&2
  exit 2
fi
aws cloudformation deploy \
  --region us-east-1 \
  --stack-name moneta-budget \
  --template-file cloudformation/budget.yml \
  --parameter-overrides "NotificationEmail=$1" MonthlyLimitUSD=3 \
  --no-fail-on-empty-changeset
printf 'Budget creato. Gli avvisi NON arrestano i servizi automaticamente.\n'
