"""Controlli statici della PWA, nessun browser o rete richiesto."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class PwaTests(unittest.TestCase):
    def test_installable_files(self):
        manifest=json.loads((ROOT/'frontend/manifest.webmanifest').read_text())
        self.assertEqual(manifest['display'],'standalone')
        self.assertEqual(manifest['start_url'],'/')
        self.assertEqual({entry['sizes'] for entry in manifest['icons']},{'192x192','512x512'})
        for icon in manifest['icons']:
            self.assertTrue((ROOT/'frontend'/icon['src'].lstrip('/')).exists())

    def test_service_worker_only_caches_static_assets(self):
        worker=(ROOT/'frontend/sw.js').read_text()
        self.assertIn("request.method !== 'GET'",worker)
        self.assertIn('STATIC.has(url.pathname)',worker)
        self.assertNotIn('config.json',worker)
        self.assertNotIn('Authorization',worker)
        self.assertNotIn('apiUrl',worker)
        self.assertIn('fetch(request)',worker)

    def test_navigation_and_forms_have_ids(self):
        html=(ROOT/'frontend/index.html').read_text()
        for section in ('view-calendar','quickDialog','plannedDialog','completeDialog','mobileDock','favoriteChips','homeUpcoming'):
            self.assertIn(f'id="{section}"',html)
        js=(ROOT/'frontend/app.js').read_text()
        self.assertIn("'/planned/'",js)
        self.assertIn('recurringOccurrences',js)
        self.assertIn('initPwa()',js)

if __name__=='__main__':unittest.main()
