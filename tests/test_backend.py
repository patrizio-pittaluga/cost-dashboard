"""Test locali (nessuna chiamata AWS). Eseguire: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import os
from pathlib import Path
import unittest
import sys
from unittest.mock import patch

os.environ.setdefault('AWS_ACCESS_KEY_ID', 'test')
os.environ.setdefault('AWS_SECRET_ACCESS_KEY', 'test')
os.environ.setdefault('AWS_DEFAULT_REGION', 'eu-south-1')
os.environ['TABLE_NAME'] = 'table-test'
os.environ['COGNITO_CLIENT_ID'] = 'only-client'
os.environ['USER_POOL_ID'] = 'eu-south-1_TEST'
source = Path(__file__).resolve().parents[1] / 'lambda' / 'index.py'
spec = importlib.util.spec_from_file_location('my_lambda', source)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
sys.path.insert(0,str(source.parent))
import admin_costs as cost_mod


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

    def scan(self, **kwargs):
        self.calls += 1
        return {'Items':[item for (_,sk),item in self.items.items() if sk.startswith('REC#')]}

    def get_item(self, **kwargs):
        self.calls += 1
        k=kwargs['Key']
        return {'Item':self.items[(k['PK'],k['SK'])]} if (k['PK'],k['SK']) in self.items else {}

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
        mod.TABLE = DummyTable()

    def test_no_token_denied_before_db(self):
        result = call('GET /state', include_claims=False)
        self.assertEqual(result['statusCode'],403)
        self.assertEqual(mod.TABLE.calls,0)

    def test_id_token_denied(self):
        self.assertEqual(call('GET /state', token_use='id')['statusCode'],403)
        self.assertEqual(mod.TABLE.calls,0)

    def test_other_app_client_denied(self):
        self.assertEqual(call('GET /state', client_id='wrong')['statusCode'],403)
        self.assertEqual(mod.TABLE.calls,0)

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

    def test_recurring_rules_are_private_and_idempotent(self):
        rule = {'id':'rent','type':'expense','category':'Casa','description':'Affitto',
                'amount':750,'startDate':'2026-01-31','frequency':'monthly','interval':1,
                'endDate':None,'active':True,'note':''}
        self.assertEqual(call('POST /recurring',data=rule)['statusCode'],201)
        self.assertEqual(call('POST /recurring',data=rule)['statusCode'],409)
        self.assertEqual(json.loads(call('GET /state',subject='b')['body'])['recurring'],[])
        self.assertEqual(mod.run_recurring(mod.dt.date(2026,3,31))['created'],3)
        self.assertEqual(mod.run_recurring(mod.dt.date(2026,3,31))['created'],0)
        tx=json.loads(call('GET /state')['body'])['transactions']
        self.assertEqual(sorted(t['date'] for t in tx), ['2026-01-31','2026-02-28','2026-03-31'])
        self.assertEqual(call('DELETE /recurring/{id}',path_params={'id':'rent'})['statusCode'],204)
        self.assertEqual(len(json.loads(call('GET /state')['body'])['transactions']),3)

    def test_delete_single_occurrence_never_regenerates(self):
        rule={'id':'monthly','type':'expense','category':'Casa','description':'Canone',
              'amount':100,'startDate':'2026-01-01','frequency':'monthly','interval':1,'note':''}
        self.assertEqual(call('POST /recurring',data=rule)['statusCode'],201)
        self.assertEqual(mod.run_recurring(mod.dt.date(2026,2,1))['created'],2)
        self.assertEqual(call('DELETE /transactions/{id}',path_params={'id':'rec-monthly-20260101'})['statusCode'],204)
        self.assertEqual(mod.run_recurring(mod.dt.date(2026,2,1))['created'],0)
        rows=json.loads(call('GET /state')['body'])['transactions']
        self.assertEqual([r['date'] for r in rows],['2026-02-01'])
        self.assertTrue(mod.TABLE.items[('USER#a','TX#rec-monthly-20260101')]['skipped'])

    def test_recurring_weekly_and_quarterly(self):
        base={'id':'q','type':'income','category':'Extra','description':'Premio',
              'amount':125,'startDate':'2026-01-30','frequency':'quarterly','interval':1,'note':''}
        self.assertEqual(call('POST /recurring',data=base)['statusCode'],201)
        self.assertEqual(mod.run_recurring(mod.dt.date(2026,8,1))['created'],3)
        days={t['date'] for t in json.loads(call('GET /state')['body'])['transactions']}
        self.assertEqual(days,{'2026-01-30','2026-04-30','2026-07-30'})
        base.update({'id':'w', 'frequency':'weekly','interval':2,'startDate':'2026-08-01'})
        self.assertEqual(call('POST /recurring',data=base)['statusCode'],201)
        self.assertEqual(mod.run_recurring(mod.dt.date(2026,8,15))['created'],2)

    def test_recurring_invalid_payload(self):
        rule={'id':'r','type':'expense','category':'Casa','description':'Abbonamento',
             'amount':10,'startDate':'2026-06-01','frequency':'hourly','interval':1}
        self.assertEqual(call('POST /recurring',data=rule)['statusCode'],400)
        rule.update({'frequency':'monthly','interval':0})
        self.assertEqual(call('POST /recurring',data=rule)['statusCode'],400)
        rule.update({'interval':1,'endDate':'2025-01-01'})
        self.assertEqual(call('POST /recurring',data=rule)['statusCode'],400)

    def test_costs_cached_without_float_dynamodb_serialization(self):
        class FakeCE:
            calls=0
            def get_cost_and_usage(self, **kwargs):
                self.calls += 1
                return {'ResultsByTime':[{'TimePeriod':{'Start':'2026-10-01'},
                  'Groups':[{'Keys':['Amazon CloudFront'],'Metrics':{'UnblendedCost':{'Amount':'0.17'}}}]}]}
        fake=FakeCE()
        cost_mod.TABLE=mod.TABLE
        with patch.object(cost_mod.boto3, 'client', return_value=fake):
            first=cost_mod.load_costs()
            second=cost_mod.load_costs()
        self.assertEqual(fake.calls,1)
        self.assertEqual(first,second)
        self.assertEqual(first['total'],0.17)
        cached=mod.TABLE.items[('SYSTEM#AWS_COSTS','COST#CURRENT')]
        self.assertIsInstance(cached['payloadJson'],str)
        self.assertNotIn('payload',cached)

    def test_no_auth_costs(self):
        self.assertEqual(call('GET /costs',include_claims=False)['statusCode'],403)
        self.assertEqual(mod.TABLE.calls,0)

    def test_invalid_paths_and_unknown(self):
        self.assertEqual(call('DELETE /transactions/{id}',path_params={'id':'../etc'})['statusCode'],400)
        self.assertEqual(call('GET /unknown')['statusCode'],404)


if __name__ == '__main__':
    unittest.main()
