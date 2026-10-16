#!/usr/bin/env python3
"""Build reproducible ZIP archives for three restricted Lambda roles; no AWS credentials."""
from pathlib import Path
import ast
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'lambda'
DIST = ROOT / 'dist'
DIST.mkdir(parents=True, exist_ok=True)
BUNDLES = {
    'moneta-lambda.zip': ('index.py',),
    'moneta-admin-users.zip': ('admin_users.py', 'admin_auth.py'),
    'moneta-costs.zip': ('admin_costs.py', 'admin_auth.py'),
}
for filename, members in BUNDLES.items():
    target = DIST / filename
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for module in members:
            data = (SRC / module).read_bytes()
            ast.parse(data.decode('utf-8'))
            info = zipfile.ZipInfo(module, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            out.writestr(info, data)
    print(f'{target.name}: {target.stat().st_size} bytes, sha256={hashlib.sha256(target.read_bytes()).hexdigest()}')
