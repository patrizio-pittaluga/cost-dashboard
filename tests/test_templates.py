"""Controlli strutturali CloudFormation offline (non sostituisce ValidateTemplate AWS)."""
from pathlib import Path
import ast
import zipfile
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
        self.assertEqual(len(routes),23)
        self.assertEqual(x['AdminsGroup']['Properties']['GroupName'],'Admins')
        self.assertTrue(all(p['AuthorizationType']=='JWT' and '!Ref' in p['AuthorizerId'] for p in routes))
        self.assertEqual(x['UserPoolDomain']['Properties']['ManagedLoginVersion'],1)
        self.assertIn('DailyRecurringSchedule',x)
        self.assertEqual(x['DailyRecurringSchedule']['Type'],'AWS::Scheduler::Schedule')
        actions=x['ApiLambdaRole']['Properties']['Policies'][0]['PolicyDocument']['Statement']
        self.assertTrue(any('ce:GetCostAndUsage' in (stmt['Action'] if isinstance(stmt['Action'],list) else [stmt['Action']]) for stmt in actions))

    def test_generated_python_matches_source(self):
        x=read_template('backend.yml')['Resources']
        source=(ROOT/'lambda'/'index.py').read_text(encoding='utf-8').strip()
        code=x['ApiLambda']['Properties']['Code']
        self.assertEqual(code['S3Bucket'],{'!Ref':'LambdaCodeBucket'})
        self.assertEqual(code['S3Key'],{'!Ref':'LambdaCodeKey'})
        artifact=ROOT/'dist'/'moneta-lambda.zip'
        self.assertTrue(artifact.exists(),'Esegui python3 scripts/sync_lambda.py')
        with zipfile.ZipFile(artifact) as z:
            self.assertEqual(z.namelist(),['index.py'])
            embedded=z.read('index.py').decode('utf-8')
        # Lo ZIP pubblicato deve contenere il codice sorgente di Lambda.

        class RemoveDocstrings(ast.NodeTransformer):
            def visit_Module(self,node):
                self.generic_visit(node)
                if node.body and isinstance(node.body[0],ast.Expr) and isinstance(node.body[0].value,ast.Constant) and isinstance(node.body[0].value.value,str):node.body.pop(0)
                return node
            def visit_FunctionDef(self,node):
                self.generic_visit(node)
                if node.body and isinstance(node.body[0],ast.Expr) and isinstance(node.body[0].value,ast.Constant) and isinstance(node.body[0].value.value,str):node.body.pop(0)
                return node
        strip=lambda code: ast.dump(RemoveDocstrings().visit(ast.parse(code)),include_attributes=False)
        self.assertEqual(strip(source),strip(embedded))
        self.assertLessEqual((ROOT/'cloudformation'/'backend.yml').stat().st_size,51200)
        self.assertEqual(read_template('backend.yml')['Resources']['DataTable']['DeletionPolicy'],'Retain') if 'DeletionPolicy' in read_template('backend.yml')['Resources']['DataTable'] else None

    def test_budget_account_wide(self):
        x=read_template('budget.yml')['Resources']['AccountMonthlyBudget']['Properties']
        self.assertEqual(x['Budget']['TimeUnit'],'MONTHLY')
        self.assertEqual(len(x['NotificationsWithSubscribers']),4)
        self.assertNotIn('CostFilters',x['Budget'])


if __name__ == '__main__':
    unittest.main()
