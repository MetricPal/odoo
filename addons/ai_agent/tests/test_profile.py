from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.addons.mail.tests.common import mail_new_test_user

from ..models.common import internal
from ..models.profile import profile_name


class FakeHermes:
    """The Hermes management API and a multiplexing gateway, as seen by Odoo (verified shapes, Hermes v0.21.3)."""

    def __init__(self, serves_profiles=True):
        self.profiles = {}
        self.calls = []
        self.serves_profiles = serves_profiles

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
        self.assertEqual(profile_name('Human Resources'), 'odoo-human-resources')
        self.assertEqual(profile_name('Ventes & Marketing — Été'), 'odoo-ventes-marketing-ete')
        self.assertTrue(len(profile_name('x' * 200)) <= 64)

    def test_sync_creates_the_profile_safely_and_runs_go_to_it(self):
        profile = self.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': self.engine.id,
                                                       'department_id': self.hr.id, 'persona': 'You help HR.'})
        self.assertEqual(profile.hermes_name, 'odoo-human-resources')
        self.assertEqual(self.agent.profile_id, profile, 'The department agent moves to its department profile')
        self.assertIsNone(self.agent._run_profile(), 'Until synced, runs use the connection default')
        fake = FakeHermes()
        self._sync(profile, fake)
        self.assertEqual(profile.state, 'in_sync', profile.sync_message)
        remote = fake.profiles['odoo-human-resources']
        self.assertEqual(remote['soul'], 'You help HR.')
        self.assertIs(remote['config']['memory']['memory_enabled'], False)
        self.assertEqual(remote['config']['platform_toolsets'], {'api_server': [], 'cli': [], 'dashboard': []})
        self.assertEqual(len(remote['key']), 64)
        self.assertEqual(profile._run_key(), remote['key'])
        self.assertEqual(self.agent._run_profile(), profile)
        # A second sync reuses the profile and its key.
        self._sync(profile, fake)
        self.assertEqual(len([c for c in fake.calls if c[:2] == ('POST', '/api/profiles')]), 1)
        self.assertEqual(len([c for c in fake.calls if c[:2] == ('PUT', '/api/env')]), 1)
        # A run is sent to /p/<name> with the profile's key, and remembers it for status and stop.
        self.agent.action_activate()
        run = self.env['ai.agent.run'].with_user(self.ai_admin)._queue(self.agent.with_user(self.ai_admin), 'Hello').sudo()
        management, run_api = self._patched(fake)
        with management, run_api, patch.object(type(self.engine), '_inspect', return_value=({}, [])), \
                patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            run._submit()
        self.assertEqual(run.profile_id, profile)
        self.assertIn(('POST', '/v1/runs', 'odoo-human-resources'), fake.calls)

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
        for values in ({'hermes_name': 'odoo-other'}, {'engine_id': self.engine.id}, {'state': 'in_sync'}):
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
        self.assertEqual((own.kind, own.hermes_name), ('agent', f'odoo-agent-{self.agent.id}'))
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
