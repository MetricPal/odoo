import sys
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..models.common import internal
from ..models.configuration import ERP_HERMES_SCRIPT
from ..services import hermes


def unreachable():
    error = hermes.HermesUnavailable('Hermes is not running or cannot be reached.')
    error.unreachable = True
    return error


class Answer:
    """What the patched Hermes calls do: answer, or not be reachable."""

    def __init__(self, dashboard=True, gateway=True):
        self.dashboard, self.gateway, self.calls = dashboard, gateway, []

    def management(self, engine, method, path, payload=None, query=None):
        self.calls.append((method, path))
        if not self.dashboard:
            raise unreachable()
        return {}

    def run_api(self, engine, method, path, *args, **kwargs):
        if not self.gateway:
            raise unreachable()
        return {}


@tagged('post_install', '-at_install')
class TestStartHermes(TransactionCase):
    """Approved mocks 2026-11-08, boards 13 (local) and 14 (remote)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': '127.0.0.1:8643,127.0.0.1:9120,hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        cls.local = cls.env['ai.agent.engine'].create({'name': 'Local Hermes', 'connection_mode': 'local'})
        cls.remote = cls.env['ai.agent.engine'].create({'name': 'Company Hermes', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        cls.ai_manager = new_test_user(cls.env, 'start_ai_manager', groups='base.group_user,ai_agent.group_manager')
        cls.ai_manager.write({'group_ids': [Command.unlink(cls.env.ref('base.group_system').id)]})

    def _patched(self, answer):
        Engine = type(self.local)
        return (patch.object(Engine, '_management', lambda e, *a, **k: answer.management(e, *a, **k)),
                patch.object(Engine, '_request', lambda e, *a, **k: answer.run_api(e, *a, **k)))

    def _probe(self, engine, **answers):
        management, run_api = self._patched(Answer(**answers))
        with management, run_api:
            return engine._probe_runtime()

    def test_the_check_tells_whether_hermes_runs(self):
        self.assertEqual(self._probe(self.local, dashboard=False, gateway=False), 'stopped')
        self.assertEqual(self._probe(self.local, gateway=False), 'gateway_stopped')
        self.assertEqual(self._probe(self.local), 'running')
        self.assertEqual(self._probe(self.remote, dashboard=False, gateway=False), 'unreachable',
                         'Another machine that does not answer cannot be started from here')
        self.assertEqual(self._probe(self.remote, gateway=False), 'gateway_stopped')
        management, run_api = self._patched(Answer(dashboard=False, gateway=False))
        with management, run_api:
            self.local._unreachable(unreachable())
        self.assertEqual((self.local.state, self.local.hermes_runtime), ('blocked', 'stopped'))
        self.assertEqual(self.local.runs_on, 'This server')
        self.assertEqual(self.remote.runs_on, 'Another machine · https://hermes.example.com')

    def test_only_settings_administrators_may_start_it(self):
        internal(self.local).write({'state': 'blocked', 'hermes_runtime': 'stopped'})
        internal(self.remote).write({'state': 'blocked', 'hermes_runtime': 'unreachable'})
        self.assertTrue(self.local.can_start_hermes)
        self.assertFalse(self.remote.can_start_hermes, 'Nothing to ask when the other machine does not answer')
        internal(self.remote).write({'hermes_runtime': 'gateway_stopped'})
        self.assertTrue(self.remote.can_start_hermes)
        self.assertFalse(self.local.with_user(self.ai_manager).can_start_hermes)
        with self.assertRaises(AccessError):
            self.local.with_user(self.ai_manager).action_start_hermes()
        internal(self.local).write({'state': 'ready', 'hermes_runtime': 'running'})
        self.assertFalse(self.local.can_start_hermes, 'Nothing to start while it runs')

    def test_start_on_this_server_runs_the_fixed_command_then_checks(self):
        internal(self.local).write({'state': 'blocked', 'hermes_runtime': 'stopped'})
        Engine = type(self.local)
        done = type('Done', (), {'returncode': 0, 'stdout': 'gateway started', 'stderr': ''})()
        with patch('odoo.addons.ai_agent.models.configuration.subprocess.run', return_value=done) as run, \
                patch.object(Engine, '_probe_runtime', return_value='running'), \
                patch.object(Engine, '_check_connection') as check:
            self.local.action_start_hermes()
        self.assertEqual(run.call_args.args[0], [sys.executable, str(ERP_HERMES_SCRIPT), 'start'])
        check.assert_called_once()
        failed = type('Failed', (), {'returncode': 1, 'stdout': '', 'stderr': 'Run "provision" first.'})()
        with patch('odoo.addons.ai_agent.models.configuration.subprocess.run', return_value=failed), \
                self.assertRaisesRegex(UserError, 'provision'):
            self.local.action_start_hermes()

    def test_start_on_another_machine_asks_its_hermes(self):
        internal(self.remote).write({'state': 'blocked', 'hermes_runtime': 'gateway_stopped'})
        answer = Answer()
        management, run_api = self._patched(answer)
        Engine = type(self.remote)
        with management, run_api, patch.object(Engine, '_check_connection') as check, \
                patch('odoo.addons.ai_agent.models.configuration.subprocess.run') as run:
            self.remote.action_start_hermes()
        self.assertIn(('POST', '/api/gateway/start'), answer.calls)
        run.assert_not_called()
        check.assert_called_once()
