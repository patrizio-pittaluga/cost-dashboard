"""Moneta 2.2: prove contabili con due account, privacy e rollback atomico."""
import unittest
from test_multiuser import MultiuserTests,ALICE,MARIO,mod,request,body

DATE='2026-10-13'

class Fund22Tests(MultiuserTests):
    def member(self,role='editor'):
        invited=request('POST /spaces/{id}/invites',params={'id':self.space},
                        data={'email':'mario@example.it','role':role})
        self.assertEqual(invited['statusCode'],201,invited)
        invitation=body(request('GET /me',sub=MARIO))['invites'][0]
        joined=request('POST /invites/{id}/accept',sub=MARIO,params={'id':invitation['id']})
        self.assertEqual(joined['statusCode'],200,joined)

    def contribution(self,ident='dep-1',amount=200,sub=ALICE):
        return request('POST /fund/operations',sub=sub,space=self.space,data={
            'id':ident,'kind':'contribution','description':'Cassa comune','amount':amount,'date':DATE})

    def advance(self,mode='direct',ident='adv-1',amount=100,alloc=None,sub=ALICE):
        return request('POST /fund/operations',sub=sub,space=self.space,data={
            'id':ident,'kind':'advance','description':'Supermercato','amount':amount,'date':DATE,
            'category':'Alimentari','allocations':alloc or {ALICE:50,MARIO:50},
            'settlementMode':mode})

    def repay(self,amount,ident,advance='adv-1',debtor=MARIO,sub=MARIO):
        return request('POST /fund/operations',sub=sub,space=self.space,data={
            'id':ident,'kind':'reimbursement','description':'Rimborso spesa','amount':amount,
            'date':DATE,'advanceId':advance,'debtorId':debtor})

    def test_contribution_transfers_money_once_and_duplicate_rejected(self):
        self.assertEqual(self.contribution()['statusCode'],201)
        family=body(request('GET /fund',space=self.space))
        self.assertEqual(family['balance'],200)
        self.assertEqual(family['contributions'][0]['amount'],200)
        self.assertEqual(len(family['operations']),1)
        personal=body(request('GET /state'))['transactions']
        self.assertEqual(len(personal),1)
        self.assertEqual(personal[0]['type'],'expense')
        self.assertTrue(personal[0]['affectsBalance'])
        self.assertTrue(personal[0]['isTransfer'])
        self.assertEqual(self.contribution()['statusCode'],409)
        self.assertEqual(body(request('GET /fund',space=self.space))['balance'],200)
        self.assertEqual(request('DELETE /transactions/{id}',params={'id':personal[0]['id']})['statusCode'],403)
        self.assertEqual(request('DELETE /transactions/{id}',space=self.space,params={'id':'fund-dep-1'})['statusCode'],400)

    def test_advance_direct_split_and_partial_repayments(self):
        self.member();self.assertEqual(self.contribution()['statusCode'],201)
        self.assertEqual(self.advance()['statusCode'],201)
        fund=body(request('GET /fund',space=self.space))
        self.assertEqual(fund['balance'],200) # paid by Alice, not by common fund
        self.assertEqual(fund['advances'][0]['outstanding'],{MARIO:50})
        paid=self.repay(20,'pay-1');self.assertEqual(paid['statusCode'],201,paid)
        self.assertEqual(self.repay(20,'pay-1')['statusCode'],409)
        self.assertEqual(body(request('GET /fund',space=self.space))['advances'][0]['outstanding'][MARIO],30)
        self.assertEqual(self.repay(31,'pay-2')['statusCode'],400)
        self.assertEqual(self.repay(30,'pay-2')['statusCode'],201)
        after=body(request('GET /fund',space=self.space))
        self.assertTrue(after['advances'][0]['settled'])
        self.assertEqual(after['balance'],200)
        mario=body(request('GET /state',sub=MARIO))['transactions']
        self.assertEqual(len(mario),2)
        self.assertTrue(all(t['isTransfer'] for t in mario))
        alice=body(request('GET /state'))['transactions']
        self.assertEqual(sum(round(t['amount']*100)*(1 if t['type']=='income' else -1) for t in alice),-25000)

    def test_fund_reimbursement_clears_advance_without_double_spending(self):
        self.member();self.assertEqual(self.contribution()['statusCode'],201)
        self.assertEqual(self.advance(mode='fund')['statusCode'],201)
        self.assertEqual(self.repay(75,'refund1',debtor='fund',sub=ALICE)['statusCode'],201)
        self.assertEqual(body(request('GET /fund',space=self.space))['balance'],125)
        self.assertEqual(self.repay(25,'refund2',debtor='fund',sub=ALICE)['statusCode'],201)
        fund=body(request('GET /fund',space=self.space))
        self.assertEqual(fund['balance'],100)
        self.assertTrue(fund['advances'][0]['settled'])
        original=body(request('GET /state',space=self.space))['transactions']
        self.assertEqual(sum(x['amount'] for x in original if x['type']=='expense' and not x.get('isTransfer')),100)
        self.assertEqual(self.repay(1,'refund3',debtor='fund',sub=ALICE)['statusCode'],400)

    def test_invalid_allocations_permissions_and_private_scopes(self):
        self.member(role='viewer')
        self.assertEqual(self.advance(alloc={ALICE:40,MARIO:40})['statusCode'],400)
        self.assertEqual(self.advance(alloc={ALICE:100})['statusCode'],201)
        self.assertEqual(self.contribution(sub=MARIO)['statusCode'],403)
        self.assertEqual(request('GET /fund',space=self.space,sub=MARIO)['statusCode'],200)
        self.assertEqual(request('GET /fund',space=self.space,sub='unauthorized')['statusCode'],403)
        self.assertEqual(request('GET /fund')['statusCode'],400)
        self.assertEqual(request('GET /insights',space=self.space)['statusCode'],400)
        self.assertEqual(request('POST /capital/items',space=self.space,data={})['statusCode'],400)

    def test_failure_does_not_leave_half_written_fund_operation(self):
        # Force transaction failure after validation; no ledger or mirror is persisted.
        old=self.tx.transact_write_items
        def fail(*args,**kwargs):raise mod.ClientError({'Error':{'Code':'TransactionCanceledException'}},'Txn')
        self.tx.transact_write_items=fail
        self.assertEqual(self.contribution()['statusCode'],409)
        self.tx.transact_write_items=old
        self.assertEqual(body(request('GET /fund',space=self.space))['operations'],[])
        self.assertEqual(body(request('GET /state'))['transactions'],[])

    def test_capital_is_private_and_not_double_counted(self):
        # Initial cash from a real personal transaction
        initial=self.record(id='initial',amount=1000,kind='income')
        self.assertEqual(request('POST /transactions',data=initial)['statusCode'],201)
        investment={'id':'i-1','name':'ETF demo','kind':'investment','value':3000,'asOf':DATE}
        self.assertEqual(request('POST /capital/items',data=investment)['statusCode'],201)
        debt={'id':'d-1','name':'Debito','kind':'debt','value':500,'asOf':DATE}
        self.assertEqual(request('POST /capital/items',data=debt)['statusCode'],201)
        facts=body(request('GET /insights'))
        self.assertEqual(facts['liquidity'],1000)
        self.assertEqual(facts['netWorth'],3500)
        self.assertEqual(len(facts['assets']),2)
        self.assertEqual(body(request('GET /insights',sub=MARIO))['assets'],[])
        self.assertEqual(request('DELETE /capital/items/{id}',sub=MARIO,params={'id':'i-1'})['statusCode'],404)
        self.assertEqual(request('DELETE /capital/items/{id}',params={'id':'i-1'})['statusCode'],204)
        self.assertEqual(body(request('GET /insights'))['netWorth'],500)

    def test_owner_only_can_record_repayments_on_another_members_behalf(self):
        self.member();self.assertEqual(self.advance()['statusCode'],201)
        # Alice is the owner; records Mario paying an actual settlement.
        self.assertEqual(self.repay(5,'pay_owner',sub=ALICE)['statusCode'],201)
        self.assertEqual(body(request('GET /fund',space=self.space))['advances'][0]['outstanding'][MARIO],45)



class Ui22Tests(unittest.TestCase):
    def test_views_and_new_api_routes_present(self):
        from pathlib import Path
        import re
        base=Path(__file__).resolve().parents[1]
        markup=(base/'frontend/index.html').read_text()
        js=(base/'frontend/app.js').read_text()
        for key in ('view-fund','view-insights','fundOperationForm','fundAllocationRows',
                    'capitalForm','capitalRows','fundDebtorSelect'):
            self.assertIn(f'id="{key}"',markup)
        ids=set(re.findall(r'id="([^"]+)"',markup))
        self.assertEqual(len(ids),len(re.findall(r'id="([^"]+)"',markup)))
        self.assertFalse(set(re.findall(r"\$\('([^']+)'\)",js))-ids)
        self.assertIn("!t.isTransfer",js)
        backend=(base/'cloudformation/backend.yml').read_text()
        for route in ('GET /fund','POST /fund/operations','GET /insights',
                      'POST /capital/items','DELETE /capital/items/{id}'):
            self.assertIn("RouteKey: '"+route+"'",backend)
        self.assertIn('moneta-static-v2.2.3',(base/'frontend/sw.js').read_text())
