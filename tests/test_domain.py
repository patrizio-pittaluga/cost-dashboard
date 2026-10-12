"""Verifiche non distruttive delle condizioni CloudFormation per alias DNS e login."""
import unittest
from test_templates import read_template

class TestMonetaDomain(unittest.TestCase):
    def test_frontend_custom_domain_optional_and_uses_sni(self):
        t=read_template('frontend.yml')
        self.assertEqual(t['Parameters']['CustomDomainName']['Default'], '')
        self.assertEqual(t['Parameters']['CustomCertificateArn']['Default'], '')
        conf=t['Resources']['Distribution']['Properties']['DistributionConfig']
        self.assertIn('!If', conf['Aliases'])
        v=conf['ViewerCertificate']['!If']
        self.assertEqual(v[0], 'HasCustomDomain')
        self.assertEqual(v[1]['SslSupportMethod'],'sni-only')
        self.assertEqual(v[1]['MinimumProtocolVersion'],'TLSv1.2_2021')
        self.assertEqual(v[2]['CloudFrontDefaultCertificate'],True)

    def test_backend_adds_custom_origin_and_login_callback_conditionally(self):
        t=read_template('backend.yml')
        self.assertEqual(t['Parameters']['CustomDomainName']['Default'], '')
        resources=t['Resources']
        client=resources['UserPoolClient']['Properties']
        for name in ('CallbackURLs', 'LogoutURLs'):
            self.assertEqual(len(client[name]),2)
            self.assertIn('!If', client[name][1])
        allow=resources['HttpApi']['Properties']['CorsConfiguration']['AllowOrigins']
        self.assertEqual(len(allow),2)
        self.assertIn('!If', allow[1])

if __name__=='__main__':
    unittest.main()
