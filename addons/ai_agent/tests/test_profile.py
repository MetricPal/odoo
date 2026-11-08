from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.addons.mail.tests.common import mail_new_test_user

from ..models.common import internal
from ..models.profile import profile_name
from ..services import hermes


class FakeHermes:
    """The Hermes management API and a multiplexing gateway, as seen by Odoo (verified shapes, Hermes v0.21.3)."""

    def __init__(self, serves_profiles=True):
        self.profiles = {}
        self.calls = []
        self.serves_profiles = serves_profiles
        self.default = ('', '')  # The connection's default provider and model.
        self.configured = {'vision', 'todo'}  # Hermes tools that have what they need.
        self.probes = {}  # Tool server name: what Hermes's test answers.
        self.jobs = {}  # Profile name: its scheduled jobs.

    def management(self, engine, method, path, payload=None, query=None):
        self.calls.append((method, path, payload, query))
        profile = (query or {}).get('profile')
        if (method, path) == ('GET', '/api/profiles'):
            return {'profiles': [{'name': name} for name in self.profiles]}
        if (method, path) == ('POST', '/api/profiles'):
            self.profiles[payload['name']] = {'config': {'memory': {'memory_enabled': True}}}
            return {'ok': True}
        if (method, path) == ('PUT', '/api/config'):
            self.profiles[profile]['config'].update(payload['config'])
            return {'ok': True}
        if (method, path) == ('GET', '/api/model/options'):
            return {'providers': [], 'provider': self.default[0], 'model': self.default[1]}
        if (method, path) == ('GET', '/api/config'):
            return self.profiles[profile]['config']
        if method == 'PUT' and path.endswith('/soul'):
            self.profiles[path.split('/')[3]]['soul'] = payload['content']
            return {'ok': True}
        if method == 'PUT' and path.endswith('/model'):
            self.profiles[path.split('/')[3]]['model'] = (payload['provider'], payload['model'])
            return {'ok': True}
        if (method, path) == ('PUT', '/api/env'):
            self.profiles[profile]['key'] = payload['value']
            return {'ok': True}
        if (method, path) == ('GET', '/api/mcp/servers'):
            return [{'name': name} for name in self.profiles[profile].get('mcp', {})]
        if (method, path) == ('POST', '/api/mcp/servers'):
            self.profiles[profile].setdefault('mcp', {})[payload['name']] = payload
            return {'name': payload['name']}
        if (method, path) == ('GET', '/api/tools/toolsets'):
            return [{'name': name, 'configured': name in self.configured}
                    for name in ('web', 'browser', 'terminal', 'vision', 'image_gen', 'todo')]
        if method == 'POST' and path.startswith('/api/mcp/servers/') and path.endswith('/test'):
            return self.probes.get(path.split('/')[4], {'ok': True, 'tools': []})
        if (method, path) == ('GET', '/api/cron/jobs'):
            return self.jobs.get(profile, [])
        if method == 'POST' and path.startswith('/api/cron/jobs/'):
            job_id, verb = path.split('/')[4:6]
            for job in self.jobs.get(profile, []):
                if job['id'] == job_id:
                    job['state'] = 'paused' if verb == 'pause' else 'scheduled'
            return {'ok': True}
        if method == 'DELETE' and path.startswith('/api/mcp/servers/'):
            self.profiles[profile].get('mcp', {}).pop(path.rsplit('/', 1)[1], None)
            return {'ok': True}
        if method == 'DELETE':
            self.profiles.pop(path.split('/')[3], None)
            return {'ok': True}
        raise AssertionError(f'unexpected management call {method} {path}')

    def run_api(self, engine, method, path, payload=None, headers=None, profile=None):
        self.calls.append((method, path, profile and profile.hermes_name))
        if profile is not None:
            if not self.serves_profiles:
                raise UserError('404')
            assert profile._run_key() == self.profiles[profile.hermes_name]['key']
        if path == '/v1/capabilities':
            return {'features': {'run_submission': True, 'run_status': True}}
        if path == '/v1/runs':
            return {'run_id': 'run_profile_1'}
        return {}


