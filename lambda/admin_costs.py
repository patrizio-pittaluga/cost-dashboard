"""Moneta: visualizzazione costi isolata dal bilancio personale e dalle azioni utente."""
import datetime as dt
import json
import logging
import os
import time
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError
from admin_auth import require_admin, reply

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.WARNING)
TABLE = boto3.resource('dynamodb').Table(os.environ['TABLE_NAME'])
COST_LIMIT = float(os.environ.get('MONTHLY_COST_LIMIT_USD', '3'))


def load_costs():
    now = int(time.time())
    key = {'PK': 'SYSTEM#AWS_COSTS', 'SK': 'COST#CURRENT'}
    cached = TABLE.get_item(Key=key).get('Item')
    if cached and int(cached.get('nextRefresh', 0)) > now:
        return json.loads(cached['payloadJson'])
    today = dt.datetime.now(dt.timezone.utc).date()
    first = today.replace(day=1)
    try:
        ce = boto3.client('ce', region_name='us-east-1')
        result = ce.get_cost_and_usage(TimePeriod={'Start': first.isoformat(),
            'End': (today + dt.timedelta(days=1)).isoformat()}, Granularity='DAILY',
            Metrics=['UnblendedCost'], GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}])
    except ClientError as err:
        LOG.warning('Cost Explorer non disponibile: %s', err.response.get('Error', {}).get('Code'))
        return {'available': False, 'message': 'Cost Explorer non disponibile', 'budgetUSD': COST_LIMIT}
    days, services = {}, {}
    for period in result.get('ResultsByTime', []):
        date = period['TimePeriod']['Start']
        total = Decimal('0')
        for group in period.get('Groups', []):
            amount = Decimal(group['Metrics']['UnblendedCost']['Amount'])
            total += amount
            name = group['Keys'][0]
            services[name] = services.get(name, Decimal('0')) + amount
        days[date] = round(float(total), 4)
    total = round(float(sum(services.values(), Decimal('0'))), 4)
    payload = {'available': True, 'month': first.strftime('%Y-%m'), 'currency': 'USD',
               'total': total, 'budgetUSD': COST_LIMIT,
               'daily': [{'date': k, 'amount': v} for k, v in sorted(days.items())],
               'services': [{'name': k, 'amount': round(float(v), 4)}
                            for k, v in sorted(services.items(), key=lambda it: -it[1]) if v > 0][:12],
               'updatedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
               'scope': 'Intero account AWS: non solo Moneta. Importi indicativi, non fattura finale.'}
    TABLE.put_item(Item={**key, 'nextRefresh': now + 86400,
                         'payloadJson': json.dumps(payload, ensure_ascii=False)})
    return payload


def handler(event, context):
    if event.get('routeKey') != 'GET /costs':
        return reply(404, {'error': 'Rotta inesistente'})
    try:
        require_admin(event)
        return reply(200, load_costs())
    except PermissionError:
        return reply(403, {'error': 'Accesso amministrativo negato'})
    except ClientError as err:
        LOG.error('Errore AWS costi: %s', err.response.get('Error', {}).get('Code'))
        return reply(500, {'error': 'Dati costi non disponibili'})
    except Exception:
        LOG.exception('Errore dashboard costi')
        return reply(500, {'error': 'Errore interno'})
