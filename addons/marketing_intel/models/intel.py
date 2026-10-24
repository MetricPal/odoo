"""Marketing intelligence, phase 1: approved sources, recurring collection, evidence and briefs.

Nothing is collected from a source or about a competitor until an
administrator approves it; changing its address sends it back for approval.
Every collection is stored as dated evidence (address, time, hash, text) and
compared with the previous one. Findings are facts ("this page changed", "new
item in this feed"), never model output. The weekly brief is a Report Studio
report built from those facts.
"""

import difflib
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from . import collector

APPROVAL = [('proposed', 'Waiting for approval'), ('approved', 'Approved'), ('paused', 'Paused'),
            ('rejected', 'Rejected')]


def is_manager(env):
    return env.user.has_group('marketing_intel.group_mi_manager')


class Brand(models.Model):
    _name = 'mi.brand'
    _description = 'Brand profile'
    _inherit = ['mail.thread']

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    offering = fields.Text(string='What we sell', help='Products or services, in a few lines.')
    audience = fields.Text(string='Who we sell to', help='Ideal customers and segments.')
    value_proposition = fields.Text(string='Why customers choose us')
    tone = fields.Char(string='Brand voice', help='e.g. friendly, expert, playful')
    markets = fields.Char(help='Countries or regions, e.g. Malaysia, Singapore')
    monthly_budget = fields.Monetary(currency_field='currency_id', string='Monthly marketing budget')
    research_interval = fields.Integer(default=7, string='Research every (days)')
    next_research_at = fields.Datetime(string='Next research', copy=False)
    goal_ids = fields.One2many('mi.goal', 'brand_id', string='Goals')
    competitor_ids = fields.One2many('mi.competitor', 'brand_id', string='Competitors')
    source_ids = fields.One2many('mi.source', 'brand_id', string='Sources')
    run_ids = fields.One2many('mi.run', 'brand_id', string='Research runs')
    approved_source_count = fields.Integer(compute='_compute_counts')
    open_finding_count = fields.Integer(compute='_compute_counts')

    def _compute_counts(self):
        for brand in self:
            brand.approved_source_count = len(brand.source_ids.filtered(lambda s: s.state == 'approved'))
            brand.open_finding_count = self.env['mi.finding'].search_count(
                [('brand_id', '=', brand.id), ('state', '=', 'new')])

    def action_run_research(self):
        self.ensure_one()
        self.check_access('read')
        run = self.sudo()._research()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.run', 'res_id': run.id, 'view_mode': 'form'}

    def _research(self):
        """Collect every approved source once, record evidence and findings, build the brief."""
        self.ensure_one()
        run = self.env['mi.run'].create({'brand_id': self.id})
        for source in self.source_ids.filtered(lambda s: s.state == 'approved'):
            source._collect(run)
        run._finish()
        days = max(self.research_interval or 7, 1)
        self.next_research_at = fields.Datetime.now() + timedelta(days=days)
        return run

    @api.model
    def _cron_research(self):
        due = self.search(['|', ('next_research_at', '=', False), ('next_research_at', '<=', fields.Datetime.now()),
                           ('source_ids.state', '=', 'approved')])
        for brand in due:
            brand._research()
            self.env.cr.commit()


class Goal(models.Model):
    _name = 'mi.goal'
    _description = 'Marketing goal'
    _order = 'date_end, id'

    brand_id = fields.Many2one('mi.brand', required=True, ondelete='cascade')
    name = fields.Char(required=True, help='e.g. New leads from social')
    metric = fields.Char(help='How it is measured, e.g. leads per month')
    target = fields.Float()
    current = fields.Float(string='Current value')
    date_start = fields.Date(string='From')
    date_end = fields.Date(string='To')
    progress = fields.Float(compute='_compute_progress', string='Progress (%)')

    @api.depends('target', 'current')
    def _compute_progress(self):
        for goal in self:
            goal.progress = 100.0 * goal.current / goal.target if goal.target else 0.0


