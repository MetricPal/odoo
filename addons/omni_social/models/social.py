"""Public activity and private social messages have distinct review targets."""

import hashlib
import io
import secrets
import uuid
import time
from datetime import timedelta
from urllib.parse import urlsplit
from PIL import Image
from odoo import api, fields, models, _
from odoo.addons.approval_center.models.common import capability
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.omni_channel.models.foundation import protected_input
from odoo.addons.omni_channel.models.command import digest
from ..providers import vault
from ..providers.registry import provider, capabilities
from ..providers.http import ProviderError

internal, trusted = capability('_social_internal')


def guarded(records, names, values):
    if not trusted(records) and protected_input(records, names, values):
        raise AccessError(_('Use the social review actions.'))


def action(model, domain=None, record=None, context=None):
    return {
        'type': 'ir.actions.act_window',
        'res_model': model,
        'view_mode': 'form' if record or (context or {}).get('default_operation') else 'list,form',
        'res_id': record,
        'domain': domain or [],
        'context': context or {},
        'target': 'current',
    }


class Connection(models.Model):
    _name = 'omni.social.connection'
    _description = 'Social Account'
    _inherit = 'omni.scope.mixin'
    name = fields.Char(required=True)
    provider = fields.Selection(
        [('unavailable', 'Choose platform')], string='Platform', required=True, default='unavailable'
    )
    channel_type_id = fields.Many2one('omni.channel.type', compute='_compute_catalog')

    @api.depends('provider')
    def _compute_catalog(self):
        for row in self:
            row.channel_type_id = self.env['omni.channel.type'].search([('code', '=', row.provider)], limit=1)

    account_kind = fields.Selection(
        [('organization', 'Company Page'), ('person', 'Personal profile')], default='organization', required=True
    )
    active = fields.Boolean(default=True)
    approval_type_id = fields.Many2one('approval.center.policy', string='Approval type', check_company=True)
    public_url = fields.Char(string='Public HTTPS address', help='Used to serve an approved Instagram image to Meta.')
    retention_days = fields.Integer(default=90, required=True, string='Activity retention (days)')
    account_key = fields.Char(readonly=True, copy=False)
    profile_name = fields.Char(readonly=True, copy=False)
    credential_reference = fields.Char(readonly=True, copy=False, groups='omni_channel.group_omni_manager')
    connected = fields.Boolean(readonly=True, copy=False)
    revision = fields.Integer(default=0, readonly=True, copy=False)
    profile = fields.Json(readonly=True, copy=False)
    sync_note = fields.Char(readonly=True, copy=False)
    synced_at = fields.Datetime(readonly=True, copy=False)
    credentials_ui = fields.Json(compute='_compute_ui')
    _protected = {
        'account_key',
        'profile_name',
        'credential_reference',
        'connected',
        'revision',
        'profile',
        'sync_note',
        'synced_at',
    }
    _unique = models.Constraint(
        'UNIQUE(provider,company_id,account_key)', 'This social account is already connected in this company.'
    )

    @api.depends('connected', 'profile_name', 'provider', 'account_kind')
    def _compute_ui(self):
        for row in self:
            row.credentials_ui = {
                'connected': row.connected,
                'name': row.profile_name,
                'provider': row.provider,
                'kind': row.account_kind,
            }

    @api.model_create_multi
    def create(self, values):
        guarded(self, self._protected, values)
        if not self.env.user.has_group('omni_channel.group_omni_manager'):
            raise AccessError(_('Administrator access is required.'))
        return super().create(values)

    def write(self, values):
        guarded(self, self._protected, [values])
        if not trusted(self):
            self._require_manager()
            for row in self:
                row._lock()
                if row.connected and {'company_id', 'purpose_id', 'provider', 'account_kind'} & values.keys():
                    raise UserError(_('Create another account to change its owner or platform.'))
            result = super().write(values)
            if {'active', 'approval_type_id', 'public_url'} & values.keys():
                for row in self:
                    internal(row).write({'revision': row.revision + 1})
            return result
        return super().write(values)

    @api.constrains('retention_days', 'public_url')
    def _check_settings(self):
        for row in self:
            if not 1 <= row.retention_days <= 365:
                raise ValidationError(_('Use 1–365 retention days.'))
            if row.public_url:
                p = urlsplit(row.public_url)
                if (
                    p.scheme != 'https'
                    or not p.hostname
                    or p.username
                    or p.password
                    or p.query
                    or p.fragment
                    or p.path not in ('', '/')
                    or p.port not in (None, 443)
                ):
                    raise ValidationError(_('Enter a public HTTPS address without a path.'))

    def unlink(self):
        self._require_manager()
        if any(self.mapped('connected')):
            raise UserError(_('Archive connected accounts to retain their review history.'))
        return super().unlink()

    def _lock(self):
        self.ensure_one()
        self.flush_recordset()
        # Write barrier serializes stale REPEATABLE READ snapshots against consent/block revocation.
        from odoo.addons.omni_channel.models.inbox import lock_company

        lock_company(self)
        self.env.cr.execute('SELECT id FROM omni_social_connection WHERE id=%s FOR UPDATE', [self.id])
        self.invalidate_recordset()

    def _retire_provider(self):
        # Native addon uninstall archives the connection, preserving publishing evidence.
        for row in self:
            row._lock()
            internal(row).write(
                {'provider': 'unavailable', 'active': False, 'connected': False, 'revision': row.revision + 1}
            )
            row._audit('social.connector_removed', _('Connector removed; account archived and publishing disabled.'))

    def _provider(self):
        return provider(self.env, self.provider)

    def _bundle(self):
        self.ensure_one()
        if not self.connected or not self.active:
            raise UserError(_('Connect an active account first.'))
        return vault.load(
            self.sudo().credential_reference,
            database=self.env.cr.dbname,
            company_id=self.company_id.id,
            purpose_id=self.purpose_id.id,
            provider=self.provider,
            account_key=self.account_key,
        )

    def _caps(self):
        """Declared platform rules (see providers/capabilities.py), or None."""
        self.ensure_one()
        return capabilities(self.provider)

    def action_connect(self, token, account=''):
        self.ensure_one()
        self._require_manager()
        self._lock()
        return self._store_verified(token, account)

    def _store_verified(self, token, account='', extra=None):
        """Verify the token with the platform, then keep it in the encrypted vault.

        ``extra`` carries sign-in details such as a refresh token and expiry.
        """
        try:
            profile = self._provider().verify(token, account, self.account_kind)
        except (ProviderError, ValueError):
            raise UserError(_('Could not verify this account. Check the token, account and app permissions.')) from None
        ref = vault.store(
            {
                'database': self.env.cr.dbname,
                'company_id': self.company_id.id,
                'purpose_id': self.purpose_id.id,
                'provider': self.provider,
                'account_key': profile['id'],
                'token': token,
                'profile': profile,
                **(extra or {}),
            }
        )
        self.env.cr.postrollback.add(lambda: vault.remove(ref, self.env.cr.dbname))
        internal(self).write(
            {
                'credential_reference': ref,
                'connected': True,
                'account_key': profile['id'],
                'profile_name': profile['name'],
                'profile': profile,
                'revision': self.revision + 1,
                'webhook_enabled': False,
                'webhook_pending': False,
                'webhook_route': False,
                'webhook_verify': False,
            }
        )
        self._audit('social.connected', _('Social account verified; publishing still requires approval.'))
        return True

    def action_sync(self):
        self.ensure_one()
        self._require_manager()
        self._lock()
        try:
            items, note = self._provider().read(self._bundle())
        except (ProviderError, ValueError):
            raise UserError(_('Activity could not be read. Check the account permissions and try again.')) from None
        Activity = self.env['omni.social.activity']
        cutoff = fields.Datetime.now() - timedelta(days=self.retention_days)
        for item in items:
            if item.get('occurred_at') and item['occurred_at'] < cutoff:
                continue
            if item['kind'] == 'message' and self.env['omni.blocked.identity']._matches(
                self, self.account_key, item['recipient_key']
            ):
                continue
            vals = {k: v for k, v in item.items() if k in Activity._provider_fields}
            vals['connection_id'] = self.id
            old = Activity.search(
                [
                    ('connection_id', '=', self.id),
                    ('external_key', '=', vals['external_key']),
                    ('kind', '=', vals['kind']),
                ],
                limit=1,
            )
            if old:
                internal(old).write(vals)
            else:
                internal(Activity).create(vals)
        internal(self).write({'synced_at': fields.Datetime.now(), 'sync_note': note})
        self._audit('social.synced', _('Latest account activity imported.'))
        # Retention is applied only to received snapshots, never publishing/approval history.
        self._purge_activity()
        return self.action_activity()

    def _purge_activity(self):
        cutoff = fields.Datetime.now() - timedelta(days=self.retention_days)
        stale = self.env['omni.social.activity'].search(
            [
                ('connection_id', '=', self.id),
                '|',
                ('occurred_at', '<', cutoff),
                '&',
                ('occurred_at', '=', False),
                ('create_date', '<', cutoff),
            ],
            limit=1000,
        )
        internal(stale).unlink()

    @api.model
    def _cron_retention(self):
        for account in self.with_context(active_test=False).search([]):
            account._purge_activity()

    def action_activity(self):
        self.ensure_one()
        self.check_access('read')
        return action('omni.social.activity', [('connection_id', '=', self.id)])

    def action_new_post(self):
        self.ensure_one()
        self.check_access('read')
        return action(
            'omni.social.publication', context={'default_connection_id': self.id, 'default_operation': 'post'}
        )


