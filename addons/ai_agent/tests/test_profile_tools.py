from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, TransactionCase, tagged

from ..models.common import internal
from .test_profile import FakeHermes
from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestProfileTools(TransactionCase):
    """ADR 0012 phase 6: a profile's Tools and services (approved mock 2026-11-08, boards 8 and 9)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        company = [Command.set(cls.env.company.ids)]
        cls.ai_admin = mail_new_test_user(cls.env, login='tools_ai_admin', groups='ai_agent.group_user',
                                          company_ids=company)
        cls.hr = cls.env['hr.department'].create({'name': 'Human Resources'})
        cls.finance = cls.env['hr.department'].create({'name': 'Finance'})
        cls.hr.write({'ai_admin_ids': [Command.set(cls.ai_admin.ids)]})
        cls.engine = cls.env['ai.agent.engine'].create({'name': 'Test engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.profile = cls.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': cls.engine.id,
                                                          'department_id': cls.hr.id})
        cls.finance_profile = cls.env['ai.agent.profile'].create({'name': 'Finance', 'engine_id': cls.engine.id,
                                                                  'department_id': cls.finance.id})

    def setUp(self):
        super().setUp()
        self.fake = FakeHermes()
        Engine = type(self.engine)
        for patcher in (patch.object(Engine, '_management', lambda e, *a, **k: self.fake.management(e, *a, **k)),
                        patch.object(Engine, '_request', lambda e, *a, **k: self.fake.run_api(e, *a, **k))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _api_server(self):
        return self.fake.profiles['human-resources']['config']['platform_toolsets']['api_server']

    def _tool(self, toolset, profile=None):
        return (profile or self.profile).tool_ids.filtered(lambda t: t.toolset == toolset)

    def _add_server(self, name='HR documents', url='https://drive-mcp.example.com/mcp', auth='key', key='k-123'):
        wizard = self.env['ai.agent.tool.server.add'].create({'profile_id': self.profile.id, 'name': name, 'url': url,
                                                              'auth': auth, 'key': key})
        return wizard, wizard.with_context(tool_server_key=key).action_add()

    def test_a_new_profile_lists_the_offered_tools_off_and_the_erp_server(self):
        self.assertEqual(self.profile.tool_ids.mapped('toolset'), ['web', 'vision', 'image_gen', 'todo'])
        self.assertFalse(any(self.profile.tool_ids.mapped('enabled')), 'Hermes tools start off')
        erp = self.profile.server_ids
        self.assertEqual((erp.kind, erp.hermes_name, erp.enabled), ('erp', 'erp', True))
        self.profile._ensure_tools()
        self.assertEqual((len(self.profile.tool_ids), len(self.profile.server_ids)), (4, 1), 'Listed once')
        self.profile.action_sync()
        self.assertEqual(self.profile.state, 'in_sync', self.profile.sync_message)
        self.assertEqual(self._api_server(), ['erp'], 'Only the ERP tools while nothing is switched on')
        secrets = self.fake.profiles['human-resources']['config']['secrets']['command']
        self.assertTrue(secrets['enabled'])
        self.assertEqual(secrets['command'], "grep -E '^[A-Z0-9_]+_API_KEY=' '/srv/hermes erp/.env' | "
                                             "grep -v '^API_SERVER_KEY='",
                         "Provider keys are read from the main profile's .env (quoted path), never copied")
        self.assertEqual(self._tool('vision').status, 'ready')
        self.assertEqual(self._tool('web').status, 'needs_key')
        self.assertEqual(erp.status, 'ready')
        action = self._tool('web').action_add_key()
        self.assertEqual(action['url'], 'https://hermes.example.com/env')

    def test_department_admins_switch_tools_and_they_reach_hermes_at_the_next_sync(self):
        self.profile.action_sync()
        web = self._tool('web')
        self.profile.with_user(self.ai_admin).write({'tool_ids': [Command.update(web.id, {'enabled': True})]})
        self.assertTrue(web.enabled)
        self.assertEqual(self.profile.state, 'needs_sync', 'Waits for the next sync')
        self.assertEqual(self._api_server(), ['erp'], 'Hermes unchanged until then')
        self.profile.with_user(self.ai_admin).action_sync()
        self.assertEqual(self._api_server(), ['erp', 'web'])
        with self.assertRaises(AccessError):
            self.finance_profile.with_user(self.ai_admin).write(
                {'tool_ids': [Command.update(self._tool('web', self.finance_profile).id, {'enabled': True})]})
        with self.assertRaises(AccessError):
            web.with_user(self.ai_admin).write({'toolset': 'web', 'enabled': False})
        with self.assertRaises(AccessError):
            self.profile.with_user(self.ai_admin).write({'tool_ids': [Command.create({'toolset': 'web'})]})
        with self.assertRaises(AccessError):
            web.unlink()
        with self.assertRaises(UserError):
            self.profile.server_ids.with_user(self.ai_admin).write({'enabled': False})

    def test_add_a_tool_server_its_key_goes_to_hermes_only(self):
        with self.assertRaises(UserError):
            self._add_server()  # The profile is not in Hermes yet.
        self.profile.action_sync()
        wizard, result = self._add_server()
        self.assertEqual(result, {'type': 'ir.actions.act_window_close'})
        sent = self.fake.profiles['human-resources']['mcp']['hr-documents']
        self.assertEqual((sent['url'], sent['auth'], sent['bearer_token']),
                         ('https://drive-mcp.example.com/mcp', 'header', 'k-123'))
        server = self.profile.server_ids.filtered(lambda s: s.kind == 'external')
        self.assertEqual((server.name, server.hermes_name, server.status), ('HR documents', 'hr-documents', 'ready'))
        for table, record in (('ai_agent_tool_server_add', wizard), ('ai_agent_tool_server', server)):
            self.env.cr.execute(f'SELECT * FROM {table} WHERE id = %s', [record.id])
            self.assertNotIn('k-123', str(self.env.cr.fetchall()), f'The key is never stored ({table})')
        self.assertEqual(self.profile.state, 'needs_sync')
        self.profile.action_sync()
        self.assertEqual(self._api_server(), ['erp', 'hr-documents'])
        # Department admins switch it off; it leaves the run platform at the next sync.
        self.profile.with_user(self.ai_admin).write({'server_ids': [Command.update(server.id, {'enabled': False})]})
        self.assertEqual(server.status, 'off')
        self.profile.action_sync()
        self.assertEqual(self._api_server(), ['erp'])
        self.assertEqual(server.status, 'off')
        # Only AI Agent managers add and remove tool servers.
        with self.assertRaises(AccessError):
            self.profile.with_user(self.ai_admin).action_add_tool_server()
        with self.assertRaises(AccessError):
            server.with_user(self.ai_admin).action_remove()
        with self.assertRaises(AccessError):
            server.unlink()
        server.action_remove()
        self.assertFalse(server.exists())
        self.assertNotIn('hr-documents', self.fake.profiles['human-resources']['mcp'])
        with self.assertRaises(UserError):
            self.profile.server_ids.action_remove()  # The ERP server stays.

    def test_the_dialog_asks_for_a_key_only_with_key_sign_in(self):
        dialog = Form(self.env['ai.agent.tool.server.add'].with_context(default_profile_id=self.profile.id))
        dialog.name = 'HR documents'
        dialog.url = 'https://drive-mcp.example.com/mcp'
        with self.assertRaises(AssertionError):
            dialog.key = 'k-123'  # Hidden while the sign-in is None.
        dialog.auth = 'key'
        dialog.key = 'k-123'
        wizard = dialog.save()
        self.assertFalse(wizard.key, 'The key is not kept on the dialog record')

    def test_tool_server_address_sign_in_and_reachability(self):
        self.profile.action_sync()
        with self.assertRaises(UserError):
            self._add_server(url='ftp://files.example.com')
        with self.assertRaises(UserError):
            self._add_server(key='')
        self.fake.probes['drive'] = {'ok': False, 'error': 'OAuth authentication required — no token found.'}
        _wizard, result = self._add_server(name='Drive', auth='oauth', key='')
        self.assertEqual((result['url'], result['close']), ('https://hermes.example.com/mcp', True))
        drive = self.profile.server_ids.filtered(lambda s: s.hermes_name == 'drive')
        self.assertEqual(drive.status, 'sign_in')
        self.assertNotIn('bearer_token', self.fake.profiles['human-resources']['mcp']['drive'])
        self.fake.probes['payroll'] = {'ok': False, 'error': 'connection refused'}
        self._add_server(name='Payroll', url='https://mcp.payroll.example/v1', auth='none', key='')
        payroll = self.profile.server_ids.filtered(lambda s: s.hermes_name == 'payroll')
        self.assertEqual((payroll.status, payroll.status_message), ('unreachable', 'connection refused'))
        self.fake.probes['payroll'] = {'ok': True, 'tools': []}
        self.profile.action_sync()
        self.assertEqual(payroll.status, 'ready', 'Checked again at each sync')

    def test_scheduled_jobs_are_read_back_and_paused_from_here(self):
        self.fake.jobs['human-resources'] = [
            {'id': 'j1', 'name': 'Weekly policy digest', 'schedule_display': 'Mondays at 08:00', 'state': 'scheduled',
             'next_run_at': '2026-11-10T08:00:00+00:00', 'last_run_at': '2026-11-03T08:00:00Z', 'last_status': 'ok'},
            {'id': 'j2', 'name': 'Old onboarding check', 'schedule_display': 'Every day at 07:30', 'state': 'paused',
             'next_run_at': None, 'last_run_at': '2026-10-31T07:30:00+00:00', 'last_status': 'error'}]
        self.profile.action_sync()
        digest, check = self.profile.job_ids.sorted('hermes_id')
        self.assertEqual((digest.name, digest.schedule, digest.state, digest.last_result),
                         ('Weekly policy digest', 'Mondays at 08:00', 'active', 'done'))
        self.assertEqual(str(digest.next_run), '2026-11-10 08:00:00')
        self.assertEqual((check.state, check.last_result, check.next_run), ('paused', 'failed', False))
        digest.with_user(self.ai_admin).action_pause()
        self.assertEqual(digest.state, 'paused')
        check.with_user(self.ai_admin).action_resume()
        self.assertEqual(check.state, 'active')
        with self.assertRaises(AccessError):
            digest.write({'state': 'active'})
        with self.assertRaises(AccessError):
            self.env['ai.agent.profile.job'].create({'profile_id': self.profile.id, 'hermes_id': 'x', 'state': 'active'})
        self.fake.jobs['human-resources'].pop(0)
        self.profile.action_sync()
        self.assertEqual(self.profile.job_ids.mapped('hermes_id'), ['j2'], 'Gone from Hermes, gone here')
        finance_user = mail_new_test_user(self.env, login='tools_other', groups='ai_agent.group_user')
        with self.assertRaises(AccessError):
            self.profile.job_ids.with_user(finance_user).action_pause()
