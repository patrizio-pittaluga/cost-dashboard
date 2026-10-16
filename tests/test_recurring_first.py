"""La prima rata nasce insieme alla regola; le successive restano allo scheduler."""
import json
import unittest
from unittest.mock import patch
from boto3.dynamodb.types import TypeDeserializer
from test_backend import mod, call, DummyTable

RULE = {'id':'rent-first','type':'expense','category':'Casa','description':'Canone',
        'amount':150,'startDate':'2020-10-01','frequency':'monthly','interval':1,
        'note':'','recordFirstOccurrence':True}

class FirstOccurrenceTests(unittest.TestCase):
    def setUp(self):
        mod.TABLE=DummyTable()
        mod.TABLE.name="table-test"

    def atomic_db(self, actions):
        decoder=TypeDeserializer()
        entries=[]
        for action in actions:
            if 'Put' in action:
                row={k:decoder.deserialize(v) for k,v in action['Put']['Item'].items()}
                key=(row['PK'],row['SK'])
                if key in mod.TABLE.items:
                    raise mod.ClientError({'Error':{'Code':'TransactionCanceledException','Message':'duplicate'}},'TransactWriteItems')
                entries.append((key,row))
        for key,row in entries:
            mod.TABLE.items[key]=row

    def test_post_from_movement_records_first_and_no_duplicate(self):
        with patch.object(mod,'txn',side_effect=self.atomic_db):
            self.assertEqual(call('POST /recurring',data=RULE)['statusCode'],201)
            self.assertEqual(call('POST /recurring',data=RULE)['statusCode'],409)
        items=json.loads(call('GET /state')['body'])
        self.assertEqual(len(items['transactions']),1)
        self.assertEqual(items['transactions'][0]['date'],'2020-10-01')
        self.assertEqual(items['transactions'][0]['amount'],150)
        self.assertEqual(items['transactions'][0]['recurringId'],'rent-first')
        # La stessa scadenza già creata non viene contabilizzata una seconda volta.
        self.assertEqual(mod.run_recurring(mod.dt.date(2020,10,1))['created'],0)
        self.assertEqual(len(json.loads(call('GET /state')['body'])['transactions']),1)

    def test_future_rule_has_no_initial_charge(self):
        rule={**RULE,'id':'future','startDate':'2099-01-01'}
        with patch.object(mod,'txn') as transaction:
            self.assertEqual(call('POST /recurring',data=rule)['statusCode'],201)
            transaction.assert_not_called()
        self.assertEqual(len(json.loads(call('GET /state')['body'])['transactions']),0)

    def test_legacy_rule_keeps_old_behavior(self):
        rule={k:v for k,v in RULE.items() if k!='recordFirstOccurrence'}
        with patch.object(mod,'txn') as transaction:
            self.assertEqual(call('POST /recurring',data=rule)['statusCode'],201)
            transaction.assert_not_called()
        self.assertEqual(len(json.loads(call('GET /state')['body'])['transactions']),0)

    def test_shared_rule_atomic_personal_projection(self):
        rule={**RULE,'paymentSource':'fund'}
        with patch.object(mod,'txn') as transaction:
            # Il permesso di spazio è verificato nella transazione stessa.
            result=call('POST /recurring',data=rule)
            self.assertEqual(result['statusCode'],201)
            self.assertEqual(len(transaction.call_args.args[0]),2)  # regola e prima spesa atomiche
        # La proiezione condivisa viene testata con la richiesta multiutente dedicata.

if __name__=='__main__':unittest.main()
