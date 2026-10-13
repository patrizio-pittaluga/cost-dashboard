#!/usr/bin/env python3
"""Compatta la Lambda inline nel template senza richiedere un bucket S3 di deploy.

Il sorgente leggibile e completo resta in lambda/index.py. Il template CloudFormation
ha limite API di 51.200 byte e deve contenere soltanto il runtime essenziale.
"""
import ast
from pathlib import Path
import re

class RemoveDocstrings(ast.NodeTransformer):
    def visit_Module(self, node):
        self.generic_visit(node)
        if node.body and isinstance(node.body[0],ast.Expr) and isinstance(node.body[0].value,ast.Constant) and isinstance(node.body[0].value.value,str):
            node.body.pop(0)
        return node
    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        if node.body and isinstance(node.body[0],ast.Expr) and isinstance(node.body[0].value,ast.Constant) and isinstance(node.body[0].value.value,str):
            node.body.pop(0)
        return node

root=Path(__file__).resolve().parent.parent
source=(root/'lambda'/'index.py').read_text(encoding='utf-8')
runtime=ast.unparse(RemoveDocstrings().visit(ast.parse(source)))+'\n'
template=root/'cloudformation'/'backend.yml'
text=template.read_text(encoding='utf-8')
pattern=r'(      Code:\n        ZipFile: \|\n)(.*?)(\n  HttpApi:\n)'
match=re.search(pattern,text,re.S)
if not match:
    raise SystemExit('Blocco inline Lambda non trovato. Template non modificato.')
indented=''.join('          '+line for line in runtime.splitlines(keepends=True))
replacement=match.group(1)+indented.rstrip('\n')+'\n'+match.group(3)
updated=text[:match.start()]+replacement+text[match.end():]
size=len(updated.encode('utf-8'))
if size>51200:
    raise SystemExit(f'Template backend.yml troppo grande ({size} byte, massimo 51200). Non modificato.')
template.write_text(updated,encoding='utf-8')
print(f'Aggiornato backend.yml: Lambda da index.py, template {size}/51200 byte')