@tagged('post_install', '-at_install')
class TestHermesProfiles(TransactionCase):
    """ADR 0012 phase 2: Hermes profiles managed from Odoo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        company = [Command.set(cls.env.company.ids)]
        cls.ai_admin = mail_new_test_user(cls.env, login='prof_ai_admin', groups='ai_agent.group_user',
                                          company_ids=company)
        cls.hr = cls.env['hr.department'].create({'name': 'Human Resources'})
        cls.finance = cls.env['hr.department'].create({'name': 'Finance'})
        cls.hr.write({'ai_admin_ids': [Command.set(cls.ai_admin.ids)]})
        cls.engine = cls.env['ai.agent.engine'].create({'name': 'Test engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.agent = cls.env['ai.agent'].create({'name': 'HR policy helper', 'engine_id': cls.engine.id,
                                               'department_id': cls.hr.id, 'access_scope': 'company'})

    def _patched(self, fake):
        Engine = type(self.engine)
        return (patch.object(Engine, '_management', lambda engine, *a, **k: fake.management(engine, *a, **k)),
                patch.object(Engine, '_request', lambda engine, *a, **k: fake.run_api(engine, *a, **k)))

    def _sync(self, profile, fake):
        management, run_api = self._patched(fake)
        with management, run_api:
            profile.action_sync()

    def test_profile_names_are_hermes_safe(self):
        self.assertEqual(profile_name('Human Resources'), 'human-resources')
        self.assertEqual(profile_name('Ventes & Marketing — Été'), 'ventes-marketing-ete')
        self.assertTrue(len(profile_name('x' * 200)) <= 64)
        self.assertEqual(profile_name('Sales', taken={'sales', 'sales-2'}), 'sales-3')
        self.assertEqual(profile_name('Default'), 'default-2', "Hermes's own profile is never used")
        self.assertEqual(profile_name('Test'), 'test-2', 'Names Hermes refuses are never used')
        self.assertEqual(profile_name('***'), 'profile')

    def test_names_are_made_here_and_never_typed(self):
        first = self.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': self.engine.id,
                                                     'department_id': self.hr.id, 'hermes_name': 'typed-name'})
        self.assertEqual(first.hermes_name, 'human-resources', 'A typed name is ignored')
        second = self.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': self.engine.id,
                                                      'department_id': self.finance.id})
        self.assertEqual(second.hermes_name, 'human-resources-2')
        second.name = 'Finance'
        self.assertEqual(second.hermes_name, 'finance', 'Follows the name until it exists in Hermes')
        with self.assertRaises(AccessError):
            second.write({'hermes_name': 'other'})
        # A profile of that name made in Hermes by someone else is never taken over.
        fake = FakeHermes()
        fake.profiles['finance'] = {'config': {'memory': {}}, 'soul': 'Not ours'}
        self._sync(second, fake)
        self.assertEqual(second.state, 'in_sync', second.sync_message)
        self.assertEqual(second.hermes_name, 'finance-2')
        self.assertEqual(fake.profiles['finance']['soul'], 'Not ours')
        second.name = 'Accounting'
        self.assertEqual(second.hermes_name, 'finance-2', 'Fixed once it exists in Hermes')

    def test_old_tool_server_is_replaced(self):
        profile = self.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': self.engine.id,
                                                       'department_id': self.hr.id})
        fake = FakeHermes()
        self._sync(profile, fake)
        remote = fake.profiles['human-resources']
        remote['mcp']['odoo'] = {'name': 'odoo'}
        self._sync(profile, fake)
        self.assertEqual(set(remote['mcp']), {'erp'})

    def test_sync_creates_the_profile_safely_and_runs_go_to_it(self):
        profile = self.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': self.engine.id,
                                                       'department_id': self.hr.id, 'persona': 'You help HR.'})
        self.assertEqual(profile.hermes_name, 'human-resources')
        self.assertEqual(self.agent.profile_id, profile, 'The department agent moves to its department profile')
        self.assertIsNone(self.agent._run_profile(), 'Until synced, runs use the connection default')
        fake = FakeHermes()
        self._sync(profile, fake)
        self.assertEqual(profile.state, 'in_sync', profile.sync_message)
        remote = fake.profiles['human-resources']
        self.assertEqual(remote['soul'], 'You help HR.')
        self.assertIs(remote['config']['memory']['memory_enabled'], False)
        self.assertEqual(remote['config']['platform_toolsets'], {'api_server': ['erp'], 'cli': [], 'dashboard': []})
        odoo_server = remote['mcp']['erp']
        self.assertTrue(odoo_server['url'].endswith('/ai_agent/mcp'))
        self.assertEqual(odoo_server['auth'], 'header')
        self.assertEqual(self.env['ai.agent.tools']._profile_for_token(odoo_server['bearer_token']), profile)
        self.assertEqual(len(remote['key']), 64)
        self.assertEqual(profile._run_key(), remote['key'])
        self.assertEqual(self.agent._run_profile(), profile)
        # A second sync reuses the profile and its key.
        self._sync(profile, fake)
        self.assertEqual(len([c for c in fake.calls if c[:2] == ('POST', '/api/profiles')]), 1)
        self.assertEqual(len([c for c in fake.calls if c[:2] == ('PUT', '/api/env')]), 1)
        self.assertEqual(len([c for c in fake.calls if c[:2] == ('POST', '/api/mcp/servers')]), 1)
        # A run is sent to /p/<name> with the profile's key, and remembers it for status and stop.
        self.agent.action_activate()
        run = self.env['ai.agent.run'].with_user(self.ai_admin)._queue(self.agent.with_user(self.ai_admin), 'Hello').sudo()
        management, run_api = self._patched(fake)
        with management, run_api, patch.object(type(self.engine), '_inspect', return_value=({}, [])), \
                patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            run._submit()
        self.assertEqual(run.profile_id, profile)
        self.assertIn(('POST', '/v1/runs', 'human-resources'), fake.calls)

    def test_sync_fails_clearly_when_the_gateway_does_not_serve_profiles(self):
        profile = self.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': self.engine.id,
                                                       'department_id': self.hr.id})
        self._sync(profile, FakeHermes(serves_profiles=False))
        self.assertEqual(profile.state, 'failed')
        self.assertIn('multiplexing', profile.sync_message)
        self.assertIsNone(self.agent._run_profile())

    def test_department_admins_edit_persona_and_model_of_their_profile_only(self):
        hr_profile = self.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': self.engine.id,
                                                          'department_id': self.hr.id})
        finance_profile = self.env['ai.agent.profile'].create({'name': 'Finance', 'engine_id': self.engine.id,
                                                               'department_id': self.finance.id})
        self._sync(hr_profile, FakeHermes())
        hr_profile.with_user(self.ai_admin).write({'persona': 'Friendly and short.'})
        self.assertEqual(hr_profile.persona, 'Friendly and short.')
        self.assertEqual(hr_profile.state, 'needs_sync', 'The change waits for the next sync')
        self.assertEqual(self.agent._run_profile(), hr_profile, 'The profile keeps working meanwhile')
        for values in ({'hermes_name': 'other'}, {'engine_id': self.engine.id}, {'state': 'in_sync'}):
            with self.assertRaises((AccessError, UserError)):
                hr_profile.with_user(self.ai_admin).write(values)
        with self.assertRaises(AccessError):
            finance_profile.with_user(self.ai_admin).write({'persona': 'Not mine'})
        with self.assertRaises(AccessError):
            self.env['ai.agent.profile'].with_user(self.ai_admin).create(
                {'name': 'Mine', 'engine_id': self.engine.id, 'department_id': self.hr.id})

    def test_company_profile_is_the_fallback_and_an_agent_can_have_its_own(self):
        company_profile = self.env['ai.agent.profile'].create({'name': 'Company', 'kind': 'company',
                                                               'engine_id': self.engine.id})
        self.assertEqual(self.agent.profile_id, company_profile)
        hr_profile = self.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': self.engine.id,
                                                          'department_id': self.hr.id})
        self.assertEqual(self.agent.profile_id, hr_profile)
        self.agent.action_own_profile()
        own = self.agent.profile_id
        self.assertEqual((own.kind, own.hermes_name), ('agent', 'hr-policy-helper'))
        hr_profile.action_archive()
        self.assertEqual(self.agent.profile_id, own, 'An own profile is kept')

    def test_company_assistant(self):
        company_profile = self.env['ai.agent.profile'].create({'name': 'Company', 'kind': 'company',
                                                               'engine_id': self.engine.id})
        with self.assertRaises(AccessError):
            company_profile.with_user(self.ai_admin).action_create_company_assistant()
        if not self.env.company.ai_assistant_user_id:
            company_profile.action_create_company_assistant()
        assistant = self.env.company.ai_assistant_user_id
        self.assertTrue(assistant.ai_assistant)
        self.assertEqual(company_profile.assistant_user_id, assistant)

    def _unreachable(self):
        error = hermes.HermesUnavailable('Hermes is not running or cannot be reached at hermes.example.com:443.')
        error.unreachable = True
        return error

    def test_unreachable_hermes_fails_clearly_and_flags_the_connection(self):
        profile = self.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': self.engine.id,
                                                       'department_id': self.hr.id})
        with patch.object(type(self.engine), '_management', side_effect=self._unreachable()):
            profile.action_sync()
        self.assertEqual(profile.state, 'failed')
        self.assertIn('not running', profile.sync_message)
        self.assertFalse(profile.in_hermes)
        self.assertEqual(self.engine.state, 'blocked', 'The connection needs attention until checked again')

    def test_remove_a_profile_that_never_reached_hermes(self):
        profile = self.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': self.engine.id,
                                                       'department_id': self.hr.id})
        internal(profile).write({'state': 'failed'})
        with patch.object(type(self.engine), '_management', side_effect=AssertionError('Hermes must not be called')):
            profile.action_remove_from_hermes()
        self.assertEqual((profile.state, profile.active), ('draft', False))

    def test_remove_a_profile_already_gone_from_hermes(self):
        profile = self.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': self.engine.id,
                                                       'department_id': self.hr.id})
        self._sync(profile, FakeHermes())
        self.assertTrue(profile.in_hermes)
        gone = hermes.HermesRejected('404')
        gone.status = 404
        with patch.object(type(self.engine), '_management', side_effect=gone):
            profile.action_remove_from_hermes()
        self.assertEqual(profile.state, 'draft')
        self.assertFalse(profile.in_hermes)
        # Any other refusal is shown, and nothing changes.
        profile.action_unarchive()
        internal(profile).write({'state': 'in_sync', 'in_hermes': True})
        refused = hermes.HermesRejected('401')
        refused.status = 401
        with patch.object(type(self.engine), '_management', side_effect=refused), self.assertRaises(UserError):
            profile.action_remove_from_hermes()
