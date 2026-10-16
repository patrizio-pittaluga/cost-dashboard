"""Autorizzazione amministrativa per Lambda dietro JWT authorizer di API Gateway."""
import json
import os

import boto3
from botocore.exceptions import ClientError

POOL = os.environ['USER_POOL_ID']
CLIENT_ID = os.environ['COGNITO_CLIENT_ID']


def reply(code, obj):
    return {'statusCode': code, 'headers': {
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'no-store', 'x-content-type-options': 'nosniff'
    }, 'body': json.dumps(obj, ensure_ascii=False)}


def _jwt(event):
    claims = ((((event or {}).get('requestContext') or {}).get('authorizer') or {}).get('jwt') or {}).get('claims') or {}
    groups = claims.get('cognito:groups') or []
    if isinstance(groups, str):
        groups = [g.strip().strip('[] \"\'') for g in groups.split(',')]
    if (not isinstance(claims.get('sub'), str) or not claims.get('sub')
            or claims.get('client_id') != CLIENT_ID or claims.get('token_use') != 'access'
            or not isinstance(groups, list) or 'Admins' not in groups):
        raise PermissionError('Accesso amministrativo negato')
    return claims


def require_admin(event, cognito=None):
    """Verifica live: disabilitazioni e rimozioni da Admins devono valere subito."""
    claims = _jwt(event)
    sub = claims['sub']
    cognito = cognito or boto3.client('cognito-idp')
    # Il filtro sulla sub vincola l'identità anche se il claim username cambiasse.
    rows = cognito.list_users(UserPoolId=POOL, Filter='sub = "' + sub + '"', Limit=2).get('Users', [])
    matches = [u for u in rows if u.get('Enabled') is True
               and any(a.get('Name') == 'sub' and a.get('Value') == sub for a in u.get('Attributes', []))]
    if len(matches) != 1:
        raise PermissionError('Account inattivo o inesistente')
    username = matches[0]['Username']
    token = None
    for _ in range(20):
        args = {'UserPoolId': POOL, 'Username': username, 'Limit': 60}
        if token:
            args['NextToken'] = token
        groups = cognito.admin_list_groups_for_user(**args)
        if any(x.get('GroupName') == 'Admins' for x in groups.get('Groups', [])):
            return sub
        token = groups.get('NextToken')
        if not token:
            break
    raise PermissionError('Permessi amministrativi revocati')


def parse_body(event):
    import base64
    raw = event.get('body') or ''
    if not isinstance(raw, str) or len(raw) > 32000:
        raise ValueError('Richiesta troppo grande')
    if event.get('isBase64Encoded'):
        raw = base64.b64decode(raw, validate=True).decode('utf-8')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Oggetto JSON richiesto')
    return data
