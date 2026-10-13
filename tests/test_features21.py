"""Regressioni Moneta 2.1 su preferiti, scadenze e contabilità condivisa."""
import unittest
from test_multiuser import (ALICE, MARIO, FakeTable, FakeClient, mod,
                            request, body, MultiuserTests)
from unittest.mock import patch

PERSONAL_PLAN={'id':'p-1','description':'Bollo auto','type':'expense','category':'Trasporti',
               'amount':125.50,'dueDate':'2026-11-20','note':''}

class Features21Tests(MultiuserTests):
    # inherits the authenticated two-user fixture and existing multiuser assertions
    def test_private_favorites_and_validation(self):
        favorite={'id':'fav-1','description':'Spesa settimanale','type':'expense','category':'Alimentari',
                  'amount':45.6,'note':'','spaceId':'','paymentSource':'fund'}
        self.assertEqual(request('POST /favorites',data=favorite)['statusCode'],201)
        self.assertEqual(body(request('GET /favorites'))['favorites'][0]['amount'],45.6)
        self.assertEqual(body(request('GET /favorites',sub=MARIO))['favorites'],[])
        self.assertEqual(request('POST /favorites',data=favorite)['statusCode'],409)
        favorite['category']='categoria falsa';favorite['id']='fav-2'
        self.assertEqual(request('POST /favorites',data=favorite)['statusCode'],400)
        self.assertEqual(request('DELETE /favorites/{id}',params={'id':'fav-1'},sub=MARIO)['statusCode'],404)
        self.assertEqual(request('DELETE /favorites/{id}',params={'id':'fav-1'})['statusCode'],204)

    def test_personal_plan_is_not_a_transaction_until_completed(self):
        self.assertEqual(request('POST /planned',data=PERSONAL_PLAN)['statusCode'],201)
        state=body(request('GET /state'))
        self.assertEqual(state['transactions'],[])
        self.assertEqual(len(state['planned']),1)
        self.assertEqual(body(request('GET /state',sub=MARIO))['planned'],[])
        self.assertEqual(request('POST /planned/{id}/complete',params={'id':'p-1'},data={'paidDate':'2026-10-13'})['statusCode'],200)
        state=body(request('GET /state'))
        self.assertEqual(len(state['transactions']),1)
        self.assertEqual(state['transactions'][0]['amount'],125.50)
        self.assertEqual(state['transactions'][0]['date'],'2026-10-13')
        self.assertEqual(state['planned'][0]['status'],'completed')
        self.assertEqual(request('POST /planned/{id}/complete',params={'id':'p-1'},data={'paidDate':'2026-10-13'})['statusCode'],200)
        self.assertEqual(len(body(request('GET /state'))['transactions']),1)
        self.assertEqual(request('PUT /planned/{id}',params={'id':'p-1'},data=PERSONAL_PLAN)['statusCode'],400)
        self.assertEqual(request('DELETE /planned/{id}',params={'id':'p-1'})['statusCode'],400)

    def test_shared_plan_creates_one_transaction_and_correct_personal_mirror(self):
        self.assertEqual(request('POST /planned',space=self.space,data={**PERSONAL_PLAN,'paymentSource':'fund'})['statusCode'],201)
        self.assertEqual(body(request('GET /state',space=self.space))['transactions'],[])
        self.assertEqual(request('POST /planned/{id}/complete',space=self.space,params={'id':'p-1'},data={'paidDate':'2026-10-15'})['statusCode'],200)
        family=body(request('GET /state',space=self.space))['transactions']
        personal=body(request('GET /state'))['transactions']
        self.assertEqual(len(family),1)
        self.assertEqual(len(personal),1)
        self.assertFalse(personal[0]['affectsBalance'])
        self.assertEqual(personal[0]['sourceTransactionId'],family[0]['id'])
        self.assertEqual(personal[0]['date'],'2026-10-15')
        self.assertEqual(request('POST /planned/{id}/complete',space=self.space,params={'id':'p-1'},data={'paidDate':'2026-10-16'})['statusCode'],200)
        self.assertEqual(len(body(request('GET /state',space=self.space))['transactions']),1)

    def test_shared_plan_personal_payment_affects_personal_balance_only(self):
        self.assertEqual(request('POST /planned',space=self.space,data={**PERSONAL_PLAN,'paymentSource':'personal'})['statusCode'],201)
        self.assertEqual(request('POST /planned/{id}/complete',space=self.space,params={'id':'p-1'},data={'paidDate':'2026-11-20'})['statusCode'],200)
        shared=body(request('GET /state',space=self.space))['transactions'][0]
        personal=body(request('GET /state'))['transactions'][0]
        self.assertFalse(shared['affectsBalance'])
        self.assertTrue(personal['affectsBalance'])
        self.assertEqual(personal['type'],'expense')

    def test_other_user_cannot_read_or_change_shared_plans(self):
        self.assertEqual(request('POST /planned',space=self.space,data=PERSONAL_PLAN)['statusCode'],201)
        self.assertEqual(request('GET /state',space=self.space,sub=MARIO)['statusCode'],403)
        self.assertEqual(request('POST /planned/{id}/complete',space=self.space,sub=MARIO,
                                 params={'id':'p-1'},data={'paidDate':'2026-10-13'})['statusCode'],403)
        self.assertEqual(request('POST /favorites',space=self.space,sub=MARIO,
                                 data={'id':'fv','description':'x','amount':1,'category':'Casa',
                                       'type':'expense','spaceId':self.space})['statusCode'],403)

    def test_bad_dates_and_duplicate_plan(self):
        self.assertEqual(request('POST /planned',data={**PERSONAL_PLAN,'dueDate':'2026-02-30'})['statusCode'],400)
        self.assertEqual(request('POST /planned',data=PERSONAL_PLAN)['statusCode'],201)
        self.assertEqual(request('POST /planned',data=PERSONAL_PLAN)['statusCode'],409)
        self.assertEqual(request('POST /planned/{id}/complete',params={'id':'p-1'},data={'paidDate':'2026-02-30'})['statusCode'],400)
        self.assertEqual(len(body(request('GET /state'))['transactions']),0)
