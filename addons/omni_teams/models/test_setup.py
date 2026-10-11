"""Manager-confirmed fixed diagnostic; setup does not enable business dispatch."""
import hashlib
import json
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.omni_channel.models.command import internal, is_internal
from odoo.addons.omni_channel.models.foundation import protected_input

from ..providers.api import TEST_MESSAGE, send_test, valid_id

RESULT_FIELDS = {'teams_test_state', 'teams_test_fingerprint'}
EDIT_FIELDS = {'setup_conversation_id', 'teams_test_received'}


class TeamsTestSetup(models.Model):
    _inherit = 'omni.channel'

    teams_tester_id = fields.Char(related='setup_conversation_id.identity_id.external_key', string='Tester', groups='omni_channel.group_omni_manager')
    teams_test_text = fields.Char(compute='_compute_teams_test_text', string='Test message', groups='omni_channel.group_omni_manager')
    teams_test_state = fields.Selection([('pending', 'Sending'), ('accepted', 'Test accepted'),
        ('failed', 'Not sent'), ('unknown', 'Delivery unconfirmed')], readonly=True, copy=False,
        groups='omni_channel.group_omni_manager')
    teams_test_fingerprint = fields.Char(readonly=True, copy=False, groups='base.group_no_one')
    teams_test_received = fields.Boolean(string='Tester received the message', copy=False,
                                            groups='omni_channel.group_omni_manager')

    def _compute_teams_test_text(self):
        for channel in self:
            channel.teams_test_text = TEST_MESSAGE

    @api.model_create_multi
    def create(self, vals_list):
        # New Odoo forms serialize editable Boolean defaults, including False.
        # An unchecked receipt is ordinary draft data, not a diagnostic result.
        if (protected_input(self, RESULT_FIELDS, vals_list)
                or any(values.get('teams_test_received', False) is not False for values in vals_list)
                or self.env.context.get('default_teams_test_received', False) is not False):
            raise AccessError(_('Test results are recorded by the setup diagnostic.'))
        if protected_input(self, {'teams_tester_id'}, vals_list):
            self._require_manager()
        return super().create(vals_list)

    def write(self, values):
        if protected_input(self, RESULT_FIELDS, [values]) and not is_internal(self):
            raise AccessError(_('Test results are recorded by the setup diagnostic.'))
        if EDIT_FIELDS & values.keys():
            for channel in self.filtered(lambda c: c.is_teams):
                channel._require_teams_setup()
                channel._lock()
                channel.invalidate_recordset()
                if ('setup_conversation_id' in values and values['setup_conversation_id'] != channel.setup_conversation_id.id
                        and channel.teams_test_state in ('pending', 'accepted', 'unknown')):
                    raise UserError(_('This test already has a tester.'))
                if values.get('teams_test_received') and (channel.teams_test_state not in ('accepted', 'unknown')
                        or channel.sudo().teams_test_fingerprint != channel._teams_test_fingerprint()):
                    raise UserError(_('Send the test for this connection first.'))
                if values.get('teams_test_received') and not channel.teams_test_received:
                    channel._audit('teams.test_receipt_confirmed', channel.teams_tester_id)
                if ('teams_test_received' in values and not values['teams_test_received']
                        and channel.teams_test_received and not is_internal(self)):
                    if channel.selected_sender_id:
                        channel.selected_sender_id.action_deactivate()
                    completed = [step for step in channel._completed_setup_steps() if step != 4]
                    internal(channel).write({'setup_completed_step_ids': completed,
                                              'setup_completed_steps': len(completed)})
                    channel._audit('teams.test_receipt_withdrawn', channel.teams_tester_id)
        return super().write(values)

    def _teams_test_fingerprint(self):
        self.ensure_one()
        return hashlib.sha256(json.dumps([self.setup_account_id.credential_reference,
            self.setup_callback_url, self.teams_tester_id, self.setup_conversation_id.id], separators=(',', ':')).encode()).hexdigest()

    def _teams_before_connection_change(self):
        """Resolve the previous diagnostic before permitting a new connection test."""
        self._require_teams_setup()
        self._lock()
        self.invalidate_recordset()
        if (self.teams_test_state == 'pending' or
                (self.teams_test_state in ('accepted', 'unknown') and not self.teams_test_received)):
            raise UserError(_('Check with the tester and confirm receipt before changing this connection.'))
        if self.selected_sender_id:
            self.selected_sender_id.action_deactivate()
        internal(self.sudo()).write({'teams_test_state': False, 'teams_test_fingerprint': False,
                              'teams_test_received': False})

    def _claim_teams_test(self):
        self._require_teams_setup()
        self._lock()
        self.invalidate_recordset()
        if not self._is_setup_receiving_ready():
            raise UserError(_('Enable receiving first.'))
        if self.teams_test_state in ('pending', 'accepted', 'unknown'):
            raise UserError(_('This test was already sent or may still arrive. Do not send it again.'))
        recipient = self.teams_tester_id or ''
        if not valid_id(recipient, 'U'):
            raise UserError(_('Choose a received Teams chat as the tester.'))
        account, endpoint = self.setup_account_id, self.setup_endpoint_id
        if self.env['omni.blocked.identity']._matches(self, account.namespace, recipient):
            raise UserError(_('This tester is blocked.'))
        now = fields.Datetime.now()
        recent = self.env['omni.message'].search([
            ('conversation_id', '=', self.setup_conversation_id.id), ('conversation_id.channel_id', '=', self.id), ('conversation_id.endpoint_id', '=', endpoint.id),
            ('conversation_id.ownership_version', '=', endpoint.ownership_version),
            ('conversation_id.identity_id.namespace', '=', account.namespace),
            ('conversation_id.identity_id.external_key', '=', recipient),
            ('occurred_at', '>=', now - timedelta(hours=24)), ('occurred_at', '<=', now),
            ('redacted', '=', False), ('expires_at', '>', now), ('policy_id', '=', endpoint.policy_id.id)], limit=1)
        if not recent:
            raise UserError(_('Ask the tester to message the connected Teams app first.'))
        credentials = account._teams_credentials()
        internal(self.sudo()).write({'teams_test_state': 'pending', 'teams_test_received': False,
                                     'teams_test_fingerprint': self._teams_test_fingerprint()})
        self._audit('teams.test_authorized', json.dumps({'tester': recipient, 'message': TEST_MESSAGE,
                    'policy': 'manager-confirmed-fixed-teams-test'}))
        return credentials, recent.conversation_id._teams_route()

    def _finish_teams_test(self, state, detail):
        self._require_teams_setup()
        self._lock()
        self.invalidate_recordset()
        if self.teams_test_state != 'pending' or state not in ('accepted', 'failed', 'unknown'):
            raise UserError(_('The test result cannot be changed.'))
        internal(self).write({'teams_test_state': state})
        self._audit('teams.test_result', json.dumps({'state': state, 'detail': detail}))

    def action_teams_send_test(self):
        self._require_teams_setup()
        # Resolve translations while this environment's cursor is still active.
        # Odoo's implicit _() fallback can inspect the closed local cursor below.
        messages = {
            'accepted': self.env._('Test accepted. Confirm that the tester received it.'),
            'failed': self.env._('Test not sent. Check Teams permissions, then try again.'),
            'unknown': self.env._('Delivery unconfirmed. Check with the tester; do not resend.'),
        }
        context = {'allowed_company_ids': self.env.companies.ids,
                   'lang': self.env.lang or self.env.user.lang or 'en_US'}
        # Independent committed claim prevents Odoo HTTP retries repeating a send.
        with self.env.registry.cursor() as cr:
            record = api.Environment(cr, self.env.uid, context)[self._name].browse(self.id)
            arguments = record._claim_teams_test()
            cr.commit()
        state, detail = send_test(*arguments)
        with self.env.registry.cursor() as cr:
            record = api.Environment(cr, self.env.uid, context)[self._name].browse(self.id)
            record._finish_teams_test(state, detail)
            cr.commit()
        self.invalidate_recordset()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'message': messages[state],
            'type': 'success' if state == 'accepted' else 'warning', 'sticky': state != 'accepted'}}

    def action_setup_validate_step(self, step):
        if self.is_teams and step == 4:
            self._require_teams_setup()
            if (not self.teams_test_received or self.teams_test_state not in ('accepted', 'unknown')
                    or self.sudo().teams_test_fingerprint != self._teams_test_fingerprint()):
                raise UserError(_('Send the test and confirm that the tester received it.'))
            return True
        return super().action_setup_validate_step(step)

    def action_setup_complete_step(self, step):
        self.ensure_one()
        if not self.is_teams or step != 4:
            return super().action_setup_complete_step(step)
        self._require_teams_setup()
        with self.env.cr.savepoint():
            result = super().action_setup_complete_step(step)
            if self.selected_sender_id != self.setup_sender_id:
                self.setup_sender_id.action_activate(self.generation)
            if not self.setup_sender_id or self.selected_sender_id != self.setup_sender_id:
                raise UserError(_('The Teams account could not be checked. Try Finish setup again.'))
        return result
