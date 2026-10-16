from pathlib import Path
import unittest

P = Path(__file__).resolve().parents[1] / 'frontend'

class BalancePrivacyTests(unittest.TestCase):
    def test_private_by_default_in_html(self):
        html = (P/'index.html').read_text()
        for target in ('totalBalance', 'fundBalance'):
            self.assertIn(f'id="{target}" data-balance-masked="true">••••••', html)
            self.assertIn(f'data-balance-toggle="{target}"', html)
        self.assertIn('aria-label="Mostra saldo"', html)

    def test_mask_kept_on_rerender(self):
        js = (P/'app.js').read_text()
        self.assertIn('let balancesVisible=false;',js)
        self.assertIn("displayBalance('totalBalance',balance(valid))",js)
        self.assertIn("displayBalance('fundBalance',fundData.balance)",js)
        self.assertIn('bindBalancePrivacy()',js)
        self.assertNotIn('localStorage.setItem(\'balanceVisible',js)

    def test_mask_respects_same_state_for_both_balances(self):
        js = (P/'app.js').read_text()
        self.assertIn("['totalBalance','fundBalance']",js)
        self.assertIn("balancesVisible=!balancesVisible",js)
