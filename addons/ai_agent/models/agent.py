import json

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.orm.domains import Domain

from .common import digest, internal, manager, trusted

SAFE_MODELS = {'res.partner', 'crm.lead', 'sale.order', 'product.product', 'product.template',
               'stock.quant', 'purchase.order', 'project.task'}
SCALAR_TYPES = {'char', 'text', 'integer', 'float', 'monetary', 'boolean', 'date', 'datetime', 'selection'}


class Agent(models.Model):
    _name = 'ai.agent'
    _description = 'AI Agent'
    _inherit = ['ai.agent.configuration.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    description = fields.Char()
    active = fields.Boolean(default=True)
    state = fields.Selection([('draft', 'Draft'), ('active', 'Active'), ('paused', 'Paused')],
                             default='draft', readonly=True, tracking=True)
    engine_id = fields.Many2one('ai.agent.engine', required=True, ondelete='restrict', check_company=True)
    engine_model_id = fields.Many2one('ai.agent.engine.model', string='AI model', ondelete='restrict', check_company=True)
    access_scope = fields.Selection([('company', 'Company'), ('users', 'Departments & users')], default='users', required=True, string='Access scope')
    department_ids = fields.Many2many('hr.department', string='Departments', check_company=True)
    user_ids = fields.Many2many('res.users', string='Users')
    can_chat = fields.Boolean(compute='_compute_can_chat', search='_search_can_chat')
    system_prompt = fields.Text(required=True, default='Explain permitted business context, draft and recommend. State uncertainty. Never claim to have performed a business action.')
    response_style = fields.Selection([('standard', 'Standard — Balanced, direct responses.'), ('nuanced', 'Nuanced — Context-aware and detailed.'),
                                       ('creative', 'Snappy & Creative — Concise, engaging, and dynamic.'), ('rigorous', 'Slow & Rigorous — Deeply analyzed and checked.')],
                                      default='standard', required=True)
    provider = fields.Char(help='Hermes provider slug. Leave blank to use its configured default.')
    model = fields.Char(string='Model', help='Verified Hermes model ID; leave blank for its default.')
    skill_ids = fields.Many2many('ai.agent.skill', check_company=True)
    source_ids = fields.Many2many('ai.agent.source', check_company=True)
    access_ids = fields.One2many('ai.agent.access', 'agent_id', string='Permitted data')
    restrict_sources = fields.Boolean(string='Ground knowledge answers in sources', default=True)
    max_concurrent = fields.Integer(default=2, required=True, string='Concurrent requests')
    max_requests_per_day = fields.Integer(default=50, required=True, string='Daily request limit')
    revision = fields.Integer(default=1, readonly=True)
    activation_hash = fields.Char(readonly=True, groups='ai_agent.group_manager')
    run_ids = fields.One2many('ai.agent.run', 'agent_id', readonly=True)

    def _audience_domain(self, user):
        if not user.active or user.share or not user.has_group('ai_agent.group_user'):
            return Domain.FALSE
        # Privileged identity lookup only; no employee data enters AI context.
        employees = self.env['hr.employee'].sudo().search([
            ('user_id', '=', user.id), ('active', '=', True), ('company_id', 'in', user.company_ids.ids),
            ('department_id.active', '=', True)])
        departments = employees.filtered(lambda e: e.department_id.company_id == e.company_id).mapped('department_id').ids
        return Domain('company_id', 'in', user.company_ids.ids) & (
            Domain('access_scope', '=', 'company') |
            (Domain('access_scope', '=', 'users') & (Domain('department_ids', 'in', departments) | Domain('user_ids', 'in', [user.id]))))

    def _search_can_chat(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return NotImplemented
        domain = self._audience_domain(self.env.user)
        return domain if (value if operator == '=' else not value) else ~domain

    @api.depends_context('uid')
    def _compute_can_chat(self):
        permitted = self.filtered_domain(self._audience_domain(self.env.user))
        for agent in self:
            agent.can_chat = agent in permitted

    @api.onchange('engine_id')
    def _onchange_engine_model(self):
        if self.engine_model_id and self.engine_model_id.engine_id != self.engine_id:
            self.engine_model_id = False
            self.provider = False
            self.model = False

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._model_values(dict(values)) for values in vals_list])

    def _model_values(self, values):
        if 'engine_model_id' not in values and {'provider', 'model'} & values.keys():
            if not values.get('provider') and not values.get('model'):
                values['engine_model_id'] = False
            else:
                engine_id = values.get('engine_id') or (self.engine_id.id if len(self) == 1 else False)
                option = self.env['ai.agent.engine.model'].search([('engine_id', '=', engine_id),
                    ('provider', '=', values.get('provider')), ('model', '=', values.get('model')), ('enabled', '=', True)], limit=1)
                if not option:
                    raise UserError(_('Enable this model on the Hermes connection before selecting it for an agent.'))
                values['engine_model_id'] = option.id
        if 'engine_model_id' in values:
            option = self.env['ai.agent.engine.model'].browse(values['engine_model_id']).exists() if values['engine_model_id'] else False
            if option:
                option.check_access('read')
                if not option.enabled:
                    raise UserError(_('Choose a model enabled on the Hermes connection.'))
                values.update(provider=option.provider, model=option.model)
            else:
                values.update(provider=False, model=False)
        return values

    def _check_enabled_model(self):
        self.ensure_one()
        option = self.sudo().engine_model_id
        if self.provider and not option:
            raise UserError(_('Select an enabled model from the Hermes connection before using this agent.'))
        if option and (not option.enabled or option.engine_id != self.engine_id):
            raise UserError(_('The selected AI model is no longer enabled on this connection. Ask an AI Agent manager to select another model.'))

    @api.constrains('access_scope', 'department_ids', 'user_ids', 'skill_ids', 'source_ids', 'engine_id', 'max_concurrent', 'max_requests_per_day', 'provider', 'model', 'engine_model_id')
    def _check_configuration(self):
        for agent in self:
            if any(d.company_id != agent.company_id for d in agent.department_ids):
                raise ValidationError(_('Choose departments in this company.'))
            if any(u.share or agent.company_id not in u.company_ids for u in agent.user_ids):
                raise ValidationError(_('Choose internal users authorized for this company.'))
            if any(r.company_id != agent.company_id for r in agent.skill_ids):
                raise ValidationError(_('Skills must belong to the agent company.'))
            if agent.engine_id.company_id != agent.company_id or any(s.company_id != agent.company_id for s in agent.source_ids):
                raise ValidationError(_('Engine and sources must belong to the agent company.'))
            if not 1 <= agent.max_concurrent <= 10 or not 1 <= agent.max_requests_per_day <= 1000:
                raise ValidationError(_('Use 1–10 concurrent requests and 1–1000 requests per day.'))
            agent._check_enabled_model()
            if agent.engine_model_id and (agent.provider != agent.engine_model_id.provider or agent.model != agent.engine_model_id.model):
                raise ValidationError(_('Provider and model must match the selected enabled model.'))
            if bool(agent.provider) != bool(agent.model):
                raise ValidationError(_('Set both provider and model, or leave both blank.'))

    def write(self, vals):
        vals = self._model_values(dict(vals))
        if not trusted(self):
            if {'state', 'revision', 'activation_hash'} & vals.keys():
                raise AccessError(_('Use the activation and pause buttons.'))
            manager(self)
            if vals and any(a.state == 'active' for a in self):
                raise UserError(_('Pause the agent before changing its configuration.'))
            for agent in self:
                super(Agent, agent).write({**vals, 'revision': agent.revision + 1, 'activation_hash': False})
            return True
        return super().write(vals)

    def _configuration_hash(self):
        self.ensure_one()
        return digest({'revision': self.revision, 'engine': self.engine_id.id,
                       'engine_revision': self.engine_id.revision,
                       'skills': [(s.id, s.revision, s.state) for s in self.skill_ids],
                       'sources': [(s.id, s.revision, s.state, s.active) for s in self.source_ids],
                       'access': [(a.id, a.model_name, a.field_names, a.domain_json, a.limit) for a in self.access_ids]})

    def action_choose_model(self):
        manager(self)
        self.ensure_one()
        if self.state == 'active':
            raise UserError(_('Pause the agent before changing its model.'))
        picker = self.env['ai.agent.model.picker'].create({'engine_id': self.engine_id.id,
            'agent_id': self.id, 'catalog': self.engine_id._model_catalog(),
            'provider': self.provider, 'model': self.model, 'use_default': not self.provider})
        return {'type': 'ir.actions.act_window', 'res_model': picker._name, 'res_id': picker.id,
                'view_mode': 'form', 'target': 'new', 'name': _('Choose provider and model')}

    def action_activate(self):
        manager(self)
        for agent in self:
            agent._check_enabled_model()
            if agent.access_scope == 'users' and not (agent.department_ids or agent.user_ids):
                raise UserError(_('Select at least one department or user.'))
            if agent.skill_ids.filtered(lambda s: s.state != 'approved'):
                raise UserError(_('Approve every assigned skill revision first.'))
            if agent.source_ids.filtered(lambda s: not s.active or s.state != 'ready'):
                raise UserError(_('Prepare and activate every assigned source first.'))
            if agent.engine_id.state != 'ready':
                raise UserError(_('Check the Hermes connection first.'))
            internal(agent).write({'state': 'active', 'activation_hash': agent._configuration_hash()})
        return True

    def action_pause(self):
        manager(self)
        internal(self).write({'state': 'paused'})
        runs = self.env['ai.agent.run'].sudo().search([('agent_id', 'in', self.ids),
                                                      ('state', 'in', ['queued', 'running', 'submitting'])])
        for run in runs:
            internal(run).write({'state': 'cancelled' if run.state == 'queued' else 'stop_requested'})
        return True

    @api.model
    def action_pause_all(self):
        if not self.env.user.has_group('ai_agent.group_manager'):
            raise AccessError(_('Only AI Agent managers may pause agents.'))
        return self.search([('state', '=', 'active')]).action_pause()

    def _usable(self):
        self.ensure_one()
        self.check_access('read')
        if self.env.user.share or not self.env.user.has_group('ai_agent.group_user'):
            raise AccessError(_('Only authorized internal users may use this assistant.'))
        if not self.sudo().filtered_domain(self._audience_domain(self.env.user)) or self.company_id not in self.env.companies:
            raise AccessError(_('You are not in this agent’s permitted audience.'))
        self._check_enabled_model()
        if not self.active or self.state != 'active':
            raise UserError(_('This agent is not active.'))
        if self.engine_id.sudo().state != 'ready':
            raise UserError(_('The Hermes connection needs attention. Ask an AI manager to check it.'))
        if self.sudo().activation_hash != self.sudo()._configuration_hash():
            raise UserError(_('Agent configuration changed. A manager must review and activate it again.'))

    def action_chat(self):
        self._usable()
        return {'type': 'ir.actions.act_window', 'res_model': 'ai.agent.ask', 'view_mode': 'form',
                'target': 'new', 'name': _('Ask AI'), 'context': {'default_agent_id': self.id}}

    def action_configure(self):
        self.ensure_one()
        manager(self)
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'current'}

    def _context_for(self, prompt):
        """Read as requester, never as a bot or sudo. No relation display-name traversal."""
        self._usable()
        context = {'company': self.company_id.name, 'records': [], 'sources': []}
        for access in self.sudo().access_ids:
            model = self.env[access.model_name].with_company(self.company_id).with_context(allowed_company_ids=[self.company_id.id])
            names = access._fields_allowed(model)
            domain = Domain(json.loads(access.domain_json))
            if 'company_id' in model._fields:
                domain &= Domain.OR([Domain('company_id', '=', False), Domain('company_id', '=', self.company_id.id)])
            records = model.search(domain, limit=access.limit, order='id')
            context['records'].append({'model': access.model_name, 'records': records.read(names, load=None)})
        terms = set(prompt.lower().split())
        for source in self.sudo().source_ids:
            permitted = source.with_user(self.env.user).sudo(False).with_context(allowed_company_ids=[self.company_id.id])
            try:
                permitted.check_access('read')
            except AccessError:
                continue
            source = permitted
            if source.state != 'ready' or not source.active:
                continue
            paragraphs = [p.strip() for p in source.extracted_text.split('\n') if p.strip()]
            paragraphs.sort(key=lambda p: len(terms & set(p.lower().split())), reverse=True)
            context['sources'].append({'name': source.name, 'revision': source.revision,
                                       'excerpt': '\n'.join(paragraphs)[:8000]})
        if len(json.dumps(context, default=str)) > 60000:
            raise UserError(_('Reduce the selected record fields or source scope before asking.'))
        return context


