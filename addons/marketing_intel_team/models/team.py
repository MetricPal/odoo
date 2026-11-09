"""The marketing department is the team (ADR 0016, approved board 5.1b, owner 2026-11-09: "everything under the
department").

- The marketing department is the department where most people with Marketing access work (owner, 2026-11-09: no
  setting); its **manager** is the head of department, its **employees** are the team, and each employee's
  **manager** in Employees reviews their work.
- The **Marketing role** (Junior, Senior, Head of department) is the person's Marketing access right; the Marketing
  tab of the department sets it.
- What a senior may release alone (budget, audience, channels) is set on the department.
- Without a marketing department the marketing apps work as before (one review, previous panel views).
"""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

ROLES = [('junior', 'Junior'), ('senior', 'Senior'), ('hod', 'Head of department')]
GROUPS = {'junior': 'marketing_intel.group_mi_user', 'senior': 'marketing_intel_team.group_mi_senior',
          'hod': 'marketing_intel_team.group_mi_hod'}
LIMITED_CHANNELS = ('email', 'sms', 'messaging', 'social')
MI_DEPARTMENT_FIELDS = {'mi_senior_budget_limit', 'mi_senior_audience_limit', 'mi_senior_channel_ids', 'mi_member_ids'}


def user_role(user):
    """A person's marketing role from their access rights, or False."""
    if not user:
        return False
    if user.has_group('marketing_intel_team.group_mi_hod'):
        return 'hod'
    if user.has_group('marketing_intel_team.group_mi_senior'):
        return 'senior'
    if user.has_group('marketing_intel.group_mi_user'):
        return 'junior'
    return False


def can_manage_marketing(env):
    return env.su or env.user.has_group('marketing_intel_team.group_mi_hod') \
        or env.user.has_group('hr.group_hr_user')


