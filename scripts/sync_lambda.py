#!/usr/bin/env python3
"""Produce ZIP Lambda nella cartella dist, senza dipendenze né credenziali AWS."""
from pathlib import Path
import ast
import zipfile
import hashlib
root=Path(__file__).resolve().parent.parent
src=(root/'lambda'/'index.py').read_bytes()
ast.parse(src.decode('utf-8'))
dst=root/'dist'/'moneta-lambda.zip'
dst.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(dst,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    info=zipfile.ZipInfo('index.py',date_time=(2026,1,1,0,0,0))
    info.compress_type=zipfile.ZIP_DEFLATED
    info.external_attr=0o644 << 16
    z.writestr(info,src)
print(f'Lambda ZIP: {dst} ({dst.stat().st_size} bytes, sha256={hashlib.sha256(dst.read_bytes()).hexdigest()})')
