"""Moneta: gestione Cognito isolata dai movimenti finanziari."""
import hashlib
import logging
import re

import boto3
from botocore.exceptions import ClientError
from admin_auth import POOL, parse_body, reply, require_admin

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


def check_admin_password(value):
    if (not isinstance(value, str) or not 14 <= len(value) <= 128
            or not all(re.search(p, value) for p in (r'[A-Z]', r'[a-z]', r'[0-9]', r'[^A-Za-z0-9]'))):
        raise ValueError('Password temporanea: minimo 14 caratteri con maiuscole, minuscole, numeri e simboli')
    return value


def _mask_identifier(value):
    """Niente indirizzi email né password nei log amministrativi."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]


def admin_users(route, params, payload, requester_sub, client):
    if route == 'GET /admin/users':
        users = []
        token = None
        while True:
            args = {'UserPoolId': POOL, 'Limit': 60}
            if token:
                args['PaginationToken'] = token
            data = client.list_users(**args)
            for u in data.get('Users', []):
                attrs = {a['Name']: a['Value'] for a in u.get('Attributes', [])}
                users.append({'username': u['Username'], 'email': attrs.get('email', ''),
                              'enabled': u.get('Enabled', False),
                              'status': u.get('UserStatus', 'UNKNOWN'), 'admin': False})
                if len(users) > 500:
                    raise ValueError('Troppi account; necessaria paginazione')
            token = data.get('PaginationToken')
            if not token:
                break
        for u in users:
            groups = client.admin_list_groups_for_user(Username=u['username'], UserPoolId=POOL).get('Groups', [])
            u['admin'] = any(g.get('GroupName') == 'Admins' for g in groups)
        return reply(200, {'users': users})

    if route == 'POST /admin/users':
        email = payload.get('email', '')
        if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise ValueError('Email non valida')
        password = check_admin_password(payload.get('password'))
        send_email = payload.get('sendEmail') is True
        email = email.strip().lower()
        args = {'UserPoolId': POOL, 'Username': email, 'TemporaryPassword': password,
                'UserAttributes': [{'Name': 'email', 'Value': email}],
                'DesiredDeliveryMediums': ['EMAIL'] if send_email else [],
                'MessageAction': 'RESEND' if send_email else 'SUPPRESS'}
        client.admin_create_user(**args)
        LOG.info('Moneta admin action=create actor=%s target=%s', requester_sub, _mask_identifier(email))
        return reply(201, {'created': True})

    username = params.get('username', '')
    if not isinstance(username, str) or not 1 <= len(username) <= 254 or '/' in username:
        raise ValueError('Utente non valido')
    action = payload.get('action')
    if action == 'resetPassword':
        client.admin_set_user_password(UserPoolId=POOL, Username=username,
                                      Password=check_admin_password(payload.get('password')), Permanent=False)
    elif action in ('disable', 'enable'):
        user = client.admin_get_user(UserPoolId=POOL, Username=username)
        # Evita sia auto-disabilitazione sia autodisabilitazione via alias email.
        if (action == 'disable' and any(a.get('Name') == 'sub' and a.get('Value') == requester_sub
                                        for a in user.get('UserAttributes', []))):
            raise ValueError('Non puoi disabilitare il tuo account')
        if action == 'disable':
            client.admin_disable_user(UserPoolId=POOL, Username=username)
            client.admin_user_global_sign_out(UserPoolId=POOL, Username=username)
        else:
            client.admin_enable_user(UserPoolId=POOL, Username=username)
    else:
        raise ValueError('Operazione non supportata')
    LOG.info('Moneta admin action=%s actor=%s target=%s', action, requester_sub, _mask_identifier(username))
    return reply(200, {'ok': True})


def handler(event, context):
    route = event.get('routeKey', '')
    if route not in ('GET /admin/users', 'POST /admin/users', 'POST /admin/users/{username}'):
        return reply(404, {'error': 'Rotta inesistente'})
    try:
        cognito = boto3.client('cognito-idp')
        actor = require_admin(event, cognito)
        payload = parse_body(event) if route.startswith('POST ') else None
        return admin_users(route, event.get('pathParameters') or {}, payload, actor, cognito)
    except PermissionError:
        return reply(403, {'error': 'Accesso amministrativo negato'})
    except (ValueError, UnicodeError):
        return reply(400, {'error': 'Dati non validi'})
    except ClientError as err:
        code = err.response.get('Error', {}).get('Code')
        if code in ('UsernameExistsException', 'AliasExistsException'):
            return reply(409, {'error': 'Utente già presente'})
        LOG.error('Errore API Cognito: %s', code)
        return reply(500, {'error': 'Operazione non disponibile'})
    except Exception:
        LOG.exception('Errore Lambda utenti')
        return reply(500, {'error': 'Errore interno'})
