from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tests.common import ChromeBrowser

from odoo.addons.omni_channel.models.command import internal


@tagged('post_install', '-at_install')
class TestOmniUI(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login='omni_ui', groups='omni_channel.group_omni_manager',
        )
        cls.operator = new_test_user(
            cls.env, login='omni_ui_operator', groups='omni_channel.group_omni_user',
        )
        purpose = cls.env['omni.purpose'].create(
            {
                'name': 'Customer care',
                'code': 'ui_test',
                'user_ids': [fields.Command.link(cls.manager.id)],
            },
        )
        channel_type = cls.env.ref('omni_channel.channel_type_telegram')
        cls.channel = cls.env['omni.channel'].create(
            {
                'name': 'Customer care / Telegram',
                'purpose_id': purpose.id,
                'channel_type_id': channel_type.id,
            },
        )
        account = cls.env['omni.account'].create(
            {
                'name': 'Care bot',
                'purpose_id': purpose.id,
                'channel_type_id': channel_type.id,
                'namespace': 'care-bot',
                'external_account_key': 'care-bot',
            },
        )
        cls.env['omni.outbound.sender'].create(
            {
                'name': 'Care bot',
                'channel_id': cls.channel.id,
                'account_id': account.id,
                'external_key': 'care-bot',
            },
        )

    def test_operator_entry_opens_inbox_with_empty_state_guidance(self):
        self.browser_js(
            '/odoo/action-omni_channel.action_workspace',
            """
            (async () => {
                for (let i = 0; i < 100; i++) {
                    if (document.body.textContent.includes('Your conversations will appear here')) break;
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                if (!document.body.textContent.includes('Your conversations will appear here')) throw new Error('Missing operator onboarding');
                if (document.querySelector('button[name="action_add_channel"]')) throw new Error('Operator landed in setup');
                console.log('test successful');
            })().catch(error => console.error(error));
            """,
            ready='odoo.isReady === true', login='omni_ui_operator', timeout=60,
        )

    def test_recipient_authorization_guidance_and_confirmation(self):
        consent = self.env['omni.consent'].with_user(self.manager).create({
            'channel_id': self.channel.id,
            'namespace': 'care-bot',
            'recipient': '123456789',
            'evidence': 'Customer requested support replies in this conversation.',
        })
        self.browser_js(
            f'/odoo/action-omni_channel.action_consent/{consent.id}',
            """
            (async () => {
                async function waitFor(check) {
                    for (let i = 0; i < 100; i++) {
                        if (check()) return;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Authorization form did not reach the expected state');
                }
                await waitFor(() => document.querySelector('.o_omni_recipient_guidance'));
                const text = document.querySelector('.o_form_view').textContent;
                for (const hint of ['sends no message', 'numeric chat ID', 'default expiry is 30 days']) {
                    if (!text.includes(hint)) throw new Error('Missing guidance: ' + hint);
                }
                const recipient = document.querySelector('[name="recipient"] input');
                if (!recipient?.placeholder.includes('Telegram chat ID')) throw new Error('Missing destination example');
                document.querySelector('button[name="action_confirm"]').click();
                await waitFor(() => document.querySelector('.modal'));
                if (!document.querySelector('.modal').textContent.includes('until the stated expiry')) {
                    throw new Error('Missing confirmation impact');
                }
                document.querySelector('.modal .btn-primary').click();
                await waitFor(() => document.querySelector('button[name="action_revoke"]'));
                if (!document.querySelector('.o_form_view').textContent.includes('Confirmed evidence cannot be edited')) {
                    throw new Error('Missing renewal guidance');
                }
                console.log('test successful');
            })().catch(error => console.error(error));
            """,
            ready='odoo.isReady === true', login='omni_ui', timeout=60,
        )
        consent.invalidate_recordset()
        self.assertEqual(consent.state, 'confirmed')
        self.assertFalse(self.env['omni.command'].search_count([
            ('channel_id', '=', self.channel.id),
        ]))

    def test_channel_sender_radio_selection_renders(self):
        original_console = ChromeBrowser._handle_console

        def capture(browser, type, args=None, **kwargs):
            if args and args[0].get('value') in ('omni_channels', 'omni_selection'):
                browser.take_screenshot(prefix=args[0]['value'] + '_')
            return original_console(browser, type, args=args, **kwargs)

        with patch.object(ChromeBrowser, '_handle_console', capture):
            self.browser_js(
                f'/odoo/action-omni_channel.action_channels/{self.channel.id}',
                """
                (async () => {
                async function waitFor(selector) {
                    for (let i = 0; i < 100; i++) {
                        const el = document.querySelector(selector);
                        if (el) return el;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Missing UI element: ' + selector);
                }
                (await waitFor('button[name="action_select_sender"]')).click();
                await waitFor('.modal input[type="radio"]');
                const modal = document.querySelector('.modal');
                if (!modal.textContent.includes('Check & Activate')) throw new Error('Missing confirmation action');
                if (!modal.textContent.includes('Failed checks preserve')) throw new Error('Missing impact explanation');
                console.log('omni_selection');
                await new Promise(resolve => setTimeout(resolve, 300));
                console.log('test successful');
                })().catch(error => console.error(error));
            """,
                ready='odoo.isReady === true',
                login='omni_ui',
                timeout=60,
            )

    def test_unknown_outcome_opens_evidence_reconciliation(self):
        command = internal(self.env['omni.command'].with_user(self.manager)).create({
            'name': 'Verify customer reply', 'channel_id': self.channel.id,
            'recipient': '12345', 'body': 'Thank you for contacting us.',
            'reason': 'Reply to the customer', 'state': 'unknown',
            'held_reason': 'Sending again could duplicate an accepted message.',
        })
        self.browser_js(
            f'/odoo/action-omni_channel.action_commands/{command.id}',
            """
            (async () => {
                async function waitFor(selector) {
                    for (let i = 0; i < 100; i++) {
                        const el = document.querySelector(selector);
                        if (el) return el;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Missing UI element: ' + selector);
                }
                (await waitFor('button[name="action_open_reconciliation"]')).click();
                await waitFor('.modal [name="evidence"]');
                const modal = document.querySelector('.modal');
                if (!modal.textContent.includes('This action never resends')) throw new Error('Missing reconciliation explanation');
                if (!modal.querySelector('button[name="action_confirm"]')) throw new Error('Missing explicit confirmation');
                if (document.querySelector('button[name="action_cancel"]')) throw new Error('Unknown sends must not offer cancellation');
                console.log('test successful');
            })().catch(error => console.error(error));
            """,
            ready='odoo.isReady === true', login='omni_ui', timeout=60,
        )

    def test_message_technical_details_collapsed(self):
        command = self.env['omni.command'].with_user(self.manager).create({
            'channel_id': self.channel.id, 'recipient': 'recipient',
            'body': 'Draft', 'reason': 'Technical details presentation test',
        })
        self.browser_js(
            f'/odoo/action-omni_channel.action_commands/{command.id}',
            """
            (async () => {
                for (let i = 0; i < 100; i++) {
                    if (document.querySelector('[name="attempt_count"]')) break;
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                for (const name of ['attempt_count', 'provider_message_key', 'next_attempt_at', 'lease_expires_at']) {
                    const field = document.querySelector('[name="' + name + '"]');
                    const details = field?.closest('details');
                    if (!details || details.open) throw new Error('Exposed technical field ' + name);
                }
                document.querySelector('details summary').click();
                if (!document.querySelector('details').open) throw new Error('Technical details cannot expand');
                console.log('test successful');
            })().catch(error => console.error(error));
            """,
            ready='odoo.isReady === true', login='omni_ui', timeout=60,
        )

    def test_system_administrator_opens_scoped_connections(self):
        new_test_user(self.env, login='omni_settings_ui', groups='base.group_system')
        self.browser_js(
            f'/odoo/action-omni_channel.action_channels/{self.channel.id}?debug=1',
            """
            (async () => {
                async function waitFor(selector) {
                    for (let i = 0; i < 100; i++) {
                        const el = document.querySelector(selector);
                        if (el) return el;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Missing administration control: ' + selector);
                }
                const button = await waitFor('button[name="action_connections"]');
                if (document.querySelector('button[name="action_add_channel"]')) throw new Error('Setup wizard remains');
                button.click();
                await waitFor('.o_list_view');
                if (!document.querySelector('.o_list_view').textContent.includes('Care bot')) throw new Error('Scoped connection missing');
                console.log('test successful');
            })().catch(error => console.error(error));
            """,
            ready='odoo.isReady === true', login='omni_settings_ui', timeout=60,
        )

    def test_clear_settings_and_message_monitoring(self):
        new_test_user(self.env, login='omni_clarity_ui', groups='base.group_system')
        policy = self.env['omni.inbound.policy'].create({'name': 'Support message storage', 'channel_id': self.channel.id})
        block = self.env['omni.blocked.identity'].create({
            'connection_id': self.channel.sender_ids.account_id.id,
            'external_key': '123456789', 'reason': 'Repeated unwanted messages',
        })
        message = self.env['omni.command'].create({
            'channel_id': self.channel.id, 'recipient': '123456789',
            'body': 'Your request was received.', 'reason': 'Customer support reply',
        })
        original = ChromeBrowser._handle_console

        def capture(browser, type, args=None, **kwargs):
            if args and args[0].get('value', '').startswith('omni_clarity_'):
                browser.take_screenshot(prefix=args[0]['value'] + '_')
            return original(browser, type, args=args, **kwargs)

        with patch.object(ChromeBrowser, '_handle_console', capture):
            for action, record, label in (
                ('action_inbound_policies', policy, 'policy'),
                ('action_blocks', block, 'block'),
                ('action_message_monitoring', message, 'monitor'),
            ):
                self.browser_js(
                    f'/odoo/action-omni_channel.{action}/{record.id}',
                    """
                    (async () => {
                        for (let i = 0; i < 100; i++) {
                            if (document.querySelector('.o_omni_setting')) break;
                            await new Promise(resolve => setTimeout(resolve, 100));
                        }
                        const settings = [...document.querySelectorAll('.o_omni_setting')].filter(el => el.getBoundingClientRect().height);
                        if (!settings.length) throw new Error('Missing clear form layout');
                        for (const setting of settings) {
                            const label = setting.querySelector('label');
                            const field = setting.querySelector('.o_field_widget');
                            if (!label || !field) continue;
                            if (label.getBoundingClientRect().bottom > field.getBoundingClientRect().top + 2) throw new Error('Label is cramped beside its field');
                        }
                        if (location.pathname.includes('action_message_monitoring')) {
                            if (document.querySelector('button[name="action_submit"],button[name="action_enqueue_approved"],.o_form_button_create,.o_form_button_edit')) throw new Error('Monitoring offers composition');
                            if (!document.querySelector('[name="attempt_count"]')?.closest('details')) throw new Error('Missing technical details');
                        }
                        console.log('omni_clarity_LABEL');
                        await new Promise(resolve => setTimeout(resolve, 250));
                        console.log('test successful');
                    })().catch(error => console.error(error));
                    """.replace('LABEL', label),
                    ready='odoo.isReady === true', login='omni_clarity_ui', timeout=60,
                )

    def test_mobile_clear_settings_and_message_monitoring(self):
        self.browser_size = '390x844'
        self.test_clear_settings_and_message_monitoring()
