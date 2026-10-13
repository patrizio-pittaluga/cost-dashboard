#!/usr/bin/env bash
# Deploy ripetibile: budget indipendente, frontend globale e backend a Milano.
set -euo pipefail
cd "$(dirname "$0")/.."

# Solo nomi Moneta: installazione pulita. Nessuna migrazione dagli stack bilancio.
FRONTEND_STACK="moneta-frontend"
BACKEND_STACK="moneta-backend"
COGNITO_PREFIX="${COGNITO_PREFIX:-}"
# Le variabili possono essere impostate per il primo deploy o lette dagli stack esistenti
# nei successivi deploy: evita di rimuovere l'alias quando non sono esportate.
MONETA_CUSTOM_DOMAIN="${MONETA_CUSTOM_DOMAIN:-}"
MONETA_ACM_CERT_ARN="${MONETA_ACM_CERT_ARN:-}"

# Evita due installazioni attive (e costi doppi) se i vecchi stack sono ancora presenti.
for target in 'us-east-1:bilancio-frontend' 'eu-south-1:bilancio-backend'; do
  region="${target%%:*}"; stack="${target#*:}"
  if status=$(aws cloudformation describe-stacks --region "$region" --stack-name "$stack" \
    --query 'Stacks[0].StackStatus' --output text 2>&1); then
    echo "ERRORE: lo stack precedente $stack esiste ancora in $region ($status)." >&2
    echo 'Per la pulizia: python3 scripts/cleanup_legacy.py' >&2
    exit 2
  elif [[ "$status" != *'does not exist'* ]]; then
    echo "ERRORE: impossibile verificare $stack: $status" >&2
    exit 2
  fi
done

# Mantiene il prefisso Cognito dello stack attuale per non sostituire il dominio Hosted UI.
# Su prima installazione usa moneta-<account-id>.
if [[ -z "$COGNITO_PREFIX" ]]; then
  COGNITO_PREFIX="$(aws cloudformation describe-stacks --region eu-south-1 --stack-name "$BACKEND_STACK" \
    --query "Stacks[0].Parameters[?ParameterKey=='CognitoDomainPrefix'].ParameterValue | [0]" --output text 2>/dev/null || true)"
  if [[ -z "$COGNITO_PREFIX" || "$COGNITO_PREFIX" == 'None' ]]; then
    ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
    COGNITO_PREFIX="moneta-${ACCOUNT_ID}"
  fi
fi

printf 'Moneta: deploy stack %s e %s.\n' "$FRONTEND_STACK" "$BACKEND_STACK"
printf '%s\n' '[1/5] Creazione pacchetto Lambda...' 
python3 scripts/sync_lambda.py

# Conserva i parametri del dominio nei deploy successivi.
get_stack_parameter() {
  local value
  value="$(aws cloudformation describe-stacks --region "$1" --stack-name "$2" \
    --query "Stacks[0].Parameters[?ParameterKey=='$3'].ParameterValue | [0]" --output text 2>/dev/null || true)"
  if [[ "$value" != "None" && "$value" != "" ]]; then printf '%s' "$value"; fi
}
if [[ -z "$MONETA_CUSTOM_DOMAIN" ]]; then
  MONETA_CUSTOM_DOMAIN="$(get_stack_parameter us-east-1 "$FRONTEND_STACK" CustomDomainName)"
fi
if [[ -z "$MONETA_ACM_CERT_ARN" ]]; then
  MONETA_ACM_CERT_ARN="$(get_stack_parameter us-east-1 "$FRONTEND_STACK" CustomCertificateArn)"
fi
if [[ -n "$MONETA_CUSTOM_DOMAIN" && -z "$MONETA_ACM_CERT_ARN" ]] || [[ -z "$MONETA_CUSTOM_DOMAIN" && -n "$MONETA_ACM_CERT_ARN" ]]; then
  echo 'ERRORE: MONETA_CUSTOM_DOMAIN e MONETA_ACM_CERT_ARN devono essere impostati insieme.' >&2
  exit 2
fi
printf '%s\n' '[2/5] CloudFront pay-as-you-go e S3 privato (us-east-1)...' 
aws cloudformation deploy \
  --region us-east-1 \
  --stack-name "$FRONTEND_STACK" \
  --template-file cloudformation/frontend.yml \
  --parameter-overrides "CustomDomainName=$MONETA_CUSTOM_DOMAIN" "CustomCertificateArn=$MONETA_ACM_CERT_ARN" \
  --no-fail-on-empty-changeset

get_output() {
  aws cloudformation describe-stacks --region "$1" --stack-name "$2" \
    --query "Stacks[0].Outputs[?OutputKey=='$3'].OutputValue | [0]" --output text
}

