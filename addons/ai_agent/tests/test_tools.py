import json
from unittest.mock import patch

from odoo import Command
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.addons.mail.tests.common import mail_new_test_user

from ..models.common import internal
from ..models.tools import TOOLS, key_hash


class ToolsCase(TransactionCase):
    """An HR agent on a synced department profile, an HR assistant user, and a person asking."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        company = [Command.set(cls.env.company.ids)]
        cls.person = mail_new_test_user(cls.env, login='tools_person', groups='ai_agent.group_user', company_ids=company)
        cls.hr = cls.env['hr.department'].create({'name': 'Human Resources'})
        cls.hr.action_create_ai_assistant()
        cls.assistant = cls.hr.ai_assistant_user_id
        # The person cannot see "restricted" contacts; the assistant can.
        cls.restricted_group = cls.env['res.groups'].create({'name': 'Tools test: no restricted contacts'})
        cls.person.write({'group_ids': [Command.link(cls.restricted_group.id)]})
        # Odoo 20 access rows: a row without a group restricts everyone; this one only narrows the person's view.
        cls.env['ir.access'].create({'name': 'Tools test restriction', 'model_id': cls.env.ref('base.model_res_partner').id,
                                     'operation': 'r',
                                     'domain': "[('ref', '!=', 'RESTRICTED')] if user.id == %d else []" % cls.person.id})
        cls.open_contact = cls.env['res.partner'].create({'name': 'Zephyr Open Ltd', 'email': 'open@zephyr.example',
                                                          'ref': 'OPEN'})
        cls.restricted_contact = cls.env['res.partner'].create({'name': 'Zephyr Restricted Ltd', 'ref': 'RESTRICTED',
                                                                'email': 'hidden@zephyr.example'})
        cls.engine = cls.env['ai.agent.engine'].create({'name': 'Test engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.profile = cls.env['ai.agent.profile'].create({'name': 'Human Resources', 'engine_id': cls.engine.id,
                                                          'department_id': cls.hr.id})
        internal(cls.profile.sudo()).write({'state': 'in_sync', 'mcp_token_hash': key_hash('profile-token')})
        cls.agent = cls.env['ai.agent'].create({
            'name': 'HR helper', 'engine_id': cls.engine.id, 'department_id': cls.hr.id, 'access_scope': 'company',
            'access_ids': [Command.create({'model_name': 'res.partner', 'field_names': 'name, email, ref',
                                           'limit': 10})]})
        cls.agent.action_activate()
        cls.agent_run = cls.env['ai.agent.run'].with_user(cls.person)._queue(cls.agent.with_user(cls.person),
                                                                       'Who is Zephyr?').sudo()
        internal(cls.agent_run).write({'state': 'running', 'profile_id': cls.profile.id,
                                 'tool_key_hash': key_hash('run-key-1')})

    def call(self, name, **arguments):
        text, is_error = self.env['ai.agent.tools']._call(self.profile, name, {'run_key': 'run-key-1', **arguments})
        return (text if is_error else json.loads(text)), is_error


@tagged('post_install', '-at_install')
class TestAgentTools(ToolsCase):

    def test_assistant_and_person_must_both_see_the_record(self):
        result, is_error = self.call('search_records', model='res.partner', text='Zephyr')
        self.assertFalse(is_error, result)
        names = [r['display_name'] for r in result['records']]
        self.assertIn('Zephyr Open Ltd', names)
        self.assertNotIn('Zephyr Restricted Ltd', names, 'The person asking may not see it')
        error, is_error = self.call('read_record', model='res.partner', id=self.restricted_contact.id)
        self.assertTrue(is_error)
        self.assertIn('No record', error)
        self.assertEqual(self.agent_run.agent_id.profile_id.assistant_user_id, self.assistant)

    def test_without_a_person_the_assistant_alone_decides(self):
        internal(self.agent_run).write({'user_id': False})
        result, _error = self.call('read_record', model='res.partner', id=self.restricted_contact.id)
        self.assertEqual(result['record']['ref'], 'RESTRICTED')

    def test_the_agent_scope_limits_models_and_fields(self):
        error, is_error = self.call('search_records', model='res.users', text='admin')
        self.assertTrue(is_error)
        self.assertIn('may not read res.users', error)
        result, _error = self.call('read_record', model='res.partner', id=self.open_contact.id,
                                   fields=['email', 'phone', 'comment'])
        self.assertEqual(set(result['record']) - {'id', 'display_name'}, {'email'})
        error, is_error = self.call('search_records', model='res.partner', filters=[['phone', '=', '1']])
        self.assertTrue(is_error, 'Filters only on fields in the scope')

    def test_the_run_key_must_belong_to_a_live_run_on_this_profile(self):
        other = self.env['ai.agent.profile'].create({'name': 'Finance', 'kind': 'company', 'engine_id': self.engine.id})
        _text, is_error = self.env['ai.agent.tools']._call(other, 'search_records',
                                                           {'run_key': 'run-key-1', 'model': 'res.partner'})
        self.assertTrue(is_error)
        _text, is_error = self.env['ai.agent.tools']._call(self.profile, 'search_records',
                                                           {'run_key': 'wrong', 'model': 'res.partner'})
        self.assertTrue(is_error)
        internal(self.agent_run).write({'state': 'completed'})
        error, is_error = self.call('search_records', model='res.partner')
        self.assertTrue(is_error)
        self.assertIn('not valid', error)

    def test_activities_messages_and_evidence(self):
        self.open_contact.message_post(body='Asked for a quote on Monday.', message_type='comment')
        self.open_contact.activity_schedule('mail.mail_activity_data_todo', summary='Call back Zephyr',
                                            user_id=self.env.uid)
        messages, _error = self.call('record_messages', model='res.partner', id=self.open_contact.id)
        self.assertIn('Asked for a quote on Monday.', [m['text'] for m in messages['messages']])
        activities, _error = self.call('record_activities', model='res.partner', id=self.open_contact.id)
        self.assertEqual([a['summary'] for a in activities['activities']], ['Call back Zephyr'])
        events = self.env['ai.agent.event'].sudo().search([('run_id', '=', self.agent_run.id), ('kind', '=', 'tool')])
        self.assertEqual(len(events), 2)

    def test_profile_runs_get_tools_and_a_masked_run_key_instead_of_pre_sent_data(self):
        payload, _hash = self.agent_run._prepare_payload('secret-run-key')
        self.assertIn('run_key="secret-run-key"', payload['instructions'])
        self.assertIn('res.partner', payload['instructions'])
        self.assertNotIn('Zephyr Open Ltd', payload['input'], 'No business data is pre-sent')
        legacy, _hash = self.agent_run._prepare_payload()
        self.assertIn('Zephyr', legacy['input'], 'Runs without a profile keep the pre-sent data')


@tagged('post_install', '-at_install')
class TestAgentMcpEndpoint(HttpCase):

    def _post(self, message, token='profile-token'):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return self.url_open('/ai_agent/mcp', data=json.dumps(message), headers=headers)

    def test_endpoint_needs_the_profile_token_and_speaks_mcp(self):
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        engine = self.env['ai.agent.engine'].create({'name': 'Endpoint engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        profile = self.env['ai.agent.profile'].create({'name': 'Endpoint', 'kind': 'company', 'engine_id': engine.id})
        internal(profile.sudo()).write({'state': 'in_sync', 'mcp_token_hash': key_hash('profile-token')})
        self.assertEqual(self._post({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}, token=None).status_code, 401)
        self.assertEqual(self._post({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}, token='wrong').status_code, 401)
        initialize = self._post({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}}}).json()
        self.assertEqual(initialize['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(self._post({'jsonrpc': '2.0', 'method': 'notifications/initialized'}).status_code, 202)
        tools = self._post({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}).json()['result']['tools']
        self.assertEqual([t['name'] for t in tools], [t['name'] for t in TOOLS])
        call = self._post({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                           'params': {'name': 'search_records', 'arguments': {'run_key': 'none', 'model': 'res.partner'}}})
        self.assertTrue(call.json()['result']['isError'])
        self.assertEqual(self.url_open('/ai_agent/mcp').status_code, 405)


@tagged('post_install', '-at_install')
class TestAgentProposals(ToolsCase):
    """ADR 0012 phase 4: prepare-only tools; a person approves before anything changes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = [Command.set(cls.env.company.ids)]
        cls.boss = mail_new_test_user(cls.env, login='tools_boss', company_ids=company,
                                      groups='base.group_user,approval_center.group_approval_center_approver')
        boss_employee = cls.env['hr.employee'].create({'name': 'Boss', 'user_id': cls.boss.id})
        cls.env['hr.employee'].create({'name': 'Person', 'user_id': cls.person.id, 'parent_id': boss_employee.id})
        contacts = Command.link(cls.env.ref('base.group_partner_manager').id)
        cls.person.write({'group_ids': [contacts]})
        cls.assistant.sudo().write({'group_ids': [contacts]})  # an administrator gives the assistant its role
        cls._set_propose(True)

    @classmethod
    def _set_propose(cls, value):
        # Fixture only: the scope of an active agent is otherwise changed by pausing it first.
        cls.env.cr.execute('UPDATE ai_agent_access SET can_propose = %s WHERE agent_id = %s', [value, cls.agent.id])
        cls.env.invalidate_all()
        internal(cls.agent.sudo()).write({'activation_hash': cls.agent.sudo()._configuration_hash()})

    def _approve(self, proposal):
        proposal.request_id.with_user(self.boss).action_approve()

    def test_a_change_waits_for_approval_then_the_assistant_applies_it(self):
        result, is_error = self.call('propose_change', model='res.partner', id=self.open_contact.id,
                                     values={'email': 'new@zephyr.example'}, reason='The customer wrote from it.')
        self.assertFalse(is_error, result)
        self.assertIn(self.boss.name, result['approvers'], "The asker's manager approves")
        proposal = self.env['ai.agent.proposal'].browse(result['proposal'])
        self.assertEqual(proposal.state, 'waiting')
        self.assertEqual(self.open_contact.email, 'open@zephyr.example', 'Nothing changes before approval')
        self.assertIn('new@zephyr.example', proposal.request_id.reason)
        self._approve(proposal)
        self.assertEqual(self.open_contact.email, 'new@zephyr.example')
        self.assertEqual(proposal.state, 'applied')
        self.assertEqual(self.open_contact.write_uid, self.assistant, 'The assistant makes the change')
        # Applied once only.
        with self.assertRaises(Exception):
            proposal.with_user(self.person).action_apply()

    def test_the_assistant_needs_the_right_too(self):
        self.assistant.sudo().write({'group_ids': [Command.unlink(self.env.ref('base.group_partner_manager').id)]})
        result, _error = self.call('propose_change', model='res.partner', id=self.open_contact.id,
                                   values={'email': 'blocked@zephyr.example'})
        proposal = self.env['ai.agent.proposal'].browse(result['proposal'])
        self._approve(proposal)
        self.assertEqual(proposal.state, 'failed')
        self.assertEqual(self.open_contact.email, 'open@zephyr.example')
        self.assertTrue(proposal.request_id.failure_reason)

    def test_refused_proposals_are_never_applied(self):
        result, _error = self.call('propose_change', model='res.partner', id=self.open_contact.id,
                                   values={'email': 'refused@zephyr.example'})
        proposal = self.env['ai.agent.proposal'].browse(result['proposal'])
        proposal.request_id.with_user(self.boss).action_refuse()
        self.assertEqual(proposal.state, 'refused')
        self.assertEqual(self.open_contact.email, 'open@zephyr.example')

    def test_the_person_must_still_be_allowed_when_it_is_approved(self):
        result, _error = self.call('propose_change', model='res.partner', id=self.open_contact.id,
                                   values={'email': 'late@zephyr.example'})
        proposal = self.env['ai.agent.proposal'].browse(result['proposal'])
        self.env['ir.access'].create({'name': 'Tools test: no partner writes for the person',
                                      'model_id': self.env.ref('base.model_res_partner').id, 'operation': 'u',
                                      'domain': "[(0, '=', 1)] if user.id == %d else []" % self.person.id})
        self._approve(proposal)
        self.assertEqual(self.open_contact.email, 'open@zephyr.example')
        self.assertEqual(proposal.state, 'failed')

    def test_notes_and_todos_and_the_propose_permission(self):
        note, _error = self.call('propose_note', model='res.partner', id=self.open_contact.id, text='Prefers e-mail.')
        todo, _error = self.call('propose_activity', model='res.partner', id=self.open_contact.id,
                                 summary='Send the quote', due_date='2026-12-01')
        for result in (note, todo):
            self._approve(self.env['ai.agent.proposal'].browse(result['proposal']))
        self.assertIn('Prefers e-mail.', self.open_contact.message_ids.mapped('body')[0])
        activity = self.open_contact.activity_ids.filtered(lambda a: a.summary == 'Send the quote')
        self.assertEqual(activity.user_id, self.person, 'The to-do is for the person who asked')
        self._set_propose(False)
        error, is_error = self.call('propose_note', model='res.partner', id=self.open_contact.id, text='No.')
        self.assertTrue(is_error)
        self.assertIn('may only read', error)
        error, is_error = self.call('propose_change', model='res.partner', id=self.open_contact.id,
                                    values={'phone': '1'})
        self.assertTrue(is_error)
