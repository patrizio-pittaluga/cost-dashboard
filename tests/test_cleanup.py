"""Safety checks della cancellazione legacy, nessun account AWS contattato."""
from pathlib import Path
from unittest import TestCase, mock
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cleanup_legacy', ROOT/'scripts'/'cleanup_legacy.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CleanupSafety(TestCase):
    def test_legacy_allowlist_only(self):
        self.assertEqual([name for name, _ in mod.LEGACY],
                         ['bilancio-backend', 'bilancio-frontend', 'bilancio-budget'])
        self.assertNotIn('moneta-frontend', [name for name, _ in mod.LEGACY])

    def test_default_is_preview_only(self):
        with mock.patch.object(sys, 'argv', ['cleanup_legacy.py']), \
             mock.patch.object(mod, 'aws', return_value={'Account': '123456789012'}), \
             mock.patch.object(mod, 'inventory', return_value={'bilancio-backend': {}}), \
             mock.patch.object(mod, 'clean') as destructive, \
             mock.patch.object(mod, 'require_budget') as check_budget:
            mod.main()
            destructive.assert_not_called()
            check_budget.assert_not_called()

    def test_execute_requires_correct_account(self):
        with mock.patch.object(sys, 'argv', ['cleanup_legacy.py','--execute','--confirm-account','000000000000']), \
             mock.patch.object(mod, 'aws', return_value={'Account': '123456789012'}), \
             mock.patch.object(mod, 'inventory', return_value={'bilancio-backend': {}}), \
             mock.patch.object(mod, 'clean') as destructive:
            with self.assertRaisesRegex(RuntimeError, 'Conferma account errata'):
                mod.main()
            destructive.assert_not_called()

    def test_requires_new_budget_before_delete(self):
        with mock.patch.object(sys, 'argv', ['cleanup_legacy.py','--execute','--confirm-account','123456789012']), \
             mock.patch.object(mod, 'aws', return_value={'Account': '123456789012'}), \
             mock.patch.object(mod, 'inventory', return_value={'bilancio-frontend': {}}), \
             mock.patch.object(mod, 'require_budget', side_effect=RuntimeError('no budget')), \
             mock.patch.object(mod, 'clean') as destructive:
            with self.assertRaisesRegex(RuntimeError, 'no budget'):
                mod.main()
            destructive.assert_not_called()
