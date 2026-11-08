from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.addons.mail.tests.common import mail_new_test_user

from ..models.common import internal


class FakeModels:
    """Hermes's provider list, key check, recommended model and default model (Hermes v0.21.3 shapes)."""

    def __init__(self):
        self.env = {}
        self.default = ('', '')
        self.calls = []

    def providers(self):
        openrouter_ready = 'OPENROUTER_API_KEY' in self.env
        return [
            {'slug': 'moa', 'name': 'Mixture of Agents', 'authenticated': True, 'source': 'virtual', 'models': ['default']},
            {'slug': 'openrouter', 'name': 'OpenRouter', 'authenticated': openrouter_ready, 'key_env': '',
             'models': ['vendor/big-model', 'vendor/small-model'] if openrouter_ready else []},
            {'slug': 'anthropic', 'name': 'Anthropic', 'authenticated': False, 'key_env': 'ANTHROPIC_API_KEY', 'models': []},
            {'slug': 'nous', 'name': 'Nous Portal', 'authenticated': False, 'key_env': '', 'models': []},
            {'slug': 'opencode-free', 'name': 'OpenCode Free', 'authenticated': True, 'models': ['free-a', 'free-b']},
        ]

    def management(self, engine, method, path, payload=None, query=None):
        self.calls.append((method, path, payload and {k: v for k, v in payload.items() if k != 'value'}, query))
        if (method, path) == ('GET', '/api/model/options'):
            return {'providers': self.providers(), 'provider': self.default[0], 'model': self.default[1]}
        if (method, path) == ('POST', '/api/providers/validate'):
            good = payload['value'] == 'good-key'
            return {'ok': good, 'reachable': True, 'message': '' if good else 'That API key was rejected.'}
        if (method, path) == ('PUT', '/api/env'):
            self.env[payload['key']] = payload['value']
            return {'ok': True}
        if (method, path) == ('GET', '/api/model/recommended-default'):
            return {'provider': query['provider'], 'model': 'vendor/small-model'}
        if (method, path) == ('POST', '/api/model/set'):
            self.default = (payload['provider'], payload['model'])
            return {'ok': True}
        if method == 'PUT' and path.endswith('/model'):
            return {'ok': True}
        raise AssertionError(f'unexpected management call {method} {path}')


