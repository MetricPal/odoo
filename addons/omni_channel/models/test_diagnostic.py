"""Shared state machine for the manager-confirmed setup test message.

Provider addons (Slack, Teams, WhatsApp) keep their own fields, method names
and wording. They describe themselves with a :class:`DiagnosticSpec` and a few
hooks, and delegate the guarded sequence to the methods below:

1. A scoped manager chooses a tester who messaged the connection recently.
2. ``Send test message`` commits a claim in its own transaction, then performs
   the network call, then records the outcome in another transaction, so an
   HTTP retry can never send twice. Pending, accepted and unknown outcomes are
   never resent automatically.
3. The manager confirms receipt; only then can setup step 4 complete and the
   tested sender become the selected sender. Withdrawing the confirmation
   deactivates the sender and reopens step 4.

Provider hooks, where ``<code>`` is ``spec.code``:

``_require_<code>_setup()``
    Raise unless the current user may set up this channel.
``_<code>_diag_texts()``
    Translated texts: ``invalid_tester``, ``no_recent_message``, ``failed``,
    ``account_unchecked``.
``_<code>_diag_valid_tester(recipient)``
    Whether the tester key has the provider's expected shape.
``_<code>_diag_prepare(account, recipient, recent)``
    Validate provider settings, fetch credentials and return the arguments of
    ``spec.send``. Called before the claim is written.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .command import internal, is_internal
from .foundation import protected_input

OPEN_STATES = ('pending', 'accepted', 'unknown')
SETUP_TEST_STEP = 4


@dataclass(frozen=True)
class DiagnosticSpec:
    code: str                       # 'slack' -> slack_test_state, is_slack, ...
    tester: str                     # field holding the tester identity key
    tester_input: str               # field the manager edits to choose the tester
    send: object                    # callable(*prepared_args) -> (state, detail)
    test_message: str
    create_manager_fields: frozenset = field(default_factory=frozenset)
    own_channels_only: bool = False  # guard only channels of this provider
    fingerprint_extra: tuple = ()   # extra field names bound into the fingerprint
    recent_extra_domain: object = None  # callable(channel) -> extra domain terms

    def name(self, suffix):
        return f'{self.code}_test_{suffix}'

    @property
    def result_fields(self):
        return {self.name('state'), self.name('fingerprint')}

    @property
    def edit_fields(self):
        return {self.tester_input, self.name('received')}


class OmniChannelTestDiagnostic(models.Model):
    _inherit = 'omni.channel'

    # -- helpers ---------------------------------------------------------

    def _diag_require(self, spec):
        getattr(self, f'_require_{spec.code}_setup')()

    def _diag_hook(self, spec, name, *args):
        return getattr(self, f'_{spec.code}_diag_{name}')(*args)

    def _diag_is_own(self, spec):
        return getattr(self, f'is_{spec.code}')

    # -- write guards ----------------------------------------------------

    def _diag_check_create(self, spec, vals_list):
        received = spec.name('received')
        # New Odoo forms serialize editable Boolean defaults, including False.
        # An unchecked receipt is ordinary draft data, not a diagnostic result.
        if (protected_input(self, spec.result_fields, vals_list)
                or any(values.get(received, False) is not False for values in vals_list)
                or self.env.context.get('default_' + received, False) is not False):
            raise AccessError(_('Test results are recorded by the setup diagnostic.'))
        if protected_input(self, set(spec.create_manager_fields), vals_list):
            self._require_manager()

    def _diag_check_write(self, spec, values):
        state, received = spec.name('state'), spec.name('received')
        if protected_input(self, spec.result_fields, [values]) and not is_internal(self):
            raise AccessError(_('Test results are recorded by the setup diagnostic.'))
        if not spec.edit_fields & values.keys():
            return
        channels = self.filtered(lambda c: c._diag_is_own(spec)) if spec.own_channels_only else self
        for channel in channels:
            channel._diag_require(spec)
            channel._lock()
            channel.invalidate_recordset()
            if spec.tester_input in values:
                current = channel[spec.tester_input]
                current = current.id if isinstance(current, models.BaseModel) else current
                if values[spec.tester_input] != current and channel[state] in OPEN_STATES:
                    raise UserError(_('This test already has a tester.'))
            if values.get(received) and (channel[state] not in ('accepted', 'unknown')
                    or channel.sudo()[spec.name('fingerprint')] != channel._diag_fingerprint(spec)):
                raise UserError(_('Send the test for this connection first.'))
            if values.get(received) and not channel[received]:
                channel._audit(f'{spec.code}.test_receipt_confirmed', channel[spec.tester])
            if (received in values and not values[received]
                    and channel[received] and not is_internal(self)):
                if channel.selected_sender_id:
                    channel.selected_sender_id.action_deactivate()
                completed = [step for step in channel._completed_setup_steps() if step != SETUP_TEST_STEP]
                internal(channel).write({'setup_completed_step_ids': completed,
                                          'setup_completed_steps': len(completed)})
                channel._audit(f'{spec.code}.test_receipt_withdrawn', channel[spec.tester])

    # -- state machine ---------------------------------------------------

    def _diag_fingerprint(self, spec):
        self.ensure_one()
        extra = [
            value.id if isinstance(value, models.BaseModel) else value
            for value in (self[name] for name in spec.fingerprint_extra)
        ]
        return hashlib.sha256(json.dumps(
            [self.setup_account_id.credential_reference, self.setup_callback_url, self[spec.tester], *extra],
            separators=(',', ':')).encode()).hexdigest()

    def _diag_before_connection_change(self, spec):
        """Resolve the previous diagnostic before permitting a new connection test."""
        self._diag_require(spec)
        self._lock()
        self.invalidate_recordset()
        state, received = self[spec.name('state')], self[spec.name('received')]
        if state == 'pending' or (state in ('accepted', 'unknown') and not received):
            raise UserError(_('Check with the tester and confirm receipt before changing this connection.'))
        if self.selected_sender_id:
            self.selected_sender_id.action_deactivate()
        internal(self.sudo()).write({spec.name('state'): False, spec.name('fingerprint'): False,
                                     spec.name('received'): False})

    def _diag_claim(self, spec):
        self._diag_require(spec)
        self._lock()
        self.invalidate_recordset()
        texts = self._diag_hook(spec, 'texts')
        if not self._is_setup_receiving_ready():
            raise UserError(_('Enable receiving first.'))
        if self[spec.name('state')] in OPEN_STATES:
            raise UserError(_('This test was already sent or may still arrive. Do not send it again.'))
        recipient = self[spec.tester] or ''
        if not self._diag_hook(spec, 'valid_tester', recipient):
            raise UserError(texts['invalid_tester'])
        account, endpoint = self.setup_account_id, self.setup_endpoint_id
        if self.env['omni.blocked.identity']._matches(self, account.namespace, recipient):
            raise UserError(_('This tester is blocked.'))
        now = fields.Datetime.now()
        domain = [
            ('conversation_id.channel_id', '=', self.id), ('conversation_id.endpoint_id', '=', endpoint.id),
            ('conversation_id.ownership_version', '=', endpoint.ownership_version),
            ('conversation_id.identity_id.namespace', '=', account.namespace),
            ('conversation_id.identity_id.external_key', '=', recipient),
            ('occurred_at', '>=', now - timedelta(hours=24)), ('occurred_at', '<=', now),
            ('redacted', '=', False), ('expires_at', '>', now), ('policy_id', '=', endpoint.policy_id.id)]
        if spec.recent_extra_domain:
            domain = spec.recent_extra_domain(self) + domain
        recent = self.env['omni.message'].search(domain, limit=1)
        if not recent:
            raise UserError(texts['no_recent_message'])
        arguments = self._diag_hook(spec, 'prepare', account, recipient, recent)
        internal(self.sudo()).write({spec.name('state'): 'pending', spec.name('received'): False,
                                     spec.name('fingerprint'): self._diag_fingerprint(spec)})
        self._audit(f'{spec.code}.test_authorized', json.dumps({
            'tester': recipient, 'message': spec.test_message,
            'policy': f'manager-confirmed-fixed-{spec.code}-test'}))
        return arguments

    def _diag_finish(self, spec, state, detail):
        self._diag_require(spec)
        self._lock()
        self.invalidate_recordset()
        if self[spec.name('state')] != 'pending' or state not in ('accepted', 'failed', 'unknown'):
            raise UserError(_('The test result cannot be changed.'))
        internal(self).write({spec.name('state'): state})
        self._audit(f'{spec.code}.test_result', json.dumps({'state': state, 'detail': detail}))

    def _diag_send(self, spec):
        self._diag_require(spec)
        # Resolve translations while this environment's cursor is still active.
        # Odoo's implicit _() fallback can inspect the closed local cursor below.
        texts = self._diag_hook(spec, 'texts')
        messages = {
            'accepted': self.env._('Test accepted. Confirm that the tester received it.'),
            'failed': texts['failed'],
            'unknown': self.env._('Delivery unconfirmed. Check with the tester; do not resend.'),
        }
        context = {'allowed_company_ids': self.env.companies.ids,
                   'lang': self.env.lang or self.env.user.lang or 'en_US'}
        # Independent committed claim prevents Odoo HTTP retries repeating a send.
        with self.env.registry.cursor() as cr:
            record = api.Environment(cr, self.env.uid, context)[self._name].browse(self.id)
            arguments = getattr(record, f'_claim_{spec.code}_test')()
            cr.commit()
        state, detail = spec.send(*arguments)
        with self.env.registry.cursor() as cr:
            record = api.Environment(cr, self.env.uid, context)[self._name].browse(self.id)
            getattr(record, f'_finish_{spec.code}_test')(state, detail)
            cr.commit()
        self.invalidate_recordset()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'message': messages[state],
            'type': 'success' if state == 'accepted' else 'warning', 'sticky': state != 'accepted'}}

    def _diag_validate_step(self, spec):
        self._diag_require(spec)
        if (not self[spec.name('received')] or self[spec.name('state')] not in ('accepted', 'unknown')
                or self.sudo()[spec.name('fingerprint')] != self._diag_fingerprint(spec)):
            raise UserError(_('Send the test and confirm that the tester received it.'))
        return True

    def _diag_complete_step(self, spec, complete):
        """Run ``complete()`` (the parent step completion) and select the tested sender."""
        self._diag_require(spec)
        with self.env.cr.savepoint():
            result = complete()
            if self.selected_sender_id != self.setup_sender_id:
                self.setup_sender_id.action_activate(self.generation)
            if not self.setup_sender_id or self.selected_sender_id != self.setup_sender_id:
                raise UserError(self._diag_hook(spec, 'texts')['account_unchecked'])
        return result
