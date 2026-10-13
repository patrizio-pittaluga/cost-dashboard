"""Moneta 2.2 completo: storni contabili, scenari e valorizzazione investimenti."""
import unittest
from pathlib import Path
from test_features22 import Fund22Tests, DATE
from test_multiuser import request, body, ALICE, MARIO, GIULIA

class CompleteAccountingTests(Fund22Tests):
    def reverse(self, ident, sub=ALICE, reason='Importo registrato per errore'):
        return request('POST /fund/operations/{id}/reverse', sub=sub,space=self.space,
                       params={'id':ident},data={'reason':reason})

    def test_reverse_contribution_has_zero_net_cash_effect_and_is_idempotent(self):
        self.assertEqual(self.contribution()['statusCode'],201)
        self.assertEqual(self.reverse('dep-1')['statusCode'],201)
        fund=body(request('GET /fund',space=self.space))
        self.assertEqual(fund['balance'],0)
        self.assertEqual(fund['contributions'],[])
        self.assertTrue(next(x for x in fund['operations'] if x['id']=='dep-1')['isReversed'])
        tx=body(request('GET /state'))['transactions']
        self.assertEqual(sum(round(t['amount']*100)*(1 if t['type']=='income' else -1)
                             for t in tx if t.get('affectsBalance')),0)
        self.assertTrue(next(t for t in tx if t.get('ledgerOperationId')=='dep-1')['isReversed'])
        self.assertEqual(self.reverse('dep-1')['statusCode'],400)
        self.assertEqual(self.reverse('rev-dep-1')['statusCode'],400)
        self.assertEqual(self.reverse('dep-missing')['statusCode'],404)

    def test_long_valid_identifier_reversal_has_valid_transaction_ids(self):
        operation='x'*72
        self.assertEqual(self.contribution(ident=operation,amount=1)['statusCode'],201)
        self.assertEqual(self.reverse(operation)['statusCode'],201)
        rows=body(request('GET /state'))['transactions']
        self.assertTrue(all(len(item['id'])<=80 for item in rows))
        self.assertEqual(body(request('GET /fund',space=self.space))['balance'],0)

    def test_reverse_requires_permission_and_reason(self):
        self.member(role='editor')
        self.assertEqual(self.contribution()['statusCode'],201)
        self.assertEqual(self.reverse('dep-1',sub=MARIO)['statusCode'],403)
        self.assertEqual(self.reverse('dep-1',sub='outsider')['statusCode'],403)
        self.assertEqual(request('POST /fund/operations/{id}/reverse',space=self.space,
                                 params={'id':'dep-1'},data={'reason':'err'})['statusCode'],400)
        self.assertEqual(self.reverse('dep-1')['statusCode'],201)

    def test_reverse_advance_requires_reverse_payments_first(self):
        self.member()
        self.assertEqual(self.advance()['statusCode'],201)
        self.assertEqual(self.repay(20,'pay-1')['statusCode'],201)
        self.assertEqual(self.reverse('adv-1')['statusCode'],400)
        self.assertEqual(self.reverse('pay-1',sub=MARIO)['statusCode'],201)
        after=body(request('GET /fund',space=self.space))
        self.assertEqual(after['advances'][0]['outstanding'][MARIO],50)
        self.assertEqual(self.reverse('adv-1')['statusCode'],201)
        after=body(request('GET /fund',space=self.space))
        self.assertTrue(after['advances'][0]['isReversed'])
        self.assertEqual(after['balance'],0)
        self.assertEqual(request('GET /insights',sub=ALICE)['statusCode'],200)
        a=body(request('GET /state'))['transactions']
        b=body(request('GET /state',sub=MARIO))['transactions']
        self.assertEqual(sum(round(t['amount']*100)*(1 if t['type']=='income' else -1)
                             for t in a if t.get('affectsBalance')),0)
        self.assertEqual(sum(round(t['amount']*100)*(1 if t['type']=='income' else -1)
                             for t in b if t.get('affectsBalance')),0)
        self.assertEqual(self.repay(2,'pay-new')['statusCode'],400)

    def test_fund_reimbursement_reversal_restores_fund_and_claim(self):
        self.member()
        self.assertEqual(self.contribution(amount=200)['statusCode'],201)
        self.assertEqual(self.advance(mode='fund')['statusCode'],201)
        self.assertEqual(self.repay(80,'refund1',debtor='fund',sub=ALICE)['statusCode'],201)
        self.assertEqual(body(request('GET /fund',space=self.space))['balance'],120)
        self.assertEqual(self.reverse('refund1')['statusCode'],201)
        after=body(request('GET /fund',space=self.space))
        self.assertEqual(after['balance'],200)
        self.assertEqual(after['advances'][0]['outstanding']['fund'],100)
        self.assertEqual(self.reverse('adv-1')['statusCode'],201)
        self.assertEqual(body(request('GET /fund',space=self.space))['balance'],200)
        self.assertEqual(self.reverse('refund1')['statusCode'],400)

    def test_owner_can_reverse_other_member_operation(self):
        self.member()
        self.assertEqual(self.contribution(ident='mario-dep',amount=15,sub=MARIO)['statusCode'],201)
        self.assertEqual(self.reverse('mario-dep',sub=ALICE)['statusCode'],201)
        self.assertEqual(body(request('GET /fund',space=self.space))['balance'],0)

    def test_invalid_reversal_after_membership_revocation(self):
        self.member()
        self.assertEqual(self.contribution(ident='mario-dep',amount=15,sub=MARIO)['statusCode'],201)
        self.assertEqual(request('DELETE /spaces/{id}/members/{userId}',params={'id':self.space,'userId':MARIO})['statusCode'],200)
        self.assertEqual(self.reverse('mario-dep')['statusCode'],400)
        self.assertEqual(body(request('GET /fund',space=self.space))['balance'],15)

    def test_portfolio_quantity_cost_basis_and_edit(self):
        item={'id':'etf1','kind':'investment','name':'ETF simulato','value':0,
              'asOf':DATE,'assetClass':'etf','symbol':'SWDA','quantity':'2.5',
              'unitPrice':'12.3333','costBasis':20,'feesPaid':1}
        self.assertEqual(request('POST /capital/items',data=item)['statusCode'],201)
        data=body(request('GET /insights'))
        self.assertEqual(data['totals']['investment'],30.83)
        self.assertEqual(data['portfolio'][0]['weightPercent'],100.0)
        self.assertEqual(data['portfolio'][0]['unrealizedGain'],10.83)
        stored=data['assets'][0]
        self.assertEqual(stored['symbol'],'SWDA')
        self.assertEqual(stored['revision'],1)
        update={**item,'quantity':'3','unitPrice':'15','revision':1}
        self.assertEqual(request('PUT /capital/items/{id}',params={'id':'etf1'},data=update)['statusCode'],200)
        self.assertEqual(body(request('GET /insights'))['totals']['investment'],45)
        self.assertEqual(request('PUT /capital/items/{id}',params={'id':'etf1'},data=update)['statusCode'],400)
        self.assertEqual(request('GET /insights',sub=MARIO)['statusCode'],200)
        self.assertEqual(request('PUT /capital/items/{id}',sub=MARIO,params={'id':'etf1'},data=update)['statusCode'],404)
        self.assertEqual(request('PUT /capital/items/{id}',params={'id':'etf1'},data={**update,'revision':2,'quantity':-3})['statusCode'],400)

    def test_simulator_zero_rate_no_market_guesses_and_privacy(self):
        start=self.record(id='salary',kind='income',amount=1000)
        self.assertEqual(request('POST /transactions',data=start)['statusCode'],201)
        scenario={'months':6,'monthlyReserve':100,'extraExpenses':0,
                  'incomeReduction':0,'oneTimeExpense':200}
        response=request('POST /insights/simulate',data=scenario)
        self.assertEqual(response['statusCode'],200,response)
        result=body(response)
        self.assertEqual(result['initialLiquidity'],1000)
        self.assertEqual(result['projection'][0]['available'],700)
        self.assertEqual(result['projection'][-1]['reserved'],600)
        self.assertEqual(result['projection'][-1]['combined'],800)
        self.assertEqual(len(result['projection']),6)
        self.assertTrue(result['warnings'])
        self.assertEqual(request('POST /insights/simulate',data={**scenario,'months':40})['statusCode'],400)
        self.assertEqual(request('POST /insights/simulate',data={**scenario,'monthlyReserve':-1})['statusCode'],400)
        self.assertEqual(request('POST /insights/simulate',space=self.space,data=scenario)['statusCode'],400)
        other=body(request('POST /insights/simulate',sub=MARIO,data=scenario))
        self.assertEqual(other['initialLiquidity'],0)

class UiFullTests(unittest.TestCase):
    def test_new_routes_and_ui_references(self):
        import re
        root=Path(__file__).resolve().parents[1]
        html=(root/'frontend/index.html').read_text()
        js=(root/'frontend/app.js').read_text()
        template=(root/'cloudformation/backend.yml').read_text()
        for route in ('POST /fund/operations/{id}/reverse','POST /insights/simulate',
                      'PUT /capital/items/{id}'):
            self.assertIn("RouteKey: '"+route+"'",template)
        for field in ('reverseForm','reverseReason','portfolioSummary','portfolioRows',
                      'simulateForm','simReserve','simulationResult','capitalQuantity',
                      'capitalUnitPrice','capitalAssetClass','capitalCancelEdit'):
            self.assertIn(f'id="{field}"',html)
        tags=re.findall(r'id="([^\"]+)"',html)
        self.assertEqual(len(tags),len(set(tags)))
        self.assertFalse(set(re.findall(r"\$\('([^']+)'\)",js)) - set(tags))
        self.assertIn('moneta-static-v2.2.3',(root/'frontend/sw.js').read_text())
