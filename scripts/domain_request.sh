#!/usr/bin/env bash
# Crea (o riutilizza) il certificato pubblico ACM e stampa i record GoDaddy richiesti.
# Non modifica CloudFront né il DNS. Eseguire da CloudShell con accesso AWS.
set -euo pipefail
cd "$(dirname "$0")/.."
DOMAIN="moneta.ilsitodipatrizio.com"
STACK="moneta-frontend"
CF_DOMAIN="$(aws cloudformation describe-stacks --region us-east-1 --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDomain'].OutputValue | [0]" --output text)"
if [[ -z "$CF_DOMAIN" || "$CF_DOMAIN" == 'None' ]]; then
  echo "ERRORE: stack $STACK senza output CloudFrontDomain." >&2
  exit 2
fi
CERT_ARN="$(aws acm list-certificates --region us-east-1 \
  --certificate-statuses ISSUED PENDING_VALIDATION \
  --query "CertificateSummaryList[?DomainName=='$DOMAIN'].CertificateArn | [0]" --output text)"
if [[ "$CERT_ARN" == "None" || -z "$CERT_ARN" ]]; then
  CERT_ARN="$(aws acm request-certificate --region us-east-1 \
    --domain-name "$DOMAIN" --validation-method DNS --query CertificateArn --output text)"
  echo "Certificato ACM richiesto in us-east-1."
else
  echo "Riutilizzo certificato ACM esistente."
fi
REC='null'
for attempt in 1 2 3 4 5 6; do
  REC="$(aws acm describe-certificate --region us-east-1 \
    --certificate-arn "$CERT_ARN" --query 'Certificate.DomainValidationOptions[0].ResourceRecord' --output json)"
  if [[ "$REC" != 'null' && "$REC" != 'None' && -n "$REC" ]]; then break; fi
  sleep 3
done
printf '\nCertificato ACM ARN:\n%s\n' "$CERT_ARN"
if [[ "$REC" == 'null' || "$REC" == 'None' || -z "$REC" ]]; then
  echo 'ACM non ha ancora preparato il record di validazione. Ripeti questo script tra poco.' >&2
  exit 3
fi
export REC CF_DOMAIN DOMAIN CERT_ARN
python3 - <<'PY'
import json,os
r=json.loads(os.environ['REC'])
name=r['Name'].rstrip('.')
zone='ilsitodipatrizio.com'
suffix='.'+zone
if not name.endswith(suffix):
    raise ValueError('Record ACM inatteso: '+name)
relative=name[:-len(suffix)]
print('\nIn GoDaddy > DNS > Aggiungi record:')
print('\n1) VERIFICA CERTIFICATO (prima di tutto)')
print('Tipo:   '+r['Type'])
print('Nome:   '+relative)
print('Valore: '+r['Value'].rstrip('.'))
print('TTL:    600 secondi o valore predefinito')
print('\n2) ACCESSO AL SITO (solo dopo il deploy del dominio)')
print('Tipo:   CNAME')
print('Nome:   moneta')
print('Valore: '+os.environ['CF_DOMAIN'])
print('TTL:    600 secondi o valore predefinito')
print('\nDopo la convalida ACM (Status ISSUED) esegui:')
print('  ./scripts/domain_activate.sh '+os.environ['CERT_ARN'])
print('\nAttenzione: non modificare gli altri record DNS del dominio principale.')
PY