class Access(models.Model):
    _name = 'ai.agent.access'
    _description = 'Agent read scope'
    _inherit = 'ai.agent.configuration.mixin'

    agent_id = fields.Many2one('ai.agent', required=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', required=True, readonly=True)
    model_name = fields.Selection(selection=lambda s: [(n, s.env[n]._description) for n in sorted(SAFE_MODELS) if n in s.env],
                                  required=True, string='Business data')
    field_names = fields.Char(required=True, string='Fields', default='name', help='Explicit scalar field allowlist, separated by commas.')
    domain_json = fields.Text(default='[]', required=True, string='Record filter', help='JSON record filter; no Python expressions.')
    limit = fields.Integer(default=10, required=True)

    def _fields_allowed(self, model):
        names = [n.strip() for n in self.field_names.split(',') if n.strip()]
        if not names or len(names) > 20 or len(set(names)) != len(names):
            raise ValidationError(_('Choose 1–20 distinct fields.'))
        for name in names:
            field = model._fields.get(name)
            if not field or name.startswith('_') or field.type not in SCALAR_TYPES or not field.store:
                raise ValidationError(_('Only stored scalar fields can be shared with AI.'))
            model.check_field_access(field, 'read')
        return names

    @api.constrains('model_name', 'field_names', 'domain_json', 'limit', 'agent_id')
    def _validate_scope(self):
        for access in self:
            if access.model_name not in SAFE_MODELS or access.model_name not in self.env:
                raise ValidationError(_('Choose a supported business document.'))
            access._fields_allowed(self.env[access.model_name])
            try:
                domain = json.loads(access.domain_json)
                if not isinstance(domain, list) or len(domain) > 50:
                    raise ValueError()
                Domain(domain).validate(self.env[access.model_name])
            except (ValueError, TypeError, KeyError):
                raise ValidationError(_('Enter a valid JSON record filter.')) from None
            if not 1 <= access.limit <= 50:
                raise ValidationError(_('Read at most 1–50 records per scope.'))
            if access.agent_id.state == 'active':
                raise UserError(_('Pause the agent before changing data access.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            agent = self.env['ai.agent'].browse(vals.get('agent_id')).exists()
            manager(agent)
            if agent.state == 'active':
                raise UserError(_('Pause the agent before changing data access.'))
            vals['company_id'] = agent.company_id.id
        return super().create(vals_list)

    def write(self, vals):
        if self.agent_id.filtered(lambda a: a.state == 'active'):
            raise UserError(_('Pause the agent before changing data access.'))
        if 'agent_id' in vals and vals['agent_id'] not in self.agent_id.ids:
            raise AccessError(_('Data scopes cannot be reassigned.'))
        return super().write(vals)

    def unlink(self):
        if self.agent_id.filtered(lambda a: a.state == 'active'):
            raise UserError(_('Pause the agent before changing data access.'))
        return super().unlink()
