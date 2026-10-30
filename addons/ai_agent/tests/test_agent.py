from unittest.mock import patch, MagicMock

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.tools import BinaryBytes

from ..models.common import internal
from ..services import hermes


@tagged('post_install', '-at_install')
class TestAgent(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                                'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        cls.env_patch.start()
        cls.addClassCleanup(cls.env_patch.stop)
        cls.user = mail_new_test_user(cls.env, login='ai_staff', groups='ai_agent.group_user',
                                     company_ids=[Command.set(cls.env.company.ids)], notification_type='inbox')
        cls.other = mail_new_test_user(cls.env, login='ai_other', groups='ai_agent.group_user',
                                      company_ids=[Command.set(cls.env.company.ids)], notification_type='inbox')
        cls.engine = cls.env['ai.agent.engine'].create({'name': 'Test engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.agent = cls.env['ai.agent'].create({'name': 'Test assistant', 'engine_id': cls.engine.id,
                                               'user_ids': [Command.set(cls.user.ids)]})
        cls.agent.action_activate()

    def _queue(self, prompt='Summarize available knowledge'):
        return self.env['ai.agent.run'].with_user(self.user)._queue(self.agent.with_user(self.user), prompt)

    def test_demo_agent_is_usable_by_everyone_in_the_company(self):
        from odoo.tools import convert_file
        if not self.env.ref('base.user_demo', raise_if_not_found=False):  # databases without demo data
            demo = mail_new_test_user(self.env, login='ai_demo_user', groups='base.group_user')
            self.env['ir.model.data'].create({'module': 'base', 'name': 'user_demo', 'model': 'res.users',
                                              'res_id': demo.id})
        with patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443'}):
            convert_file(self.env, 'ai_agent', 'demo/ai_agent_demo.xml', {}, mode='init', noupdate=True)
        agent = self.env.ref('ai_agent.demo_agent_ops')
        self.assertTrue(self.env.ref('base.user_admin').has_group('ai_agent.group_user'))
        demo_user = self.env.ref('base.user_demo')
        self.assertIn(agent.id, [o['id'] for o in self.env['ai.agent'].with_user(demo_user)._chat_options()])
        self.assertEqual((agent.engine_id.state, agent.state), ('ready', 'active'))
        self.assertTrue(agent.engine_id.demo)
        self.assertIn(agent.id, [o['id'] for o in self.env['ai.agent'].with_user(self.other)._chat_options()])
        # Outside demo data files nobody can mark a connection as demo or ready.
        with self.assertRaises((AccessError, UserError)):
            self.env['ai.agent.engine'].create({'name': 'Not demo', 'connection_mode': 'local', 'state': 'ready'})
        with self.assertRaises(UserError):
            self.env['ai.agent.engine'].create({'name': 'Not demo', 'connection_mode': 'local', 'demo': True})
        # Changing it afterwards still needs a manager to review and activate it again.
        agent.action_pause()
        agent.write({'description': 'changed'})
        self.assertNotIn(agent.id, [o['id'] for o in self.env['ai.agent'].with_user(self.other)._chat_options()])

    def test_explicit_audience(self):
        with self.assertRaises(AccessError):
            self.agent.with_user(self.other)._usable()
        self.agent.with_user(self.user)._usable()

    def test_company_audience_is_dynamic(self):
        self.agent.action_pause()
        self.agent.write({'access_scope': 'company', 'user_ids': [Command.clear()]})
        self.agent.action_activate()
        self.agent.with_user(self.other)._usable()
        self.assertIn(self.agent, self.env['ai.agent'].with_user(self.other).search([]))
        self.other.active = False
        with self.assertRaises(AccessError):
            self.agent.with_user(self.other)._usable()

    def test_department_audience_tracks_membership(self):
        sales = self.env['hr.department'].create({'name': 'Sales', 'company_id': self.env.company.id})
        finance = self.env['hr.department'].create({'name': 'Finance', 'company_id': self.env.company.id})
        employee = self.env['hr.employee'].create({'name': 'Staff', 'user_id': self.other.id,
            'company_id': self.env.company.id, 'department_id': sales.id})
        self.agent.action_pause()
        self.agent.write({'access_scope': 'users', 'department_ids': [Command.set(sales.ids)]})
        self.agent.action_activate()
        self.agent.with_user(self.other)._usable()
        self.assertIn(self.agent, self.env['ai.agent'].with_user(self.other).search([]))
        self.agent.with_user(self.user)._usable()
        employee.department_id = finance
        self.assertNotIn(self.agent, self.env['ai.agent'].with_user(self.other).search([]))
        with self.assertRaises(AccessError):
            self.agent.with_user(self.other)._usable()
        employee.department_id = sales
        employee.active = False
        with self.assertRaises(AccessError):
            self.agent.with_user(self.other)._usable()

    def test_department_scope_requires_selection(self):
        self.agent.action_pause()
        self.agent.write({'access_scope': 'users', 'user_ids': [Command.clear()]})
        with self.assertRaises(UserError):
            self.agent.action_activate()

    def test_portal_denied_even_when_groups_forged(self):
        portal = mail_new_test_user(self.env, login='ai_portal', groups='base.group_portal', notification_type='email')
        self.agent.action_pause()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.agent.write({'user_ids': [Command.set(portal.ids)]})

    def test_selected_company_boundary(self):
        company = self.env['res.company'].create({'name': 'Other company'})
        with self.assertRaises(AccessError):
            self.agent.with_user(self.user).with_context(allowed_company_ids=[company.id])._usable()

    def test_configuration_cannot_bypass_activation(self):
        with self.assertRaises(AccessError):
            self.agent.write({'state': 'active'})
        with self.assertRaises(UserError):
            self.agent.write({'system_prompt': 'Different prompt'})
        with self.assertRaises(AccessError):
            self.agent.with_context(_ai_agent_token=True).write({'state': 'paused'})

    def test_privileged_create_cannot_forge_readiness(self):
        with self.assertRaises(AccessError):
            self.env['ai.agent'].create({'name': 'Forged', 'engine_id': self.engine.id, 'state': 'active'})
        with self.assertRaises(AccessError):
            self.env['ai.agent.skill'].create({'name': 'Forged', 'instructions': 'x', 'state': 'approved'})

    def test_employee_cannot_configure(self):
        with self.assertRaises(AccessError):
            self.agent.with_user(self.user).write({'description': 'Changed'})
        with self.assertRaises(AccessError):
            self.engine.with_user(self.user).action_check()

    def test_source_reader_scope(self):
        self.agent.action_pause()
        source = self.env['ai.agent.source'].create({'name': 'Private source', 'text': 'PRIVATE_REFERENCE',
                                                    'user_ids': [Command.set(self.other.ids)]})
        source.action_prepare()
        self.agent.write({'source_ids': [Command.set(source.ids)]})
        self.agent.action_activate()
        context = self.agent.with_user(self.user)._context_for('Private')
        self.assertEqual(context['sources'], [])
        with self.assertRaises(AccessError):
            source.with_user(self.user).read(['extracted_text'])

    def test_source_revision_invalidates_activation(self):
        self.agent.action_pause()
        source = self.env['ai.agent.source'].create({'name': 'Guide', 'text': 'Approved reference',
                                                    'user_ids': [Command.set(self.user.ids)]})
        source.action_prepare()
        self.agent.write({'source_ids': [Command.set(source.ids)]})
        self.agent.action_activate()
        source.write({'text': 'New content'})
        with self.assertRaises(UserError):
            self.agent.with_user(self.user)._usable()
        self.assertEqual(source.state, 'ready')
        self.assertEqual(source.extracted_text, 'New content')

    def test_skill_revision_requires_review(self):
        skill = self.env['ai.agent.skill'].create({'name': 'Summarize', 'instructions': 'Explain evidence.'})
        skill.action_approve()
        skill.write({'instructions': 'Different instructions'})
        self.assertEqual(skill.state, 'draft')
        self.assertEqual(skill.revision, 2)

    def test_file_preparation_and_inert_markup(self):
        source = self.env['ai.agent.source'].create({'name': 'Text', 'kind': 'file', 'filename': 'notes.txt',
            'file': BinaryBytes(b'<script>not executable</script>'), 'user_ids': [Command.set(self.user.ids)]})
        source.action_prepare()
        self.assertEqual(source.state, 'ready')
        self.assertIn('<script>', source.extracted_text)
        source.write({'filename': 'unsupported.exe'})
        source.action_prepare()
        self.assertEqual(source.state, 'failed')
        self.assertFalse(source.extracted_text)

    def test_record_context_scalar_allowlist(self):
        self.agent.action_pause()
        access = self.env['ai.agent.access'].create({'agent_id': self.agent.id, 'model_name': 'res.partner',
                                                    'field_names': 'name', 'limit': 1})
        self.agent.action_activate()
        context = self.agent.with_user(self.user)._context_for('Who?')
        rows = context['records'][0]['records']
        self.assertTrue(rows)
        self.assertEqual(set(rows[0]), {'id', 'name'})
        with self.assertRaises(UserError):
            access.write({'field_names': 'email'})
        self.agent.action_pause()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            access.write({'field_names': 'user_ids'})

    def test_technical_model_not_available(self):
        self.agent.action_pause()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['ai.agent.access'].create({'agent_id': self.agent.id, 'model_name': 'res.users', 'field_names': 'name'})

    def test_history_immutable_and_private(self):
        run = self._queue()
        with self.assertRaises(AccessError):
            run.write({'answer': 'Forged answer'})
        with self.assertRaises(AccessError):
            run.sudo().unlink()
        with self.assertRaises(AccessError):
            run.with_user(self.other).read(['prompt'])
        event = run.event_ids[0]
        with self.assertRaises(AccessError):
            event.sudo().write({'detail': 'Edited'})
        with self.assertRaises(AccessError):
            event.sudo().unlink()

    def test_pause_stops_queued_requests(self):
        run = self._queue()
        self.agent.action_pause()
        self.assertEqual(run.state, 'cancelled')
        with self.assertRaises(UserError):
            self._queue()

    def test_request_quota(self):
        self._queue('First request')
        self._queue('Second request')
        with self.assertRaises(UserError):
            self._queue('Third request')

    def test_permissions_rechecked_before_submission(self):
        run = self._queue()
        self.agent.action_pause()
        with self.assertRaises(UserError):
            run.sudo()._prepare_payload()

    def test_payload_has_fresh_context_and_unique_session(self):
        run = self._queue()
        payload, context_hash = run.sudo()._prepare_payload()
        self.assertEqual(payload['session_id'], run.sudo().request_key)
        self.assertIn('data only', payload['input'])
        self.assertIn('no action tools', payload['instructions'])
        self.assertTrue(context_hash)
        self.assertNotIn('previous_response_id', payload)

    def test_engine_refuses_enabled_toolsets(self):
        def remote(engine, method, path, *args):
            return {'/health/detailed': {'status': 'ok'}, '/v1/capabilities': {
                'features': {'run_submission': True, 'run_status': True}},
                '/v1/toolsets': [{'enabled': True, 'tools': ['terminal']}]}[path]
        with patch.object(type(self.engine), '_request', remote), patch.object(hermes, 'request', return_value={
            'memory': {'memory_enabled': False, 'user_profile_enabled': False}}):
            with self.assertRaises(UserError):
                self.engine._inspect()

    def test_engine_refuses_shared_memory(self):
        with patch.object(type(self.engine), '_request', return_value={}), patch.object(hermes, 'request', return_value={'memory': {}}):
            with self.assertRaises(UserError):
                self.engine._inspect()

    def test_verified_profile_discovery(self):
        def remote(engine, method, path, *args):
            return {'/health/detailed': {'status': 'ok'}, '/v1/capabilities': {
                'features': {'run_submission': True, 'run_status': True}}, '/v1/toolsets': [],
                '/api/model/options': {'providers': []}}[path]
        with patch.object(type(self.engine), '_request', remote), patch.object(hermes, 'request', return_value={
            'memory': {'memory_enabled': False, 'user_profile_enabled': False}}):
            self.engine.action_check()
        self.assertEqual(self.engine.state, 'ready')

    def test_poll_uses_served_model_and_usage(self):
        run = self._queue().sudo()
        internal(run).write({'remote_id': 'run_test', 'state': 'running'})
        with patch.object(type(self.engine), '_request', return_value={'status': 'completed', 'output': 'Answer',
             'usage': {'input_tokens': 12, 'output_tokens': 4}, 'runtime': {'provider': 'test', 'model': 'fallback'}}):
            run._poll()
        self.assertEqual(run.answer, 'Answer')
        self.assertEqual(run.runtime_model, 'fallback')
        self.assertEqual(run.input_tokens, 12)

    def test_unknown_remote_state_is_not_success(self):
        run = self._queue().sudo()
        internal(run).write({'remote_id': 'run_test', 'state': 'running'})
        with patch.object(type(self.engine), '_request', return_value={'status': 'surprise'}):
            with self.assertRaises(UserError):
                run._poll()
        self.assertNotEqual(run.state, 'completed')

    def test_transport_rejects_unapproved_origins(self):
        for url in ('http://hermes.example.com', 'https://evil.example.com',
                    'https://user:pass@hermes.example.com', 'https://hermes.example.com/path',
                    'https://hermes.example.com#fragment'):
            with self.assertRaises(UserError):
                hermes.target(url, resolve=False)

    def test_transport_pins_ip_and_disallows_redirects(self):
        pool = MagicMock()
        pool.request.return_value.status = 200
        pool.request.return_value.read.return_value = b'{"status":"ok"}'
        with patch.object(hermes.socket, 'getaddrinfo', return_value=[(None, None, None, None, ('10.0.0.5', 443))]), \
             patch.object(hermes.urllib3, 'HTTPSConnectionPool', return_value=pool) as connection:
            self.assertEqual(hermes.request(self.engine.url, self.engine.secret_reference, 'GET', '/health')['status'], 'ok')
        self.assertEqual(connection.call_args.args[0], '10.0.0.5')
        self.assertEqual(connection.call_args.kwargs['assert_hostname'], 'hermes.example.com')
        self.assertFalse(pool.request.call_args.kwargs['redirect'])
        self.assertFalse(pool.request.call_args.kwargs['retries'])

    def test_transport_sanitizes_uncertain_post(self):
        pool = MagicMock()
        pool.request.side_effect = OSError('SECRET_FROM_PROVIDER')
        with patch.object(hermes.socket, 'getaddrinfo', return_value=[(None, None, None, None, ('10.0.0.5', 443))]), \
             patch.object(hermes.urllib3, 'HTTPSConnectionPool', return_value=pool):
            with self.assertRaises(hermes.HermesUncertain) as error:
                hermes.request(self.engine.url, self.engine.secret_reference, 'POST', '/v1/runs', {})
        self.assertNotIn('SECRET_FROM_PROVIDER', str(error.exception))
        self.assertEqual(pool.request.call_count, 1)

    def test_worker_claims_once_and_reconciles(self):
        run = self._queue().sudo()
        with patch.object(type(self.engine), '_inspect', return_value=({}, [])), \
             patch.object(type(self.engine), '_request', return_value={'run_id': 'run_worker'}) as remote, \
             patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            self.env['ai.agent.run']._cron_process()
        self.assertEqual(run.state, 'running')
        self.assertEqual(remote.call_count, 1)
        self.assertTrue(run.request_payload)
        self.assertTrue(run.context_hash)
        internal(run).write({'next_poll_at': False})
        with patch.object(type(self.engine), '_request', return_value={'status': 'completed', 'output': 'Safe answer'}), \
             patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            self.env['ai.agent.run']._cron_process()
        self.assertEqual(run.state, 'completed')

    def test_worker_never_retries_claim_without_response(self):
        run = self._queue().sudo()
        internal(run).write({'state': 'submitting'})
        with patch.object(type(self.engine), '_request') as remote, \
             patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            self.env['ai.agent.run']._cron_process()
        remote.assert_not_called()
        self.assertEqual(run.state, 'uncertain')

    def test_worker_uncertain_post_keeps_admission_slot(self):
        run = self._queue().sudo()
        with patch.object(type(self.engine), '_inspect', return_value=({}, [])), \
             patch.object(type(self.engine), '_request', side_effect=hermes.HermesUncertain('synthetic secret')), \
             patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            self.env['ai.agent.run']._cron_process()
        self.assertEqual(run.state, 'uncertain')
        self.assertNotIn('synthetic secret', run.error_message)
        self.assertTrue(run.request_payload)

    def test_cancellation_claim_not_repeated(self):
        run = self._queue().sudo()
        internal(run).write({'state': 'stop_requested', 'remote_id': 'run_stop', 'stop_claimed': True})
        with patch.object(type(self.engine), '_request', return_value={'status': 'cancelled'}) as remote, \
             patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            self.env['ai.agent.run']._cron_process()
        self.assertEqual(run.state, 'cancelled')
        self.assertEqual(remote.call_count, 1)
        self.assertEqual(remote.call_args.args[0], 'GET')

    def test_health_refresh_does_not_revoke_activation(self):
        original_hash = self.agent._configuration_hash()
        internal(self.engine).write({'status_message': 'Fresh health check'})
        self.assertEqual(original_hash, self.agent._configuration_hash())
        self.agent.with_user(self.user)._usable()

    def test_employee_cannot_read_engine_credentials(self):
        with self.assertRaises(AccessError):
            self.engine.with_user(self.user).read(['secret_reference'])

    def test_context_respects_business_record_restrictions(self):
        secret = self.env['res.partner'].create({'name': 'DO_NOT_DISCLOSE'})
        visible = self.env['res.partner'].create({'name': 'Permitted partner'})
        self.env['ir.access'].create({'name': 'Synthetic requester restriction',
            'model_id': self.env['ir.model']._get('res.partner').id, 'operation': 'r',
            'domain': "[('id', '!=', %s)]" % secret.id})
        self.agent.action_pause()
        self.env['ai.agent.access'].create({'agent_id': self.agent.id, 'model_name': 'res.partner',
            'field_names': 'name', 'domain_json': '[["id", "in", [%s, %s]]]' % (secret.id, visible.id)})
        self.agent.action_activate()
        context = self.agent.with_user(self.user)._context_for('Show partners')
        self.assertEqual([r['id'] for r in context['records'][0]['records']], visible.ids)

    def test_readable_pdf_preparation(self):
        import io
        from PyPDF2 import PdfWriter
        from PyPDF2.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/F1'): writer._add_object(font)})})
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 12 Tf 20 100 Td (Verified PDF knowledge) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(content)
        buffer = io.BytesIO()
        writer.write(buffer)
        source = self.env['ai.agent.source'].create({'name': 'PDF guide', 'kind': 'file', 'filename': 'guide.pdf',
            'file': BinaryBytes(buffer.getvalue()), 'user_ids': [Command.set(self.user.ids)]})
        source.action_prepare()
        self.assertEqual(source.state, 'ready')
        self.assertIn('Verified PDF knowledge', source.extracted_text)

    def test_completed_output_not_published_after_stop(self):
        run = self._queue().sudo()
        internal(run).write({'remote_id': 'run_stop', 'state': 'stop_requested', 'stop_claimed': True})
        with patch.object(type(self.engine), '_request', return_value={'status': 'completed', 'output': 'Late answer'}):
            run._poll()
        self.assertEqual(run.state, 'cancelled')
        self.assertFalse(run.answer)

    def test_numeric_localhost_http_is_explicit_and_pinned(self):
        pool = MagicMock()
        pool.request.return_value.status = 200
        pool.request.return_value.read.return_value = b'{"status":"ok"}'
        with patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': '127.0.0.1:8643'}), \
             patch.object(hermes.socket, 'getaddrinfo', return_value=[(None, None, None, None, ('127.0.0.1', 8643))]), \
             patch.object(hermes.urllib3, 'HTTPConnectionPool', return_value=pool) as connection:
            self.assertEqual(hermes.request('http://127.0.0.1:8643', self.engine.secret_reference, 'GET', '/health')['status'], 'ok')
        self.assertEqual(connection.call_args.args[0], '127.0.0.1')
        self.assertFalse(pool.request.call_args.kwargs['redirect'])
        with patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'localhost:8643,10.0.0.5:8643'}):
            for url in ('http://localhost:8643', 'http://10.0.0.5:8643'):
                with self.assertRaises(UserError):
                    hermes.target(url, resolve=False)

    def test_localhost_http_rejects_non_loopback_resolution(self):
        with patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': '127.0.0.1:8643'}), \
             patch.object(hermes.socket, 'getaddrinfo', return_value=[(None, None, None, None, ('10.0.0.5', 8643))]):
            with self.assertRaises(UserError):
                hermes.request('http://127.0.0.1:8643', self.engine.secret_reference, 'GET', '/health')

    def test_actual_hermes_discovery_list_envelope(self):
        def remote(engine, method, path, *args):
            return {'/health/detailed': {'status': 'ok'}, '/v1/capabilities': {
                'features': {'run_submission': True, 'run_status': True}},
                '/v1/toolsets': {'object': 'list', 'platform': 'api_server',
                    'data': [{'name': 'terminal', 'enabled': False, 'tools': ['terminal']}]}}[path]
        with patch.object(type(self.engine), '_request', remote), patch.object(hermes, 'request', return_value={
            'memory': {'memory_enabled': False, 'user_profile_enabled': False}}):
            _, tools = self.engine._inspect()
        self.assertEqual(tools[0]['name'], 'terminal')

    def test_masked_keys_are_encrypted_and_never_read_back(self):
        key = 'synthetic-run-key-for-form-test'
        engine = self.env['ai.agent.engine'].create({'name': 'Remote connection',
            'url': 'https://hermes.example.com', 'api_key': key})
        self.assertFalse(engine.read(['api_key'])[0]['api_key'])
        self.assertFalse(engine.management_api_key)
        self.assertTrue(engine.api_key_saved)
        self.assertEqual(engine._credential('run'), key)
        self.assertEqual(engine._credential('management'), key)
        from ..services import secrets
        path = secrets._root(self.cr.dbname) / (engine.sudo().secret_reference + '.bin')
        self.assertNotIn(key.encode(), path.read_bytes())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_non_system_manager_can_save_key_without_reading_reference(self):
        manager_user = mail_new_test_user(self.env, login='ai_form_manager', groups='ai_agent.group_manager', notification_type='inbox')
        engine = self.env['ai.agent.engine'].with_user(manager_user).create({'name': 'Manager connection',
            'url': 'https://hermes.example.com', 'api_key': 'synthetic-manager-key'})
        self.assertTrue(engine.api_key_saved)
        with self.assertRaises(AccessError):
            engine.read(['secret_reference'])
        self.assertFalse(engine.read(['api_key'])[0]['api_key'])

    def test_replacing_key_requires_recheck_and_does_not_return_plaintext(self):
        self.engine.write({'api_key': 'synthetic-replacement'})
        self.assertEqual(self.engine.state, 'unchecked')
        self.assertFalse(self.engine.api_key)
        self.assertEqual(self.engine._credential('run'), 'synthetic-replacement')
        self.engine.write({'api_key': False, 'name': 'Renamed engine'})
        self.assertEqual(self.engine._credential('run'), 'synthetic-replacement')

    def test_credentials_bound_to_engine_origin(self):
        self.engine.write({'api_key': 'synthetic-bound-key'})
        with patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443,second.example.com:443'}):
            self.engine.write({'url': 'https://second.example.com'})
        with self.assertRaises(UserError):
            self.engine._credential('run')

    def test_local_connect_imports_without_key_fields(self):
        with patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': '127.0.0.1:8643,127.0.0.1:9120'}):
            engine = self.env['ai.agent.engine'].create({'name': 'Local Hermes', 'connection_mode': 'local'})
        with patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': '127.0.0.1:8643,127.0.0.1:9120'}), \
             patch('odoo.addons.ai_agent.services.secrets.local_keys', return_value={
                 'API_SERVER_KEY': 'synthetic-local-run', 'HERMES_DASHBOARD_SESSION_TOKEN': 'synthetic-local-management'}), \
             patch.object(type(engine), '_inspect', return_value=({}, [])), \
             patch.object(type(engine), '_request', return_value={'providers': []}):
            engine.action_check()
        self.assertEqual(engine.state, 'ready')
        self.assertEqual(engine._credential('run'), 'synthetic-local-run')
        self.assertEqual(engine._credential('management'), 'synthetic-local-management')

    def test_source_automatically_prepares_saved_content(self):
        source = self.env['ai.agent.source'].create({'name': 'Saved content', 'text': 'Automatic preparation'})
        self.assertEqual(source.state, 'ready')
        self.assertEqual(source.extracted_text, 'Automatic preparation')
        source.write({'text': 'Updated knowledge'})
        self.assertEqual(source.state, 'ready')
        self.assertEqual(source.extracted_text, 'Updated knowledge')

    def test_sources_follow_native_odoo_group_permissions(self):
        self.agent.action_pause()
        source = self.env['ai.agent.source'].create({'name': 'Company policy', 'text': 'Permitted through native Odoo security'})
        self.agent.write({'source_ids': [Command.set(source.ids)]})
        self.agent.action_activate()
        self.assertEqual(self.agent.with_user(self.user)._context_for('Policy')['sources'], [])
        self.env['ir.access'].create({'name': 'Read company policy', 'model_id': self.env['ir.model']._get('ai.agent.source').id,
            'group_id': self.env.ref('base.group_user').id, 'operation': 'r', 'domain': "[('id', '=', %s)]" % source.id})
        context = self.agent.with_user(self.user)._context_for('Policy')
        self.assertEqual(context['sources'][0]['name'], 'Company policy')
        self.assertFalse(source.user_ids)
        self.assertEqual(source.create_uid, self.env.user)

    def test_source_security_shortcut_is_system_only(self):
        source = self.env['ai.agent.source'].create({'name': 'Access source', 'text': 'Content', 'user_ids': [Command.set(self.user.ids)]})
        with self.assertRaises(AccessError):
            source.with_user(self.user).action_access_rights()
        action = source.action_access_rights()
        self.assertEqual(action['res_model'], 'ir.access')

    def test_management_checkbox_reuses_run_connection(self):
        with patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443,management.example.com:443'}):
            engine = self.env['ai.agent.engine'].create({'name': 'Shared connection',
                'url': 'https://hermes.example.com', 'management_url': 'https://management.example.com',
                'api_key': 'synthetic-run', 'management_api_key': 'synthetic-management'})
            self.assertEqual(engine._credential('management'), 'synthetic-management')
            revision = engine.revision
            engine.write({'management_same_connection': True})
            self.assertEqual(engine._credential('management'), 'synthetic-run')
            self.assertGreater(engine.revision, revision)
            self.assertEqual(engine.state, 'unchecked')
            engine.write({'management_same_connection': False})
            self.assertEqual(engine._credential('management'), 'synthetic-management')

    def test_connection_errors_explain_the_rejected_url(self):
        cases = [('', 'Enter the Hermes server URL'),
            ('hermes.example.com', 'complete Hermes server URL'),
            ('https://hermes.example.com:0', 'port between'),
            ('https://hermes.example.com:bad', 'port between'),
            ('https://user:password@hermes.example.com', 'Remove the username'),
            ('http://remote.example.com', 'Remote Hermes requires HTTPS'),
            ('https://www.google.com/search/example', 'base URL only'),
            ('https://hermes.example.com?query=test', 'base URL only'),
            ('https://hermes.example.com#fragment', 'base URL only'),
            ('https://hermes.example.com ', 'must not contain spaces'),
            ('https://unapproved.example.com', 'not approved')]
        with patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443'}):
            for url, message in cases:
                with self.subTest(url=url), self.assertRaisesRegex(UserError, message):
                    hermes.target(url, resolve=False)
            self.assertEqual(hermes.target('https://hermes.example.com/', resolve=False)[2], 443)

    def _picker_catalog(self, authenticated=True):
        return {'provider': 'nous', 'model': 'example/current', 'providers': [
            {'slug': 'nous', 'name': 'Nous Portal', 'authenticated': authenticated,
             'models': ['example/current', 'example/other'], 'api_key': 'must-never-leave-hermes'}]}

    def test_picker_catalog_drops_credentials_and_checks_types(self):
        with patch.object(type(self.engine), '_request', return_value=self._picker_catalog()):
            catalog = self.engine._model_catalog()
            self.assertNotIn('api_key', catalog['providers'][0])
            self.assertEqual(catalog['providers'][0]['models'], ['example/current', 'example/other'])
        with patch.object(type(self.engine), '_request', return_value={'providers': [{'slug': '../unsafe', 'models': []}]}):
            with self.assertRaises(UserError):
                self.engine._model_catalog()

    def test_picker_requires_fresh_authenticated_model(self):
        self.agent.action_pause()
        picker = self.env['ai.agent.model.picker'].create({'engine_id': self.engine.id,
            'agent_id': self.agent.id, 'provider': 'nous', 'model': 'example/other'})
        with patch.object(type(self.engine), '_request', return_value=self._picker_catalog(False)):
            with self.assertRaises(UserError):
                picker.action_apply()
        with patch.object(type(self.engine), '_request', return_value=self._picker_catalog()):
            picker.write({'model': 'invented/model'})
            with self.assertRaises(UserError):
                picker.action_apply()
            self.engine.set_model_enabled('nous', 'example/other', True)
            picker.write({'model': 'example/other'})
            picker.action_apply()
        self.assertEqual(self.agent.provider, 'nous')
        self.assertEqual(self.agent.model, 'example/other')
        picker.write({'use_default': True})
        picker.action_apply()
        self.assertFalse(self.agent.provider)
        self.assertFalse(self.agent.model)

    def test_picker_access_and_engine_binding(self):
        with self.assertRaises(AccessError):
            self.engine.with_user(self.user).action_models()
        self.agent.action_pause()
        picker = self.env['ai.agent.model.picker'].create({'engine_id': self.engine.id, 'agent_id': self.agent.id})
        self.assertEqual(picker.action_setup()['url'], 'https://hermes.example.com/models')
        with self.assertRaises(AccessError):
            picker.with_user(self.user).action_setup()
        self.agent.action_activate()
        picker.write({'use_default': True})
        with self.assertRaises(UserError):
            picker.action_apply()

    def test_engine_supports_multiple_enabled_models(self):
        with patch.object(type(self.engine), '_request', return_value=self._picker_catalog()):
            self.engine.set_model_enabled('nous', 'example/current', True)
            self.engine.set_model_enabled('nous', 'example/other', True)
            self.engine.set_model_enabled('nous', 'example/other', True)
            self.assertEqual(len(self.engine.enabled_model_ids), 2)
            self.assertEqual(self.engine.provider_catalog['providers'][0]['enabled_models'], ['example/current', 'example/other'])
            self.agent.action_pause()
            option = self.engine.enabled_model_ids.filtered(lambda m: m.model == 'example/other')
            self.agent.write({'engine_model_id': option.id})
            self.assertEqual(self.agent.model, 'example/other')
            self.agent.action_activate()
            option.action_disable()
            with self.assertRaises(UserError):
                self.agent.with_user(self.user)._usable()
            with self.assertRaises(AccessError):
                self.engine.with_user(self.user).set_model_enabled('nous', 'example/current', False)

    def test_enabled_models_cannot_bypass_authentication(self):
        with patch.object(type(self.engine), '_request', return_value=self._picker_catalog(False)):
            with self.assertRaises(UserError):
                self.engine.set_model_enabled('nous', 'example/current', True)
            with self.assertRaises(UserError):
                self.env['ai.agent.engine.model'].create({'engine_id': self.engine.id, 'provider': 'nous', 'model': 'example/current'})
        self.agent.action_pause()
        with self.assertRaises(UserError):
            self.agent.write({'provider': 'nous', 'model': 'example/unregistered'})

    def test_provider_authentication_is_rechecked_before_submission(self):
        with patch.object(type(self.engine), '_request', return_value=self._picker_catalog()):
            self.engine.set_model_enabled('nous', 'example/other', True)
        self.agent.action_pause()
        self.agent.write({'engine_model_id': self.engine.enabled_model_ids.id})
        self.agent.action_activate()
        run = self._queue()
        with patch.object(type(self.engine), '_inspect', return_value=({}, [])), \
             patch.object(type(self.engine), '_request', return_value=self._picker_catalog(False)) as request:
            with self.assertRaises(UserError):
                run._submit()
            self.assertTrue(all(call.args[0] == 'GET' for call in request.call_args_list))

    def test_local_setup_opens_profile_scoped_browser_dashboard(self):
        with patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': '127.0.0.1:8643,127.0.0.1:9120'}):
            engine = self.env['ai.agent.engine'].create({'name': 'Local setup', 'connection_mode': 'local'})
            action = engine.action_provider_setup()
            self.assertEqual(action['url'], 'http://127.0.0.1:9119/models?profile=odoo-internal')
            self.assertEqual(engine.management_url, 'http://127.0.0.1:9120')
            picker = self.env['ai.agent.model.picker'].create({'engine_id': engine.id})
            self.assertEqual(picker.action_setup(), action)
            with self.assertRaises(AccessError):
                engine.with_user(self.user).action_provider_setup()

    def test_connection_changes_clear_previous_verification(self):
        internal(self.engine).write({'state': 'ready', 'status_message': 'Connection verified.'})
        self.engine.write({'management_same_connection': True})
        self.assertEqual(self.engine.state, 'unchecked')
        self.assertFalse(self.engine.status_message)
        self.assertFalse(self.engine.checked_at)


