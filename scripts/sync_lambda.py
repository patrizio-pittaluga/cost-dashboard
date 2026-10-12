#!/usr/bin/env python3
"""Rigenera l'inline Python ZipFile nel template CloudFormation dal sorgente unico."""
from pathlib import Path
import re

root = Path(__file__).resolve().parent.parent
source = (root / 'lambda' / 'index.py').read_text(encoding='utf-8').rstrip() + '\n'
template = root / 'cloudformation' / 'backend.yml'
text = template.read_text(encoding='utf-8')
pattern = r'(      Code:\n        ZipFile: \|\n)(.*?)(\n  HttpApi:\n)'
match = re.search(pattern, text, re.S)
if not match:
    raise SystemExit('Blocco inline Lambda non trovato. Template non modificato.')
indented = ''.join('          ' + line for line in source.splitlines(keepends=True))
replacement = match.group(1) + indented.rstrip('\n') + '\n' + match.group(3)
text = text[:match.start()] + replacement + text[match.end():]
template.write_text(text, encoding='utf-8')
print('Aggiornato cloudformation/backend.yml da lambda/index.py')