class ApprovalMixin(models.AbstractModel):
    _name = 'mi.approval.mixin'
    _description = 'Approved by an administrator before use'

    state = fields.Selection(APPROVAL, required=True, default='proposed', tracking=True, readonly=True, string='Status')
    approval_note = fields.Text(string='Why we trust it',
                                help='Why this is a fair source of truth, and that collecting it is allowed '
                                     '(public page, terms of use, no login).')
    approved_by = fields.Many2one('res.users', readonly=True)
    approved_at = fields.Datetime(readonly=True)

    def _set_state(self, state):
        if not is_manager(self.env):
            raise AccessError(_('Only a Marketing Intelligence administrator can approve, pause or reject.'))
        values = {'state': state}
        if state == 'approved':
            values.update(approved_by=self.env.uid, approved_at=fields.Datetime.now())
        self.sudo().with_context(mi_approval=True).write(values)
        for row in self:
            row.message_post(body=_('%(state)s by %(user)s.', state=dict(APPROVAL)[state], user=self.env.user.name))

    def action_approve(self):
        if not is_manager(self.env):
            raise AccessError(_('Only a Marketing Intelligence administrator can approve, pause or reject.'))
        for row in self:
            if not (row.approval_note or '').strip():
                raise UserError(_('Explain why “%s” can be trusted and collected before approving it.', row.display_name))
        self._set_state('approved')

    def action_pause(self):
        self._set_state('paused')

    def action_reject(self):
        self._set_state('rejected')

    def write(self, vals):
        if not self.env.context.get('mi_approval') and {'state', 'approved_by', 'approved_at'} & vals.keys():
            raise AccessError(_('Use Approve, Pause or Reject.'))
        return super().write(vals)


class Competitor(models.Model):
    _name = 'mi.competitor'
    _description = 'Competitor'
    _inherit = ['mi.approval.mixin', 'mail.thread']
    _order = 'name'

    brand_id = fields.Many2one('mi.brand', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='brand_id.company_id', store=True)
    name = fields.Char(required=True, tracking=True)
    website = fields.Char()
    notes = fields.Text(help='Positioning, products, prices: what we know.')
    source_ids = fields.One2many('mi.source', 'competitor_id', string='Sources')
    finding_count = fields.Integer(compute='_compute_finding_count')

    def _compute_finding_count(self):
        for row in self:
            row.finding_count = self.env['mi.finding'].search_count([('competitor_id', '=', row.id)])


