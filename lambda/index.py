"""Moneta API privata e motore movimenti ricorrenti.

API Gateway autentica JWT; la Lambda richiede un access token del client previsto.
Il job schedulato è invocabile soltanto da EventBridge Scheduler via IAM.
"""
import base64
import calendar
import datetime as dt
import json
import logging
import os
import re
import time
from decimal import Decimal, InvalidOperation

import boto3
from botocore.exceptions import ClientError

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.WARNING)
TABLE = boto3.resource('dynamodb').Table(os.environ['TABLE_NAME'])
CLIENT_ID = os.environ['COGNITO_CLIENT_ID']
COST_LIMIT = float(os.environ.get('MONTHLY_COST_LIMIT_USD', '3'))
ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,80}$')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
EXPENSE = frozenset(('Casa', 'Alimentari', 'Trasporti', 'Bollette', 'Salute', 'Svago', 'Shopping', 'Altro'))
INCOME = frozenset(('Stipendio', 'Extra', 'Rimborsi', 'Altre entrate'))
FREQUENCIES = frozenset(('weekly', 'monthly', 'quarterly', 'yearly'))

class BadRequest(Exception):
    pass

def response(status, data=None):
    out = {'statusCode': status, 'headers': {'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store'}}
    if data is not None:
        out['body'] = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    return out

def body_json(event):
    raw = event.get('body') or ''
    if not isinstance(raw, str) or len(raw) > 32000:
        raise BadRequest('Richiesta troppo grande')
    try:
        if event.get('isBase64Encoded'):
            raw = base64.b64decode(raw, validate=True).decode('utf-8')
        obj = json.loads(raw)
    except (ValueError, UnicodeError):
        raise BadRequest('JSON non valido') from None
    if not isinstance(obj, dict):
        raise BadRequest('Oggetto JSON richiesto')
    return obj