class Department(models.Model):
    _inherit = 'hr.department'

    mi_is_marketing = fields.Boolean(compute='_compute_mi_is_marketing', search='_search_mi_is_marketing',
                                     string='Marketing department',
                                     help='The department where most people with Marketing access work.')
    mi_member_ids = fields.One2many('hr.employee', 'department_id', string='The team')
    mi_currency_id = fields.Many2one(related='company_id.currency_id', string='Marketing currency')
    mi_senior_budget_limit = fields.Monetary(string='Campaign budget up to', currency_field='mi_currency_id',
                                             tracking=True, help='A senior releases campaigns up to this budget alone. '
                                                                 '0: no limit.')
    mi_senior_audience_limit = fields.Integer(string='Audience up to', tracking=True,
                                              help='People an email, SMS or message goes to. 0: no limit.')
    mi_senior_channel_ids = fields.Many2many('mi.channel', 'hr_department_mi_channel_rel', 'department_id',
                                             'channel_id', string='Channels', domain=[('code', 'in', LIMITED_CHANNELS)],
                                             help='Channels a senior releases alone. Others go to the head of '
                                                  'department.')
    mi_hod_user_id = fields.Many2one('res.users', compute='_compute_mi_hod', string='Head of department ')
    mi_hod_label = fields.Char(compute='_compute_mi_hod', string='Head of department')
    mi_approver_ids = fields.Many2many('mi.approver', compute='_compute_mi_approver_ids', string='Proposal approvers')

    @api.depends('manager_id.user_id', 'company_id')
    def _compute_mi_hod(self):
        for department in self:
            user = department.manager_id.user_id
            department.mi_hod_user_id = user
            if user:
                department.mi_hod_label = _('Department manager: %s', user.name)
            else:
                department.mi_hod_label = _('Nobody: set the department\'s manager')

    def _compute_mi_approver_ids(self):
        for department in self:
            department.mi_approver_ids = self.env['mi.approver'].sudo().search(
                [('company_id', '=', department.company_id.id)])

    def _compute_mi_is_marketing(self):
        found = {}
        for department in self:
            company = department.company_id or self.env.company
            if company.id not in found:
                found[company.id] = self._mi_department(company)
            department.mi_is_marketing = department == found[company.id]

    def _search_mi_is_marketing(self, operator, value):
        if operator not in ('in', 'not in', '=', '!='):
            raise UserError(_('Unsupported search.'))
        if operator in ('=', '!='):
            wanted = bool(value) == (operator == '=')
        else:
            values = {bool(v) for v in value}
            if values == {True, False}:
                return [] if operator == 'in' else [('id', '=', False)]
            wanted = (True in values) == (operator == 'in')
        ids = [i for i in (self._mi_department(company).id for company in self.env.companies) if i]
        return [('id', 'in' if wanted else 'not in', ids)]

    @api.constrains('mi_senior_budget_limit', 'mi_senior_audience_limit')
    def _check_mi_limits(self):
        if any(d.mi_senior_budget_limit < 0 or d.mi_senior_audience_limit < 0 for d in self):
            raise ValidationError(_('Limits cannot be negative.'))

    def write(self, vals):
        """The head of department changes the marketing fields without HR rights (only those fields)."""
        if vals and set(vals) <= MI_DEPARTMENT_FIELDS and not self.env.su \
                and self.env.user.has_group('marketing_intel_team.group_mi_hod') \
                and not self.env.user.has_group('hr.group_hr_user'):
            return super(Department, self.sudo()).write(vals)
        return super().write(vals)

    @api.model
    def _mi_department(self, company=None):
        """Where most people with Marketing access work (administrators count only when nobody else has access)."""
        company = company or self.env.company
        group = self.env.ref('marketing_intel.group_mi_user')
        Employee = self.env['hr.employee'].sudo()
        employees = Employee.search([('company_id', '=', company.id), ('department_id', '!=', False),
                                     ('user_id.all_group_ids', 'in', group.ids), ('user_id.share', '=', False)])
        people = employees.filtered(lambda e: not e.user_id.has_group('base.group_system')) or employees
        if not people:
            return self.browse()
        counts = {}
        for employee in people:
            counts[employee.department_id] = counts.get(employee.department_id, 0) + 1
        return max(counts, key=lambda d: (counts[d], -d.id)).with_env(self.env)

    @api.model
    def action_open_mi_department(self):
        """The marketing department's form (from the Department dashboard's links), else the departments."""
        department = self._mi_department()
        view = self.env.ref('hr.view_department_form').id
        if department:
            return {'type': 'ir.actions.act_window', 'res_model': 'hr.department', 'res_id': department.id,
                    'views': [(view, 'form')], 'target': 'current', 'name': _('Marketing department')}
        return {'type': 'ir.actions.act_window', 'res_model': 'hr.department', 'views': [(False, 'list'), (view, 'form')],
                'target': 'current', 'name': _('Departments'),
                'help': _('<p>The marketing department is where most people with Marketing access work: put them in '
                          'their department in Employees.</p>')}

    def action_set_mi_approvers(self):
        return self.env['ir.actions.actions']._for_xml_id('marketing_intel_plan.action_approvers')

    # -- who is who --------------------------------------------------------------------------------------------
    def _mi_users(self):
        """The team's people (employees with a user)."""
        self.ensure_one()
        return self.sudo().member_ids.user_id

    def _senior_for(self, user):
        """Who reviews this person's work: their manager in Employees when that manager is a senior or the head of
        department, else the head of department."""
        self.ensure_one()
        employee = self.sudo().member_ids.filtered(lambda e: e.user_id == user)[:1]
        manager = employee.parent_id.user_id
        if manager and manager != user and user_role(manager) in ('senior', 'hod'):
            return manager
        return self.mi_hod_user_id if self.mi_hod_user_id != user else self.env['res.users']

    def _limit_problems(self, plan, releaser):
        """Why ``releaser`` may not release ``plan`` alone ([] when they may)."""
        self.ensure_one()
        role = user_role(releaser)
        if role == 'hod':
            return []
        if role != 'senior':
            return [_('Only a senior or the head of department releases campaigns.')]
        problems = []
        if self.mi_senior_budget_limit and plan.budget > self.mi_senior_budget_limit:
            problems.append(_('Budget %(budget)s is above the limit (%(limit)s)',
                              budget=plan._money(plan.budget), limit=plan._money(self.mi_senior_budget_limit)))
        audience = plan._audience()
        if self.mi_senior_audience_limit and audience > self.mi_senior_audience_limit:
            problems.append(_('Audience %(audience)s is above the limit (%(limit)s)', audience=audience,
                              limit=self.mi_senior_audience_limit))
        allowed = set(self.mi_senior_channel_ids.mapped('code'))
        outside = [channel for channel in plan.channel_ids if channel.code in LIMITED_CHANNELS
                   and channel.code not in allowed] if self.mi_senior_channel_ids else []
        if outside:
            problems.append(_('%s not in the channels a senior releases', ', '.join(c.name for c in outside)))
        return problems


