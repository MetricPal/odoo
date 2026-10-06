from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

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

    def _run(self):
        # Any direct transport call is a test failure; only queue creation is allowed.
        with patch.object(type(self.env['mail.mail']), 'send', side_effect=AssertionError('Unexpected send')):
            self.channel._collect_operations_alert()

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
