"""Scheduling, the planning board and campaign posts.

Scheduled publishing (decision 2 of the plan): the publish time is part of the
content the approver reviews. The approval then stays valid until that time
plus a short grace period, and at most 14 days after submission; changing the
time voids it like any other edit. A cron publishes approved posts when they
are due, as the person who requested them. Nothing publishes early.

Campaigns: one brief, one version per account. Each version keeps its own
frozen approval evidence; the campaign gives the reviewer one screen and one
"Approve all" button that approves each version they are assigned to.
"""

import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from .social import internal, trusted, guarded, Publication as BasePublication
from ..providers.registry import capabilities

_logger = logging.getLogger(__name__)

MAX_SCHEDULE_DAYS = 14
GRACE = timedelta(hours=2)
CRON_BATCH = 10

STAGES = [
    ('draft', 'Draft'),
    ('review', 'In review'),
    ('scheduled', 'Scheduled'),
    ('ready', 'Ready to publish'),
    ('published', 'Published'),
    ('attention', 'Needs attention'),
    ('cancelled', 'Cancelled'),
]


class Publication(models.Model):
    _inherit = 'omni.social.publication'

    scheduled_at = fields.Datetime(
        string='Publish at',
        copy=False,
        help='Leave empty to publish by hand after approval. Approved posts with a time publish automatically.',
    )
    published_at = fields.Datetime(readonly=True, copy=False)
    stage = fields.Selection(
        STAGES, compute='_compute_stage', store=True, group_expand='_expand_stages', string='Stage'
    )
    calendar_date = fields.Datetime(compute='_compute_calendar_date', store=True, string='Date')
    campaign_id = fields.Many2one('omni.social.campaign', ondelete='set null', index=True, copy=False)
    limit_note = fields.Char(compute='_compute_limit_note')
    _protected = BasePublication._protected | {'published_at'}

    @api.depends('state', 'scheduled_at')
    def _compute_stage(self):
        for row in self:
            state = row.state
            if state == 'draft':
                row.stage = 'draft'
            elif state == 'pending':
                row.stage = 'review'
            elif state in ('approved', 'executing', 'waiting'):
                row.stage = 'scheduled' if row.scheduled_at else 'ready'
            elif state == 'sent':
                row.stage = 'published'
            elif state in ('failed', 'unknown'):
                row.stage = 'attention'
            else:
                row.stage = 'cancelled'

    @api.model
    def _expand_stages(self, stages, domain):
        return [key for key, _label in STAGES if key != 'cancelled']

    @api.depends('published_at', 'scheduled_at', 'create_date')
    def _compute_calendar_date(self):
        for row in self:
            row.calendar_date = row.published_at or row.scheduled_at or row.create_date or fields.Datetime.now()

    @api.depends('body', 'connection_id', 'operation')
    def _compute_limit_note(self):
        for row in self:
            caps = capabilities(row.connection_id.provider)
            count = len(row.body or '')
            limit = caps.limit_for(row.operation) if caps else 0
            row.limit_note = (
                _('%(platform)s: %(count)s of %(limit)s characters', platform=caps.label, count=count, limit=limit)
                if caps and count > limit
                else ''
            )

    @api.constrains('scheduled_at')
    def _check_schedule(self):
        for row in self:
            if row.scheduled_at and row.state == 'draft' and row.scheduled_at < fields.Datetime.now() - timedelta(minutes=1):
                raise UserError(_('Choose a publish time in the future.'))

    def _document(self, media_token):
        doc = super()._document(media_token)
        if self.scheduled_at:
            # The approver reviews the time too; changing it voids the approval.
            doc['scheduled_at'] = fields.Datetime.to_string(self.scheduled_at)
        return doc

    def action_submit(self):
        self.ensure_one()
        now = fields.Datetime.now()
        if self.scheduled_at:
            if self.scheduled_at <= now:
                raise UserError(_('The publish time has passed. Choose a new time or clear it.'))
            if self.scheduled_at > now + timedelta(days=MAX_SCHEDULE_DAYS):
                raise UserError(
                    _('Submit for approval at most %(days)s days before the publish time, so the review stays current.',
                      days=MAX_SCHEDULE_DAYS)
                )
        result = super().action_submit()
        if self.scheduled_at:
            internal(self.sudo()).write({'expires_at': max(self.expires_at, self.scheduled_at + GRACE)})
        return result

    def _claim(self):
        if self.scheduled_at and self.state == 'approved' and fields.Datetime.now() < self.scheduled_at:
            raise UserError(
                _('Scheduled for %(when)s; it publishes automatically then.',
                  when=fields.Datetime.context_timestamp(self, self.scheduled_at).strftime('%Y-%m-%d %H:%M'))
            )
        return super()._claim()

    @api.model
    def _cron_publish_scheduled(self):
        """Publish approved posts that are due, each as its requester."""
        due = self.sudo().search(
            # 'waiting' = media still processing on the platform; publishing continues it.
            [('state', 'in', ('approved', 'waiting')), ('scheduled_at', '!=', False),
             ('scheduled_at', '<=', fields.Datetime.now())],
            order='scheduled_at, id',
            limit=CRON_BATCH,
        )
        for row in due:
            actor = row.with_user(row.requester_id).with_context(allowed_company_ids=[row.company_id.id])
            try:
                actor.action_publish()
            except (UserError, AccessError) as failure:
                # Left approved: the next run retries until the review expires.
                message = str(failure.args[0] if failure.args else failure)
                internal(row).write({'result_note': _('Waiting to publish: %(reason)s', reason=message)[:250]})
                self.env.cr.commit()
            except Exception:
                _logger.exception('Scheduled social publication %s failed', row.id)
                self.env.cr.rollback()


