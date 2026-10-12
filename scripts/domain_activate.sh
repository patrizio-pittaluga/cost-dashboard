#!/usr/bin/env bash
# Attiva l'alias CloudFront + redirect/CORS Cognito senza ricreare le risorse.
set -euo pipefail
cd "$(dirname "$0")/.."
CERT_ARN="${1:-}"
DOMAIN='moneta.ilsitodipatrizio.com'
if [[ -z "$CERT_ARN" ]]; then
  echo 'Uso: ./scripts/domain_activate.sh arn:aws:acm:us-east-1:ACCOUNT:certificate/UUID' >&2
  exit 2
fi
if [[ "$CERT_ARN" != arn:aws:acm:us-east-1:* ]]; then
  echo 'Errore: il certificato deve trovarsi in us-east-1.' >&2
  exit 2
fi
CERT_STATUS="$(aws acm describe-certificate --region us-east-1 --certificate-arn "$CERT_ARN" \
  --query 'Certificate.Status' --output text)"
CERT_DOMAIN="$(aws acm describe-certificate --region us-east-1 --certificate-arn "$CERT_ARN" \
  --query 'Certificate.DomainName' --output text)"
if [[ "$CERT_STATUS" != 'ISSUED' ]]; then
  echo "Certificato non ancora valido ($CERT_STATUS). Configura il CNAME ACM su GoDaddy." >&2
  exit 2
fi
if [[ "$CERT_DOMAIN" != "$DOMAIN" ]]; then
  echo "Errore: certificato per $CERT_DOMAIN, atteso $DOMAIN." >&2
  exit 2
fi
MONETA_CUSTOM_DOMAIN="$DOMAIN" MONETA_ACM_CERT_ARN="$CERT_ARN" ./scripts/deploy.sh
printf '\nOra aggiungi su GoDaddy: CNAME moneta -> dominio CloudFront indicato sopra.\n'
