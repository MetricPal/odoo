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

    def test_multiple_channels_per_team_and_type_including_archived(self):
        values = {
            'company_id': self.company.id,
            'purpose_id': self.purpose.id,
            'channel_type_id': self.type.id,
        }
        second = self.env['omni.channel'].with_user(self.manager).create(dict(values, name='Second team channel'))
        self.channel.active = False
        third = self.env['omni.channel'].with_user(self.manager).create(dict(values, name='Third team channel'))
        self.assertNotEqual(second, third)
        self.assertEqual(second.purpose_id, self.channel.purpose_id)
        self.assertEqual(third.channel_type_id, self.channel.channel_type_id)
        self.assertFalse(self.channel.active)

    def test_same_scope_channels_still_cannot_share_a_sending_identity(self):
        second = self.env['omni.channel'].create({
            'name': 'Another channel', 'company_id': self.company.id,
            'purpose_id': self.purpose.id, 'channel_type_id': self.type.id,
        })
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.env['omni.outbound.sender'].create({
                'name': 'Duplicate sender', 'channel_id': second.id,
                'account_id': self.account.id, 'external_key': self.sender.external_key,
            })

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

    def test_system_admin_has_default_configuration_access_without_team(self):
        admin = new_test_user(
            self.env, login='omni_system_admin', groups='base.group_system',
            company_id=self.company.id,
        )
        self.assertTrue(admin.has_group('omni_channel.group_omni_manager'))
        self.assertNotIn(admin, self.other_purpose.user_ids)
        channels = self.env['omni.channel'].with_user(admin).with_context(
            allowed_company_ids=[self.company.id],
        )
        self.assertFalse(channels.env.su)
        channel = channels.create({
            'name': 'Admin private channel',
            'purpose_id': self.other_purpose.id,
            'channel_type_id': self.type.id,
        })
        self.assertIn(channel, channels.search([]))
        channel.write({'name': 'Renamed by administrator'})
        self.assertEqual(channel.read(['name'])[0]['name'], 'Renamed by administrator')
        channel.unlink()
        block = self.env['omni.blocked.identity'].with_user(admin).create({
            'company_id': self.company.id,
            'purpose_id': self.other_purpose.id,
            'channel_type_id': self.type.id,
            'namespace': 'admin-test',
            'external_key': 'blocked-identity',
            'reason': 'Administrator draft without team membership',
        })
        self.assertEqual(block.state, 'draft')
        self.account.with_user(admin).read(['credential_reference'])
        self.sender.with_user(admin).action_check_health()
        audit = self.env['omni.audit.event'].with_user(admin).search([
            ('actor_id', '=', admin.id), ('event', '=', 'sender.health'),
        ])
        self.assertTrue(audit)
        with self.assertRaises(AccessError):
            audit.write({'detail': 'Tampered'})
        with self.assertRaises(AccessError):
            self.sender.with_user(admin).write({'is_selected': True})

    def test_system_admin_still_respects_selected_companies(self):
        admin = new_test_user(
            self.env, login='omni_company_admin', groups='base.group_system',
            company_id=self.company.id,
            company_ids=[fields.Command.set([self.company.id, self.other_company.id])],
        )
        channels = self.env['omni.channel'].with_user(admin).with_context(
            allowed_company_ids=[self.company.id],
        )
        vals = {
            'name': 'Other company private channel',
            'purpose_id': self.other_purpose.id,
            'channel_type_id': self.type.id,
            'company_id': self.other_company.id,
        }
        with self.assertRaises(AccessError), self.cr.savepoint():
            channels.create(vals)
        channel = channels.with_context(
            allowed_company_ids=[self.other_company.id],
        ).create(vals)
        self.assertNotIn(channel, channels.search([]))
        with self.assertRaises(AccessError):
            channel.with_context(allowed_company_ids=[self.company.id]).read(['name'])

    def test_omni_manager_cannot_create_outside_team(self):
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['omni.channel'].with_user(self.manager).create({
                'name': 'Unauthorized private channel',
                'purpose_id': self.other_purpose.id,
                'channel_type_id': self.type.id,
            })

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

    def test_setup_progress_is_validated_persistent_and_resumable(self):
        channel = self.channel.with_user(self.manager)
        self.assertEqual(channel.setup_completed_steps, 0)
        self.assertEqual(channel.action_setup_complete_step(0), 1)
        self.assertEqual(channel.action_setup_complete_step(0), 1)
        with self.assertRaises(UserError):
            channel.action_setup_complete_step(2)
        with self.assertRaises(UserError):
            channel.action_setup_complete_step(1)  # No guided connection configured.
        self.assertEqual(channel.setup_completed_steps, 1)
        action = channel.action_continue_setup()
        self.assertEqual(action['res_id'], channel.id)
        self.assertEqual(action['context']['setup_completed_steps'], 1)
        self.assertEqual(action['views'][0][0], self.env.ref('omni_channel.channel_setup_form').id)
        with self.assertRaises(AccessError):
            channel.write({'setup_completed_steps': 6})
        for user in (self.operator, self.outsider, self.portal):
            with self.assertRaises(AccessError):
                channel.with_user(user).action_setup_complete_step(0)
            with self.assertRaises(AccessError):
                channel.with_user(user).action_continue_setup()
        with patch.object(type(channel), 'action_setup_validate_step', return_value=True), patch.object(type(channel), '_is_setup_receiving_ready', return_value=True):
            for step in range(1, 6):
                channel.action_setup_complete_step(step)
        self.assertEqual(channel.setup_completed_steps, 6)
        self.assertFalse(channel.dispatch_enabled)
        self.assertNotIn(channel, self.env['omni.channel'].search([('setup_completed_steps', '<', 6)]))

    def test_receiving_can_be_deferred_without_false_completion(self):
        channel = self.channel.with_user(self.manager)
        with self.assertRaises(UserError):
            channel.action_setup_defer_receiving()
        with patch.object(type(channel), 'action_setup_validate_step', return_value=True):
            channel.action_setup_complete_step(0)
            channel.action_setup_complete_step(1)
            channel.action_setup_defer_receiving()
            channel.action_setup_complete_step(3)
            channel.action_setup_complete_step(4)
            self.assertEqual(channel.setup_completed_steps, 4)
            self.assertEqual(channel._completed_setup_steps(), [0, 1, 3, 4])
            self.assertTrue(channel.setup_receiving_deferred)
            with self.assertRaises(UserError):
                channel.action_setup_complete_step(5)
            self.assertFalse(channel.dispatch_enabled)
            self.assertEqual(channel.action_continue_setup()['context']['setup_completed_step_ids'], [0, 1, 3, 4])
            channel.action_setup_complete_step(2)
            self.assertFalse(channel.setup_receiving_deferred)
            with self.assertRaises(UserError):
                channel.action_setup_complete_step(5)  # A stale completed step is not readiness.
            with patch.object(type(channel), '_is_setup_receiving_ready', return_value=True):
                channel.action_setup_complete_step(5)
            self.assertEqual(channel.setup_completed_steps, 6)
            self.assertFalse(channel.dispatch_enabled)
        for user in (self.operator, self.outsider, self.portal):
            with self.assertRaises(AccessError):
                channel.with_user(user).action_setup_defer_receiving()
        for name, value in [('setup_receiving_deferred', True), ('setup_completed_step_ids', [0, 1, 2, 3, 4, 5])]:
            with self.assertRaises(AccessError):
                channel.write({name: value})
