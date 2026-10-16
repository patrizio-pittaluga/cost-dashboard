import unittest
from unittest.mock import patch,MagicMock
from pathlib import Path
from test_backend import mod,call,DummyTable
import admin_users as admin_mod
ROOT=Path(__file__).resolve().parents[1]
class Features224(unittest.TestCase):
 def setUp(self):mod.TABLE=DummyTable()
 def test_admin_endpoints_denied_to_nonadmins(self):
  with patch.object(mod.boto3,'client') as client:
   for route in ('GET /admin/users','POST /admin/users','POST /admin/users/{username}'):
    self.assertEqual(call(route,data={'email':'a@example.com','password':'SafePass#2026xx'} if route.startswith('POST') else None,path_params={'username':'foo'})['statusCode'],403)
   client.assert_not_called()
 def test_valid_password_policy(self):
  for pw in ('short','abcdefghijklmnopqrst','SHORT#123456789','Password123456'):
   with self.assertRaises(ValueError):admin_mod.check_admin_password(pw)
  self.assertEqual(admin_mod.check_admin_password('Password#2026Safe'),'Password#2026Safe')
 def test_admin_cannot_disable_self(self):
  client=MagicMock()
  client.admin_get_user.return_value={'UserAttributes':[{'Name':'sub','Value':'abc'}]}
  with patch.object(mod.boto3,'client',return_value=client):
   with self.assertRaises(ValueError):
    admin_mod.admin_users('POST /admin/users/{username}',{'username':'abc'}, {'action':'disable'},'abc',client)
  client.admin_disable_user.assert_not_called()
 def test_admin_creates_temporary_not_permanent(self):
  client=MagicMock()
  with patch.object(mod.boto3,'client',return_value=client):
   result=admin_mod.admin_users('POST /admin/users',{}, {'email':'X@Example.com','password':'Password#2026Safe','sendEmail':False},'abc',client)
  self.assertEqual(result['statusCode'],201)
  args=client.admin_create_user.call_args.kwargs
  self.assertEqual(args['Username'],'x@example.com')
  self.assertEqual(args['MessageAction'],'SUPPRESS')
  self.assertNotIn('Permanent',args)
 def test_recurring_ui_and_routes(self):
  js=(ROOT/'frontend/app.js').read_text();html=(ROOT/'frontend/index.html').read_text();yaml=(ROOT/'cloudformation/backend.yml').read_text()
  for needle in ('id="txRepeat"','id="txFrequency"','id="txEnd"','data-view="users"','id="usersRows"'):
   self.assertIn(needle,html)
  self.assertIn("await api('/recurring','POST'",js)
  self.assertIn("if(!editId&&$('txRepeat').checked)",js)
  for route in ('GET /admin/users','POST /admin/users','POST /admin/users/{username}'):
   self.assertIn('RouteKey: \''+route+'\'',yaml)
