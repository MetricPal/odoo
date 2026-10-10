from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from .test_users import new_test_user

from .test_foundation import HealthyAdapter, TestOmniFoundation


@tagged('post_install', '-at_install')
class TestOmniCommands(TestOmniFoundation):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.approver = new_test_user(
            cls.env,
            login='omni_approver',
            groups='omni_channel.group_omni_user,approval_center.group_approval_center_approver',
            company_id=cls.company.id,
        )
        cls.purpose.write({'user_ids': [fields.Command.link(cls.approver.id)]})
        cls.policy = cls.env['approval.center.policy'].create(
            {
                'name': 'Review communication',
                'company_id': cls.company.id,
                'approver_ids': [
                    fields.Command.create(
                        {'user_id': cls.approver.id, 'required': True},
                    ),
                ],
            },
        )
        cls.channel.approval_type_id = cls.policy

    def _draft(self):
        with patch(
            'odoo.addons.omni_channel.models.foundation.get_adapter',
            return_value=HealthyAdapter(),
        ):
            self.sender.with_user(self.manager).action_activate(self.channel.generation)
        return (
            self.env['omni.command']
            .with_user(self.operator)
            .create(
                {
                    'name': 'Customer follow-up',
                    'channel_id': self.channel.id,
                    'recipient': '12345',
                    'body': 'Thank you for contacting us.',
                    'reason': 'Reply to the customer request.',
                },
            )
        )

    def test_review_then_queue_is_one_shot_and_keeps_payload(self):
        command = self._draft()
        command.action_submit()
        payload_hash = command.payload_hash
        self.assertEqual(command.state, 'pending')
        self.assertEqual(command.approval_request_id.omni_body, command.body)
        with self.assertRaises(AccessError):
            command.action_enqueue_approved()
        command.approval_request_id.with_user(self.approver).action_approve()
        self.assertEqual(command.state, 'approved')
        command.action_enqueue_approved()
        command.action_enqueue_approved()
        self.assertEqual(command.state, 'queued')
        self.assertEqual(command.payload_hash, payload_hash)
        self.assertEqual(
            self.env['omni.audit.event'].search_count(
                [
                    ('resource', '=', f'omni.command,{command.id}'),
                    ('event', '=', 'message.queued'),
                ],
            ),
            1,
        )

    def test_frozen_payload_and_approval_cannot_be_forged(self):
        command = self._draft()
        command.action_submit()
        request = command.approval_request_id
        for vals in (
            {'body': 'Changed'},
            {'state': 'approved'},
            {'payload_hash': 'fake'},
        ):
            with self.assertRaises(AccessError):
                command.write(vals)
        with self.assertRaises(AccessError):
            request.write({'state': 'approved'})
        with self.assertRaises(AccessError):
            request.with_user(self.approver).approver_ids.write({'status': 'approved'})
        with self.assertRaises(AccessError):
            request.with_user(self.approver).approver_ids.unlink()
        with self.assertRaises(AccessError):
            request.write({'omni_command_id': False})
        with self.assertRaises(AccessError):
            request.action_approve()
        self.assertEqual(command.state, 'pending')

    def test_sender_change_holds_pending_message(self):
        command = self._draft()
        command.action_submit()
        self.sender.with_user(self.manager).action_deactivate()
        self.assertEqual(command.state, 'held')
        with self.assertRaises(UserError):
            command.approval_request_id.with_user(self.approver).action_approve()

    def test_policy_change_requires_fresh_review(self):
        command = self._draft()
        command.action_submit()
        self.policy.approver_sequence = True
        with self.assertRaises(UserError):
            command.approval_request_id.with_user(self.approver).action_approve()

    def test_refusal_and_cancellation(self):
        command = self._draft()
        command.action_submit()
        command.approval_request_id.with_user(self.approver).action_refuse()
        self.assertEqual(command.state, 'held')
        self.assertEqual(command.approval_request_id.state, 'refused')
        command.action_cancel()
        self.assertEqual(command.state, 'cancelled')
        with self.assertRaises(AccessError):
            command.unlink()

    def test_other_purpose_cannot_read_approval_or_content(self):
        command = self._draft()
        command.action_submit()
        with self.assertRaises(AccessError):
            command.approval_request_id.with_user(self.outsider).read(['omni_body'])
        with self.assertRaises(AccessError):
            command.with_user(self.outsider).read(['body'])

    def test_context_boolean_does_not_grant_internal_capability(self):
        command = self._draft()
        with self.assertRaises(AccessError):
            command.with_context(_omni_internal=True).write({'state': 'approved'})
        with self.assertRaises(AccessError):
            command.create(
                {
                    'name': 'Forged',
                    'channel_id': self.channel.id,
                    'recipient': '1',
                    'body': 'bad',
                    'reason': 'bad',
                    'state': 'approved',
                },
            )

    def test_stale_sender_selection_dialog_rejected(self):
        self._draft()
        expected = self.channel.generation
        self.sender.with_user(self.manager).action_deactivate()
        with self.assertRaises(UserError):
            self.sender.with_user(self.manager).action_activate(expected)

    def test_client_defaults_cannot_forge_governance(self):
        vals = {'name': 'Draft', 'channel_id': self.channel.id, 'recipient': '1', 'body': 'Hello', 'reason': 'Testing'}
        with self.assertRaises(AccessError):
            self.env['omni.command'].with_user(self.operator).with_context(default_state='approved').create(vals)
        command = self._draft()
        command.action_submit()
        with self.assertRaises(AccessError):
            self.env['approval.center.request'].with_user(self.operator).with_context(default_omni_command_id=command.id).create({'name': 'Forged', 'policy_id': self.policy.id})
        with self.assertRaises(AccessError):
            self.env['approval.center.approver'].with_user(self.operator).with_context(default_request_id=command.approval_request_id.id).create({'user_id': self.operator.id})

    def test_unsubmitted_command_cannot_enqueue(self):
        command = self._draft()
        with self.assertRaises(AccessError):
            command.action_enqueue_approved()

    def test_generic_approval_behavior_is_preserved(self):
        request = self.env['approval.center.request'].with_user(self.operator).create({
            'name': 'Ordinary request', 'policy_id': self.policy.id, 'reason': 'Existing workflow',
        })
        request.action_submit()
        request.with_user(self.approver).action_approve()
        self.assertEqual(request.state, 'approved')
        self.assertFalse(request.omni_command_id)
        request.action_execute()
        self.assertTrue(request.executed_at)