class Employee(models.Model):
    _inherit = 'hr.employee'

    mi_role = fields.Selection(ROLES, string='Marketing role', compute='_compute_mi_role', inverse='_inverse_mi_role',
                               help='The person\'s Marketing access right.')
    mi_reviews_label = fields.Char(compute='_compute_mi_reviews_label', string='Reviews whose work')
    mi_is_assistant = fields.Boolean(compute='_compute_mi_role', string='AI assistant')

    @api.depends('user_id')
    def _compute_mi_role(self):
        for employee in self:
            user = employee.sudo().user_id
            employee.mi_role = user_role(user) if user else False
            employee.mi_is_assistant = bool(getattr(user, 'ai_assistant', False))

    @api.depends('department_id.member_ids.parent_id')
    def _compute_mi_reviews_label(self):
        for employee in self:
            if employee.mi_role == 'hod' and employee.department_id.manager_id == employee:
                employee.mi_reviews_label = _('Approves above the seniors\' limits')
                continue
            reviewed = employee.sudo().child_ids.filtered(lambda e: e.department_id == employee.department_id)
            employee.mi_reviews_label = ', '.join(reviewed.mapped('name'))

    def write(self, vals):
        """The head of department sets Marketing roles without HR rights (only that field)."""
        if vals and set(vals) <= {'mi_role'} and not self.env.su \
                and self.env.user.has_group('marketing_intel_team.group_mi_hod') \
                and not self.env.user.has_group('hr.group_hr_user'):
            return super(Employee, self.sudo().with_context(mi_role_by=self.env.uid)).write(vals)
        return super().write(vals)

    def _inverse_mi_role(self):
        """The role is the person's Marketing access right. AI assistant users' rights stay with administrators
        (ADR 0012)."""
        actor = self.env['res.users'].browse(self.env.context.get('mi_role_by') or self.env.uid)
        if not (self.env.context.get('mi_role_by') or can_manage_marketing(self.env)):
            raise AccessError(_('Only the head of department or HR sets Marketing roles.'))
        groups = {role: self.env.ref(xmlid) for role, xmlid in GROUPS.items()}
        manager = self.env.ref('marketing_intel.group_mi_manager')
        for employee in self:
            user = employee.sudo().user_id
            if not employee.mi_role or not user:
                continue
            if employee.mi_is_assistant and not actor.has_group('base.group_system'):
                raise AccessError(_('An AI assistant\'s access rights are set by administrators.'))
            if employee.mi_role == 'hod' and not actor.has_group('marketing_intel.group_mi_manager') \
                    and not actor.has_group('base.group_system'):
                raise AccessError(_('Only a Marketing administrator makes someone head of department.'))
            if user.has_group('marketing_intel.group_mi_manager') and employee.mi_role != 'hod':
                raise UserError(_('%s is a Marketing administrator: an administrator is always head of department.',
                                  user.name))
            if user_role(user) == employee.mi_role:
                continue
            higher = {'junior': ('senior', 'hod'), 'senior': ('hod',), 'hod': ()}[employee.mi_role]
            commands = [(3, groups[role].id) for role in higher] + [(4, groups[employee.mi_role].id)]
            if manager in user.group_ids:
                commands = [(4, groups[employee.mi_role].id)]
            user.write({'group_ids': commands})