class Activity(models.Model):
    _name = 'omni.social.activity'
    _description = 'Social Activity'
    _order = 'occurred_at desc,id desc'
    _check_company_auto = True
    connection_id = fields.Many2one(
        'omni.social.connection', string='Account', required=True, ondelete='cascade', check_company=True
    )
    company_id = fields.Many2one(related='connection_id.company_id', store=True)
    purpose_id = fields.Many2one(related='connection_id.purpose_id', store=True)
    provider = fields.Selection(related='connection_id.provider')
    external_key = fields.Char(required=True)
    root_key = fields.Char()
    kind = fields.Selection([('post', 'Post'), ('comment', 'Comment'), ('message', 'Private message')], required=True)
    body = fields.Text(string='Content')
    author = fields.Char()
    recipient_key = fields.Char()
    thread_key = fields.Char()
    occurred_at = fields.Datetime()
    permalink = fields.Char(string='On platform')
    likes = fields.Integer()
    comments = fields.Integer()
    consent = fields.Boolean(readonly=True, copy=False, string='Recipient agreed to replies')
    format = fields.Char(readonly=True, string='Format')
    _provider_fields = {
        'format',
        'external_key',
        'root_key',
        'kind',
        'body',
        'author',
        'recipient_key',
        'thread_key',
        'occurred_at',
        'likes',
        'comments',
        'permalink',
    }

    @api.depends('author', 'body', 'kind')
    def _compute_display_name(self):
        for row in self:
            row.display_name = (
                (row.author or dict(self._fields['kind'].selection).get(row.kind, 'Activity'))
                + ': '
                + (row.body or '')[:80]
            )

    _unique = models.Constraint('UNIQUE(connection_id,kind,external_key)', 'Activity is already recorded.')

    @api.model_create_multi
    def create(self, values):
        if not trusted(self):
            raise AccessError(_('Activity is imported from the social account.'))
        return super().create(values)

    def write(self, values):
        if not trusted(self):
            raise AccessError(_('Imported activity is read-only.'))
        return super().write(values)

    def unlink(self):
        if not trusted(self):
            raise AccessError(_('Activity follows its account retention policy.'))
        return super().unlink()

    def action_consent(self):
        self.ensure_one()
        self.check_access('read')
        self.connection_id._require_manager()
        self.connection_id._lock()
        if self.kind != 'message':
            raise UserError(_('Consent applies to private messages.'))
        # Consent is tied to this received message and is never inferred from sending a DM.
        internal(self).write({'consent': True})
        self.connection_id._audit('social.consent', _('Manager confirmed recipient agreement for private replies.'))

    def action_revoke(self):
        self.ensure_one()
        self.check_access('read')
        self.connection_id._require_manager()
        self.connection_id._lock()
        internal(self).write({'consent': False})
        self.connection_id._audit('social.consent_revoked', _('Private reply authorization revoked.'))

    def action_reply(self):
        self.ensure_one()
        self.check_access('read')
        return action(
            'omni.social.publication',
            context={
                'default_connection_id': self.connection_id.id,
                'default_target_id': self.id,
                'default_operation': 'message' if self.kind == 'message' else 'reply',
            },
        )


