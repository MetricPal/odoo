"""Explicitly authorized channel alerts, delivered by the native Odoo mail queue."""

import json
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import email_normalize

from .command import digest, internal, is_internal
from .foundation import protected_input


class OmniOperations(models.Model):
    _inherit = 'omni.channel'

    alert_user_ids = fields.Many2many(
        'res.users', 'omni_channel_alert_user_rel', string='Alert recipients',
        groups='base.group_system', domain=[('share', '=', False), ('active', '=', True)],
        copy=False,
    )
    alerts_enabled = fields.Boolean(readonly=True, copy=False, groups='base.group_system')
    alerts_authorized_by = fields.Many2one('res.users', readonly=True, copy=False, groups='base.group_system')
    alerts_authorized_at = fields.Datetime(readonly=True, copy=False, groups='base.group_system')
    alerts_addresses = fields.Char(readonly=True, copy=False, groups='base.group_system')
    alerts_snapshot = fields.Json(readonly=True, copy=False, groups='base.group_system')
    alerts_checked_at = fields.Datetime(readonly=True, copy=False, groups='base.group_system')
    alerts_status = fields.Char(readonly=True, copy=False, groups='base.group_system')
    alerts_last_mail_id = fields.Many2one('mail.mail', readonly=True, copy=False, groups='base.group_system')
    alerts_mail_state = fields.Selection(related='alerts_last_mail_id.state', groups='base.group_system')

    _alert_controls = {
        'alerts_enabled', 'alerts_authorized_by', 'alerts_authorized_at',
        'alerts_addresses', 'alerts_snapshot', 'alerts_checked_at',
        'alerts_status', 'alerts_last_mail_id', 'alerts_mail_state',
    }

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, self._alert_controls, vals_list) and not is_internal(self):
            raise AccessError(_('Use the alert activation actions.'))
        return super().create(vals_list)

    def write(self, vals):
        if self._alert_controls & vals.keys() and not is_internal(self):
            raise AccessError(_('Alert state is managed by verified server actions.'))
        if {'alert_user_ids', 'company_id', 'purpose_id'} & vals.keys():
            for channel in self.sorted('id'):
                channel._lock()
                if channel.sudo().alerts_enabled:
                    raise UserError(_('Pause alerts before changing recipients or ownership.'))
        return super().write(vals)

    def _require_alert_admin(self):
        self.ensure_one()
        self._require_manager()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only system administrators can enable or pause alerts.'))

    def _recipient_addresses(self):
        self.ensure_one()
        users = self.with_context(active_test=False).alert_user_ids
        if not users:
            raise UserError(_('Select at least one internal recipient.'))
        addresses = []
        for user in users:
            address = email_normalize(user.email or '')
            if (not user.active or user.share or not address
                    or self.company_id not in user.company_ids
                    or user not in self.purpose_id.user_ids
                    or not user.has_group('omni_channel.group_omni_user')):
                raise UserError(_('Recipients must have a valid email and current access to this company and purpose.'))
            addresses.append(address)
        return ','.join(sorted(set(addresses)))

    def action_enable_alerts(self):
        self._require_alert_admin()
        self._lock()
        if not self.active:
            raise UserError(_('Restore the channel before enabling alerts.'))
        if self.alerts_enabled:
            return
        if not email_normalize(self.env.user.email or ''):
            raise UserError(_('Your administrator account needs a valid email for native Odoo mail routing.'))
        addresses = self._recipient_addresses()
        internal(self).write({
            'alerts_enabled': True, 'alerts_authorized_by': self.env.uid,
            'alerts_authorized_at': fields.Datetime.now(), 'alerts_addresses': addresses,
            'alerts_snapshot': False, 'alerts_status': 'Enabled; awaiting collection.',
        })
        self.env.ref('omni_channel.cron_operations_alerts').sudo().write({'active': True})
        policy = {
            'recipient_user_ids': sorted(self.alert_user_ids.ids),
            'addresses': addresses, 'interval_minutes': 1,
            'company_id': self.company_id.id, 'purpose_id': self.purpose_id.id,
        }
        self._audit(
            'alerts_enabled',
            f"Authorized one-minute monitoring and native email queueing; recipients {policy['recipient_user_ids']}; policy SHA256 {digest(policy)}.",
        )

    def action_pause_alerts(self):
        self._require_alert_admin()
        self._lock()
        internal(self).write({'alerts_enabled': False, 'alerts_status': 'Paused. Already queued emails remain in the Odoo queue.'})
        self._audit('alerts_paused', 'Administrator paused new operations email queueing.')

    def _operations_snapshot(self):
        self.ensure_one()
        old = fields.Datetime.now() - timedelta(minutes=5)
        command = self.env['omni.command'].sudo()
        event = self.env['omni.webhook.event'].sudo()
        command_scope = [('channel_id', '=', self.id)]
        event_scope = [('endpoint_id.channel_id', '=', self.id)]
        counts = {
            'unknown_outcomes': command.search_count(command_scope + [('state', '=', 'unknown')]),
            'expired_worker_leases': command.search_count(command_scope + [('state', '=', 'dispatching'), ('lease_expires_at', '<=', fields.Datetime.now())]),
            'aged_queue': command.search_count(command_scope + [('state', '=', 'queued'), ('write_date', '<=', old)]),
            'aged_inbox': event.search_count(event_scope + [('state', 'in', ['received', 'retry']), ('create_date', '<=', old)]),
            'dead_letters': event.search_count(event_scope + [('state', '=', 'dead')]),
            'unresolved_events': event.search_count(event_scope + [('state', '=', 'unresolved')]),
            'open_circuit_breakers': int(self.failure_count >= 5 and not self.dispatch_enabled),
            'unhealthy_senders': self.env['omni.outbound.sender'].sudo().search_count([
                ('channel_id', '=', self.id), ('is_selected', '=', True), ('health', '=', 'unhealthy'),
            ]),
        }
        critical = ('unknown_outcomes', 'expired_worker_leases', 'open_circuit_breakers')
        severity = 'critical' if any(counts[key] for key in critical) else ('warning' if any(counts.values()) else 'ok')
        return {'severity': severity, 'counts': counts}

    def _validate_alert_authorization(self):
        actor = self.alerts_authorized_by
        if (not self.active or not actor.active or actor.share
                or self.company_id not in actor.company_ids
                or actor not in self.purpose_id.user_ids
                or not email_normalize(actor.email or '')):
            raise AccessError(_('Alert authorization is no longer valid.'))
        self.with_user(actor).with_context(allowed_company_ids=[self.company_id.id])._require_alert_admin()
        if self._recipient_addresses() != self.alerts_addresses:
            raise UserError(_('Recipient email addresses changed.'))

    def _collect_operations_alert(self):
        self.ensure_one()
        if not self.env.su:
            raise AccessError(_('Operations collection requires the trusted scheduler.'))
        self._lock()
        if not self.alerts_enabled:
            return
        actor = self.alerts_authorized_by
        try:
            self._validate_alert_authorization()
        except (AccessError, UserError):
            internal(self).write({'alerts_enabled': False, 'alerts_status': 'Paused: recipient or administrator access changed. Review and enable again.'})
            self._audit('alerts_revoked', 'Current administrator or recipient authorization no longer matches the approved policy.')
            return
        snapshot = self._operations_snapshot()
        previous = self.alerts_snapshot
        values = {'alerts_snapshot': snapshot, 'alerts_checked_at': fields.Datetime.now()}
        if snapshot != previous and (snapshot['severity'] != 'ok' or previous):
            body = Markup('<p>Channel: %s</p><p>Status: %s</p><pre>%s</pre><p>Review the channel queue and attempts. Do not automatically resend unknown outcomes.</p>') % (
                escape(self.name), escape(snapshot['severity']), escape(json.dumps(snapshot['counts'], sort_keys=True, indent=2)),
            )
            mail = self.env['mail.mail'].sudo().with_company(self.company_id).create({
                'subject': f"Omni-Channel operations: {snapshot['severity']}",
                'body_html': body, 'email_to': self.alerts_addresses,
                'author_id': actor.partner_id.id, 'email_from': actor.email_formatted,
                'auto_delete': False,
            })
            values.update(alerts_last_mail_id=mail.id, alerts_status='Email queued through Odoo; see delivery status.')
            self._audit('operations_alert_queued', f"Aggregate {snapshot['severity']} notification queued as mail {mail.id}.")
        else:
            values['alerts_status'] = 'Healthy baseline; no email.' if not previous else 'No counter change; no new email.'
        internal(self).write(values)

    @api.model
    def _cron_operations_alerts(self):
        # Private scheduled entry point; no exposed send endpoint.
        if not self.env.su:
            raise AccessError(_('Operations collection requires the trusted scheduler.'))
        channels = self.with_context(active_test=False).search(
            [('alerts_enabled', '=', True)], order='alerts_checked_at ASC NULLS FIRST, id', limit=100,
        )
        for index, channel in enumerate(channels):
            channel._collect_operations_alert()
            if self.env.context.get('ir_cron_progress_id') and not self.env['ir.cron']._commit_progress(
                1, remaining=len(channels) - index - 1,
            ):
                break
