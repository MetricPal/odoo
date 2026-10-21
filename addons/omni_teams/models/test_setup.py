"""Manager-confirmed fixed diagnostic; setup does not enable business dispatch.

The guarded sequence is shared: see ``omni_channel.models.test_diagnostic``.
"""
from odoo import _, api, fields, models
from odoo.addons.omni_channel.models.test_diagnostic import DiagnosticSpec

from ..providers.api import TEST_MESSAGE, send_test, valid_id


def _send(*arguments):
    return send_test(*arguments)  # resolved at call time so it can be patched


SPEC = DiagnosticSpec(
    code='teams', tester='teams_tester_id', tester_input='setup_conversation_id',
    send=_send, test_message=TEST_MESSAGE, create_manager_fields=frozenset({'teams_tester_id'}),
    own_channels_only=True, fingerprint_extra=('setup_conversation_id',),
    recent_extra_domain=lambda channel: [('conversation_id', '=', channel.setup_conversation_id.id)],
)


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

    def _teams_diag_texts(self):
        return {
            'invalid_tester': _('Choose a received Teams chat as the tester.'),
            'no_recent_message': _('Ask the tester to message the connected Teams app first.'),
            'failed': self.env._('Test not sent. Check Teams permissions, then try again.'),
            'account_unchecked': _('The Teams account could not be checked. Try Finish setup again.'),
        }

    def _teams_diag_valid_tester(self, recipient):
        return valid_id(recipient, 'U')

    def _teams_diag_prepare(self, account, recipient, recent):
        credentials = account._teams_credentials()
        return credentials, recent.conversation_id._teams_route()

    @api.model_create_multi
    def create(self, vals_list):
        self._diag_check_create(SPEC, vals_list)
        return super().create(vals_list)

    def write(self, values):
        self._diag_check_write(SPEC, values)
        return super().write(values)

    def _teams_test_fingerprint(self):
        return self._diag_fingerprint(SPEC)

    def _teams_before_connection_change(self):
        """Resolve the previous diagnostic before permitting a new connection test."""
        return self._diag_before_connection_change(SPEC)

    def _claim_teams_test(self):
        return self._diag_claim(SPEC)

    def _finish_teams_test(self, state, detail):
        return self._diag_finish(SPEC, state, detail)

    def action_teams_send_test(self):
        return self._diag_send(SPEC)

    def action_setup_validate_step(self, step):
        if self.is_teams and step == 4:
            return self._diag_validate_step(SPEC)
        return super().action_setup_validate_step(step)

    def action_setup_complete_step(self, step):
        self.ensure_one()
        if not self.is_teams or step != 4:
            return super().action_setup_complete_step(step)
        return self._diag_complete_step(SPEC, lambda: super(TeamsTestSetup, self).action_setup_complete_step(step))
