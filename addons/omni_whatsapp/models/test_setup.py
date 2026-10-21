"""Manager-confirmed fixed setup diagnostic; business dispatch remains disabled.

The guarded sequence is shared: see ``omni_channel.models.test_diagnostic``.
"""
import os
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.addons.omni_channel.models.test_diagnostic import DiagnosticSpec

from ..providers.connection import GraphReadOnly
from ..providers.test_message import TEST_MESSAGE, send_test


def _send(*arguments):
    return send_test(*arguments)  # resolved at call time so it can be patched


SPEC = DiagnosticSpec(
    code='whatsapp', tester='whatsapp_tester_phone', tester_input='whatsapp_tester_phone',
    send=_send, test_message=TEST_MESSAGE, create_manager_fields=frozenset({'whatsapp_tester_phone'}),
)


class WhatsAppTestSetup(models.Model):
    _inherit = 'omni.channel'

    whatsapp_tester_phone = fields.Char(string='Tester phone', copy=False, groups='omni_channel.group_omni_manager')
    whatsapp_test_text = fields.Char(compute='_compute_whatsapp_test_text', string='Test message', groups='omni_channel.group_omni_manager')
    whatsapp_test_state = fields.Selection([('pending', 'Sending'), ('accepted', 'Test accepted'),
        ('failed', 'Not sent'), ('unknown', 'Delivery unconfirmed')], readonly=True, copy=False,
        groups='omni_channel.group_omni_manager')
    whatsapp_test_fingerprint = fields.Char(readonly=True, copy=False, groups='base.group_no_one')
    whatsapp_test_received = fields.Boolean(string='Tester received the message', copy=False,
                                            groups='omni_channel.group_omni_manager')

    def _compute_whatsapp_test_text(self):
        for channel in self:
            channel.whatsapp_test_text = TEST_MESSAGE

    def _whatsapp_diag_texts(self):
        return {
            'invalid_tester': _('Enter the tester’s international phone number, digits only.'),
            'no_recent_message': _('Ask the tester to message your connected WhatsApp number first.'),
            'failed': self.env._('Test not sent. Check Meta permissions, then try again.'),
            'account_unchecked': _('The WhatsApp account could not be checked. Try Finish setup again.'),
        }

    def _whatsapp_diag_valid_tester(self, recipient):
        return bool(re.fullmatch(r'[1-9][0-9]{5,14}', recipient))

    def _whatsapp_diag_prepare(self, account, recipient, recent):
        version = os.environ.get('OMNI_WHATSAPP_GRAPH_VERSION')
        try:
            GraphReadOnly(version)  # Validate deployment version without network I/O.
        except ValueError:
            raise UserError(_('Ask your administrator to configure the WhatsApp API version.')) from None
        credentials = account._whatsapp_credentials()
        return version, account.external_account_key, credentials['access_token'], recipient

    @api.model_create_multi
    def create(self, vals_list):
        self._diag_check_create(SPEC, vals_list)
        return super().create(vals_list)

    def write(self, values):
        self._diag_check_write(SPEC, values)
        return super().write(values)

    def _whatsapp_test_fingerprint(self):
        return self._diag_fingerprint(SPEC)

    def _whatsapp_before_connection_change(self):
        """Resolve the previous diagnostic before permitting a new connection test."""
        return self._diag_before_connection_change(SPEC)

    def _claim_whatsapp_test(self):
        return self._diag_claim(SPEC)

    def _finish_whatsapp_test(self, state, detail):
        return self._diag_finish(SPEC, state, detail)

    def action_whatsapp_send_test(self):
        return self._diag_send(SPEC)

    def action_setup_validate_step(self, step):
        if self.is_whatsapp and step == 4:
            return self._diag_validate_step(SPEC)
        return super().action_setup_validate_step(step)

    def action_setup_complete_step(self, step):
        self.ensure_one()
        if not self.is_whatsapp or step != 4:
            return super().action_setup_complete_step(step)
        return self._diag_complete_step(SPEC, lambda: super(WhatsAppTestSetup, self).action_setup_complete_step(step))
