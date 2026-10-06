import smtplib
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, RedirectWarning, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from .smtp_sink import smtp_sink
from odoo.addons.omni_channel.models.command import internal


@tagged('post_install', '-at_install', 'omni_operations')
class TestOperationsAlerts(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(
            cls.env, login='alerts_admin', email='admin@example.com',
            groups='base.group_system,omni_channel.group_omni_manager',
        )
        cls.operator = new_test_user(
            cls.env, login='alerts_operator', email='operator@example.com',
            groups='omni_channel.group_omni_user',
        )
        cls.manager = new_test_user(
            cls.env, login='alerts_manager', email='manager@example.com',
            groups='omni_channel.group_omni_manager',
        )
        cls.purpose = cls.env['omni.purpose'].create({
            'name': 'Alerts team', 'code': 'alerts_test',
            'user_ids': [fields.Command.set((cls.admin | cls.operator | cls.manager).ids)],
        })
        cls.channel = cls.env['omni.channel'].create({
            'name': 'Alerts test', 'purpose_id': cls.purpose.id,
            'channel_type_id': cls.env.ref('omni_channel.channel_type_telegram').id,
            'alert_user_ids': [fields.Command.set(cls.operator.ids)],
        })

    def _enable(self):
        self.channel.with_user(self.admin).action_enable_alerts()

    def test_operator_assignments_are_admin_only_and_audited(self):
        channel = self.channel.with_user(self.admin)
        recipients = channel.alert_user_ids
        channel.write({'primary_operator_id': self.operator.id, 'backup_operator_id': self.manager.id})
        self.assertEqual(channel.primary_operator_id, self.operator)
        self.assertEqual(channel.backup_operator_id, self.manager)
        self.assertEqual(channel.alert_user_ids, recipients)
        self.assertFalse(channel.alerts_enabled)
        self.assertFalse(channel.dispatch_enabled)
        audit = self.env['omni.audit.event'].search([
            ('resource', '=', f'omni.channel,{channel.id}'), ('event', '=', 'operators_assigned'),
        ], order='id desc', limit=1)
        self.assertEqual(audit.actor_id, self.admin)
        self.assertIn(str(self.operator.id), audit.detail)
        for user in (self.manager, self.operator):
            for field in ('primary_operator_id', 'backup_operator_id'):
                with self.subTest(user=user.login, field=field):
                    with self.assertRaises(AccessError), self.cr.savepoint():
                        channel.with_user(user).write({field: False})
        channel.write({'primary_operator_id': False, 'backup_operator_id': False})
        self.assertFalse(channel.primary_operator_id | channel.backup_operator_id)

    def test_operator_validation_and_scope_changes(self):
        channel = self.channel.with_user(self.admin)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            channel.write({'primary_operator_id': self.operator.id, 'backup_operator_id': self.operator.id})
        outsider = new_test_user(self.env, login='operator_outsider', groups='omni_channel.group_omni_user')
        for user in (outsider, self.env.ref('base.public_user')):
            with self.assertRaises(RedirectWarning), self.cr.savepoint():
                channel.write({'primary_operator_id': user.id})
        with self.assertRaises(RedirectWarning), self.cr.savepoint():
            self.operator.active = False
            channel.write({'primary_operator_id': self.operator.id})
        with self.assertRaises(RedirectWarning), self.cr.savepoint():
            self.operator.group_ids = [fields.Command.clear()]
            channel.write({'primary_operator_id': self.operator.id})
        channel.write({'primary_operator_id': self.operator.id})
        other_purpose = self.env['omni.purpose'].create({
            'name': 'Other operators', 'code': 'other_operators',
            'user_ids': [fields.Command.set(self.admin.ids)],
        })
        with self.assertRaises(RedirectWarning), self.cr.savepoint():
            channel.write({'purpose_id': other_purpose.id})
        other_company = self.env['res.company'].create({'name': 'Other operators company'})
        with self.assertRaises(RedirectWarning), self.cr.savepoint():
            channel.sudo().write({'company_id': other_company.id})

    def test_operator_errors_link_to_exact_record(self):
        outsider = new_test_user(self.env, login='operator_fix', groups='omni_channel.group_omni_user')
        with self.assertRaises(RedirectWarning) as caught, self.cr.savepoint():
            self.channel.with_user(self.admin).write({'primary_operator_id': outsider.id})
        message, action, button, _context = caught.exception.args
        self.assertIn(self.purpose.name, message)
        self.assertIn('Authorized team', message)
        self.assertEqual((action['res_model'], action['res_id']), ('omni.purpose', self.purpose.id))
        self.assertEqual(action['target'], 'new')
        self.assertEqual(button, 'Open communication team')
        with self.assertRaises(RedirectWarning) as caught, self.cr.savepoint():
            outsider.group_ids = [fields.Command.set(self.env.ref('base.group_user').ids)]
            self.channel.with_user(self.admin).write({'primary_operator_id': outsider.id})
        message, action, button, _context = caught.exception.args
        self.assertIn('Omni-Channel to Operator or Administrator', message)
        self.assertEqual((action['res_model'], action['res_id']), ('res.users', outsider.id))
        self.assertEqual(button, 'Open user settings')

    def test_grouped_navigation_preserves_actions(self):
        root = self.env.ref('omni_channel.menu_omni_root')
        self.assertEqual(root.child_id.sorted('sequence').mapped('name'),
                         ['Inbox', 'Messages', 'Channels', 'Monitoring', 'Configuration'])
        for name in ('menu_channels', 'menu_senders', 'menu_endpoints'):
            self.assertEqual(self.env.ref(f'omni_channel.{name}').parent_id,
                             self.env.ref('omni_channel.menu_channel_setup'))
        for name in ('menu_attempts', 'menu_events', 'menu_blocks', 'menu_audit'):
            self.assertEqual(self.env.ref(f'omni_channel.{name}').parent_id,
                             self.env.ref('omni_channel.menu_monitoring'))

    def test_operator_create_copy_and_other_provider(self):
        values = {
            'name': 'Slack operators', 'purpose_id': self.purpose.id,
            'channel_type_id': self.env.ref('omni_channel.channel_type_slack').id,
            'primary_operator_id': self.operator.id, 'backup_operator_id': self.manager.id,
        }
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['omni.channel'].with_user(self.manager).create(values)
        channel = self.env['omni.channel'].with_user(self.admin).create(values)
        self.assertEqual(channel.primary_operator_id, self.operator)
        copied = channel.copy({'channel_type_id': self.env.ref('omni_channel.channel_type_discord').id})
        self.assertFalse(copied.primary_operator_id | copied.backup_operator_id)
        self.assertFalse(copied.alerts_enabled)

    def _run(self):
        # Any direct transport call is a test failure; only queue creation is allowed.
        with patch.object(type(self.env['mail.mail']), 'send', side_effect=AssertionError('Unexpected send')):
            self.channel._collect_operations_alert()

    @contextmanager
    def _local_mail_transport(self, *, reject=False):
        # Only disposable fixture servers are modified, within test rollback.
        servers = self.env['ir.mail_server']
        servers.search([]).write({'active': False})
        with smtp_sink(reject=reject) as sink:
            host, port = sink.server_address
            servers.create({
                'name': 'Loopback alert test', 'smtp_host': host, 'smtp_port': port,
                'smtp_encryption': 'none', 'smtp_user': False, 'smtp_pass': False,
                'owner_user_id': False, 'from_filter': self.admin.email, 'sequence': 1,
            })
            original_smtp = smtplib.SMTP

            def loopback_only(host, port, *args, **kwargs):
                self.assertEqual((host, port), sink.server_address, 'Unexpected SMTP destination')
                kwargs['timeout'] = 3
                return original_smtp(host, port, *args, **kwargs)

            # Native Odoo suppresses sends in tests. Permit only this strictly
            # bounded loopback connection; SMTP_SSL must never be attempted.
            with patch.object(type(servers), '_disable_send', return_value=False), \
                    patch.object(smtplib, 'SMTP', side_effect=loopback_only), \
                    patch.object(smtplib, 'SMTP_SSL', side_effect=AssertionError('Unexpected TLS transport')):
                yield sink

    def test_native_smtp_delivery_and_recovery(self):
        self._enable()
        internal(self.channel).write({'failure_count': 5})
        self._run()
        mail = self.channel.alerts_last_mail_id
        with self._local_mail_transport() as sink:
            mail.send(raise_exception=True)
            self.assertEqual(mail.state, 'sent')
            self.assertEqual(self.channel.alerts_mail_state, 'sent')
            self.assertEqual(len(sink.messages), 1)
            parsed = BytesParser(policy=policy.default).parsebytes(sink.messages[0])
            self.assertIn(self.operator.email, parsed['To'])
            self.assertIn('critical', parsed['Subject'])
            self.assertIn('open_circuit_breakers', parsed.get_body(preferencelist=('html',)).get_content())
            self.assertEqual(sink.recipients, [f'rcpt TO:<{self.operator.email}>'])
            self._run()
            self.assertEqual(self.channel.alerts_last_mail_id, mail)
            self.assertEqual(len(sink.messages), 1)
            internal(self.channel).write({'failure_count': 0})
            self._run()
            recovery = self.channel.alerts_last_mail_id
            recovery.send(raise_exception=True)
            self.assertEqual(recovery.state, 'sent')
            self.assertEqual(len(sink.messages), 2)
            parsed = BytesParser(policy=policy.default).parsebytes(sink.messages[1])
            self.assertIn('ok', parsed['Subject'])

    def test_native_smtp_rejection_is_visible_without_duplicate(self):
        self._enable()
        internal(self.channel).write({'failure_count': 5})
        self._run()
        mail = self.channel.alerts_last_mail_id
        with self._local_mail_transport(reject=True) as sink:
            mail.send()
            self.assertEqual(mail.state, 'exception')
            self.assertEqual(self.channel.alerts_mail_state, 'exception')
            self.assertTrue(mail.failure_reason)
            self.assertFalse(sink.messages)
            self._run()
            self.assertEqual(self.channel.alerts_last_mail_id, mail)
            self.assertEqual(len(sink.recipients), 1)

    def test_disabled_defaults_and_guarded_activation(self):
        self.assertFalse(self.channel.alerts_enabled)
        self.assertFalse(self.env.ref('omni_channel.cron_operations_alerts').active)
        self._run()
        self.assertFalse(self.channel.alerts_last_mail_id)
        for user in (self.manager, self.operator, self.env.ref('base.public_user')):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError), self.cr.savepoint():
                    self.channel.with_user(user).action_enable_alerts()
                with self.assertRaises(AccessError), self.cr.savepoint():
                    self.channel.with_user(user).write({'alerts_enabled': True})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.channel.with_user(self.admin).write({'alerts_enabled': True})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['omni.channel'].with_context(default_alerts_enabled=True).create({
                'name': 'Bypass', 'purpose_id': self.purpose.id,
                'channel_type_id': self.env.ref('omni_channel.channel_type_slack').id,
            })
        self._enable()
        self.assertTrue(self.channel.alerts_enabled)
        self.assertTrue(self.env.ref('omni_channel.cron_operations_alerts').active)
        self.assertEqual(self.channel.alerts_authorized_by, self.admin)
        self.assertFalse(self.channel.dispatch_enabled)
        audit = self.env['omni.audit.event'].search([
            ('resource', '=', f'omni.channel,{self.channel.id}'), ('event', '=', 'alerts_enabled'),
        ], limit=1)
        self.assertEqual(audit.actor_id, self.admin)
        self.assertIn('policy SHA256', audit.detail)

    def test_changes_deduplicate_and_recover(self):
        self._enable()
        self._run()
        self.assertFalse(self.channel.alerts_last_mail_id)
        internal(self.channel).write({'failure_count': 5})
        self._run()
        mail = self.channel.alerts_last_mail_id
        self.assertEqual(mail.state, 'outgoing')
        self.assertEqual(mail.email_to, self.operator.email)
        self.assertFalse(mail.mail_server_id)  # Native routing selects existing server.
        self.assertIn('critical', mail.subject)
        self._run()
        self.assertEqual(self.channel.alerts_last_mail_id, mail)
        mail.write({'state': 'exception'})
        self._run()
        self.assertEqual(self.channel.alerts_mail_state, 'exception')
        self.assertEqual(self.channel.alerts_last_mail_id, mail)
        internal(self.channel).write({'failure_count': 0})
        self._run()
        recovery = self.channel.alerts_last_mail_id
        self.assertNotEqual(mail, recovery)
        self.assertIn('ok', recovery.subject)
        self._run()
        self.assertEqual(self.channel.alerts_last_mail_id, recovery)

    def test_alert_contains_counts_not_message_content(self):
        internal(self.env['omni.command']).create({
            'name': 'Sensitive command', 'channel_id': self.channel.id,
            'recipient': '123456789', 'body': 'Private customer message',
            'reason': 'Private reason', 'state': 'unknown',
        })
        self._enable()
        self._run()
        mail = self.channel.alerts_last_mail_id
        self.assertIn('unknown_outcomes', mail.body_html)
        for value in ['Private customer message', 'Private reason', '123456789']:
            self.assertNotIn(value, mail.body_html)
        self.assertEqual(self.channel.alerts_snapshot['counts']['unknown_outcomes'], 1)

    def test_recipient_edit_requires_pause_and_current_access(self):
        self._enable()
        with self.assertRaises(UserError), self.cr.savepoint():
            self.channel.with_user(self.admin).write({'alert_user_ids': [fields.Command.clear()]})
        self.operator.email = 'changed@example.com'
        internal(self.channel).write({'failure_count': 5})
        self._run()
        self.assertFalse(self.channel.alerts_enabled)
        self.assertFalse(self.channel.alerts_last_mail_id)
        self.operator.email = 'operator@example.com'
        self._enable()
        self.purpose.user_ids -= self.operator
        self._run()
        self.assertFalse(self.channel.alerts_enabled)

    def test_revoked_admin_and_pause_block_queueing(self):
        self._enable()
        self.channel.with_user(self.admin).action_pause_alerts()
        internal(self.channel).write({'failure_count': 5})
        self._run()
        self.assertFalse(self.channel.alerts_last_mail_id)
        self._enable()
        self.purpose.user_ids -= self.admin
        self._run()
        self.assertFalse(self.channel.alerts_enabled)
        self.assertFalse(self.channel.alerts_last_mail_id)

    def test_recipient_scope_and_snapshot_isolation(self):
        outsider = new_test_user(self.env, login='alerts_outsider', email='outsider@example.com', groups='omni_channel.group_omni_user')
        self.channel.alert_user_ids = outsider
        with self.assertRaises(UserError), self.cr.savepoint():
            self._enable()
        other_company = self.env['res.company'].create({'name': 'Other alert company'})
        other = self.env['omni.channel'].create({
            'name': 'Private channel', 'purpose_id': self.purpose.id,
            'company_id': other_company.id,
            'channel_type_id': self.env.ref('omni_channel.channel_type_telegram').id,
        })
        internal(other).write({'failure_count': 5})
        self.assertEqual(self.channel._operations_snapshot()['severity'], 'ok')
        self.assertEqual(other._operations_snapshot()['severity'], 'critical')
        other.alert_user_ids = self.operator
        with self.assertRaises(UserError), self.cr.savepoint():
            other._recipient_addresses()

    def test_restore_neutralizes_alerts(self):
        self._enable()
        from odoo.modules.neutralize import neutralize_database  # noqa: PLC0415
        self.env.flush_all()
        neutralize_database(self.env.cr)
        self.env.invalidate_all()
        self.assertFalse(self.channel.alerts_enabled)
        self.assertFalse(self.env.ref('omni_channel.cron_operations_alerts').active)


