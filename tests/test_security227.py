"""Moneta 2.2.7: isolation, token revocation, least-privilege and secret gate."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_backend import mod, call
from test_templates import read_template
import admin_auth
import admin_users
import admin_costs

ROOT = Path(__file__).resolve().parents[1]
SUB = 'e4c11c5a-2222-4a33-8b44-97d01b992344'


def event(route='GET /admin/users', groups=('Admins',), sub=SUB, enabled=True):
    return {'routeKey': route, 'body': None, 'pathParameters': {},
            'requestContext': {'authorizer': {'jwt': {'claims': {
                'sub': sub, 'client_id': 'only-client', 'token_use': 'access',
                'cognito:groups': list(groups)}}}}}


class FakeCognito:
    def __init__(self, enabled=True, groups=('Admins',)):
        self.enabled=enabled
        self.groups=groups
        self.lookups=0
    def list_users(self, **kwargs):
        self.lookups += 1
        return {'Users': [{'Username': 'cognito-username', 'Enabled': self.enabled,
                           'Attributes': [{'Name': 'sub', 'Value': SUB}]}]}
    def admin_list_groups_for_user(self, **kwargs):
        return {'Groups': [{'GroupName': g} for g in self.groups]}


class Security227Tests(unittest.TestCase):
    def test_cognito_live_check_success(self):
        c=FakeCognito()
        self.assertEqual(admin_auth.require_admin(event(), c), SUB)
        self.assertEqual(c.lookups, 1)

    def test_missing_bad_token_does_not_query_cognito(self):
        for changes in ({'cognito:groups': []}, {'token_use': 'id'}, {'client_id': 'forged'}, {'sub': ''}):
            e=event()
            e['requestContext']['authorizer']['jwt']['claims'].update(changes)
            c=FakeCognito()
            with self.assertRaises(PermissionError):
                admin_auth.require_admin(e, c)
            self.assertEqual(c.lookups, 0)

    def test_revoked_admin_claim_denied_immediately(self):
        with self.assertRaises(PermissionError):
            admin_auth.require_admin(event(), FakeCognito(groups=('Users',)))

    def test_disabled_admin_denied_immediately(self):
        with self.assertRaises(PermissionError):
            admin_auth.require_admin(event(), FakeCognito(enabled=False))

    def test_cognito_user_listing_wrong_sub_fails_closed(self):
        c=FakeCognito()
        with self.assertRaises(PermissionError):
            admin_auth.require_admin(event(sub='another-sub'), c)

    def test_admin_lambda_denies_stale_admin_token(self):
        with patch.object(admin_users.boto3, 'client', return_value=FakeCognito(groups=('Users',))):
            res=admin_users.handler(event(), None)
        self.assertEqual(res['statusCode'], 403)

    def test_cost_lambda_denies_revoked_admin_without_calling_ce(self):
        c=FakeCognito(groups=('Users',))
        with patch.object(admin_costs.boto3, 'client', return_value=c), \
             patch.object(admin_costs, 'load_costs') as load:
            res=admin_costs.handler(event('GET /costs'), None)
        self.assertEqual(res['statusCode'], 403)
        load.assert_not_called()

    def test_cost_and_user_lambda_reject_wrong_routes(self):
        self.assertEqual(admin_costs.handler(event('GET /state'), None)['statusCode'], 404)
        self.assertEqual(admin_users.handler(event('GET /state'), None)['statusCode'], 404)

    def test_finance_lambda_denies_admin_routes_even_with_claim(self):
        for r in ('GET /costs','GET /admin/users','POST /admin/users','POST /admin/users/{username}'):
            e=event(r)
            result=mod.handler(e, None)
            self.assertEqual(result['statusCode'],403,r)

    def test_cognito_administration_and_costs_permissions_are_disjoint(self):
        resources=read_template('backend.yml')['Resources']
        def allowed(name):
            statements=resources[name]['Properties']['Policies'][0]['PolicyDocument']['Statement']
            result=set()
            for stmt in statements:
                a=stmt['Action']
                result.update(a if isinstance(a,list) else [a])
            return result
        finance=allowed('ApiLambdaRole')
        users=allowed('AdminUsersRole')
        costs=allowed('CostsRole')
        self.assertNotIn('cognito-idp:AdminSetUserPassword',finance)
        self.assertNotIn('cognito-idp:AdminCreateUser',finance)
        self.assertNotIn('ce:GetCostAndUsage',finance)
        self.assertFalse(any(a.startswith('dynamodb:') for a in users))
        self.assertFalse(any(a.startswith('dynamodb:Scan') for a in costs))
        self.assertFalse(any(a.startswith('cognito-idp:AdminCreateUser') for a in costs))
        self.assertNotIn('ce:GetCostAndUsage',users)
        self.assertIn('dynamodb:LeadingKeys',str(resources['CostsRole']))
        self.assertIn('SYSTEM#AWS_COSTS',str(resources['CostsRole']))
        self.assertIn("'false'", (ROOT/'cloudformation/backend.yml').read_text().split('Sid: CostCacheOnly',1)[1])

    def test_api_routing_isolated(self):
        resources=read_template('backend.yml')['Resources']
        target=lambda name:resources[name]['Properties']['Target']
        for name in ('ListAdminUsersRoute','CreateAdminUserRoute','ManageAdminUserRoute'):
            self.assertIn('AdminUsersIntegration', str(target(name)))
        self.assertIn('CostsIntegration',str(target('ReadCostsRoute')))
        self.assertIn('ApiIntegration',str(target('ReadStateRoute')))
        for item in resources.values():
            if item['Type']=='AWS::ApiGatewayV2::Route':
                p=item['Properties']
                self.assertEqual(p['AuthorizationType'], 'JWT')

    def test_security_headers_on_both_behaviors(self):
        r=read_template('frontend.yml')['Resources']
        d=r['Distribution']['Properties']['DistributionConfig']
        self.assertIn('ResponseHeadersPolicyId',d['DefaultCacheBehavior'])
        self.assertIn('ResponseHeadersPolicyId',d['CacheBehaviors'][0])
        policy=r['SecureResponseHeaders']['Properties']['ResponseHeadersPolicyConfig']['SecurityHeadersConfig']
        self.assertEqual(policy['FrameOptions']['FrameOption'],'DENY')
        self.assertIn("frame-ancestors 'none'",policy['ContentSecurityPolicy']['ContentSecurityPolicy'])
        self.assertGreater(policy['StrictTransportSecurity']['AccessControlMaxAgeSec'],3600)

    def test_three_separate_code_archives(self):
        import zipfile
        bundles={'moneta-lambda.zip':['index.py'],
                 'moneta-admin-users.zip':['admin_users.py','admin_auth.py'],
                 'moneta-costs.zip':['admin_costs.py','admin_auth.py']}
        for name,expected in bundles.items():
            with zipfile.ZipFile(ROOT/'dist'/name) as z:
                self.assertEqual(z.namelist(),expected)

    def test_deploy_security_gate_without_aws(self):
        run=subprocess.run([sys.executable, str(ROOT/'scripts/security_check.py')],
                           cwd=str(ROOT), stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.assertEqual(run.returncode,0,run.stderr+run.stdout)

if __name__=='__main__':
    unittest.main()