@tagged('post_install', '-at_install')
class TestAgentReliability(TransactionCase):
    """Transient failures, configuration drift and per-user quota."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                                'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        cls.env_patch.start()
        cls.addClassCleanup(cls.env_patch.stop)
        cls.user = mail_new_test_user(cls.env, login='ai_rel_staff', groups='ai_agent.group_user',
                                     company_ids=[Command.set(cls.env.company.ids)], notification_type='inbox')
        cls.engine = cls.env['ai.agent.engine'].create({'name': 'Reliability engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.agent = cls.env['ai.agent'].create({'name': 'Reliability assistant', 'engine_id': cls.engine.id,
                                               'user_ids': [Command.set(cls.user.ids)]})
        cls.agent.action_activate()

    def _queue(self, prompt='Summarize available knowledge'):
        return self.env['ai.agent.run'].with_user(self.user)._queue(self.agent.with_user(self.user), prompt)

    def _running(self):
        run = self._queue().sudo()
        internal(run).write({'state': 'running', 'remote_id': 'run_reliability', 'next_poll_at': False,
                             'started_at': fields.Datetime.now()})
        return run

    def test_transient_poll_failure_retries_without_manager(self):
        run = self._running()
        with patch.object(type(self.engine), '_request', side_effect=hermes.HermesUnavailable('down')), \
             patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            self.env['ai.agent.run']._cron_process()
        self.assertEqual(run.state, 'running')
        self.assertEqual(run.poll_failures, 1)
        self.assertGreater(run.next_poll_at, fields.Datetime.now())
        internal(run).write({'next_poll_at': False})
        with patch.object(type(self.engine), '_request', return_value={'status': 'completed', 'output': 'Answer'}), \
             patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            self.env['ai.agent.run']._cron_process()
        self.assertEqual(run.state, 'completed')
        self.assertEqual(run.poll_failures, 0)

    def test_configuration_change_during_run_discards_answer(self):
        run = self._running()
        with patch.object(type(run), '_authorized_agent', side_effect=[run.agent_id, UserError('changed')]), \
             patch.object(type(self.engine), '_request', return_value={'status': 'completed', 'output': 'Late'}), \
             patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            self.env['ai.agent.run']._cron_process()
        self.assertEqual(run.state, 'discarded')
        self.assertFalse(run.answer)
        self.assertTrue(run.finished_at)

    def test_rejected_post_fails_without_reconciliation(self):
        run = self._queue().sudo()
        with patch.object(type(self.engine), '_inspect', return_value=({}, [])), \
             patch.object(type(self.engine), '_request', side_effect=hermes.HermesRejected('HTTP 401')), \
             patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            self.env['ai.agent.run']._cron_process()
        self.assertEqual(run.state, 'failed')

    def test_transport_classifies_post_status(self):
        for status, expected in ((401, hermes.HermesRejected), (422, hermes.HermesRejected),
                                 (429, hermes.HermesUncertain), (503, hermes.HermesUncertain)):
            pool = MagicMock()
            pool.request.return_value.status = status
            pool.request.return_value.read.return_value = b'{}'
            with patch.object(hermes.socket, 'getaddrinfo', return_value=[(None, None, None, None, ('10.0.0.5', 443))]), \
                 patch.object(hermes.urllib3, 'HTTPSConnectionPool', return_value=pool):
                with self.assertRaises(expected, msg=str(status)):
                    hermes.request(self.engine.url, self.engine.secret_reference, 'POST', '/v1/runs', {})
        pool = MagicMock()
        pool.request.side_effect = OSError('reset')
        with patch.object(hermes.socket, 'getaddrinfo', return_value=[(None, None, None, None, ('10.0.0.5', 443))]), \
             patch.object(hermes.urllib3, 'HTTPSConnectionPool', return_value=pool):
            with self.assertRaises(hermes.HermesUnavailable):
                hermes.request(self.engine.url, self.engine.secret_reference, 'GET', '/v1/runs/x')

    def test_per_user_daily_quota(self):
        self.agent.action_pause()
        self.agent.write({'max_requests_per_user_day': 1})
        self.agent.action_activate()
        self._queue('first question')
        with self.assertRaises(UserError):
            self._queue('second question')
        self.agent.action_pause()
        with self.assertRaises(ValidationError):
            self.agent.write({'max_requests_per_user_day': 5000})

    def test_explain_approval_request_prefills_question_only(self):
        # Only this test's agent is usable (demo databases also have the demo Ops Assistant).
        internal(self.env['ai.agent'].sudo().search([('id', '!=', self.agent.id), ('state', '=', 'active')])).write(
            {'state': 'paused'})
        self.user.write({'group_ids': [Command.link(self.env.ref('approval_center.group_approval_center_user').id)]})
        policy = self.env['approval.center.policy'].create({
            'name': 'Explain test', 'has_document': 'no', 'company_id': False,
            'approver_ids': [Command.create({'user_id': self.env.ref('base.user_admin').id})]})
        request = self.env['approval.center.request'].with_user(self.user).create({
            'name': 'Laptop purchase', 'policy_id': policy.id, 'reason': 'Replacement for broken device'})
        request.action_submit()
        runs = self.env['ai.agent.run'].sudo().search_count([])
        action = request.with_user(self.user).action_ai_explain()
        self.assertEqual(action['res_model'], 'ai.agent.ask')
        self.assertEqual(action['context']['default_agent_id'], self.agent.id)
        prompt = action['context']['default_prompt']
        self.assertIn('Laptop purchase', prompt)
        self.assertIn('Replacement for broken device', prompt)
        self.assertIn('Do not approve or refuse', prompt)
        self.assertEqual(self.env['ai.agent.run'].sudo().search_count([]), runs, 'Nothing is sent')


class TestAgentAttachments(TransactionCase):
    """Files attached to a question are read as text and travel with the run."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                                'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        cls.env_patch.start()
        cls.addClassCleanup(cls.env_patch.stop)
        cls.user = mail_new_test_user(cls.env, login='ai_attach_staff', groups='ai_agent.group_user',
                                     company_ids=[Command.set(cls.env.company.ids)], notification_type='inbox')
        cls.engine = cls.env['ai.agent.engine'].create({'name': 'Attachment engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.agent = cls.env['ai.agent'].create({'name': 'Attachment assistant', 'engine_id': cls.engine.id,
                                               'user_ids': [Command.set(cls.user.ids)]})
        cls.agent.action_activate()

    def _attachment(self, name, raw, user=None):
        return self.env['ir.attachment'].with_user(user or self.user).create({
            'name': name, 'raw': raw, 'res_model': False, 'res_id': 0})

    def test_attached_text_reaches_the_payload_and_follows_the_run(self):
        note = self._attachment('brief.md', b'# Brief\nCustomer wants delivery by Friday.')
        run = self.env['ai.agent.run'].with_user(self.user)._queue(
            self.agent.with_user(self.user), 'Summarize the brief', attachments=note)
        self.assertEqual(run.attachment_ids, note)
        self.assertEqual((note.sudo().res_model, note.sudo().res_id), ('ai.agent.run', run.id))
        payload, _digest = run.sudo()._prepare_payload()
        self.assertIn('Customer wants delivery by Friday.', payload['input'])
        self.assertIn('attached files', payload['instructions'])
        other = mail_new_test_user(self.env, login='ai_attach_other', groups='ai_agent.group_user',
                                   company_ids=[Command.set(self.env.company.ids)])
        with self.assertRaises(AccessError):
            note.with_user(other).check_access('read')

    def test_can_chat_filter_accepts_odoo20_operators(self):
        Agent = self.env['ai.agent'].with_user(self.user)
        self.assertIn(self.agent, Agent.search([('can_chat', 'in', [True])]))
        self.assertIn(self.agent, Agent.search([('can_chat', '=', True)]))
        self.assertNotIn(self.agent, Agent.search([('can_chat', 'not in', [True])]))

    def test_wizard_sends_attachments(self):
        note = self._attachment('numbers.csv', b'month,revenue\nJan,10\n')
        ask = self.env['ai.agent.ask'].with_user(self.user).create({
            'agent_id': self.agent.id, 'prompt': 'Explain the numbers',
            'attachment_ids': [Command.set(note.ids)]})
        ask.action_send()
        run = self.env['ai.agent.run'].sudo().search([('attachment_ids', 'in', note.ids)])
        self.assertEqual(len(run), 1)

    def test_unreadable_foreign_or_too_many_files_are_refused(self):
        with self.assertRaisesRegex(UserError, 'cannot be read'):
            self._queue_with(self._attachment('photo.png', b'\x89PNG\r\n'))
        admin_file = self._attachment('admin.txt', b'secret plan', user=self.env.ref('base.user_admin'))
        with self.assertRaises(AccessError):
            self._queue_with(admin_file)
        many = self.env['ir.attachment'].browse()
        for index in range(6):
            many |= self._attachment(f'note{index}.txt', b'hello')
        with self.assertRaisesRegex(UserError, 'at most 5'):
            self._queue_with(many)

    def _queue_with(self, attachments):
        return self.env['ai.agent.run'].with_user(self.user)._queue(
            self.agent.with_user(self.user), 'Read this', attachments=attachments.with_user(self.user))
