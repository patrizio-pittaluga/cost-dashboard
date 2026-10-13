#!/usr/bin/env bash
# Aggiunge manualmente un utente Cognito esistente al gruppo Admins.
# Richiede permessi AWS Cognito amministrativi. Non modifica i dati Moneta.
set -euo pipefail
cd "$(dirname "$0")/.."
EMAIL="${1:-}"
if [[ ! "$EMAIL" =~ ^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,20}$ ]]; then
  echo 'Uso: bash scripts/add_admin.sh email_account_moneta@example.it' >&2
  exit 2
fi
POOL_ID="$(aws cloudformation describe-stacks --region eu-south-1 --stack-name moneta-backend \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue | [0]' --output text)"
if [[ -z "$POOL_ID" || "$POOL_ID" == 'None' ]]; then
  echo 'User Pool non trovato nello stack moneta-backend' >&2
  exit 2
fi
USERNAME="$(aws cognito-idp list-users --region eu-south-1 --user-pool-id "$POOL_ID" \
  --filter "email = \"$EMAIL\"" --query 'Users[0].Username' --output text)"
if [[ -z "$USERNAME" || "$USERNAME" == 'None' ]]; then
  echo "Utente non trovato in Cognito: $EMAIL" >&2
  exit 2
fi
printf 'Stai per aggiungere %s (Cognito username: %s) al gruppo Admins.\n' "$EMAIL" "$USERNAME"
printf 'Solo questo utente vedrà la dashboard AWS. Continua? [y/N] '
read -r answer
if [[ "$answer" != 'y' && "$answer" != 'Y' ]]; then exit 1; fi
aws cognito-idp admin-add-user-to-group --region eu-south-1 --user-pool-id "$POOL_ID" \
  --username "$USERNAME" --group-name Admins
printf 'Assegnazione completata. Esci e rientra in Moneta per aggiornare il token JWT.\n'