class Source(models.Model):
    _name = 'mi.source'
    _description = 'Source of truth'
    _inherit = ['mi.approval.mixin', 'mail.thread']
    _order = 'brand_id, competitor_id, name'

    brand_id = fields.Many2one('mi.brand', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='brand_id.company_id', store=True)
    competitor_id = fields.Many2one('mi.competitor', ondelete='set null', domain="[('brand_id', '=', brand_id)]",
                                    help='Leave empty for market sources (news, industry, our own site).')
    name = fields.Char(required=True, help='e.g. Competitor pricing page')
    url = fields.Char(required=True, tracking=True, string='Address', help='Full HTTPS address.')
    kind = fields.Selection([('page', 'Web page'), ('rss', 'News feed (RSS/Atom)')], required=True, default='page')
    snapshot_ids = fields.One2many('mi.snapshot', 'source_id', string='Evidence')
    last_collected_at = fields.Datetime(readonly=True)
    last_error = fields.Char(readonly=True)
    change_count = fields.Integer(compute='_compute_change_count', string='Changes found')

    def _compute_change_count(self):
        for row in self:
            row.change_count = self.env['mi.finding'].search_count([('source_id', '=', row.id), ('kind', '!=', 'error')])

    def write(self, vals):
        result = super().write(vals)
        if {'url', 'kind'} & vals.keys():
            # A new address is a new source of truth: it needs approval again.
            moved = self.filtered(lambda s: s.state == 'approved')
            if moved:
                moved.sudo().with_context(mi_approval=True).write({'state': 'proposed', 'approved_by': False,
                                                                   'approved_at': False})
                for row in moved:
                    row.message_post(body=_('Address changed: waiting for approval again.'))
        return result

    def _collect(self, run):
        """One collection: evidence snapshot plus findings for what changed."""
        self.ensure_one()
        Finding = self.env['mi.finding']
        base = {'run_id': run.id, 'brand_id': self.brand_id.id, 'source_id': self.id,
                'competitor_id': self.competitor_id.id}
        try:
            result = collector.fetch(self.url, self.kind)
        except collector.CollectError as error:
            self.write({'last_error': str(error), 'last_collected_at': fields.Datetime.now()})
            Finding.create(dict(base, kind='error', title=_('Could not collect %s', self.name), summary=str(error)))
            return
        previous = self.snapshot_ids[:1]
        changed = bool(previous) and previous.content_hash != result.digest
        snapshot = self.env['mi.snapshot'].create({
            'source_id': self.id, 'run_id': run.id, 'url': result.url, 'status_code': result.status,
            'title': result.title[:500], 'text': result.text, 'content_hash': result.digest, 'changed': changed,
        })
        self.write({'last_error': False, 'last_collected_at': fields.Datetime.now()})
        if not previous:
            Finding.create(dict(base, snapshot_id=snapshot.id, kind='baseline',
                                title=_('First evidence of %s', self.name),
                                summary=_('%s lines recorded. Changes are reported from the next research.',
                                          len(result.lines))))
            return
        if not changed:
            return
        old = (previous.text or '').splitlines()
        new = result.lines
        if self.kind == 'rss':
            added = [line for line in new if line not in set(old)]
            for line in added[:10]:
                Finding.create(dict(base, snapshot_id=snapshot.id, kind='new_item',
                                    title=line.split(' — ')[0][:200] or self.name, summary=line))
            return
        diff = list(difflib.unified_diff(old, new, lineterm='', n=0))
        added = [line[1:] for line in diff if line.startswith('+') and not line.startswith('+++')]
        removed = [line[1:] for line in diff if line.startswith('-') and not line.startswith('---')]
        snapshot.diff_summary = '\n'.join(['Added:'] + [f'+ {l}' for l in added[:20]] +
                                          ['', 'Removed:'] + [f'- {l}' for l in removed[:20]])
        Finding.create(dict(base, snapshot_id=snapshot.id, kind='change',
                            title=_('%s changed', self.name),
                            summary=_('%(added)s lines added, %(removed)s removed. %(sample)s',
                                      added=len(added), removed=len(removed),
                                      sample=('“%s”' % added[0][:160]) if added else '')))

    def action_collect_now(self):
        """Collect this source once (approved sources only), for checking the setup."""
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Approve the source before collecting it.'))
        run = self.env['mi.run'].sudo().create({'brand_id': self.brand_id.id})
        self.sudo()._collect(run)
        run._finish()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.run', 'res_id': run.id, 'view_mode': 'form'}


class Snapshot(models.Model):
    _name = 'mi.snapshot'
    _description = 'Collected evidence'
    _order = 'fetched_at desc, id desc'

    source_id = fields.Many2one('mi.source', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='source_id.company_id', store=True)
    run_id = fields.Many2one('mi.run', ondelete='set null')
    fetched_at = fields.Datetime(required=True, default=fields.Datetime.now, string='Collected on')
    url = fields.Char(string='Address collected')
    status_code = fields.Integer()
    title = fields.Char()
    text = fields.Text()
    content_hash = fields.Char(string='SHA-256')
    changed = fields.Boolean(string='Changed since previous')
    diff_summary = fields.Text(string='What changed')