def cents(value, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise BadRequest('Importo non valido')
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise BadRequest('Importo non valido') from None
    if not dec.is_finite() or dec > 1000000 or (dec < 0 if allow_zero else dec <= 0) or dec*100 != (dec*100).to_integral_value():
        raise BadRequest('Importo fuori limite o oltre due decimali')
    return int(dec*100)

def date_value(value):
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise BadRequest('Data non valida')
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise BadRequest('Data non valida') from None

def validate_record(obj, expected_id=None):
    ident = obj.get('id')
    if not isinstance(ident, str) or not ID_RE.fullmatch(ident) or (expected_id is not None and ident != expected_id):
        raise BadRequest('ID non valido')
    description = obj.get('description')
    if not isinstance(description, str) or not (1 <= len(description.strip()) <= 120):
        raise BadRequest('Descrizione non valida')
    kind = obj.get('type')
    if kind not in ('income', 'expense'):
        raise BadRequest('Tipo non valido')
    category = obj.get('category')
    if category not in (INCOME if kind == 'income' else EXPENSE):
        raise BadRequest('Categoria non valida')
    note = obj.get('note', '')
    if not isinstance(note, str) or len(note) > 300:
        raise BadRequest('Nota troppo lunga')
    # Solo i campi dichiarati vengono persistiti.
    return {'id': ident, 'description': description.strip(), 'type': kind,
            'category': category, 'date': date_value(obj.get('date')).isoformat(),
            'amountCents': cents(obj.get('amount')), 'note': note}

def validate_rule(obj, expected_id=None):
    record = validate_record({**obj, 'date': obj.get('startDate')}, expected_id)
    frequency = obj.get('frequency')
    if frequency not in FREQUENCIES:
        raise BadRequest('Frequenza non valida')
    interval = obj.get('interval', 1)
    if type(interval) is not int or not 1 <= interval <= 12:
        raise BadRequest('Intervallo da 1 a 12')
    end_date = obj.get('endDate') or None
    if end_date and date_value(end_date) < date_value(record['date']):
        raise BadRequest('Scadenza precedente all’inizio')
    if end_date:
        end_date = date_value(end_date).isoformat()
    return {**{k:v for k,v in record.items() if k != 'date'}, 'startDate': record['date'],
            'frequency': frequency, 'interval': interval, 'endDate': end_date,
            'active': obj.get('active', True) is not False}

def public(row):
    val = dict(row)
    val['amount'] = int(val.pop('amountCents')) / 100
    return val

def query_user(pk):
    rows, last = [], None
    while True:
        args = {'KeyConditionExpression': 'PK = :pk', 'ExpressionAttributeValues': {':pk': pk}}
        if last:
            args['ExclusiveStartKey'] = last
        result = TABLE.query(**args)
        rows.extend(result.get('Items', []))
        if len(rows) > 10000:
            raise BadRequest('Archivio troppo grande: necessaria paginazione')
        last = result.get('LastEvaluatedKey')
        if not last:
            return rows

def month_offset(start, step):
    idx = start.year*12 + (start.month-1) + step
    year, month = divmod(idx, 12)
    month += 1
    return dt.date(year, month, min(start.day, calendar.monthrange(year,month)[1]))

def occurrence_at(rule, index):
    start = date_value(rule['startDate'])
    step = index*rule['interval']
    freq = rule['frequency']
    if freq == 'weekly':
        return start + dt.timedelta(days=7*step)
    return month_offset(start, step*{'monthly':1, 'quarterly':3, 'yearly':12}[freq])

def due_dates(rule, today):
    """Fino a 24 occorrenze non ancora scadute, ancorate alla data iniziale.
    Ripetere l'esecuzione è sicuro: le put condizionali evitano duplicati.
    """
    end = date_value(rule['endDate']) if rule.get('endDate') else today
    limit = min(today, end)
    start = date_value(rule['startDate'])
    if limit < start or not rule.get('active', True):
        return []
    elapsed = (limit-start).days
    if rule['frequency'] == 'weekly':
        last_index = elapsed//(7*rule['interval'])
    else:
        span = (limit.year-start.year)*12 + limit.month-start.month
        width = rule['interval']*{'monthly':1,'quarterly':3,'yearly':12}[rule['frequency']]
        last_index = span//width + 1
    result = []
    for i in range(max(0,last_index-23),last_index+2):
        due = occurrence_at(rule,i)
        if due <= limit:
            result.append(due)
    return result[-24:]

def run_recurring(today=None):
    # Lo Scheduler parte alle 06:10 Europe/Rome: a quell'ora data UTC e data italiana coincidono.
    today = today or dt.datetime.now(dt.timezone.utc).date()
    created = 0
    # La tabella è piccola (uso personale); scan paginata, limite di sicurezza.
    last = None
    count = 0
    while True:
        args = {'FilterExpression': 'begins_with(SK, :prefix)', 'ExpressionAttributeValues': {':prefix':'REC#'}}
        if last:
            args['ExclusiveStartKey'] = last
        result = TABLE.scan(**args)
        for row in result.get('Items', []):
            count += 1
            if count > 200:
                raise RuntimeError('Troppe regole per il piano personale')
            rule = row['value']
            for due in due_dates(rule, today):
                # ID deterministico: la stessa scadenza non si registra due volte.
                txid = 'rec-' + rule['id'][:45] + '-' + due.strftime('%Y%m%d')
                tx = {k:rule[k] for k in ('description','type','category','note','amountCents')}
                tx.update({'id':txid, 'date':due.isoformat(), 'recurringId':rule['id']})
                try:
                    TABLE.put_item(Item={'PK':row['PK'], 'SK':'TX#'+txid, 'value':tx}, ConditionExpression='attribute_not_exists(PK)')
                    created += 1
                except ClientError as err:
                    if err.response['Error']['Code'] != 'ConditionalCheckFailedException':
                        raise
        last = result.get('LastEvaluatedKey')
        if not last:
            return {'created': created, 'rules': count, 'date': today.isoformat()}

def load_costs(pk):
    """Una sola chiamata Cost Explorer ogni 24h per utente; query manuale."""
    now = int(time.time())
    key = {'PK':pk, 'SK':'COST#CURRENT'}
    cached = TABLE.get_item(Key=key).get('Item')
    if cached and int(cached.get('nextRefresh', 0)) > now:
        return json.loads(cached['payloadJson'])
    today = dt.datetime.now(dt.timezone.utc).date()
    first = today.replace(day=1)
    # End esclusivo. Dati CE possono arrivare con 24-48 ore di ritardo.
    end = today + dt.timedelta(days=1)
    try:
        ce = boto3.client('ce', region_name='us-east-1')
        result = ce.get_cost_and_usage(TimePeriod={'Start':first.isoformat(), 'End':end.isoformat()},
            Granularity='DAILY', Metrics=['UnblendedCost'], GroupBy=[{'Type':'DIMENSION','Key':'SERVICE'}])
    except ClientError as err:
        code = err.response['Error'].get('Code', 'Unavailable')
        LOG.warning('Cost Explorer non disponibile: %s', code)
        return {'available':False, 'message':'Cost Explorer non disponibile: controlla attivazione e permessi.', 'budgetUSD':COST_LIMIT}
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
    payload = {'available':True, 'month':first.strftime('%Y-%m'), 'currency':'USD',
               'total':total, 'budgetUSD':COST_LIMIT, 'daily':[{'date':k,'amount':v} for k,v in sorted(days.items())],
               'services':[{'name':k,'amount':round(float(v),4)} for k,v in sorted(services.items(),key=lambda it:-it[1]) if v>0][:12],
               'updatedAt':dt.datetime.now(dt.timezone.utc).isoformat(),
               'scope':'Intero account AWS: non solo Moneta. Importi indicativi, non fattura finale.'}
    TABLE.put_item(Item={**key,'nextRefresh':now+86400,'payloadJson':json.dumps(payload,ensure_ascii=False)})
    return payload

def handler(event, context):
    # EventBridge non è un endpoint pubblico e può invocare solo via permessi IAM.
    if event.get('source') == 'aws.scheduler' and event.get('operation') == 'recurring-tick':
        return run_recurring()
    claims = (((event.get('requestContext') or {}).get('authorizer') or {}).get('jwt') or {}).get('claims') or {}
    sub = claims.get('sub')
    if not isinstance(sub,str) or not sub or claims.get('token_use') != 'access' or claims.get('client_id') != CLIENT_ID:
        return response(403, {'error':'Access token Cognito richiesto'})
    pk = 'USER#'+sub
    route = event.get('routeKey','')
    params = event.get('pathParameters') or {}
    try:
        if route == 'GET /state':
            tx, budgets, rules = [], {}, []
            for row in query_user(pk):
                sk = row['SK']
                if sk.startswith('TX#') and not row.get('skipped'):
                    tx.append(public(row['value']))
                elif sk.startswith('B#'):
                    budgets[sk[2:]] = int(row['amountCents'])/100
                elif sk.startswith('REC#'):
                    rules.append(public(row['value']))
            return response(200, {'transactions':tx, 'budgets':budgets, 'recurring':rules})
        if route == 'GET /costs':
            return response(200, load_costs(pk))
        if route in ('POST /transactions','PUT /transactions/{id}'):
            rid = params.get('id') if route.startswith('PUT') else None
            record = validate_record(body_json(event), rid)
            key = {'PK':pk, 'SK':'TX#'+record['id'], 'value':record}
            if rid:
                previous = TABLE.get_item(Key={'PK':pk,'SK':'TX#'+rid}).get('Item') or {}
                if previous.get('skipped'):
                    return response(404,{'error':'Movimento eliminato'})
                rec_id = (previous.get('value') or {}).get('recurringId')
                if rec_id:
                    record['recurringId'] = rec_id
            cond = 'attribute_exists(PK)' if rid else 'attribute_not_exists(PK)'
            try:
                TABLE.put_item(Item=key,ConditionExpression=cond)
            except ClientError as err:
                if err.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    return response(404 if rid else 409, {'error':'Movimento inesistente' if rid else 'ID già esistente'})
                raise
            return response(200 if rid else 201, public(record))
        if route in ('DELETE /transactions/{id}', 'DELETE /recurring/{id}'):
            rid = params.get('id')
            if not isinstance(rid,str) or not ID_RE.fullmatch(rid):
                raise BadRequest('ID non valido')
            sk = ('TX#' if 'transactions' in route else 'REC#') + rid
            try:
                if sk.startswith('TX#'):
                    old = TABLE.get_item(Key={'PK':pk,'SK':sk}).get('Item') or {}
                    if old.get('skipped'):
                        return response(204)
                    if (old.get('value') or {}).get('recurringId'):
                        # Una tombstone impedisce che il job rigeneri un'occurrenza cancellata.
                        TABLE.put_item(Item={'PK':pk,'SK':sk,'skipped':True},ConditionExpression='attribute_exists(PK)')
                        return response(204)
                TABLE.delete_item(Key={'PK':pk,'SK':sk},ConditionExpression='attribute_exists(PK)')
            except ClientError as err:
                if err.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    return response(404, {'error':'Elemento inesistente'})
                raise
            return response(204)
        if route in ('POST /recurring','PUT /recurring/{id}'):
            rid = params.get('id') if route.startswith('PUT') else None
            record = validate_rule(body_json(event),rid)
            cond = 'attribute_exists(PK)' if rid else 'attribute_not_exists(PK)'
            try:
                TABLE.put_item(Item={'PK':pk,'SK':'REC#'+record['id'],'value':record},ConditionExpression=cond)
            except ClientError as err:
                if err.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    return response(404 if rid else 409, {'error':'Ricorrenza non trovata' if rid else 'ID esistente'})
                raise
            return response(200 if rid else 201, public(record))
        if route == 'PUT /budgets/{category}':
            category = params.get('category')
            if category not in EXPENSE:
                raise BadRequest('Categoria budget non valida')
            value = cents(body_json(event).get('amount'), allow_zero=True)
            TABLE.put_item(Item={'PK':pk,'SK':'B#'+category,'amountCents':value})
            return response(200,{'category':category,'amount':value/100})
        return response(404,{'error':'Rotta inesistente'})
    except BadRequest as err:
        return response(400,{'error':str(err)})
    except Exception:
        LOG.exception('Errore interno Moneta')
        return response(500,{'error':'Errore interno'})
