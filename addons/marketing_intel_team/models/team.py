"""The marketing team (ADR 0016, approved board 5.1): who is Junior, Senior or Head of department, who reviews whose
work, and what a senior may release alone.

The role is the person's Marketing access right (Junior ⊂ Senior ⊂ Head of department ⊂ Administrator); this page
sets it. The head of department is the Marketing department's manager when one is set, else the team member with
that role. Without a team the marketing apps work as before (one review, no senior step).
"""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

ROLES = [('junior', 'Junior'), ('senior', 'Senior'), ('hod', 'Head of department')]
GROUPS = {'junior': 'marketing_intel.group_mi_user', 'senior': 'marketing_intel_team.group_mi_senior',
          'hod': 'marketing_intel_team.group_mi_hod'}
LIMITED_CHANNELS = ('email', 'sms', 'messaging', 'social')


def user_role(user):
    """A person's marketing role from their access rights, or False."""
    if user.has_group('marketing_intel_team.group_mi_hod'):
        return 'hod'
    if user.has_group('marketing_intel_team.group_mi_senior'):
        return 'senior'
    if user.has_group('marketing_intel.group_mi_user'):
        return 'junior'
    return False


class Team(models.Model):
    _name = 'mi.team'
    _description = 'Marketing team'
    _inherit = ['mail.thread']

    name = fields.Char(default=lambda self: _('Marketing team'), required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    department_id = fields.Many2one('hr.department', string='Department', tracking=True,
                                    help='Its manager is the head of department.')
    member_ids = fields.One2many('mi.team.member', 'team_id', string='Marketing team')
    senior_budget_limit = fields.Monetary(string='Campaign budget up to', currency_field='currency_id', tracking=True,
                                          help='A senior releases campaigns up to this budget alone. 0: no limit.')
    senior_audience_limit = fields.Integer(string='Audience up to', tracking=True,
                                           help='People an email, SMS or message goes to. 0: no limit.')
    senior_channel_ids = fields.Many2many('mi.channel', string='Channels',
                                          domain=[('code', 'in', LIMITED_CHANNELS)],
                                          help='Channels a senior releases alone. Others go to the head of department.')
    hod_user_id = fields.Many2one('res.users', compute='_compute_hod', string='Head of department')
    hod_label = fields.Char(compute='_compute_hod', string='Head of department ')
    approver_ids = fields.Many2many('mi.approver', compute='_compute_approver_ids', string='Approvers')

    _company_unique = models.Constraint('UNIQUE(company_id)', 'One marketing team per company.')

    @api.depends('department_id.manager_id.user_id', 'member_ids.role', 'member_ids.user_id')
    def _compute_hod(self):
        for team in self:
            user = team.department_id.manager_id.user_id
            team.hod_user_id = user or team.member_ids.filtered(lambda m: m.role == 'hod')[:1].user_id
            if user:
                team.hod_label = _("%(department)s department's manager: %(name)s", department=team.department_id.name,
                                   name=user.name)
            else:
                team.hod_label = team.hod_user_id.name or _('Nobody yet: give someone the Head of department role')

    def _compute_approver_ids(self):
        for team in self:
            team.approver_ids = self.env['mi.approver'].sudo().search([('company_id', '=', team.company_id.id)])

    @api.constrains('senior_budget_limit', 'senior_audience_limit')
    def _check_limits(self):
        if any(team.senior_budget_limit < 0 or team.senior_audience_limit < 0 for team in self):
            raise ValidationError(_('Limits cannot be negative.'))

    @api.model
    def _for_company(self, company):
        return self.sudo().search([('company_id', '=', company.id)], limit=1)

    @api.model
    def action_open_team(self):
        """Configuration › Team and roles: the company's team, made on first open."""
        team = self._for_company(self.env.company)
        if not team:
            if not self.env.user.has_group('marketing_intel_team.group_mi_hod'):
                raise UserError(_('Ask the head of department to set up the marketing team.'))
            team = self.create({'company_id': self.env.company.id})
            team._add_current_marketers()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': team.id, 'view_mode': 'form',
                'target': 'current', 'name': _('Team and roles')}

    def _add_current_marketers(self):
        """Everyone with marketing access in the company, with the role their access gives today."""
        group = self.env.ref('marketing_intel.group_mi_user')
        users = self.env['res.users'].sudo().search([('all_group_ids', 'in', group.ids), ('share', '=', False),
                                                     ('company_ids', 'in', self.company_id.ids)])
        for user in users - self.member_ids.user_id:
            role = user_role(user) or 'junior'
            self.env['mi.team.member'].sudo().with_context(mi_team_no_sync=True).create(
                {'team_id': self.id, 'user_id': user.id, 'role': role})
        for member in self.member_ids.filtered(lambda m: m.role == 'junior' and not m.senior_id):
            member.sudo().with_context(mi_team_no_sync=True).senior_id = member._default_senior()

    def action_set_approvers(self):
        return self.env['ir.actions.actions']._for_xml_id('marketing_intel_plan.action_approvers') \
            if self.env.ref('marketing_intel_plan.action_approvers', raise_if_not_found=False) else False

    # -- who is who --------------------------------------------------------------------------------------------
    def _member(self, user):
        self.ensure_one()
        return self.member_ids.filtered(lambda m: m.user_id == user)[:1]

    def _senior_for(self, user):
        """Who reviews this person's work: their senior on the team, else the head of department."""
        self.ensure_one()
        member = self._member(user)
        return member.senior_id or self.hod_user_id

    def _limit_problems(self, plan, releaser):
        """Why ``releaser`` may not release ``plan`` alone ([] when they may)."""
        self.ensure_one()
        role = user_role(releaser)
        if role == 'hod':
            return []
        if role != 'senior':
            return [_('Only a senior or the head of department releases campaigns.')]
        problems = []
        if self.senior_budget_limit and plan.budget > self.senior_budget_limit:
            problems.append(_('Budget %(budget)s is above the limit (%(limit)s)',
                              budget=plan._money(plan.budget), limit=plan._money(self.senior_budget_limit)))
        audience = plan._audience()
        if self.senior_audience_limit and audience > self.senior_audience_limit:
            problems.append(_('Audience %(audience)s is above the limit (%(limit)s)', audience=audience,
                              limit=self.senior_audience_limit))
        allowed = set(self.senior_channel_ids.mapped('code'))
        outside = [channel for channel in plan.channel_ids if channel.code in LIMITED_CHANNELS
                   and channel.code not in allowed] if self.senior_channel_ids else []
        if outside:
            problems.append(_('%s not in the channels a senior releases', ', '.join(c.name for c in outside)))
        return problems