DOMAIN="$(get_output us-east-1 "$FRONTEND_STACK" CloudFrontDomain)"
BUCKET="$(get_output us-east-1 "$FRONTEND_STACK" BucketName)"
DISTRIBUTION="$(get_output us-east-1 "$FRONTEND_STACK" DistributionId)"
# Lambda Python 3.13 supera il limite del Code.ZipFile inline CloudFormation.
# Deployment ZIP privato nella stessa regione della Lambda: nessun cambiamento ai dati.
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
CODE_BUCKET="moneta-deploy-${ACCOUNT_ID}-eu-south-1"
if ! aws s3api head-bucket --bucket "$CODE_BUCKET" 2>/dev/null; then
  aws s3api create-bucket --bucket "$CODE_BUCKET" --region eu-south-1 \
    --create-bucket-configuration LocationConstraint=eu-south-1 >/dev/null
  aws s3api put-public-access-block --bucket "$CODE_BUCKET" \
    --public-access-block-configuration 'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'
  aws s3api put-bucket-encryption --bucket "$CODE_BUCKET" \
    --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
fi
CODE_HASH="$(sha256sum dist/moneta-lambda.zip | cut -d' ' -f1)"
CODE_KEY="lambda/moneta-${CODE_HASH}.zip"
aws s3 cp dist/moneta-lambda.zip "s3://$CODE_BUCKET/$CODE_KEY" \
  --region eu-south-1 --sse AES256 --only-show-errors
printf '%s\n' '[3/5] Cognito, API HTTP, Lambda Python, DynamoDB (eu-south-1 Milano)...'
aws cloudformation deploy \
  --region eu-south-1 \
  --stack-name "$BACKEND_STACK" \
  --template-file cloudformation/backend.yml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides "CloudFrontDomain=$DOMAIN" "CognitoDomainPrefix=$COGNITO_PREFIX" "CustomDomainName=$MONETA_CUSTOM_DOMAIN" "LambdaCodeBucket=$CODE_BUCKET" "LambdaCodeKey=$CODE_KEY" \
  --no-fail-on-empty-changeset

API_URL="$(get_output eu-south-1 "$BACKEND_STACK" ApiUrl)"
CLIENT_ID="$(get_output eu-south-1 "$BACKEND_STACK" UserPoolClientId)"
USER_POOL_ID="$(get_output eu-south-1 "$BACKEND_STACK" UserPoolId)"
COGNITO_URL="$(get_output eu-south-1 "$BACKEND_STACK" CognitoHostedUiBaseUrl)"

printf '%s\n' '[4/5] Configurazione del frontend (nessuna password/token nei file)...'
API_URL="$API_URL" CLIENT_ID="$CLIENT_ID" COGNITO_URL="$COGNITO_URL" python3 - <<'PY'
import json, os
from pathlib import Path
p=Path('frontend/config.json')
p.write_text(json.dumps({
    'apiUrl':os.environ['API_URL'],
    'clientId':os.environ['CLIENT_ID'],
    'cognitoUrl':os.environ['COGNITO_URL'],
}, indent=2)+'\n',encoding='utf-8')
PY

printf '%s\n' '[5/5] Caricamento Moneta e invalidazione cache CloudFront...'
aws s3 sync frontend/ "s3://$BUCKET/" --region us-east-1 \
  --exclude 'config.json' \
  --cache-control 'public, max-age=300'
aws s3 cp frontend/sw.js "s3://$BUCKET/sw.js" --region us-east-1 \
  --content-type 'application/javascript' --cache-control 'no-store' --only-show-errors
aws s3 cp frontend/manifest.webmanifest "s3://$BUCKET/manifest.webmanifest" --region us-east-1 \
  --content-type 'application/manifest+json' --cache-control 'public, max-age=300' --only-show-errors
aws s3 cp frontend/config.json "s3://$BUCKET/config.json" \
  --region us-east-1 \
  --content-type 'application/json' \
  --cache-control 'no-store'
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION" --paths '/*' > /dev/null

printf '\nDEPLOY COMPLETATO (o stack aggiornati).\n'
if [[ -n "$MONETA_CUSTOM_DOMAIN" ]]; then
  printf 'Moneta (dominio personalizzato): https://%s/\n' "$MONETA_CUSTOM_DOMAIN"
fi
printf 'Moneta (CloudFront AWS): https://%s/\n' "$DOMAIN"
printf 'UserPool (Milano): %s\n' "$USER_POOL_ID"
printf 'API (Milano): %s\n' "$API_URL"
printf 'CloudFront: pay-as-you-go, senza WAF.\n'
printf 'Utenti Cognito esistenti preservati durante gli aggiornamenti CloudFormation.\n'
