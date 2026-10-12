from unittest.mock import patch, MagicMock

from odoo import Command
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

    def test_explicit_audience(self):
        with self.assertRaises(AccessError):
            self.agent.with_user(self.other)._usable()
        self.agent.with_user(self.user)._usable()

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
             patch.object(type(engine), '_request', return_value={}):
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