class TeamMember(models.Model):
    _name = 'mi.team.member'
    _description = 'Marketing team member'
    _order = 'role desc, id'

    team_id = fields.Many2one('mi.team', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='team_id.company_id', store=True)
    user_id = fields.Many2one('res.users', string='Person', required=True, domain=[('share', '=', False)])
    role = fields.Selection(ROLES, required=True, default='junior')
    senior_id = fields.Many2one('res.users', string='Reviewed by',
                                help='The senior who reviews this person\'s work (default: their manager in Employees '
                                     'when they are a senior).')
    reviews_label = fields.Char(compute='_compute_reviews_label', string='Reviews whose work')
    is_assistant = fields.Boolean(compute='_compute_is_assistant', string='AI assistant')

    _user_unique = models.Constraint('UNIQUE(team_id, user_id)', 'Each person once in the team.')

    @api.depends('team_id.member_ids.senior_id', 'role')
    def _compute_reviews_label(self):
        for member in self:
            if member.role == 'hod':
                member.reviews_label = _('Approves above the seniors\' limits')
            else:
                reviewed = member.team_id.member_ids.filtered(lambda m: m.senior_id == member.user_id)
                member.reviews_label = ', '.join(reviewed.user_id.mapped('name'))

    def _compute_is_assistant(self):
        for member in self:
            member.is_assistant = bool(getattr(member.user_id, 'ai_assistant', False))

    def _default_senior(self):
        """The person's manager in Employees, when that manager is a senior or head of department in the team."""
        self.ensure_one()
        manager = self.user_id.employee_id.parent_id.user_id
        if manager and manager in self.team_id.member_ids.filtered(lambda m: m.role in ('senior', 'hod')).user_id:
            return manager
        seniors = self.team_id.member_ids.filtered(lambda m: m.role == 'senior').user_id
        return seniors[:1] if len(seniors) == 1 else self.env['res.users']

    @api.constrains('senior_id', 'user_id')
    def _check_senior(self):
        for member in self:
            if member.senior_id and member.senior_id == member.user_id:
                raise ValidationError(_('Nobody reviews their own work.'))

    def _check_manage(self):
        if not self.env.su and not self.env.user.has_group('marketing_intel_team.group_mi_hod'):
            raise AccessError(_('Only the head of department changes the marketing team.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_manage()
        members = super().create(vals_list)
        for member in members.filtered(lambda m: m.role == 'junior' and not m.senior_id):
            super(TeamMember, member).write({'senior_id': member._default_senior().id})
        members._sync_groups()
        return members

    def write(self, vals):
        self._check_manage()
        result = super().write(vals)
        if 'role' in vals or 'user_id' in vals:
            self._sync_groups()
        return result

    def _sync_groups(self):
        """The role is the person's Marketing access right. AI assistant users' rights stay with administrators
        (ADR 0012)."""
        if self.env.context.get('mi_team_no_sync'):
            return
        groups = {role: self.env.ref(xmlid) for role, xmlid in GROUPS.items()}
        manager = self.env.ref('marketing_intel.group_mi_manager')
        for member in self:
            user = member.user_id.sudo()
            if member.is_assistant and not self.env.user.has_group('base.group_system'):
                continue
            if user.has_group('marketing_intel.group_mi_manager') and member.role != 'hod':
                raise UserError(_('%s is a Marketing administrator: an administrator is always head of department.',
                                  user.name))
            if user_role(user) == member.role:
                continue
            higher = {'junior': ('senior', 'hod'), 'senior': ('hod',), 'hod': ()}[member.role]
            commands = [(3, groups[role].id) for role in higher] + [(4, groups[member.role].id)]
            if manager in user.group_ids:
                commands = [(4, groups[member.role].id)]
            user.write({'group_ids': commands})
