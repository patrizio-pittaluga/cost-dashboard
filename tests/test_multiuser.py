"""Test accessi multiutente e atomicità senza chiamate reali ad AWS."""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault('AWS_ACCESS_KEY_ID','test')
os.environ.setdefault('AWS_SECRET_ACCESS_KEY','test')
os.environ.setdefault('AWS_DEFAULT_REGION','eu-south-1')
os.environ['TABLE_NAME']='fake-moneta-table'
os.environ['COGNITO_CLIENT_ID']='client'
os.environ['USER_POOL_ID']='eu-south-1_fake'
spec = importlib.util.spec_from_file_location('multi_lambda',Path(__file__).resolve().parents[1]/'lambda'/'index.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
from boto3.dynamodb.types import TypeDeserializer
DE = TypeDeserializer()

class FakeTable:
    name='fake-moneta-table'
    def __init__(self): self.items={}
    def get_item(self,Key,**kwargs):
        row=self.items.get((Key['PK'],Key['SK']))
        return {'Item':row} if row else {}
    def query(self,**kwargs):
        vals=kwargs['ExpressionAttributeValues'];pk=vals[':pk'];pref=vals.get(':prefix')
        items=[row for (p,s),row in self.items.items() if p==pk and (not pref or s.startswith(pref))]
        return {'Items':items}
    def put_item(self,Item,ConditionExpression=None,**kw):
        key=(Item['PK'],Item['SK']);exists=key in self.items
        if ConditionExpression=='attribute_not_exists(PK)' and exists or ConditionExpression=='attribute_exists(PK)' and not exists:
            self.fail('ConditionalCheckFailedException')
        self.items[key]=Item
    def delete_item(self,Key,ConditionExpression=None):
        key=(Key['PK'],Key['SK'])
        if ConditionExpression=='attribute_exists(PK)' and key not in self.items: self.fail('ConditionalCheckFailedException')
        self.items.pop(key,None)
    def scan(self,**kw):
        return {'Items':[v for (_,sk),v in self.items.items() if sk.startswith('REC#')]}
    def fail(self,code):
        raise mod.ClientError({'Error':{'Code':code, 'Message':code}},'FakeDynamo')

class FakeClient:
    def __init__(self,table):self.table=table;self.calls=0
    def transact_write_items(self,TransactItems):
        self.calls+=1; changes=[]
        for action in TransactItems:
            kind,x=next(iter(action.items()))
            key={k:DE.deserialize(v) for k,v in x.get('Key',x.get('Item')).items()}
            current=self.table.items.get((key['PK'],key['SK']))
            cond=x.get('ConditionExpression','')
            values={k:DE.deserialize(v) for k,v in x.get('ExpressionAttributeValues',{}).items()}
            if cond.startswith('#role =') or cond.startswith('#role IN'):
                r=(current or {}).get('role')
                if r not in [v for v in values.values()]:self.table.fail('TransactionCanceledException')
            if cond.startswith('attribute_not_exists(PK)') and ' OR ' not in cond and current:
                self.table.fail('TransactionCanceledException')
            if cond=='attribute_exists(PK)' and not current:self.table.fail('TransactionCanceledException')
            if cond=='#role <> :owner' and (current or {}).get('role')=='owner':self.table.fail('TransactionCanceledException')
            if cond=='#v.#status = :scheduled' and (current or {}).get('value',{}).get('status')!='scheduled':self.table.fail('TransactionCanceledException')
            if kind=='Put':changes.append(('put',key))
            elif kind=='Delete':changes.append(('del',key))
        for action in TransactItems:
            kind,x=next(iter(action.items()))
            if kind=='Put':
                row={k:DE.deserialize(v) for k,v in x['Item'].items()}
                self.table.items[(row['PK'],row['SK'])]=row
            elif kind=='Delete':
                key={k:DE.deserialize(v) for k,v in x['Key'].items()}
                self.table.items.pop((key['PK'],key['SK']),None)
        return {}

class FakeCognito:
    def list_users(self,UserPoolId,Filter,Limit):
        email=Filter.split('"')[1]
        names={'mario@example.it':'22222222-2222-2222-2222-222222222222',
               'giulia@example.it':'33333333-3333-3333-3333-333333333333'}
        if email not in names:return {'Users':[]}
        return {'Users':[{'Attributes':[{'Name':'sub','Value':names[email]},
                      {'Name':'email','Value':email},{'Name':'email_verified','Value':'true'}]}]}

ALICE='11111111-1111-1111-1111-111111111111'
MARIO='22222222-2222-2222-2222-222222222222'
GIULIA='33333333-3333-3333-3333-333333333333'

def request(route,sub=ALICE,space=None,data=None,params=None,groups=None):
    claims={'sub':sub,'client_id':'client','token_use':'access'}
    if groups is not None:claims['cognito:groups']=groups
    return mod.handler({'routeKey':route,'pathParameters':params or {},
        'queryStringParameters':{'spaceId':space} if space else {},
        'body':json.dumps(data) if data is not None else None,
        'requestContext':{'authorizer':{'jwt':{'claims':claims}}}},None)

def body(result):return json.loads(result.get('body') or '{}')

class MultiuserTests(unittest.TestCase):
    def setUp(self):
        self.db=FakeTable();mod.TABLE=self.db;self.tx=FakeClient(self.db)
        self.cognito=FakeCognito()
        def client(service,**kwargs):
            if service=='dynamodb':return self.tx
            if service=='cognito-idp':return self.cognito
            raise AssertionError('Unexpected service '+service)
        self.patch=patch.object(mod.boto3,'client',side_effect=client);self.patch.start()
        created=request('POST /spaces',data={'name':'Casa'})
        self.assertEqual(created['statusCode'],201,created)
        self.space=body(created)['id']
    def tearDown(self):self.patch.stop()

    def test_private_and_membership(self):
        self.assertEqual(request('GET /state',sub=MARIO,space=self.space)['statusCode'],403)
        self.assertEqual(request('POST /transactions',sub=MARIO,space=self.space,data=self.record())['statusCode'],403)
        self.assertEqual(request('GET /spaces/{id}/members',sub=MARIO,params={'id':self.space})['statusCode'],403)
        self.assertEqual(len(body(request('GET /me'))['spaces']),1)
        self.assertEqual(body(request('GET /me',sub=MARIO))['spaces'],[])

    def record(self,id='spesa1',amount=50,source='fund',kind='expense'):
        return {'id':id,'description':'Alimentari','type':kind,
                'category':'Alimentari' if kind=='expense' else 'Extra',
                'amount':amount,'date':'2026-10-13','note':'test','paymentSource':source}

    def test_fund_spending_appears_personal_without_second_debit(self):
        self.assertEqual(request('POST /transactions',space=self.space,data=self.record())['statusCode'],201)
        p=body(request('GET /state'))['transactions'][0]
        f=body(request('GET /state',space=self.space))['transactions'][0]
        self.assertFalse(p['affectsBalance']);self.assertTrue(f['affectsBalance'])
        self.assertTrue(p['readOnly']);self.assertEqual(p['linkedSpaceId'],self.space)
        self.assertEqual(request('DELETE /transactions/{id}',params={'id':p['id']})['statusCode'],403)
        self.assertEqual(request('PUT /transactions/{id}',params={'id':p['id']},data={**self.record(id=p['id'])})['statusCode'],403)

    def test_personal_paid_and_edit_and_delete_linked(self):
        self.assertEqual(request('POST /transactions',space=self.space,data=self.record(source='personal'))['statusCode'],201)
        self.assertEqual(body(request('GET /state'))['transactions'][0]['affectsBalance'],True)
        update=self.record(amount=75,source='fund')
        self.assertEqual(request('PUT /transactions/{id}',space=self.space,params={'id':'spesa1'},data=update)['statusCode'],200)
        self.assertEqual(body(request('GET /state'))['transactions'][0]['amount'],75)
        self.assertEqual(body(request('GET /state'))['transactions'][0]['affectsBalance'],False)
        self.assertEqual(request('DELETE /transactions/{id}',space=self.space,params={'id':'spesa1'})['statusCode'],204)
        self.assertEqual(body(request('GET /state'))['transactions'],[])
        self.assertEqual(body(request('GET /state',space=self.space))['transactions'],[])

    def test_contribution_is_family_income_and_personal_expense(self):
        original=self.record(id='topup',amount=100,source='personal',kind='income')
        r=request('POST /transactions',space=self.space,data=original)
        self.assertEqual(r['statusCode'],201,r)
        self.assertEqual(body(request('GET /state',space=self.space))['transactions'][0]['type'],'income')
        linked=body(request('GET /state'))['transactions'][0]
        self.assertEqual(linked['type'],'expense')
        self.assertEqual(linked['category'],'Casa')
        self.assertTrue(linked['affectsBalance'])

    def test_invitation_permissions_and_revoke(self):
        inv=request('POST /spaces/{id}/invites',params={'id':self.space},data={'email':'mario@example.it','role':'viewer'})
        self.assertEqual(inv['statusCode'],201,inv)
        mario_inv=body(request('GET /me',sub=MARIO))['invites'][0]
        self.assertEqual(request('POST /invites/{id}/accept',sub=GIULIA,params={'id':mario_inv['id']})['statusCode'],404)
        self.assertEqual(request('POST /invites/{id}/accept',sub=MARIO,params={'id':mario_inv['id']})['statusCode'],200)
        self.assertEqual(request('GET /state',sub=MARIO,space=self.space)['statusCode'],200)
        self.assertEqual(request('POST /transactions',sub=MARIO,space=self.space,data=self.record())['statusCode'],403)
        self.assertEqual(request('POST /spaces/{id}/invites',sub=MARIO,params={'id':self.space},data={'email':'giulia@example.it'})['statusCode'],403)
        self.assertEqual(request('DELETE /spaces/{id}/members/{userId}',params={'id':self.space,'userId':MARIO})['statusCode'],200)
        self.assertEqual(request('GET /state',sub=MARIO,space=self.space)['statusCode'],403)
        self.assertEqual(body(request('GET /me',sub=MARIO))['spaces'],[])

    def test_admin_claim_does_not_bypass_private_data(self):
        self.assertEqual(request('GET /costs')['statusCode'],403)
        self.assertEqual(request('GET /costs',groups=['Other'])['statusCode'],403)
        self.assertEqual(request('GET /state',sub=MARIO,space=self.space,groups=['Admins'])['statusCode'],403)
        self.assertEqual(body(request('GET /me',groups='[Admins]'))['isAdmin'],True)
        self.assertEqual(body(request('GET /me',groups=['Users']))['isAdmin'],False)

    def test_shared_recurring_idempotent_and_linked(self):
        rule={'id':'canone','type':'expense','category':'Casa','description':'Affitto',
              'amount':750,'startDate':'2026-10-01','frequency':'monthly','interval':1,
              'note':'','paymentSource':'fund'}
        self.assertEqual(request('POST /recurring',space=self.space,data=rule)['statusCode'],201)
        today=mod.dt.date(2026,10,13)
        self.assertEqual(mod.run_recurring(today)['created'],1)
        self.assertEqual(mod.run_recurring(today)['created'],0)
        self.assertEqual(len(body(request('GET /state'))['transactions']),1)
        self.assertEqual(len(body(request('GET /state',space=self.space))['transactions']),1)
        self.assertEqual(request('DELETE /transactions/{id}',space=self.space,params={'id':'rec-canone-20261001'})['statusCode'],204)
        self.assertEqual(mod.run_recurring(today)['created'],0)
        self.assertEqual(len(body(request('GET /state'))['transactions']),0)

if __name__=='__main__':unittest.main()
