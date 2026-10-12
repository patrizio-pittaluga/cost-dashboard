#!/usr/bin/env bash
# Deploy ripetibile: budget indipendente, frontend globale e backend a Milano.
set -euo pipefail
cd "$(dirname "$0")/.."

FRONTEND_STACK="${FRONTEND_STACK:-bilancio-frontend}"
BACKEND_STACK="${BACKEND_STACK:-bilancio-backend}"
COGNITO_PREFIX="${COGNITO_PREFIX:-}"

if [[ -z "$COGNITO_PREFIX" ]]; then
  ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
  COGNITO_PREFIX="bilancio-${ACCOUNT_ID}"
fi

printf '%s\n' '[1/5] Rigenerazione del template Python...'
python3 scripts/sync_lambda.py

printf '%s\n' '[2/5] CloudFront pay-as-you-go e S3 privato (us-east-1)...'
aws cloudformation deploy \
  --region us-east-1 \
  --stack-name "$FRONTEND_STACK" \
  --template-file cloudformation/frontend.yml \
  --no-fail-on-empty-changeset

get_output() {
  aws cloudformation describe-stacks --region "$1" --stack-name "$2" \
    --query "Stacks[0].Outputs[?OutputKey=='$3'].OutputValue | [0]" --output text
}

DOMAIN="$(get_output us-east-1 "$FRONTEND_STACK" CloudFrontDomain)"
BUCKET="$(get_output us-east-1 "$FRONTEND_STACK" BucketName)"
DISTRIBUTION="$(get_output us-east-1 "$FRONTEND_STACK" DistributionId)"
printf '%s\n' '[3/5] Cognito, API HTTP, Lambda Python, DynamoDB (eu-south-1 Milano)...'
aws cloudformation deploy \
  --region eu-south-1 \
  --stack-name "$BACKEND_STACK" \
  --template-file cloudformation/backend.yml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides "CloudFrontDomain=$DOMAIN" "CognitoDomainPrefix=$COGNITO_PREFIX" \
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

printf '%s\n' '[5/5] Caricamento frontend e invalidazione cache CloudFront...'
aws s3 sync frontend/ "s3://$BUCKET/" --region us-east-1 \
  --exclude 'config.json' \
  --cache-control 'public, max-age=300'
aws s3 cp frontend/config.json "s3://$BUCKET/config.json" \
  --region us-east-1 \
  --content-type 'application/json' \
  --cache-control 'no-store'
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION" --paths '/*' > /dev/null

printf '\nDEPLOY COMPLETATO (o stack aggiornati).\nSito: https://%s/\n' "$DOMAIN"
printf 'UserPool (Milano): %s\n' "$USER_POOL_ID"
printf 'API (Milano): %s\n' "$API_URL"
printf 'CloudFront: pay-as-you-go, senza WAF.\n'
printf 'PROSSIMO PASSO: crea manualmente un singolo utente Cognito da Console, poi completa MFA.\n'
