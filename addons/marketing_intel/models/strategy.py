"""Marketing intelligence, phase 2: analysis, campaign options and risks.

A research run can carry an analysis (summary and SWOT), campaign options
(recommendations) and a risk register. People can write them by hand; the
optional ``marketing_intel_ai`` module asks an AI agent for them as validated
structured output. Either way nothing is executed: choosing an option only
marks it as chosen for the next phase (drafts in each app).
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

CHANNELS = [('social', 'Social'), ('messaging', 'Messaging'), ('email', 'Email'), ('sms', 'SMS'),
            ('event_virtual', 'Virtual event'), ('event_physical', 'Physical event'), ('content', 'Content / SEO'),
            ('ads', 'Paid ads'), ('partnership', 'Partnership')]
CHANNEL_KEYS = {key for key, _label in CHANNELS}
RISK_CATEGORIES = [('market', 'Market'), ('competitor', 'Competitor'), ('compliance', 'Compliance / consent'),
                   ('brand', 'Brand safety'), ('budget', 'Budget'), ('operational', 'Operational')]
LEVELS = [('1', 'Low'), ('2', 'Medium'), ('3', 'High')]
CONFIDENCE = [('low', 'Low'), ('medium', 'Medium'), ('high', 'High')]
ORIGIN = [('manual', 'Person'), ('ai', 'AI agent'), ('rule', 'Automatic check')]


class Channel(models.Model):
    _name = 'mi.channel'
    _description = 'Marketing channel'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Selection(CHANNELS, required=True)
    sequence = fields.Integer(default=10)
    color = fields.Integer()

    _code_unique = models.Constraint('unique(code)', 'Each channel exists once.')


class Recommendation(models.Model):
    _name = 'mi.recommendation'
    _description = 'Suggested campaign'
    _inherit = ['mail.thread']
    _order = 'run_id desc, sequence, id'

    run_id = fields.Many2one('mi.run', ondelete='cascade', index=True, string='Research run')
    brand_id = fields.Many2one('mi.brand', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='brand_id.company_id', store=True)
    currency_id = fields.Many2one(related='brand_id.currency_id')
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, string='Idea', tracking=True)
    problem = fields.Text(string='Problem or opportunity')
    channel_ids = fields.Many2many('mi.channel', string='Channel mix')
    audience = fields.Text(string='Audience')
    budget = fields.Monetary(currency_field='currency_id', string='Suggested budget')
    duration_days = fields.Integer(string='Duration (days)', default=14)
    kpis = fields.Text(string='KPIs', help='One per line, e.g. 40 qualified leads.')
    expected_result = fields.Text(string='Expected result')
    confidence = fields.Selection(CONFIDENCE, default='medium', required=True)
    risk_notes = fields.Text(string='Risks and compliance notes')
    finding_ids = fields.Many2many('mi.finding', string='Evidence', domain="[('brand_id', '=', brand_id)]")
    origin = fields.Selection(ORIGIN, default='manual', required=True, readonly=True)
    state = fields.Selection([('proposed', 'Proposed'), ('chosen', 'Chosen'), ('rejected', 'Rejected')],
                             default='proposed', required=True, readonly=True, tracking=True, string='Status')
    decided_by = fields.Many2one('res.users', readonly=True)
    decided_at = fields.Datetime(readonly=True)
    decision_note = fields.Text(string='Why')

    def _decide(self, state):
        for row in self:
            if row.state != 'proposed' and state != 'proposed':
                raise UserError(_('“%s” is already decided. Reset it to proposed first.', row.name))
        self.write({'state': state, 'decided_by': self.env.uid if state != 'proposed' else False,
                    'decided_at': fields.Datetime.now() if state != 'proposed' else False})
        return True

    def action_choose(self):
        """Chosen means "prepare this one"; drafts in each app come in phase 3, still under their own approval."""
        return self._decide('chosen')

    def action_reject(self):
        return self._decide('rejected')

    def action_reset(self):
        return self._decide('proposed')


class Risk(models.Model):
    _name = 'mi.risk'
    _description = 'Marketing risk'
    _inherit = ['mail.thread']
    _order = 'score desc, id desc'

    brand_id = fields.Many2one('mi.brand', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='brand_id.company_id', store=True)
    run_id = fields.Many2one('mi.run', ondelete='set null', index=True, string='Found in run')
    recommendation_id = fields.Many2one('mi.recommendation', ondelete='set null', string='Campaign option',
                                        domain="[('brand_id', '=', brand_id)]")
    name = fields.Char(required=True, string='Risk', tracking=True)
    description = fields.Text()
    category = fields.Selection(RISK_CATEGORIES, required=True, default='market')
    likelihood = fields.Selection(LEVELS, required=True, default='2')
    impact = fields.Selection(LEVELS, required=True, default='2')
    score = fields.Integer(compute='_compute_score', store=True, help='Likelihood × impact, 1 to 9.')
    level = fields.Selection([('low', 'Low'), ('medium', 'Medium'), ('high', 'High')], compute='_compute_score',
                             store=True)
    mitigation = fields.Text()
    owner_id = fields.Many2one('res.users', string='Owner', tracking=True)
    origin = fields.Selection(ORIGIN, default='manual', required=True, readonly=True)
    state = fields.Selection([('open', 'Open'), ('mitigated', 'Mitigated'), ('accepted', 'Accepted'),
                              ('closed', 'Closed')], default='open', required=True, tracking=True, string='Status')

    @api.depends('likelihood', 'impact')
    def _compute_score(self):
        for risk in self:
            risk.score = int(risk.likelihood or 1) * int(risk.impact or 1)
            risk.level = 'high' if risk.score >= 6 else 'medium' if risk.score >= 3 else 'low'


class Brand(models.Model):
    _inherit = 'mi.brand'

    recommendation_ids = fields.One2many('mi.recommendation', 'brand_id', string='Suggested campaigns')
    risk_ids = fields.One2many('mi.risk', 'brand_id', string='Risks')
    idea_count = fields.Integer(compute='_compute_insight_counts', string='Suggested campaigns')
    risk_count = fields.Integer(compute='_compute_insight_counts', string='Open risks')
    run_count = fields.Integer(compute='_compute_insight_counts', string='Research')
    latest_run_id = fields.Many2one('mi.run', compute='_compute_insight_counts', string='Latest research')

    def _compute_insight_counts(self):
        for brand in self:
            brand.idea_count = self.env['mi.recommendation'].search_count(
                [('brand_id', '=', brand.id), ('state', '=', 'proposed')])
            brand.risk_count = self.env['mi.risk'].search_count([('brand_id', '=', brand.id), ('state', '=', 'open')])
            runs = self.env['mi.run'].search([('brand_id', '=', brand.id)], order='started_at desc, id desc')
            brand.run_count = len(runs)
            brand.latest_run_id = runs[:1]

    def _open(self, model, name, domain, context=None, views='list,form'):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': model, 'name': name, 'view_mode': views,
                'domain': domain, 'context': dict(context or {}, default_brand_id=self.id)}

    def action_open_changes(self):
        return self._open('mi.finding', _('Market changes'), [('brand_id', '=', self.id)], {'search_default_new': 1})

    def action_open_ideas(self):
        return self._open('mi.recommendation', _('Suggested campaigns'), [('brand_id', '=', self.id)],
                          {'search_default_proposed': 1})

    def action_open_risks(self):
        return self._open('mi.risk', _('Risks'), [('brand_id', '=', self.id)], {'search_default_open': 1})

    def action_open_research(self):
        return self._open('mi.run', _('Research'), [('brand_id', '=', self.id)])

    def action_open_latest_research(self):
        self.ensure_one()
        if not self.latest_run_id:
            raise UserError(_('No research yet. Add competitors or sources, then click Research now.'))
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.run', 'res_id': self.latest_run_id.id,
                'view_mode': 'form'}

    def _learning_lines(self, limit=5):
        """Short lines about past campaigns and their results, for analysis. Filled by campaign plans."""
        return []


class Run(models.Model):
    _inherit = 'mi.run'

    summary = fields.Text(string='Analysis', help='What the evidence means for us, in a few paragraphs.')
    strengths = fields.Text()
    weaknesses = fields.Text()
    opportunities = fields.Text()
    threats = fields.Text()
    recommendation_ids = fields.One2many('mi.recommendation', 'run_id', string='Suggested campaigns')
    risk_ids = fields.One2many('mi.risk', 'run_id', string='Risks')
    analysed_at = fields.Datetime(readonly=True)

    def _budget_checks(self):
        """Deterministic flags next to whatever wrote the options: never model output."""
        self.ensure_one()
        brand = self.brand_id
        total = sum(self.recommendation_ids.filtered(lambda r: r.state != 'rejected').mapped('budget'))
        self.risk_ids.filtered(lambda r: r.origin == 'rule' and r.state == 'open').unlink()
        if brand.monthly_budget and total > brand.monthly_budget:
            self.env['mi.risk'].create({
                'brand_id': brand.id, 'run_id': self.id, 'origin': 'rule', 'category': 'budget',
                'likelihood': '3', 'impact': '2',
                'name': _('Options exceed the monthly budget'),
                'description': _('Proposed options total %(total)s against a monthly budget of %(budget)s.',
                                 total=round(total, 2), budget=brand.monthly_budget),
                'mitigation': _('Choose fewer options or phase them over several months.'),
            })
        for option in self.recommendation_ids.filtered(lambda r: r.state == 'proposed' and not r.finding_ids
                                                       and r.confidence != 'low'):
            option.confidence = 'low'

    def action_refresh_brief(self):
        """Rebuild the brief after people edited the analysis, options or risks."""
        for run in self:
            run.check_access('read')
            run._budget_checks()
            run.sudo()._refresh_brief()
        return True

    def _refresh_brief(self):
        self.ensure_one()
        old = self.report_id
        self.report_id = self._build_brief()
        if old:
            old.sudo().unlink()

    def _build_brief(self):
        report = super()._build_brief()
        sections = []
        if self.summary:
            sections.append((_('Analysis'), self.summary))
        swot = [(_('Strengths'), self.strengths), (_('Weaknesses'), self.weaknesses),
                (_('Opportunities'), self.opportunities), (_('Threats'), self.threats)]
        if any(text for _label, text in swot):
            sections.append((_('SWOT'), '\n\n'.join(f'{label}:\n{text or "-"}' for label, text in swot)))
        blocks = []
        sequence = 10
        for title, text in sections:
            blocks.append((0, 0, {'sequence': sequence, 'type': 'text', 'title': title,
                                  'content': _text_html(text)}))
            sequence += 1
        if self.recommendation_ids:
            blocks.append((0, 0, {
                'sequence': 20, 'type': 'table', 'title': _('Suggested campaigns'),
                'model_id': self.env['ir.model']._get('mi.recommendation').id,
                'domain': repr([('run_id', '=', self.id)]), 'limit': 20, 'order': 'sequence',
                'field_names': 'name, problem, channel_ids, budget, duration_days, kpis, confidence, state'}))
        if self.risk_ids:
            blocks.append((0, 0, {
                'sequence': 21, 'type': 'table', 'title': _('Risks'),
                'model_id': self.env['ir.model']._get('mi.risk').id,
                'domain': repr([('run_id', '=', self.id)]), 'limit': 50, 'order': 'score desc',
                'field_names': 'name, category, level, mitigation, origin, state'}))
        if blocks:
            report.write({'block_ids': blocks})
        return report


def _text_html(text):
    from markupsafe import escape
    paragraphs = [p.strip() for p in (text or '').split('\n\n') if p.strip()]
    return ''.join('<p>%s</p>' % escape(p).replace('\n', '<br/>') for p in paragraphs)


ACCOUNT_MODELS = [('omni.social.connection', 'Social page or account'), ('omni.channel', 'Messaging channel'),
                  ('mm.list', 'Messaging list'), ('mailing.list', 'Email / SMS mailing list')]


class BrandTeam(models.Model):
    _inherit = 'mi.brand'

    member_ids = fields.Many2many('res.users', 'mi_brand_member_rel', 'brand_id', 'user_id', string='Team',
                                  domain="[('share', '=', False)]",
                                  help='People working on this brand. They find it under "My brands". '
                                       'Empty: everyone in marketing works on it.')
    owner_type = fields.Selection([('own', 'Our company'), ('client', 'A client')], string='Brand of',
                                  default='own', required=True,
                                  help='Our company: a brand of one of our (group) companies. A client: a brand we '
                                       'market for someone else, as an advisor or agency.')
    partner_id = fields.Many2one('res.partner', string='Client contact',
                                 help='For advisors and agencies: the client this brand belongs to (internal for now).')
    retainer_fee = fields.Monetary(currency_field='currency_id', string='Monthly fee',
                                   help='For client brands: what the client pays you each month.')
    contract_start = fields.Date(string='Contract from')
    contract_end = fields.Date(string='Contract until')
    portfolio = fields.Char(compute='_compute_portfolio', store=True, string='Company or client',
                            help='How brand cards are grouped: the company for our brands, the client otherwise.')
    email_from = fields.Char(string='Email sender', help='e.g. "Brand <hello@brand.com>"; used for email drafts.')
    account_ids = fields.One2many('mi.brand.account', 'brand_id', string='Channels & accounts')

    @api.depends('owner_type', 'company_id.name', 'partner_id.commercial_partner_id.name')
    def _compute_portfolio(self):
        for brand in self:
            if brand.owner_type == 'client':
                brand.portfolio = brand.partner_id.commercial_partner_id.name or _('Clients')
            else:
                brand.portfolio = brand.company_id.name

    @api.model
    def _marketing_home(self):
        """One brand: open it. Several: brand cards, the person's own first, grouped when they span
        several companies of the group or several clients."""
        brands = self.search([])
        if len(brands) == 1:
            return {'type': 'ir.actions.act_window', 'res_model': 'mi.brand', 'res_id': brands.id,
                    'views': [(False, 'form')], 'name': brands.name}
        action = self.env['ir.actions.act_window']._for_xml_id('marketing_intel.action_brands')
        context = {}
        if brands.filtered(lambda b: self.env.user in b.member_ids):
            context['search_default_my_brands'] = 1
        if len(set(brands.mapped('portfolio'))) > 1:
            context['search_default_group_portfolio'] = 1
        action['context'] = context
        return action

    def _accounts(self, model):
        """The brand's own accounts of one kind (records of `model`), readable by the current user."""
        self.ensure_one()
        if model not in self.env:
            return False
        ids = [a.account.id for a in self.account_ids if a.account and a.account._name == model]
        return self.env[model].browse(ids).exists()


class BrandAccount(models.Model):
    _name = 'mi.brand.account'
    _description = 'Brand channel account'
    _order = 'brand_id, sequence, id'

    brand_id = fields.Many2one('mi.brand', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='brand_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    account = fields.Reference(selection='_selection_account', string='Account', required=True,
                               help='A Social page, Messaging channel or list, or mailing list that belongs to this brand.')
    kind = fields.Char(compute='_compute_kind', string='Kind')

    @api.model
    def _selection_account(self):
        return [(model, label) for model, label in ACCOUNT_MODELS if model in self.env]

    @api.depends('account')
    def _compute_kind(self):
        labels = dict(ACCOUNT_MODELS)
        for row in self:
            row.kind = labels.get(row.account._name, '') if row.account else ''