@tagged('post_install', '-at_install')
class TestDefaultModel(TransactionCase):
    """Choose the default model of a Hermes connection from the ERP (approved mock 2026-11-07, boards 5 and 6)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        cls.engine = cls.env['ai.agent.engine'].create({
            'name': 'Model engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'needs_model'})

    def _hermes(self, fake, ready_after_set=True):
        Engine = type(self.engine)

        def check(engines):
            for engine in engines:
                internal(engine).write({'state': 'ready' if fake.default[1] and ready_after_set else 'needs_model'})
            return True

        def catalog(engine):
            return {'providers': [{'slug': p['slug'], 'name': p['name'], 'models': p['models'],
                                   'authenticated': p['authenticated'], 'total_models': len(p['models'])}
                                  for p in fake.providers()], 'provider': fake.default[0], 'model': fake.default[1]}
        return (patch.object(Engine, '_management', lambda engine, *a, **k: fake.management(engine, *a, **k)),
                patch.object(Engine, 'action_check', check),
                patch.object(Engine, '_model_catalog', catalog))

    def test_health_without_a_model_means_needs_a_model(self):
        health = {'status': 'degraded', 'readiness': {'checks': {'model': {'status': 'degraded'},
                                                                 'disk': {'status': 'ok'}}}}
        with self.assertRaises(UserError) as error:
            self.engine._check_health(health)
        self.assertTrue(error.exception.needs_model)
        health['readiness']['checks']['disk'] = {'status': 'failed'}
        with self.assertRaises(UserError) as error:
            self.engine._check_health(health)
        self.assertFalse(getattr(error.exception, 'needs_model', False))
        self.assertIn('disk', str(error.exception))

    def test_the_list_shows_suggestions_and_every_provider(self):
        fake = FakeModels()
        management, check, catalog = self._hermes(fake)
        with management, check, catalog:
            data = self.engine.default_model_data()
        self.assertEqual([p['slug'] for p in data['key_providers']], ['openrouter', 'anthropic'])
        self.assertEqual(data['key_providers'][0]['key_env'], 'OPENROUTER_API_KEY', 'Known key name filled in')
        self.assertEqual(data['free']['models'], ['free-a', 'free-b'])
        self.assertNotIn('moa', [p['slug'] for p in data['providers']], 'Virtual providers are left out')
        nous = next(p for p in data['providers'] if p['slug'] == 'nous')
        self.assertEqual((nous['ready'], nous['key_env']), (False, ''), 'Sign-in providers have no key field')

    def test_own_key_sets_the_recommended_model(self):
        fake = FakeModels()
        management, check, catalog = self._hermes(fake)
        with management, check, catalog:
            with self.assertRaises(UserError) as error:
                self.engine.set_default_model('openrouter', key='bad-key')
            self.assertIn('rejected', str(error.exception))
            self.assertNotIn('OPENROUTER_API_KEY', fake.env, 'A refused key is not saved')
            data = self.engine.set_default_model('openrouter', key='good-key')
        self.assertEqual(fake.env['OPENROUTER_API_KEY'], 'good-key')
        self.assertEqual(fake.default, ('openrouter', 'vendor/small-model'))
        self.assertEqual(data['current']['model'], 'vendor/small-model')
        self.assertEqual(self.engine.state, 'ready')
        self.assertEqual(self.engine.enabled_model_ids.mapped('model'), ['vendor/small-model'])

    def test_free_provider_and_validation(self):
        fake = FakeModels()
        management, check, catalog = self._hermes(fake)
        with management, check, catalog:
            with self.assertRaises(UserError):
                self.engine.set_default_model('anthropic')  # needs its key first
            with self.assertRaises(UserError):
                self.engine.set_default_model('nous', key='good-key')  # sign-in provider
            with self.assertRaises(UserError):
                self.engine.set_default_model('opencode-free', model='not-offered')
            with self.assertRaises(UserError):
                self.engine.set_default_model('unknown')
            self.engine.set_default_model('opencode-free', model='free-b')
        self.assertEqual(fake.default, ('opencode-free', 'free-b'))

    def test_profiles_without_their_own_model_follow_the_default(self):
        fake = FakeModels()
        profile = self.env['ai.agent.profile'].create({'name': 'Company', 'kind': 'company',
                                                       'engine_id': self.engine.id})
        internal(profile).write({'in_hermes': True, 'state': 'in_sync'})
        management, check, catalog = self._hermes(fake)
        with management, check, catalog:
            self.engine.set_default_model('opencode-free', model='free-a')
        self.assertIn(('PUT', f'/api/profiles/{profile.hermes_name}/model', {'provider': 'opencode-free',
                                                                             'model': 'free-a'}, None), fake.calls)

    def test_add_model_sets_up_a_provider_with_its_key(self):
        fake = FakeModels()
        management, check, catalog = self._hermes(fake)
        with management, check, catalog:
            internal(self.engine).write({'state': 'ready', 'models_catalog': self.engine._model_catalog()})
            picker = self.env['ai.agent.model.picker'].create({'engine_id': self.engine.id,
                                                               'catalog': self.engine.provider_catalog})
            openrouter = next(p for p in picker.catalog['providers'] if p['slug'] == 'openrouter')
            self.assertEqual((openrouter['authenticated'], openrouter['key_env']), (False, 'OPENROUTER_API_KEY'))
            with self.assertRaises(UserError):
                picker.save_provider_key('openrouter', 'bad-key')
            picker.save_provider_key('openrouter', 'good-key')
            openrouter = next(p for p in picker.catalog['providers'] if p['slug'] == 'openrouter')
            self.assertTrue(openrouter['authenticated'])
            self.assertEqual(openrouter['models'], ['vendor/big-model', 'vendor/small-model'])
            self.assertEqual(fake.default, ('', ''), 'Adding a key does not change the default model')
            picker.set_model_enabled('openrouter', 'vendor/big-model', True)
            self.assertIn('vendor/big-model', self.engine.enabled_model_ids.mapped('model'))
            with self.assertRaises(UserError):
                picker.save_provider_key('nous', 'good-key')  # sign-in provider
            agent = self.env['ai.agent'].create({'name': 'Picker agent', 'engine_id': self.engine.id,
                                                 'access_scope': 'company'})
            agent_picker = self.env['ai.agent.model.picker'].create({'engine_id': self.engine.id, 'agent_id': agent.id,
                                                                     'catalog': self.engine.provider_catalog})
            with self.assertRaises(UserError):
                agent_picker.save_provider_key('anthropic', 'good-key')

    def test_only_managers_choose(self):
        user = mail_new_test_user(self.env, login='dm_ai_user', groups='ai_agent.group_user',
                                  company_ids=[Command.set(self.env.company.ids)])
        for method, args in (('default_model_data', ()), ('set_default_model', ('opencode-free', 'free-a')),
                             ('save_provider_key', ('openrouter', 'good-key'))):
            with self.assertRaises(AccessError):
                getattr(self.engine.with_user(user), method)(*args)