class Finding(models.Model):
    _name = 'mi.finding'
    _description = 'Research finding'
    _order = 'create_date desc, id desc'

    run_id = fields.Many2one('mi.run', ondelete='cascade', index=True)
    brand_id = fields.Many2one('mi.brand', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='brand_id.company_id', store=True)
    source_id = fields.Many2one('mi.source', ondelete='cascade')
    competitor_id = fields.Many2one('mi.competitor', ondelete='set null')
    snapshot_id = fields.Many2one('mi.snapshot', ondelete='set null', string='Evidence')
    kind = fields.Selection([('baseline', 'First evidence'), ('change', 'Page changed'), ('new_item', 'New item'),
                             ('error', 'Could not collect')], required=True)
    title = fields.Char(required=True)
    summary = fields.Text()
    state = fields.Selection([('new', 'New'), ('reviewed', 'Reviewed'), ('dismissed', 'Dismissed')],
                             default='new', required=True)

    def action_reviewed(self):
        self.write({'state': 'reviewed'})

    def action_dismiss(self):
        self.write({'state': 'dismissed'})


class Run(models.Model):
    _name = 'mi.run'
    _description = 'Research run'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'started_at desc, id desc'

    brand_id = fields.Many2one('mi.brand', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='brand_id.company_id', store=True)
    started_at = fields.Datetime(default=fields.Datetime.now, required=True)
    finished_at = fields.Datetime()
    finding_ids = fields.One2many('mi.finding', 'run_id', string='Findings')
    source_count = fields.Integer(string='Sources checked')
    change_count = fields.Integer(string='Changes')
    error_count = fields.Integer(string='Errors')
    report_id = fields.Many2one('report.studio.report', string='Brief', ondelete='set null')
    name = fields.Char(compute='_compute_name')

    @api.depends('brand_id', 'started_at')
    def _compute_name(self):
        for run in self:
            run.name = _('%(brand)s research, %(date)s', brand=run.brand_id.name,
                         date=fields.Date.to_string(run.started_at) if run.started_at else '')

    def _finish(self):
        self.ensure_one()
        findings = self.finding_ids
        self.write({
            'finished_at': fields.Datetime.now(),
            'source_count': len(self.env['mi.snapshot'].search([('run_id', '=', self.id)]).source_id
                                | findings.filtered(lambda f: f.kind == 'error').source_id),
            'change_count': len(findings.filtered(lambda f: f.kind in ('change', 'new_item'))),
            'error_count': len(findings.filtered(lambda f: f.kind == 'error')),
        })
        self.report_id = self._build_brief()

    def _build_brief(self):
        """The weekly brief as a shared Report Studio report built only from recorded facts."""
        finding_model = self.env['ir.model']._get('mi.finding')
        domain = repr([('run_id', '=', self.id)])
        summary = _('<p>%(sources)s sources checked, %(changes)s changes found, %(errors)s could not be collected.</p>'
                    '<p>Review each change and its evidence before acting on it.</p>',
                    sources=self.source_count, changes=self.change_count, errors=self.error_count)
        return self.env['report.studio.report'].create({
            'name': self.name, 'subtitle': _('Marketing intelligence brief'), 'shared': True,
            'company_id': self.company_id.id, 'user_id': self.env.user.id,
            'res_model': self._name, 'res_id': self.id, 'accent_color': '#1D6F8A',
            'block_ids': [
                (0, 0, {'sequence': 1, 'type': 'kpi', 'width': 2, 'title': _('Changes'), 'model_id': finding_model.id,
                        'domain': repr([('run_id', '=', self.id), ('kind', 'in', ['change', 'new_item'])])}),
                (0, 0, {'sequence': 2, 'type': 'kpi', 'width': 2, 'title': _('Collection errors'),
                        'model_id': finding_model.id,
                        'domain': repr([('run_id', '=', self.id), ('kind', '=', 'error')])}),
                (0, 0, {'sequence': 3, 'type': 'text', 'title': _('Summary'), 'content': summary}),
                (0, 0, {'sequence': 4, 'type': 'table', 'title': _('What we found'), 'model_id': finding_model.id,
                        'domain': domain, 'field_names': 'kind, title, competitor_id, source_id, summary',
                        'limit': 200, 'order': 'kind'}),
            ]})

    def action_open_brief(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'report.studio.report', 'res_id': self.report_id.id,
                'view_mode': 'form'}