class Publication(models.Model):
    _name = 'omni.social.publication'
    _description = 'Social Publication'
    _inherit = 'omni.scope.mixin'
    _order = 'create_date desc,id desc'
    name = fields.Char(required=True, string='Subject')
    connection_id = fields.Many2one(
        'omni.social.connection', string='Account', required=True, ondelete='restrict', check_company=True
    )
    company_id = fields.Many2one(related='connection_id.company_id', store=True, precompute=True)
    purpose_id = fields.Many2one(related='connection_id.purpose_id', store=True, precompute=True)
    provider = fields.Selection(related='connection_id.provider')
    operation = fields.Selection(
        [('post', 'Post'), ('reply', 'Public reply'), ('message', 'Private reply')],
        string='Action',
        default='post',
        required=True,
    )
    target_id = fields.Many2one('omni.social.activity', string='Reply to', ondelete='set null', check_company=True)
    body = fields.Text(string='Content')
    image = fields.Binary(string='Photo', attachment=False)
    format = fields.Selection(
        [('standard', 'Post'), ('carousel', 'Carousel'), ('reel', 'Reel'), ('story', 'Story')],
        default='standard',
        required=True,
    )
    media_ids = fields.One2many('omni.social.media', 'publication_id', string='Media', copy=True)
    reason = fields.Text(string='Reason', required=True)
    requester_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True, required=True)
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('pending', 'In review'),
            ('approved', 'Approved'),
            ('executing', 'Publishing'),
            ('waiting', 'Processing media'),
            ('sent', 'Published'),
            ('failed', 'Not sent'),
            ('unknown', 'Check platform'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft',
        readonly=True,
        copy=False,
    )
    approval_request_id = fields.Many2one('approval.center.request', readonly=True, copy=False, ondelete='restrict')
    payload = fields.Json(readonly=True, copy=False)
    payload_hash = fields.Char(readonly=True, copy=False)
    policy_hash = fields.Char(readonly=True, copy=False)
    expires_at = fields.Datetime(readonly=True, copy=False)
    container_key = fields.Char(readonly=True, copy=False)
    result_key = fields.Char(readonly=True, copy=False, string='Platform reference')
    result_note = fields.Char(readonly=True, copy=False)
    media_token = fields.Char(readonly=True, copy=False, groups='omni_channel.group_omni_manager')
    claim_key = fields.Char(readonly=True, copy=False)
    _protected = {
        'company_id',
        'purpose_id',
        'requester_id',
        'state',
        'approval_request_id',
        'payload',
        'payload_hash',
        'policy_hash',
        'expires_at',
        'container_key',
        'result_key',
        'result_note',
        'media_token',
        'claim_key',
    }

    @api.onchange('format')
    def _onchange_format(self):
        if self.format == 'story':
            self.body = False
        caps = capabilities(self.connection_id.provider)
        if caps and self.format not in caps.formats:
            self.format = caps.formats[0]

    @api.onchange('connection_id')
    def _onchange_account(self):
        if self.target_id and self.target_id.connection_id != self.connection_id:
            self.target_id = False
        caps = capabilities(self.connection_id.provider)
        if caps:
            if self.operation not in caps.operations:
                self.operation = 'post'
            if self.format not in caps.formats:
                self.format = caps.formats[0]

    @api.model_create_multi
    def create(self, values):
        guarded(self, self._protected, values)
        rows = super().create(values)
        for row in rows:
            row.connection_id.check_access('read')
            row._check_target()
        return rows

    def write(self, values):
        guarded(self, self._protected, [values])
        if not trusted(self):
            for row in self:
                row._lock()
                if row.state != 'draft' or row.requester_id != self.env.user:
                    raise AccessError(_('Only the owner can edit a draft.'))
        result = super().write(values)
        for row in self:
            row._check_target()
        return result

    def unlink(self):
        if any(r.state != 'draft' or r.requester_id != self.env.user for r in self):
            raise AccessError(_('Review and publishing history is retained.'))
        return super().unlink()

    def copy(self, default=None):
        self.ensure_one()
        self.check_access('read')
        return self.create(
            {
                'name': self.name,
                'connection_id': self.connection_id.id,
                'operation': self.operation,
                'target_id': self.target_id.id,
                'body': self.body,
                'image': self.image,
                'format': self.format,
                'media_ids': [
                    fields.Command.create(
                        {'sequence': m.sequence, 'name': m.name, 'kind': m.kind, 'file': m.file, 'alt_text': m.alt_text}
                    )
                    for m in self.media_ids
                ],
                'reason': self.reason,
                **(default or {}),
            }
        )

    def _lock(self):
        self.ensure_one()
        self.connection_id._lock()
        self.flush_recordset()
        self.env.cr.execute('SELECT id FROM omni_social_publication WHERE id=%s FOR UPDATE', [self.id])
        self.invalidate_recordset()

    def _check_target(self):
        if self.target_id:
            self.target_id.check_access('read')
            if self.target_id.connection_id != self.connection_id:
                raise ValidationError(_('The reply must belong to this account.'))

    def _policy(self):
        policy = self.connection_id.approval_type_id
        if (
            not policy
            or not policy.active
            or policy.company_id != self.company_id
            or policy.manager_approval
            or policy.model
        ):
            raise UserError(
                _('Choose a company approval type with explicitly assigned approvers and no backend action.')
            )
        lines = policy.sudo().approver_ids.sorted(lambda r: (r.sequence, r.id))
        if not lines or policy.approval_minimum > len(lines):
            raise UserError(_('Configure enough approvers.'))
        for line in lines:
            user = line.user_id
            if (
                user == self.requester_id
                or not user.active
                or user.share
                or user not in self.purpose_id.user_ids
                or self.company_id not in user.company_ids
                or not user.has_group('approval_center.group_approval_center_approver')
            ):
                raise UserError(_('Approvers must be other authorized internal team members.'))
        return {
            'id': policy.id,
            'version': str(policy.write_date),
            'minimum': policy.approval_minimum,
            'sequence': policy.approver_sequence,
            'approvers': [(l.user_id.id, l.sequence, l.required) for l in lines],
        }

    def _document(self, media_token):
        target = self.target_id
        if (
            (self.format != 'story' and (not self.body or not self.body.strip()))
            or not self.reason
            or not self.reason.strip()
        ):
            raise UserError(_('Enter content and a reason.'))
        if self.operation != 'post' and not target:
            raise UserError(_('Choose the received activity to reply to.'))
        if self.operation == 'message':
            if self.env['omni.blocked.identity']._matches(
                self.connection_id, self.connection_id.account_key, target.recipient_key
            ):
                raise UserError(_('This recipient is blocked.'))
            if (
                target.kind != 'message'
                or not target.consent
                or not target.occurred_at
                or target.occurred_at < fields.Datetime.now() - timedelta(hours=24)
            ):
                raise UserError(_('A recent incoming message and recipient agreement are required.'))
        elif self.operation == 'reply' and (target.kind not in ('post', 'comment') or target.format == 'STORY'):
            raise UserError(_('Choose a public post or comment.'))
        image_digest = ''
        media_url = ''
        if self.image:
            if self.provider != 'instagram' or self.operation != 'post' or self.format != 'standard' or self.media_ids:
                raise UserError(_('Use Media for this format; remove the separate photo.'))
            raw = self.image.content
            if len(raw) > 8 * 1024 * 1024:
                raise UserError(_('Use a JPEG photo smaller than 8 MB.'))
            try:
                with Image.open(io.BytesIO(raw)) as photo:
                    if photo.format != 'JPEG' or photo.width * photo.height > 24000000:
                        raise ValueError('photo')
                    photo.verify()
            except Exception:
                raise UserError(_('Upload a valid JPEG photo.')) from None
            if not self.connection_id.public_url:
                raise UserError(_('Set the account’s public HTTPS address for photo publishing.'))
            image_digest = hashlib.sha256(raw).hexdigest()
            media_url = self.connection_id.public_url.rstrip('/') + '/omni/social/media/' + media_token
        media = [
            m._manifest(media_token, index)
            for index, m in enumerate(self.media_ids.sorted(lambda m: (m.sequence, m.id)))
        ]
        if media and (self.operation != 'post' or self.image):
            raise UserError(_('Media belongs to posts only.'))
        if self.format != 'standard' and self.operation != 'post':
            raise UserError(_('Choose Post for replies.'))
        self._check_capabilities(media)
        doc = {
            'format': self.format,
            'media': media,
            'connection': self.connection_id.id,
            'revision': self.connection_id.revision,
            'provider': self.provider,
            'account': self.connection_id.account_key,
            'operation': self.operation,
            'body': self.body or '',
            'target_content': target.body or '',
            'target_author': target.author or '',
            'target': target.external_key or '',
            'root': target.root_key or target.external_key or '',
            'thread': target.thread_key or '',
            'recipient': target.recipient_key or '',
            'media_url': media_url,
            'image_digest': image_digest,
        }
        # Preserve the already-reviewed legacy single-photo/text document shape.
        if self.payload and 'format' not in self.payload and self.format == 'standard' and not media:
            doc.pop('format')
            doc.pop('media')
        try:
            self.connection_id._provider().validate(doc)
        except ValueError:
            raise UserError(
                _('This platform does not support the selected action or content. Check the content and photo.')
            ) from None
        return doc

    def _check_capabilities(self, media):
        """Apply the platform's declared rules with messages a person can act on."""
        caps = self.connection_id._caps()
        if not caps:
            return
        label = caps.label
        if self.operation not in caps.operations:
            raise UserError(
                _('%(platform)s does not support this action. Choose: %(allowed)s.',
                  platform=label,
                  allowed=', '.join(dict(self._fields['operation'].selection)[o] for o in caps.operations
                                    if o in dict(self._fields['operation'].selection)))
            )
        if self.operation == 'post' and self.format not in caps.formats:
            raise UserError(_('%(platform)s does not support this format.', platform=label))
        limit = caps.limit_for(self.operation)
        if len(self.body or '') > limit:
            raise UserError(
                _('%(platform)s allows up to %(limit)s characters; this text has %(count)s.',
                  platform=label, limit=limit, count=len(self.body or ''))
            )
        if self.operation == 'post':
            count = len(media) + (1 if self.image else 0)
            if caps.media_required and not count:
                raise UserError(_('%(platform)s posts need a photo or video.', platform=label))
            if count > caps.max_media:
                raise UserError(
                    _('%(platform)s allows up to %(limit)s files in one post.', platform=label, limit=caps.max_media)
                )
            if any(item['kind'] not in caps.media_kinds for item in media):
                raise UserError(_('%(platform)s does not accept this kind of file.', platform=label))

    def action_submit(self):
        self.ensure_one()
        self.check_access('write')
        self._lock()
        self.connection_id._lock()
        if self.state != 'draft' or self.requester_id != self.env.user:
            raise AccessError(_('Only the draft owner can submit.'))
        self.connection_id._bundle()
        policy = self._policy()
        token = secrets.token_urlsafe(32)
        doc = self._document(token)
        request = internal(self.env['approval.center.request']).create(
            {
                'name': self.name,
                'policy_id': policy['id'],
                'company_id': self.company_id.id,
                'requester_id': self.env.uid,
                'social_publication_id': self.id,
                'target_model': self._name,
                'target_res_id': self.id,
                'reason': self.reason,
                'state': 'submitted',
                'approver_ids': [
                    fields.Command.create(
                        {'user_id': uid, 'sequence': seq, 'required': required, 'status': 'submitted'}
                    )
                    for uid, seq, required in policy['approvers']
                ],
            }
        )
        request._check_required_fields()
        request._audit('submitted', _('Social content submitted for review.'))
        internal(self.sudo()).write(
            {
                'state': 'pending',
                'approval_request_id': request.id,
                'payload': doc,
                'payload_hash': digest(doc),
                'policy_hash': digest(policy),
                'media_token': token,
                'expires_at': fields.Datetime.now() + timedelta(hours=24),
            }
        )
        self._audit('social.submitted', _('Exact content, account and destination frozen for review.'))
        return self.action_approval()

    def _frozen(self):
        self.connection_id._lock()
        self.connection_id.with_user(self.requester_id).with_context(
            allowed_company_ids=[self.company_id.id]
        ).check_access('read')
        if (
            not self.requester_id.active
            or not self.connection_id.active
            or not self.connection_id.connected
            or not self.expires_at
            or self.expires_at <= fields.Datetime.now()
            or self.payload_hash != digest(self.payload)
            or self.policy_hash != digest(self._policy())
            or self.payload['revision'] != self.connection_id.revision
        ):
            raise UserError(_('This review expired or its account settings changed. Duplicate it for a new review.'))
        if self.payload != self._document(self.sudo().media_token):
            raise UserError(_('The approved content or recipient authorization changed.'))

    def action_approval(self):
        self.ensure_one()
        self.check_access('read')
        return action('approval.center.request', record=self.approval_request_id.id)

    def action_cancel(self):
        self.ensure_one()
        self.check_access('read')
        self._lock()
        if self.requester_id != self.env.user or self.state not in (
            'draft',
            'pending',
            'approved',
            'waiting',
            'failed',
        ):
            raise AccessError(_('This publication cannot be cancelled.'))
        internal(self).write({'state': 'cancelled'})
        self._audit('social.cancelled', _('Publication cancelled.'))

    def _claim(self):
        self.check_access('read')
        self._lock()
        self._frozen()
        if self.state not in ('approved', 'waiting'):
            raise UserError(_('Only an approved, unsent action can publish.'))
        if self.state == 'approved':
            # Daily platform caps and the monthly budget are checked before the first call only.
            self.connection_id._check_quota(self.operation, self.payload)
        req = self.approval_request_id
        approved = req.sudo().approver_ids.filtered(lambda l: l.status == 'approved')
        policy = self._policy()
        if (
            req.state != 'approved'
            or len(approved) < policy['minimum']
            or not {u for u, s, r in policy['approvers'] if r}.issubset(set(approved.user_id.ids))
        ):
            raise AccessError(_('Required approvals are missing.'))
        key = uuid.uuid4().hex
        internal(self).write({'state': 'executing', 'claim_key': key, 'result_note': False})
        self._audit('social.claimed', _('Publishing attempt recorded before contacting the platform.'))
        bundle = self.connection_id._bundle()
        caps = self.connection_id._caps()
        if caps and caps.upload_bytes:
            bundle = {**bundle, 'media_bytes': {m.id: m.file.content for m in self.media_ids}}
        return key, self.payload, bundle, self.container_key

    def action_publish(self):
        # Commit each accepted preparation stage before starting the next provider mutation.
        started = time.monotonic()
        for unused in range(45):
            result = self._publish_step()
            if not result.pop('_social_continue', False) or time.monotonic() - started > 40:
                break
        return result

    def _publish_step(self):
        """Independent committed claim prevents duplicate POST after outer RPC rollback."""
        self.ensure_one()
        self.check_access('read')
        uid = self.env.uid
        context = {'allowed_company_ids': self.env.companies.ids, 'lang': self.env.lang}
        with self.env.registry.cursor() as cr:
            row = api.Environment(cr, uid, context)[self._name].browse(self.id)
            key, doc, bundle, container = row._claim()
            adapter = row.connection_id._provider()
            cr.commit()
        try:
            outcome, result, note = adapter.execute(bundle, doc, container)
        except Exception:
            outcome, result, note = 'unknown', '', 'Check the platform before taking further action.'
        with self.env.registry.cursor() as cr:
            row = api.Environment(cr, uid, context)[self._name].browse(self.id)
            row._lock()
            if row.claim_key != key or row.state != 'executing':
                raise UserError(_('Publishing attempt changed.'))
            if outcome not in ('sent', 'waiting', 'failed', 'unknown'):
                outcome = 'unknown'
            values = {'state': outcome, 'result_note': note}
            if outcome == 'sent':
                values['published_at'] = fields.Datetime.now()
            values['container_key' if outcome == 'waiting' else 'result_key'] = result
            internal(row).write(values)
            if outcome in ('sent', 'unknown'):
                # An uncertain result may have reached the platform: count it.
                row.connection_id._record_usage(row, doc)
            if outcome == 'sent':
                row._social_sent()
            request = row.approval_request_id
            if outcome == 'sent':
                internal(request.sudo()).write({'executed_at': fields.Datetime.now()})
            request._audit(
                'executed' if outcome == 'sent' else 'failed' if outcome in ('failed', 'unknown') else 'submitted',
                _('Social platform result recorded.'),
                result=outcome,
            )
            row._audit('social.' + outcome, _('Platform result recorded.'))
            cr.commit()
        self.invalidate_recordset()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
            '_social_continue': outcome == 'waiting' and note == 'Preparing media.',
        }
