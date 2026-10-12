"""HTTP API privata per il bilancio personale.

Non riceve credenziali. API Gateway convalida firma e scadenza JWT; qui
verifichiamo che sia un *access token* per il client atteso e imponiamo
la partizione DynamoDB ricavata ESCLUSIVAMENTE dal claim `sub` firmato.
"""

import base64
import datetime as dt
import json
import logging
import os
import re
from decimal import Decimal, InvalidOperation

import boto3
from botocore.exceptions import ClientError

_LOG = logging.getLogger(__name__)
_LOG.setLevel(logging.WARNING)
_TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
_CLIENT_ID = os.environ["COGNITO_CLIENT_ID"]

EXPENSE_CATEGORIES = frozenset(
    ["Casa", "Alimentari", "Trasporti", "Bollette", "Salute", "Svago", "Shopping", "Altro"]
)
INCOME_CATEGORIES = frozenset(["Stipendio", "Extra", "Rimborsi", "Altre entrate"])
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class BadRequest(Exception):
    pass


def response(status, data=None):
    result = {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8", "cache-control": "no-store"},
    }
    if data is not None:
        result["body"] = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return result


def parse_json(event):
    body = event.get("body") or ""
    if not isinstance(body, str) or len(body) > 32000:
        raise BadRequest("Richiesta troppo grande")
    try:
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body, validate=True).decode("utf-8")
        data = json.loads(body)
    except (ValueError, UnicodeError):
        raise BadRequest("JSON non valido") from None
    if not isinstance(data, dict):
        raise BadRequest("Il corpo deve essere un oggetto JSON")
    return data


def amount_to_cents(value, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise BadRequest("Importo non valido")
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise BadRequest("Importo non valido") from None
    if not dec.is_finite() or (dec < 0 if allow_zero else dec <= 0) or dec > 1_000_000:
        raise BadRequest("Importo fuori limite")
    cents = dec * 100
    if cents != cents.to_integral_value():
        raise BadRequest("Massimo due decimali")
    return int(cents)


def validate_transaction(data, tx_id=None):
    ident = data.get("id")
    if not isinstance(ident, str) or not ID_PATTERN.fullmatch(ident):
        raise BadRequest("ID movimento non valido")
    if tx_id is not None and ident != tx_id:
        raise BadRequest("ID incoerente")
    description = data.get("description")
    if not isinstance(description, str) or not (1 <= len(description.strip()) <= 120):
        raise BadRequest("Descrizione non valida")
    kind = data.get("type")
    if kind not in ("income", "expense"):
        raise BadRequest("Tipo movimento non valido")
    category = data.get("category")
    valid_categories = INCOME_CATEGORIES if kind == "income" else EXPENSE_CATEGORIES
    if not isinstance(category, str) or category not in valid_categories:
        raise BadRequest("Categoria non valida")
    date_string = data.get("date")
    if not isinstance(date_string, str) or not DATE_PATTERN.fullmatch(date_string):
        raise BadRequest("Data non valida")
    try:
        dt.date.fromisoformat(date_string)
    except ValueError:
        raise BadRequest("Data non valida") from None
    note = data.get("note", "")
    if not isinstance(note, str) or len(note) > 300:
        raise BadRequest("Nota troppo lunga")
    cents = amount_to_cents(data.get("amount"))
    return {
        "id": ident,
        "description": description.strip(),
        "type": kind,
        "category": category,
        "date": date_string,
        "note": note,
        "amountCents": cents,
    }


def to_public_transaction(row):
    value = dict(row)
    value["amount"] = int(value.pop("amountCents")) / 100
    return value


def handler(event, context):
    # Il JWT Authorizer e' configurato su OGNI route applicativa.
    claims = (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims") or {}
    subject = claims.get("sub")
    if (
        not isinstance(subject, str)
        or not subject
        or claims.get("token_use") != "access"
        or claims.get("client_id") != _CLIENT_ID
    ):
        return response(403, {"error": "Access token Cognito richiesto"})

    user_pk = "USER#" + subject
    route = event.get("routeKey", "")
    path_params = event.get("pathParameters") or {}

    try:
        if route == "GET /state":
            transactions, budgets = [], {}
            exclusive_key = None
            while True:
                kwargs = {"KeyConditionExpression": "PK = :pk", "ExpressionAttributeValues": {":pk": user_pk}}
                if exclusive_key:
                    kwargs["ExclusiveStartKey"] = exclusive_key
                result = _TABLE.query(**kwargs)
                for item in result.get("Items", []):
                    sk = item["SK"]
                    if sk.startswith("TX#"):
                        transactions.append(to_public_transaction(item["value"]))
                    elif sk.startswith("B#"):
                        budgets[sk[2:]] = int(item["amountCents"]) / 100
                if len(transactions) > 10000:
                    return response(413, {"error": "Archivio troppo grande: serve paginazione"})
                exclusive_key = result.get("LastEvaluatedKey")
                if not exclusive_key:
                    break
            return response(200, {"transactions": transactions, "budgets": budgets})

        if route == "POST /transactions":
            record = validate_transaction(parse_json(event))
            try:
                _TABLE.put_item(
                    Item={"PK": user_pk, "SK": "TX#" + record["id"], "value": record},
                    ConditionExpression="attribute_not_exists(PK)",
                )
            except ClientError as err:
                if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    return response(409, {"error": "ID movimento già esistente"})
                raise
            return response(201, to_public_transaction(record))

        if route == "PUT /transactions/{id}":
            tx_id = path_params.get("id")
            if not isinstance(tx_id, str) or not ID_PATTERN.fullmatch(tx_id):
                raise BadRequest("ID movimento non valido")
            record = validate_transaction(parse_json(event), tx_id)
            try:
                _TABLE.put_item(
                    Item={"PK": user_pk, "SK": "TX#" + tx_id, "value": record},
                    ConditionExpression="attribute_exists(PK)",
                )
            except ClientError as err:
                if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    return response(404, {"error": "Movimento inesistente"})
                raise
            return response(200, to_public_transaction(record))

        if route == "DELETE /transactions/{id}":
            tx_id = path_params.get("id")
            if not isinstance(tx_id, str) or not ID_PATTERN.fullmatch(tx_id):
                raise BadRequest("ID movimento non valido")
            try:
                _TABLE.delete_item(
                    Key={"PK": user_pk, "SK": "TX#" + tx_id},
                    ConditionExpression="attribute_exists(PK)",
                )
            except ClientError as err:
                if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    return response(404, {"error": "Movimento inesistente"})
                raise
            return response(204)

        if route == "PUT /budgets/{category}":
            category = path_params.get("category")
            if category not in EXPENSE_CATEGORIES:
                raise BadRequest("Categoria budget non valida")
            data = parse_json(event)
            cents = amount_to_cents(data.get("amount"), allow_zero=True)
            _TABLE.put_item(Item={"PK": user_pk, "SK": "B#" + category, "amountCents": cents})
            return response(200, {"category": category, "amount": cents / 100})

        return response(404, {"error": "Rotta inesistente"})
    except BadRequest as err:
        return response(400, {"error": str(err)})
    except Exception:
        _LOG.exception("Errore inatteso nell'API")
        return response(500, {"error": "Errore interno"})
