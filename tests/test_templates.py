"""Controlli strutturali CloudFormation offline (non sostituisce ValidateTemplate AWS)."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class CfnLoader(yaml.SafeLoader):
    pass


def cloudformation_tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        value = loader.construct_mapping(node)
    return {'!' + suffix: value}


CfnLoader.add_multi_constructor('!', cloudformation_tag)


def read_template(name):
    with (ROOT/'cloudformation'/name).open(encoding='utf-8') as f:
        return yaml.load(f, Loader=CfnLoader)


class TestTemplates(unittest.TestCase):
    def test_frontend_payg_s3_private(self):
        x=read_template('frontend.yml')['Resources']
        self.assertNotIn('CloudFrontFree',x)
        self.assertNotIn('FrontendWaf',x)
        self.assertNotIn('WebACLId',x['Distribution']['Properties']['DistributionConfig'])
        self.assertEqual(x['WebBucket']['Properties']['PublicAccessBlockConfiguration']['BlockPublicPolicy'],True)
        self.assertIn('OriginAccessControlId',x['Distribution']['Properties']['DistributionConfig']['Origins'][0])

    def test_backend_mfa_and_jwt_protection(self):
        x=read_template('backend.yml')['Resources']
        self.assertEqual(x['ApiLambda']['Properties']['Runtime'],'python3.13')
        self.assertEqual(x['UserPool']['Properties']['MfaConfiguration'],'ON')
        self.assertEqual(x['UserPool']['Properties']['EnabledMfas'],['SOFTWARE_TOKEN_MFA'])
        self.assertEqual(x['UserPool']['Properties']['UserPoolTier'],'LITE')
        self.assertEqual(x['UserPool']['Properties']['AdminCreateUserConfig']['AllowAdminCreateUserOnly'],True)
        self.assertEqual(x['DataTable']['Properties']['BillingMode'],'PROVISIONED')
        routes=[p for v in x.values() if v['Type']=='AWS::ApiGatewayV2::Route' for p in [v['Properties']]]
        self.assertEqual(len(routes),9)
        self.assertTrue(all(p['AuthorizationType']=='JWT' and '!Ref' in p['AuthorizerId'] for p in routes))
        self.assertEqual(x['UserPoolDomain']['Properties']['ManagedLoginVersion'],1)
        self.assertIn('DailyRecurringSchedule',x)
        self.assertEqual(x['DailyRecurringSchedule']['Type'],'AWS::Scheduler::Schedule')
        actions=x['ApiLambdaRole']['Properties']['Policies'][0]['PolicyDocument']['Statement']
        self.assertTrue(any('ce:GetCostAndUsage' in (stmt['Action'] if isinstance(stmt['Action'],list) else [stmt['Action']]) for stmt in actions))

    def test_generated_python_matches_source(self):
        x=read_template('backend.yml')['Resources']
        source=(ROOT/'lambda'/'index.py').read_text(encoding='utf-8').strip()
        embedded=x['ApiLambda']['Properties']['Code']['ZipFile'].strip()
        self.assertEqual(source,embedded)

    def test_budget_account_wide(self):
        x=read_template('budget.yml')['Resources']['AccountMonthlyBudget']['Properties']
        self.assertEqual(x['Budget']['TimeUnit'],'MONTHLY')
        self.assertEqual(len(x['NotificationsWithSubscribers']),4)
        self.assertNotIn('CostFilters',x['Budget'])


if __name__ == '__main__':
    unittest.main()