@tagged('post_install', '-at_install', 'omni_operations')
class TestOperationsAlertsUI(HttpCase):
    def test_operator_error_opens_team_settings(self):
        admin = new_test_user(
            self.env, login='operator_fix_admin',
            groups='base.group_system,omni_channel.group_omni_manager',
        )
        new_test_user(self.env, login='operator_fix_ui', name='Operator Needs Team',
                      groups='omni_channel.group_omni_user')
        purpose = self.env['omni.purpose'].create({
            'name': 'Exact operator team', 'code': 'operator_fix_ui',
            'user_ids': [fields.Command.set(admin.ids)],
        })
        channel = self.env['omni.channel'].create({
            'name': 'Operator fix UI', 'purpose_id': purpose.id,
            'channel_type_id': self.env.ref('omni_channel.channel_type_telegram').id,
        })
        self.browser_js(
            f'/odoo/action-omni_channel.action_channels/{channel.id}',
            """
            (async () => {
                async function waitFor(find) {
                    for (let i = 0; i < 100; i++) {
                        const el = find();
                        if (el) return el;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Missing expected operator correction UI');
                }
                (await waitFor(() => [...document.querySelectorAll('.o_notebook .nav-link')]
                    .find(el => el.textContent.includes('Operations alerts')))).click();
                const input = await waitFor(() => document.querySelector('[name="primary_operator_id"] input'));
                input.value = 'Operator Needs Team';
                input.dispatchEvent(new Event('input', {bubbles: true}));
                (await waitFor(() => [...document.querySelectorAll('.o-autocomplete--dropdown-item')]
                    .find(el => el.textContent.includes('Operator Needs Team')))).click();
                (await waitFor(() => document.querySelector('.o_form_button_save'))).click();
                const error = await waitFor(() => document.querySelector('.o_error_dialog'));
                if (!error.textContent.includes('Exact operator team') || !error.textContent.includes('Authorized team')) {
                    throw new Error('Missing precise correction instruction');
                }
                [...error.querySelectorAll('button')].find(el => el.textContent.includes('Open communication team')).click();
                const team = await waitFor(() => document.querySelector('.modal [name="user_ids"]'));
                const name = team.closest('.modal').querySelector('[name="name"] input');
                if (!name || name.value !== 'Exact operator team') throw new Error('Wrong team opened');
                team.closest('.modal').querySelector('.modal-header .btn-close').click();
                await waitFor(() => !document.querySelector('.modal'));
                (await waitFor(() => document.querySelector('.o_form_button_cancel'))).click();
                await waitFor(() => document.querySelector('.o_form_status_indicator_buttons.invisible'));
                console.log('test successful');
            })().catch(error => console.error(error));
            """, login=admin.login,
        )
        self.assertFalse(channel.primary_operator_id)

    def test_activation_requires_visible_confirmation(self):
        admin = new_test_user(
            self.env, login='alerts_ui', email='admin@example.com',
            groups='base.group_system,omni_channel.group_omni_manager',
        )
        purpose = self.env['omni.purpose'].create({
            'name': 'UI alert team', 'code': 'alerts_ui', 'user_ids': [fields.Command.set(admin.ids)],
        })
        channel = self.env['omni.channel'].create({
            'name': 'UI alerts', 'purpose_id': purpose.id,
            'channel_type_id': self.env.ref('omni_channel.channel_type_telegram').id,
        })
        self.browser_js(
            f'/odoo/action-omni_channel.action_channels/{channel.id}',
            """
            (async () => {
                async function waitFor(selector) {
                    for (let i = 0; i < 100; i++) {
                        const el = document.querySelector(selector);
                        if (el) return el;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Missing element: ' + selector);
                }
                await waitFor('.o_notebook .nav-link');
                const tab = [...document.querySelectorAll('.o_notebook .nav-link')]
                    .find(el => el.textContent.includes('Operations alerts'));
                if (!tab) throw new Error('Missing operations tab');
                tab.click();
                await waitFor('.o_field_widget[name="primary_operator_id"]');
                await waitFor('.o_field_widget[name="backup_operator_id"]');
                (await waitFor('button[name="action_enable_alerts"]')).click();
                const modal = await waitFor('.modal');
                if (!modal.textContent.includes('monitoring every minute') ||
                    !modal.textContent.includes('existing Odoo mail queue')) {
                    throw new Error('Missing email authorization explanation');
                }
                console.log('test successful');
            })().catch(error => console.error(error));
            """,
            login='alerts_ui',
        )
        self.assertFalse(channel.alerts_enabled)
