"""Test locali (nessuna chiamata AWS). Eseguire: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import os
from pathlib import Path
import unittest

os.environ.setdefault('AWS_ACCESS_KEY_ID', 'test')
os.environ.setdefault('AWS_SECRET_ACCESS_KEY', 'test')
os.environ.setdefault('AWS_DEFAULT_REGION', 'eu-south-1')
os.environ['TABLE_NAME'] = 'table-test'
os.environ['COGNITO_CLIENT_ID'] = 'only-client'
source = Path(__file__).resolve().parents[1] / 'lambda' / 'index.py'
spec = importlib.util.spec_from_file_location('my_lambda', source)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ConditionalError(Exception):
    def __init__(self):
        self.response = {'Error': {'Code': 'ConditionalCheckFailedException'}}


class DummyTable:
    def __init__(self):
        self.items = {}
        self.calls = 0

    def query(self, **kwargs):
        self.calls += 1
        pk = kwargs['ExpressionAttributeValues'][':pk']
        return {'Items': [item for (p, _), item in self.items.items() if p == pk]}

    def put_item(self, **kwargs):
        self.calls += 1
        row = kwargs['Item']
        key = row['PK'], row['SK']
        cond = kwargs.get('ConditionExpression')
        if (cond == 'attribute_not_exists(PK)' and key in self.items) or (cond == 'attribute_exists(PK)' and key not in self.items):
            raise mod.ClientError({'Error': {'Code':'ConditionalCheckFailedException', 'Message':'Conflict'}},'PutItem')
        self.items[key] = row

    def delete_item(self, **kwargs):
        self.calls += 1
        key = kwargs['Key']['PK'], kwargs['Key']['SK']
        if key not in self.items:
            raise mod.ClientError({'Error': {'Code':'ConditionalCheckFailedException', 'Message':'Conflict'}},'DeleteItem')
        del self.items[key]


def call(route, subject='a', token_use='access', client_id='only-client', data=None, path_params=None, include_claims=True):
    claims = {'sub':subject,'token_use':token_use,'client_id':client_id} if include_claims else {}
    return mod.handler({
        'routeKey': route,
        'requestContext': {'authorizer': {'jwt': {'claims':claims}}},
        'body':json.dumps(data) if data is not None else None,
        'pathParameters':path_params or {},
    }, None)


class BackendTests(unittest.TestCase):
    def setUp(self):
        mod._TABLE = DummyTable()

    def test_no_token_denied_before_db(self):
        result = call('GET /state', include_claims=False)
        self.assertEqual(result['statusCode'],403)
        self.assertEqual(mod._TABLE.calls,0)

    def test_id_token_denied(self):
        self.assertEqual(call('GET /state', token_use='id')['statusCode'],403)
        self.assertEqual(mod._TABLE.calls,0)

    def test_other_app_client_denied(self):
        self.assertEqual(call('GET /state', client_id='wrong')['statusCode'],403)
        self.assertEqual(mod._TABLE.calls,0)

    def test_crud_and_isolation(self):
        tx = {'id':'tx-A','type':'expense','category':'Alimentari','description':'Spesa','amount':12.30,'date':'2026-10-12','note':''}
        self.assertEqual(call('POST /transactions', data=tx)['statusCode'],201)
        self.assertEqual(call('POST /transactions', data=tx)['statusCode'],409)
        data_a = json.loads(call('GET /state')['body'])
        data_b = json.loads(call('GET /state',subject='b')['body'])
        self.assertEqual(data_a['transactions'][0]['amount'],12.30)
        self.assertEqual(data_b['transactions'],[])
        self.assertEqual(call('DELETE /transactions/{id}',subject='b',path_params={'id':'tx-A'})['statusCode'],404)
        tx['amount'] = 13.25
        self.assertEqual(call('PUT /transactions/{id}', data=tx,path_params={'id':'tx-A'})['statusCode'],200)
        self.assertEqual(call('DELETE /transactions/{id}',path_params={'id':'tx-A'})['statusCode'],204)
        self.assertEqual(json.loads(call('GET /state')['body'])['transactions'],[])

    def test_bad_amount_and_date(self):
        tx = {'id':'x','type':'expense','category':'Casa','description':'Test','amount':2.001,'date':'2026-02-29','note':''}
        self.assertEqual(call('POST /transactions', data=tx)['statusCode'],400)
        tx['amount'] = 2.00
        self.assertEqual(call('POST /transactions', data=tx)['statusCode'],400)
        tx['date'] = '2026-02-28'
        self.assertEqual(call('POST /transactions', data=tx)['statusCode'],201)
        self.assertEqual(call('PUT /budgets/{category}', data={'amount':0},path_params={'category':'Casa'})['statusCode'],200)

    def test_invalid_paths_and_unknown(self):
        self.assertEqual(call('DELETE /transactions/{id}',path_params={'id':'../etc'})['statusCode'],400)
        self.assertEqual(call('GET /unknown')['statusCode'],404)


if __name__ == '__main__':
    unittest.main()
