from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.omni_channel.providers.base import HealthResult, installed_adapters


class HealthyAdapter:
    def check_sender_health(self, config):
        return HealthResult(
            True, config['namespace'], config['account_key'], config['sender_key'],
        )


@tagged('post_install', '-at_install')
class TestOmniFoundation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create(
            {'name': 'Omni other company'},
        )
        cls.manager = new_test_user(
            cls.env,
            login='omni_manager',
            groups='omni_channel.group_omni_manager',
            company_id=cls.company.id,
        )
        cls.operator = new_test_user(
            cls.env,
            login='omni_operator',
            groups='omni_channel.group_omni_user',
            company_id=cls.company.id,
        )
        cls.outsider = new_test_user(
            cls.env,
            login='omni_outsider',
            groups='omni_channel.group_omni_manager',
            company_id=cls.company.id,
        )
        cls.portal = new_test_user(
            cls.env,
            login='omni_portal',
            groups='base.group_portal',
            company_id=cls.company.id,
        )
        cls.purpose = cls.env['omni.purpose'].create(
            {
                'name': 'Test team',
                'code': 'test',
                'user_ids': [fields.Command.set([cls.manager.id, cls.operator.id])],
            },
        )
        cls.other_purpose = cls.env['omni.purpose'].create(
            {'name': 'Private team', 'code': 'private'},
        )
        cls.type = cls.env['omni.channel.type'].create(
            {'name': 'Mock transport', 'code': 'omni_test_mock'},
        )
        cls.channel = cls.env['omni.channel'].create(
            {
                'name': 'Test Telegram',
                'purpose_id': cls.purpose.id,
                'channel_type_id': cls.type.id,
            },
        )
        cls.account = cls.env['omni.account'].create(
            {
                'name': 'Test bot',
                'purpose_id': cls.purpose.id,
                'channel_type_id': cls.type.id,
                'external_account_key': 'bot-1',
                'namespace': 'bot-1',
                'credential_reference': 'OMNI_SECRET_TEST',
            },
        )
        cls.sender = cls.env['omni.outbound.sender'].create(
            {
                'name': 'Bot one',
                'channel_id': cls.channel.id,
                'account_id': cls.account.id,
                'external_key': 'bot-1',
            },
        )

    def test_unique_channel_including_archived(self):
        self.channel.active = False
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.channel.copy({'name': 'Duplicate'})

    def test_inbound_many_but_physical_identity_exclusive(self):
        model = self.env['omni.inbound.endpoint']
        vals = {
            'name': 'Inbound one',
            'channel_id': self.channel.id,
            'account_id': self.account.id,
            'external_key': 'endpoint-1',
        }
        first = model.create(vals)
        model.create(dict(vals, external_key='endpoint-2'))
        self.assertEqual(self.channel.endpoint_count, 2)
        first.active = False
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            model.create(vals)

    def test_company_and_purpose_isolation(self):
        private = self.channel.copy(
            {'name': 'Private', 'purpose_id': self.other_purpose.id},
        )
        other = self.env['omni.channel'].create(
            {
                'name': 'Other company',
                'purpose_id': self.purpose.id,
                'channel_type_id': self.type.id,
                'company_id': self.other_company.id,
            },
        )
        visible = self.env['omni.channel'].with_user(self.manager).search([])
        self.assertIn(self.channel, visible)
        self.assertNotIn(private, visible)
        self.assertNotIn(other, visible)
        with self.assertRaises(AccessError):
            private.with_user(self.manager).read(['name'])
        self.assertFalse(self.env['omni.channel'].with_user(self.outsider).search([]))

    def test_operator_readonly_and_portal_denied(self):
        self.assertTrue(self.channel.with_user(self.operator).has_access('read'))
        with self.assertRaises(AccessError):
            self.channel.with_user(self.operator).write({'name': 'Changed'})
        with self.assertRaises(AccessError):
            self.sender.with_user(self.operator).action_activate(
                self.channel.generation,
            )
        with self.assertRaises(AccessError):
            self.channel.with_user(self.portal).read(['name'])
        with self.assertRaises(AccessError):
            self.account.with_user(self.operator).read(['credential_reference'])

    def test_no_adapter_is_not_ready_and_cannot_activate(self):
        self.sender.with_user(self.manager).action_activate(self.channel.generation)
        self.assertFalse(self.sender.is_selected)
        self.assertEqual(self.sender.health, 'unhealthy')
        self.assertEqual(self.channel.readiness, 'unavailable')
        self.assertTrue(
            self.env['omni.audit.event'].search([('event', '=', 'sender.health')]),
        )

    def test_health_verified_selection_and_deactivation(self):
        with patch(
            'odoo.addons.omni_channel.models.foundation.get_adapter',
            return_value=HealthyAdapter(),
        ):
            self.sender.with_user(self.manager).action_activate(self.channel.generation)
        self.assertTrue(self.sender.is_selected)
        self.assertEqual(self.channel.generation, 1)
        self.assertEqual(self.sender.health, 'healthy')
        self.sender.with_user(self.manager).action_deactivate()
        self.assertFalse(self.sender.is_selected)
        self.assertEqual(self.channel.generation, 2)

    def test_failed_candidate_preserves_previous_selection(self):
        with patch(
            'odoo.addons.omni_channel.models.foundation.get_adapter',
            return_value=HealthyAdapter(),
        ):
            self.sender.with_user(self.manager).action_activate(self.channel.generation)
        candidate = self.sender.copy({'name': 'Candidate', 'external_key': 'bot-2'})
        candidate.with_user(self.manager).action_activate(self.channel.generation)
        self.assertTrue(self.sender.is_selected)
        self.assertFalse(candidate.is_selected)
        self.assertEqual(self.channel.generation, 1)

    def test_sensitive_mutations_cannot_bypass_actions(self):
        for vals in ({'is_selected': True}, {'health': 'healthy'}):
            with self.assertRaises(AccessError):
                self.sender.with_user(self.manager).write(vals)
        with self.assertRaises(AccessError):
            self.env['omni.outbound.sender'].create(
                {
                    'name': 'Forged',
                    'channel_id': self.channel.id,
                    'account_id': self.account.id,
                    'external_key': 'forged',
                    'is_selected': True,
                },
            )
        with self.assertRaises(AccessError):
            self.channel.write({'generation': 99})

    def test_wrong_provider_identity_rejected(self):
        adapter = HealthyAdapter()
        adapter.check_sender_health = lambda config: HealthResult(
            True, 'attacker', 'attacker', 'attacker',
        )
        with patch(
            'odoo.addons.omni_channel.models.foundation.get_adapter',
            return_value=adapter,
        ):
            self.sender.with_user(self.manager).action_activate(self.channel.generation)
        self.assertFalse(self.sender.is_selected)

    def test_no_secret_in_failure_or_audit(self):
        with patch(
            'odoo.addons.omni_channel.models.foundation.get_adapter',
            side_effect=RuntimeError('SECRET_TOKEN'),
        ):
            self.sender.with_user(self.manager).action_check_health()
        self.assertNotIn('SECRET_TOKEN', self.sender.health_message)
        self.assertFalse(
            self.env['omni.audit.event'].search([('detail', 'ilike', 'SECRET_TOKEN')]),
        )

    def test_selected_sender_cannot_be_archived_or_reconfigured(self):
        with patch(
            'odoo.addons.omni_channel.models.foundation.get_adapter',
            return_value=HealthyAdapter(),
        ):
            self.sender.with_user(self.manager).action_activate(self.channel.generation)
        with self.assertRaises(UserError):
            self.sender.write({'active': False})
        with self.assertRaises(UserError):
            self.account.write({'credential_reference': 'OMNI_SECRET_REPLACEMENT'})
        with self.assertRaises(UserError):
            self.sender.unlink()

    def test_bound_company_and_purpose_are_checked(self):
        account = self.account.copy(
            {
                'name': 'Private',
                'external_account_key': 'private',
                'namespace': 'private',
                'purpose_id': self.other_purpose.id,
            },
        )
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['omni.outbound.sender'].create(
                {
                    'name': 'Invalid',
                    'channel_id': self.channel.id,
                    'account_id': account.id,
                    'external_key': 'private',
                },
            )

    def test_ownership_cannot_move_after_configuration(self):
        with self.assertRaises(UserError):
            self.channel.write({'purpose_id': self.other_purpose.id})
        with self.assertRaises(UserError):
            self.sender.write({'external_key': 'another'})

    def test_audit_is_append_only(self):
        self.sender.with_user(self.manager).action_check_health()
        audit = self.env['omni.audit.event'].search([], limit=1)
        self.assertEqual(audit.actor_id, self.manager)
        with self.assertRaises(AccessError):
            audit.write({'detail': 'changed'})
        with self.assertRaises(AccessError):
            audit.unlink()
        with self.assertRaises(AccessError):
            self.env['omni.audit.event'].with_user(self.manager).create(
                {
                    'company_id': self.company.id,
                    'purpose_id': self.purpose.id,
                    'actor_id': self.manager.id,
                    'event': 'forged',
                    'resource': 'fake',
                    'detail': 'fake',
                },
            )

    def test_catalog_contains_twelve_integrations_with_truthful_adapter_availability(self):
        codes = ('whatsapp', 'telegram', 'slack', 'discord', 'linkedin', 'facebook',
                 'instagram', 'x', 'tiktok', 'youtube', 'threads', 'pinterest')
        catalog = self.env['omni.channel.type'].browse([
            self.env.ref('omni_channel.channel_type_' + code).id for code in codes
        ])
        self.assertEqual(len(catalog), 12)
        for channel_type in catalog:
            self.assertEqual(channel_type.adapter_ready, channel_type.code in installed_adapters(self.env))
        for key in (
            'channel_kanban',
            'channel_form',
            'channel_list',
            'omni_outbound_sender_form',
        ):
            self.assertTrue(self.env.ref('omni_channel.' + key).get_combined_arch())

    def test_context_defaults_cannot_select_sender_or_forge_scope(self):
        vals = {'name': 'Forged', 'channel_id': self.channel.id, 'account_id': self.account.id, 'external_key': 'forged'}
        with self.assertRaises(AccessError):
            self.env['omni.outbound.sender'].with_context(default_is_selected=True).create(vals)
        with self.assertRaises(AccessError):
            self.env['omni.outbound.sender'].with_context(default_namespace='another').create(vals)
        with self.assertRaises(AccessError):
            self.env['omni.channel'].with_context(default_generation=9).create({'name': 'Forged', 'purpose_id': self.other_purpose.id, 'channel_type_id': self.type.id})

    def test_health_preflight_precedes_lock_and_rejects_changed_configuration(self):
        channel_model = type(self.channel)
        original_lock = channel_model._lock
        calls = []

        def observe_lock(records):
            calls.append('lock')
            return original_lock(records)

        class ReadOnlyAdapter(HealthyAdapter):
            def check_sender_health(adapter, config):
                self.assertFalse(calls)
                calls.append('health')
                return super().check_sender_health(config)

        with patch.object(channel_model, '_lock', observe_lock), patch(
            'odoo.addons.omni_channel.models.foundation.get_adapter', return_value=ReadOnlyAdapter(),
        ):
            self.sender.with_user(self.manager).action_activate(self.channel.generation)
        self.assertEqual(calls[:2], ['health', 'lock'])
        self.sender.with_user(self.manager).action_deactivate()

        class ChangedAdapter(HealthyAdapter):
            def check_sender_health(adapter, config):
                self.account.write({'credential_reference': 'OMNI_SECRET_ROTATED'})
                return super().check_sender_health(config)

        with patch('odoo.addons.omni_channel.models.foundation.get_adapter', return_value=ChangedAdapter()), self.assertRaises(UserError):
            self.sender.with_user(self.manager).action_activate(self.channel.generation)
        self.assertFalse(self.sender.is_selected)
