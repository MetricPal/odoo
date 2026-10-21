"""Signed incoming hints queue read-only synchronization, never dispatch."""

import secrets
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from .social import internal, trusted, Connection as BaseConnection
from ..providers import vault


class Connection(models.Model):
    _inherit = 'omni.social.connection'
    webhook_route = fields.Char(readonly=True, copy=False, groups='omni_channel.group_omni_manager')
    webhook_verify = fields.Char(
        readonly=True, copy=False, groups='omni_channel.group_omni_manager', string='Verify token'
    )
    webhook_url = fields.Char(
        compute='_compute_webhook_url', groups='omni_channel.group_omni_manager', string='Callback URL'
    )
    webhook_pending = fields.Boolean(readonly=True, copy=False)
    webhook_enabled = fields.Boolean(readonly=True, copy=False)
    _protected = BaseConnection._protected | {'webhook_route', 'webhook_verify', 'webhook_pending', 'webhook_enabled'}

    @api.depends('public_url', 'webhook_route')
    def _compute_webhook_url(self):
        for row in self:
            row.webhook_url = (
                (row.public_url.rstrip('/') + '/omni/social/webhook/' + row.webhook_route)
                if row.public_url and row.webhook_route
                else ''
            )

    def action_configure_webhook(self, secret):
        self.ensure_one()
        self._require_manager()
        self._lock()
        if not self.public_url:
            raise UserError(_('Set the public HTTPS address first.'))
        if self.provider == 'linkedin' and self.account_kind != 'organization':
            raise UserError(_('LinkedIn activity webhooks support company Pages.'))
        if not isinstance(secret, str) or not 16 <= len(secret) <= 512:
            raise UserError(_('Enter the app secret from the developer portal.'))
        bundle = {**self._bundle(), 'webhook_secret': secret}
        ref = vault.store(bundle)
        self.env.cr.postrollback.add(lambda: vault.remove(ref, self.env.cr.dbname))
        internal(self).write(
            {
                'credential_reference': ref,
                'webhook_route': secrets.token_urlsafe(32),
                'webhook_verify': secrets.token_urlsafe(32),
                'webhook_enabled': True,
                'webhook_pending': False,
                'revision': self.revision + 1,
            }
        )
        self._audit(
            'social.webhook_enabled',
            _('Signed incoming activity enabled. Register the displayed callback with the platform.'),
        )
        return True

    def action_disable_webhook(self):
        self.ensure_one()
        self._require_manager()
        self._lock()
        internal(self).write(
            {'webhook_enabled': False, 'webhook_pending': False, 'webhook_route': False, 'webhook_verify': False}
        )
        self._audit('social.webhook_disabled', _('Incoming webhook disabled.'))

    def _enqueue_webhook(self, keys):
        self._lock()
        if not self.active or not self.connected or not self.webhook_enabled:
            return
        receipts = internal(self.env['omni.social.webhook.receipt'])
        fresh = False
        for key in set(keys):
            if not receipts.search_count([('connection_id', '=', self.id), ('key', '=', key)]):
                receipts.create({'connection_id': self.id, 'key': key})
                fresh = True
        if fresh:
            internal(self).write({'webhook_pending': True})

    @api.model
    def _cron_webhooks(self):
        for account in self.search(
            [
                ('active', '=', True),
                ('connected', '=', True),
                ('webhook_enabled', '=', True),
                ('webhook_pending', '=', True),
            ],
            limit=20,
        ):
            try:
                with self.env.cr.savepoint():
                    account._lock()
                    account.action_sync()
                    internal(account).write({'webhook_pending': False})
            except Exception:
                internal(account).write({'sync_note': _('Webhook activity sync failed. Check account permissions.')})
        receipts = self.env['omni.social.webhook.receipt'].search(
            [('create_date', '<', fields.Datetime.now() - timedelta(days=90))], limit=1000
        )
        internal(receipts).unlink()


class Receipt(models.Model):
    _name = 'omni.social.webhook.receipt'
    _description = 'Social Webhook Receipt'
    connection_id = fields.Many2one('omni.social.connection', required=True, ondelete='cascade')
    key = fields.Char(required=True)
    _unique = models.Constraint('UNIQUE(connection_id,key)', 'Notification already received.')

    @api.model_create_multi
    def create(self, values):
        if not trusted(self):
            raise UserError(_('Webhook receipts are server-owned.'))
        return super().create(values)

    def write(self, values):
        if not trusted(self):
            raise UserError(_('Webhook receipts are server-owned.'))
        return super().write(values)

    def unlink(self):
        if not trusted(self):
            raise UserError(_('Webhook receipts are retained.'))
        return super().unlink()
