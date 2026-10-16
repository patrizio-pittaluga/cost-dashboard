#!/usr/bin/env python3
"""Moneta offline pre-deploy security gate. Zero API, zero external dependencies.

Not a comprehensive secret scanner nor a CloudFormation verifier. Tests use PyYAML.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
issues = []


def check(condition, message):
    if not condition:
        issues.append(message)


# Scan deployed source, not test fakes, release notes or generated distribution.
files = [p for part in ('lambda', 'frontend', 'cloudformation', 'scripts')
         for p in (ROOT / part).rglob('*') if p.is_file() and p.suffix in ('.py','.js','.json','.yml','.yaml','.sh','.html')
         and p.name != 'config.json']
patterns = {
    'AWS access key': re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b'),
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'GitHub token': re.compile(r'\bgh[pousr]_[A-Za-z0-9_]{25,}\b'),
    'AWS secret literal': re.compile(r'''(?im)^\s*(?:export\s+)?AWS_SECRET_ACCESS_KEY\s*=\s*['\"]?[^'\"#\s$]{12,}'''),
    'password literal': re.compile(r'''(?im)^\s*(?:PASSWORD|DB_PASSWORD|CLIENT_SECRET|API_SECRET)\s*=\s*['\"][^'\"]{8,}['\"]'''),
}
for file in files:
    content = file.read_text(encoding='utf-8', errors='replace')
    for label, pattern in patterns.items():
        for match in pattern.finditer(content):
            issues.append(f'{file.relative_to(ROOT)}:{content.count(chr(10), 0, match.start())+1}: possible {label}')

back = (ROOT/'cloudformation/backend.yml').read_text()
front = (ROOT/'cloudformation/frontend.yml').read_text()
main = (ROOT/'lambda/index.py').read_text()
check('CognitoAdminUsers' not in back, 'Old merged Cognito admin policy still present')
check('cognito-idp:AdminCreateUser' not in back.split('  ApiLambdaRole:',1)[1].split('  ApiLambda:',1)[0],
      'Finance role still has Cognito mutation rights')
check('ce:GetCostAndUsage' not in back.split('  ApiLambdaRole:',1)[1].split('  ApiLambda:',1)[0],
      'Finance role still has cost read privileges')
check('dynamodb:LeadingKeys' in back and "'SYSTEM#AWS_COSTS'" in back,
      'Cost cache not restricted to dedicated partition')
check('AdminUsersLambda:' in back and 'CostsLambda:' in back, 'Admin roles not isolated')
check('require_admin(event' in (ROOT/'lambda/admin_users.py').read_text(), 'User admin lacks live group check')
check('require_admin(event' in (ROOT/'lambda/admin_costs.py').read_text(), 'Cost lambda lacks live group check')
check('ResponseHeadersPolicyId: !Ref SecureResponseHeaders' in front and 'FrameOption: DENY' in front
      and 'StrictTransportSecurity:' in front, 'CloudFront security headers missing')
check('BlockPublicPolicy: true' in front and 'OriginAccessControlId:' in front,
      'Frontend S3 private access protection missing')
check('return admin_users(' not in main and 'load_costs(' not in main,
      'Financial handler still includes admin/cost business logic')
check("AuthorizationType: JWT" in back and 'JwtAuthorizer' in back,
      'JWT authorization missing from backend template')

if issues:
    print('FAILED: security checks found issues:')
    for issue in issues:
        print(' - ' + issue)
    sys.exit(1)
print(f'OK: offline security gate, {len(files)} operational files inspected, {len(issues)} findings')
print('Limitation: not a penetration test or AWS account audit; git history and AWS runtime not scanned.')
