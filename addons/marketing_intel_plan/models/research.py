"""Market Research tab: the proposal's research, filled by the team (and the research agent when installed).

* Upstream and downstream organisations with their role in the value chain.
* Target audience: company profile, people, demographics and locations at any level (countries, states or
  regions, and free places such as islands, hotels or stations).
* Action plan with milestones, and evidence with its source.
The research is part of the proposal: it is locked while the proposal is in approval and frozen with it.
"""

from markupsafe import Markup, escape

from odoo import _, fields, models
from odoo.exceptions import UserError

PARTY_ROLES = [('supplier', 'Supplier'), ('vendor', 'Vendor'), ('partner', 'Partner'), ('distributor', 'Distributor'),
               ('reseller', 'Reseller'), ('sales_channel', 'Sales channel'), ('customer', 'Customer'),
               ('other', 'Other')]
SOURCE_TYPES = [('own_data', 'Own data'), ('competitor', 'Competitor'), ('social_listening', 'Social listening'),
                ('customer', 'Customer'), ('trend', 'Trend'), ('market', 'Market data'), ('other', 'Other')]


class PlanParty(models.Model):
    _name = 'mi.plan.party'
    _description = 'Upstream or downstream organisation'
    _order = 'side, sequence, id'

    plan_id = fields.Many2one('mi.plan', required=True, ondelete='cascade', index=True)
    side = fields.Selection([('upstream', 'Upstream'), ('downstream', 'Downstream')], required=True)
    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one('res.partner', string='Organisation', required=True)
    role = fields.Selection(PARTY_ROLES, required=True)
    note = fields.Char()


class PlanMilestone(models.Model):
    _name = 'mi.plan.milestone'
    _description = 'Campaign milestone'
    _order = 'date, id'

    plan_id = fields.Many2one('mi.plan', required=True, ondelete='cascade', index=True)
    name = fields.Char(required=True, string='Milestone')
    date = fields.Date()
    done = fields.Boolean()


class PlanEvidence(models.Model):
    _name = 'mi.plan.evidence'
    _description = 'Research evidence'
    _order = 'date desc, id desc'

    plan_id = fields.Many2one('mi.plan', required=True, ondelete='cascade', index=True)
    source_type = fields.Selection(SOURCE_TYPES, string='Source', required=True, default='own_data')
    finding = fields.Text(required=True)
    date = fields.Date(default=fields.Date.context_today)
    url = fields.Char(string='Link')
    by_ai = fields.Boolean(string='From the research agent', readonly=True)


class Plan(models.Model):
    _inherit = 'mi.plan'

    upstream_ids = fields.One2many('mi.plan.party', 'plan_id', string='Upstream', domain=[('side', '=', 'upstream')],
                                   context={'default_side': 'upstream'},
                                   help='Suppliers, vendors and partners before us in the value chain.')
    downstream_ids = fields.One2many('mi.plan.party', 'plan_id', string='Downstream',
                                     domain=[('side', '=', 'downstream')], context={'default_side': 'downstream'},
                                     help='Distributors, resellers, sales channels and customers after us.')
    audience_company = fields.Char(string='Company profile', help='e.g. Private clinics, 10–200 staff')
    audience_people = fields.Char(string='People', help='e.g. Owners, practice managers')
    audience_demographics = fields.Char(string='Demographics', help='e.g. 30–55, decision makers')
    country_ids = fields.Many2many('res.country', string='Countries')
    state_ids = fields.Many2many('res.country.state', string='States or regions',
                                 domain="[('country_id', 'in', country_ids)]")
    places = fields.Char(string='Places', help='Any other level: cities, islands, hotels, railway stations…')
    location_label = fields.Char(compute='_compute_location_label', string='Locations')
    action_plan = fields.Text(string='Action plan', help='The proposed actions and how they will be carried out.')
    milestone_ids = fields.One2many('mi.plan.milestone', 'plan_id', string='Milestones')
    evidence_ids = fields.One2many('mi.plan.evidence', 'plan_id', string='Evidence')
    research_summary = fields.Text(string='Findings', help='What the research found, in a few sentences.')
    research_locked = fields.Boolean(compute='_compute_research_locked')

    def _compute_location_label(self):
        for plan in self:
            parts = []
            for country in plan.country_ids:
                states = plan.state_ids.filtered(lambda s: s.country_id == country)
                parts.append('%s › %s' % (country.name, ', '.join(states.mapped('name'))) if states else country.name)
            if plan.places:
                parts.append(plan.places)
            plan.location_label = ' · '.join(parts) or False

    def _compute_research_locked(self):
        for plan in self:
            plan.research_locked = plan.proposal_state == 'approval'

    def write(self, vals):
        research = {'upstream_ids', 'downstream_ids', 'audience_company', 'audience_people', 'audience_demographics',
                    'country_ids', 'state_ids', 'places', 'action_plan', 'milestone_ids', 'evidence_ids',
                    'research_summary', 'proposal_type', 'budget', 'channel_ids'}
        if research & set(vals) and not self.env.su and any(p.proposal_state == 'approval' for p in self):
            raise UserError(_('The proposal is in approval: it can change again once it is approved, or when '
                              'changes are requested.'))
        return super().write(vals)

    def _proposal_rows(self):
        rows = super()._proposal_rows()
        parties = lambda lines: Markup('<br/>').join(
            Markup('%s (%s)') % (line.partner_id.display_name, dict(PARTY_ROLES)[line.role]) for line in lines)
        rows += [
            (_('Findings'), self.research_summary),
            (_('Upstream'), parties(self.upstream_ids) if self.upstream_ids else False),
            (_('Downstream'), parties(self.downstream_ids) if self.downstream_ids else False),
            (_('Company profile'), self.audience_company), (_('People'), self.audience_people),
            (_('Demographics'), self.audience_demographics), (_('Locations'), self.location_label),
            (_('Action plan'), self.action_plan),
            (_('Milestones'), Markup('<br/>').join(Markup('%s: %s') % (m.date or '', m.name) for m in self.milestone_ids)
             if self.milestone_ids else False),
            (_('Evidence'), Markup('<br/>').join(Markup('%s — %s') % (dict(SOURCE_TYPES)[e.source_type], escape(e.finding))
                                                  for e in self.evidence_ids) if self.evidence_ids else False),
        ]
        return rows