class Campaign(models.Model):
    _name = 'omni.social.campaign'
    _description = 'Social Campaign'
    _inherit = 'omni.scope.mixin'
    _order = 'create_date desc, id desc'

    name = fields.Char(required=True)
    brief = fields.Text(string='Text', required=True, help='Starting text for every version; adapt each one to its platform.')
    reason = fields.Text(
        required=True, string='Note for the approver',
        help='Why this campaign goes out and anything the approver should check. Only approvers see it.',
    )
    scheduled_at = fields.Datetime(string='Publish at')
    purpose_id = fields.Many2one(default=lambda self: self.env['omni.social.connection']._default_social_team())
    connection_ids = fields.Many2many(
        'omni.social.connection', string='Accounts', check_company=True,
        domain="[('connected', '=', True), ('active', '=', True), ('purpose_id', '=', purpose_id), ('company_id', '=', company_id)]",
    )
    publication_ids = fields.One2many('omni.social.publication', 'campaign_id', string='Versions')
    requester_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True, required=True)
    version_count = fields.Integer(compute='_compute_progress')
    progress = fields.Char(compute='_compute_progress')
    state = fields.Selection(
        [('draft', 'Draft'), ('review', 'In review'), ('approved', 'Approved'), ('done', 'Published'),
         ('attention', 'Needs attention')],
        compute='_compute_progress',
    )
    can_approve = fields.Boolean(compute='_compute_can_approve')
    missing_versions = fields.Boolean(compute='_compute_missing_versions')

    @api.depends('connection_ids', 'publication_ids.connection_id', 'publication_ids.state')
    def _compute_missing_versions(self):
        for row in self:
            have = row.publication_ids.filtered(lambda p: p.state != 'cancelled').connection_id
            row.missing_versions = bool(row.connection_ids - have)

    @api.depends('publication_ids.stage')
    def _compute_progress(self):
        labels = dict(STAGES)
        for row in self:
            versions = row.publication_ids.filtered(lambda p: p.stage != 'cancelled')
            row.version_count = len(versions)
            counts = {}
            for stage in versions.mapped('stage'):
                counts[stage] = counts.get(stage, 0) + 1
            row.progress = ', '.join('%s %s' % (n, labels[s].lower()) for s, n in counts.items())
            stages = set(versions.mapped('stage'))
            if not versions or 'draft' in stages:
                row.state = 'draft'
            elif 'attention' in stages:
                row.state = 'attention'
            elif 'review' in stages:
                row.state = 'review'
            elif stages == {'published'}:
                row.state = 'done'
            else:
                row.state = 'approved'

    @api.depends_context('uid')
    @api.depends('publication_ids.state')
    def _compute_can_approve(self):
        for row in self:
            row.can_approve = bool(row._my_reviews())

    def _my_reviews(self):
        self.ensure_one()
        requests = self.publication_ids.filtered(lambda p: p.state == 'pending').approval_request_id
        return requests.filtered(
            lambda r: r.state == 'submitted'
            and r.sudo().approver_ids.filtered(lambda l: l.user_id == self.env.user and l.status == 'submitted')
        )

    @api.model_create_multi
    def create(self, values):
        guarded(self, {'requester_id'}, values)
        return super().create(values)

    def write(self, values):
        guarded(self, {'requester_id'}, [values])
        if not trusted(self) and any(r.requester_id != self.env.user for r in self):
            if set(values) - {'connection_ids'}:
                raise AccessError(_('Only the person who started the campaign can change it.'))
        return super().write(values)

    def action_create_versions(self):
        """One draft per selected account that does not have one yet."""
        self.ensure_one()
        self.check_access('write')
        if not self.connection_ids:
            raise UserError(_('Choose the accounts to post to.'))
        have = self.publication_ids.filtered(lambda p: p.state != 'cancelled').connection_id
        Publication = self.env['omni.social.publication']
        for account in self.connection_ids - have:
            Publication.create({
                'name': '%s · %s' % (self.name, account.name),
                'connection_id': account.id,
                'operation': 'post',
                'body': self.brief,
                'reason': self.reason,
                'scheduled_at': self.scheduled_at,
                'campaign_id': self.id,
            })
        return True

    def action_submit_all(self):
        self.ensure_one()
        drafts = self.publication_ids.filtered(lambda p: p.state == 'draft' and p.requester_id == self.env.user)
        if not drafts:
            raise UserError(_('There are no drafts of yours to submit.'))
        for version in drafts:
            try:
                version.action_submit()
            except UserError as failure:
                raise UserError(
                    _('%(account)s: %(reason)s', account=version.connection_id.name,
                      reason=failure.args[0] if failure.args else failure)
                ) from None
        return True

    def action_approve_all(self):
        """Approve every version this reviewer is assigned to; each decision is checked and audited."""
        self.ensure_one()
        reviews = self._my_reviews()
        if not reviews:
            raise UserError(_('Nothing here is waiting for your approval.'))
        for request in reviews:
            request.action_approve()
        return True

    def action_publish_ready(self):
        """Publish approved versions without a time (scheduled ones publish on their own)."""
        self.ensure_one()
        ready = self.publication_ids.filtered(lambda p: p.state in ('approved', 'waiting') and not p.scheduled_at)
        if not ready:
            raise UserError(_('No approved version is waiting to be published by hand.'))
        for version in ready:
            version.action_publish()
        return True


class Request(models.Model):
    _inherit = 'approval.center.request'

    social_scheduled_at = fields.Datetime(related='social_publication_id.scheduled_at', string='Publishes automatically at')
    social_campaign_id = fields.Many2one(related='social_publication_id.campaign_id', string='Campaign')
