"""Department AI assistants and department AI admins (ADR 0012).

Each department may have an AI assistant user: an internal user nobody signs in as, that the department's agents
act as, so an agent keeps working when a person leaves. Its groups are its role and are managed by administrators.
The department's managers in Employees (with their sub-departments) and the AI admins an AI Agent manager chooses
on the department configure the department's agents without approval.
"""

from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, AccessError, UserError


class ResUsers(models.Model):
    _inherit = 'res.users'

    ai_assistant = fields.Boolean(string='AI assistant', readonly=True, copy=False,
                                  help='Agents act as this user. Nobody can sign in as it.')
    ai_assistant_department_id = fields.Many2one('hr.department', string='Assistant of', readonly=True, copy=False,
                                                 index='btree_not_null')

    def _check_credentials(self, credential, env):
        # An AI assistant never signs in, whatever password or method is tried.
        if self.ai_assistant:
            raise AccessDenied()
        return super()._check_credentials(credential, env)

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('ai_assistant') or vals.get('ai_assistant_department_id') for vals in vals_list) \
                and not self.env.su:
            raise AccessError(_('Create AI assistants from the department.'))
        return super().create(vals_list)

    def write(self, vals):
        if {'ai_assistant', 'ai_assistant_department_id'} & vals.keys() and not self.env.su:
            raise AccessError(_('Create AI assistants from the department.'))
        return super().write(vals)

    def _ai_admin_department_ids(self):
        """Departments, with their sub-departments, whose agents this user configures: those they manage in
        Employees and those an AI Agent manager made them AI admin of."""
        self.ensure_one()
        Department = self.env['hr.department'].sudo()
        roots = Department.search(['|', ('manager_id.user_id', '=', self.id), ('ai_admin_ids', 'in', self.id)])
        return Department.search([('id', 'child_of', roots.ids)]).ids if roots else []


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    ai_assistant_user_id = fields.Many2one('res.users', string='AI assistant', readonly=True, copy=False)
    ai_assistant_access = fields.Char(string='Its access', compute='_compute_ai_assistant_access')
    ai_admin_ids = fields.Many2many('res.users', 'hr_department_ai_admin_rel', 'department_id', 'user_id',
                                    string='AI admins', domain="[('share', '=', False), ('ai_assistant', '=', False)]",
                                    help='Besides the department manager, these people configure the department\'s '
                                         'agents. No approval is needed.')
    ai_agent_ids = fields.One2many('ai.agent', 'department_id', string='Agents')
    ai_agent_count = fields.Integer(string='Agents', compute='_compute_ai_agent_count')
    ai_can_manage = fields.Boolean(compute='_compute_ai_can_manage')

    @api.depends('ai_assistant_user_id.group_ids')
    def _compute_ai_assistant_access(self):
        internal = self.env.ref('base.group_user')
        for department in self:
            # Access rights only: groups under a privilege (Employees: Officer, ...), not settings like inbox notices.
            groups = (department.sudo().ai_assistant_user_id.group_ids - internal).filtered('privilege_id')
            department.ai_assistant_access = ' · '.join(sorted(groups.mapped('full_name'))) or _('No access yet')

    def _compute_ai_agent_count(self):
        counts = dict(self.env['ai.agent'].sudo()._read_group(
            [('department_id', 'in', self.ids)], ['department_id'], ['__count']))
        for department in self:
            department.ai_agent_count = counts.get(department, 0)

    @api.depends_context('uid')
    def _compute_ai_can_manage(self):
        can = self.env.user.has_group('ai_agent.group_manager')
        for department in self:
            department.ai_can_manage = can

    def write(self, vals):
        if 'ai_assistant_user_id' in vals and not self.env.su:
            raise AccessError(_('Use Create AI assistant.'))
        if 'ai_admin_ids' in vals:
            if not self.env.user.has_group('ai_agent.group_manager'):
                raise AccessError(_('Only AI Agent managers choose department AI admins.'))
            if not vals.keys() - {'ai_admin_ids'}:
                # AI Agent managers may not have Employees write access: they only set this field.
                return super(HrDepartment, self.sudo()).write(vals)
        return super().write(vals)

    def action_create_ai_assistant(self):
        """Create the department's AI assistant user (internal, cannot sign in, no access beyond Internal User
        until an administrator gives it groups)."""
        if not self.env.user.has_group('ai_agent.group_manager'):
            raise AccessError(_('Only AI Agent managers create AI assistants.'))
        Users = self.env['res.users'].sudo().with_context(no_reset_password=True, mail_create_nosubscribe=True)
        for department in self:
            if department.ai_assistant_user_id:
                raise UserError(_('%s already has an AI assistant.', department.name))
            company = department.company_id or self.env.company
            user = Users.create({
                'name': _('%s Assistant', department.name),
                'login': f'ai-assistant-{department.id}',
                'ai_assistant': True,
                'ai_assistant_department_id': department.id,
                'company_id': company.id,
                'company_ids': [(6, 0, company.ids)],
                'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('ai_agent.group_user').id])],
                'notification_type': 'inbox',
            })
            department.sudo().ai_assistant_user_id = user
        return True

    def action_open_ai_assistant(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'res.users', 'res_id': self.ai_assistant_user_id.id,
                'view_mode': 'form', 'target': 'current'}

    def action_open_ai_agents(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('ai_agent.action_agents')
        action.update(domain=[('department_id', '=', self.id)],
                      context={'default_department_id': self.id, 'default_access_scope': 'users',
                               'default_department_ids': [(6, 0, self.ids)]})
        return action
