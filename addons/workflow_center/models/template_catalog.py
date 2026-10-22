"""Workflow templates: built-in recipes (from code, read-only) and the
organization's own templates, saved from a workflow.

A saved template keeps a hidden copy of the workflow (``is_template``) that
can be edited in the builder but never activated. Starting from any template
creates a new draft that still needs a preview and an administrator's
activation.
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .templates import catalog

CATEGORIES = [
    ('reminders', 'Reminders'),
    ('data_updates', 'Data updates'),
    ('create_records', 'Create records'),
    ('scheduled', 'Scheduled'),
    ('integrations', 'Integrations'),
    ('approvals', 'Approvals'),
    ('other', 'Other'),
]
CATEGORY_KEYS = {label: key for key, label in CATEGORIES}
# Application that each built-in recipe belongs to (its module in Apps).
APP_MODULES = {
    'Invoicing': 'account', 'CRM': 'crm', 'Employees': 'hr', 'Expenses': 'hr_expense',
    'Inventory': 'stock', 'Sales': 'sale_management', 'Purchase': 'purchase', 'Recruitment': 'hr_recruitment',
}
TRIGGERS = {
    'manual': 'Button / run manually', 'create': 'Record created', 'write': 'Record changed',
    'stage': 'Stage or status changed', 'date': 'Date field', 'schedule': 'Schedule', 'webhook': 'Incoming webhook',
}


def boolean_search_values(operator, value):
    """Booleans a search on a computed Boolean field asks for, or None if unsupported.

    Odoo 20 passes ``in``/``not in`` with a set of values (``= True`` becomes
    ``in {True}``); older callers may still pass ``=``/``!=``.
    """
    if operator in ('=', '!='):
        values = {bool(value)}
    elif operator in ('in', 'not in'):
        values = {bool(item) for item in value}
    else:
        return None
    if operator in ('!=', 'not in'):
        values = {True, False} - values
    return values


class WorkflowTemplate(models.Model):
    _name = 'workflow.template'
    _description = 'Workflow template'
    _order = 'builtin desc, sequence, id'

    key = fields.Char(readonly=True, index=True, help='Built-in recipe key.')
    name = fields.Char(required=True)
    description = fields.Text()
    sequence = fields.Integer(default=100)
    active = fields.Boolean(default=True)
    builtin = fields.Boolean(readonly=True, string='Built-in')
    app_id = fields.Many2one('ir.module.module', string='Application', readonly=True, ondelete='set null')
    category = fields.Selection(CATEGORIES, required=True, default='other')
    model_name = fields.Char(string='Document model', readonly=True)
    trigger = fields.Char(string='Starts when', readonly=True)
    workflow_id = fields.Many2one('workflow.definition', string='Template workflow', readonly=True,
                                  ondelete='cascade', help='Hidden copy that new workflows start from.')
    available = fields.Boolean(string='Application installed', compute='_compute_details',
                               search='_search_available')
    blocks = fields.Char(string='Steps', compute='_compute_details')
    app_name = fields.Char(string='Application name', compute='_compute_details')
    _key_unique = models.Constraint('UNIQUE(key)', 'Built-in template keys are unique.')

    @api.depends('key', 'model_name', 'workflow_id.step_ids.name', 'app_id')
    def _compute_details(self):
        recipes = {item['key']: item for item in catalog()}
        for record in self:
            record.available = bool(record.model_name) and record.model_name in self.env
            if record.builtin:
                names = recipes.get(record.key, {}).get('blocks', [])
            else:
                names = record.sudo().workflow_id.step_ids.sorted('sequence').mapped('name')
            record.blocks = ' · '.join(names[:4])
            record.app_name = record.sudo().app_id.shortdesc or ''

    def _search_available(self, operator, value):
        values = boolean_search_values(operator, value)
        if values is None:
            return NotImplemented
        if values == {True, False}:
            return []
        installed = [record.id for record in self.sudo().with_context(active_test=False).search([])
                     if record.model_name in self.env]
        if not values:
            return [('id', 'in', [])]
        return [('id', 'in' if True in values else 'not in', installed)]

    # ------------------------------------------------------------------ built-ins

    @api.model
    def _app_for(self, label):
        module = APP_MODULES.get(label)
        return self.env['ir.module.module'].sudo().search([('name', '=', module)], limit=1) if module else False

    @api.model
    def _sync_builtin(self):
        """Create or refresh the built-in templates from the code catalogue (install and upgrade)."""
        Template = self.sudo().with_context(active_test=False)
        keys = []
        for index, item in enumerate(catalog(), 1):
            keys.append(item['key'])
            values = {
                'name': item['name'], 'description': item['description'], 'sequence': index,
                'builtin': True, 'category': CATEGORY_KEYS.get(item['category'], 'other'),
                'model_name': item['model'], 'trigger': TRIGGERS.get(item['trigger'], item['trigger']),
                'app_id': (self._app_for(item['app']) or self.env['ir.module.module']).id,
            }
            existing = Template.search([('key', '=', item['key'])], limit=1)
            if existing:
                existing.with_context(workflow_template_sync=True).write(values)
            else:
                Template.with_context(workflow_template_sync=True).create(dict(values, key=item['key']))
        Template.search([('builtin', '=', True), ('key', 'not in', keys)]).with_context(
            workflow_template_sync=True).unlink()

    # ------------------------------------------------------------------ protection

    def _manager(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only Settings administrators manage workflow templates.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('workflow_template_sync'):
            self._manager()
            if not self.env.context.get('workflow_template_save') or any(
                    vals.get('builtin') or vals.get('key') for vals in vals_list):
                raise AccessError(_('Save a workflow as a template from the workflow itself.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('workflow_template_sync'):
            self._manager()
            if self.filtered('builtin') and set(vals) - {'active', 'sequence'}:
                raise UserError(_('Built-in templates cannot be changed. Start a workflow from it and save that '
                                  'as your own template instead.'))
            if {'builtin', 'key', 'workflow_id'} & vals.keys():
                raise AccessError(_('This template field is managed by the Workflows app.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('workflow_template_sync'):
            self._manager()
            if self.filtered('builtin'):
                raise UserError(_('Built-in templates cannot be deleted. Archive them to hide them.'))
        workflows = self.sudo().workflow_id
        result = super().unlink()
        workflows.with_context(workflow_template_cleanup=True).unlink()
        return result

    # ------------------------------------------------------------------ actions

    def action_start(self):
        self.ensure_one()
        self.check_access('read')
        Workflow = self.env['workflow.definition']
        if self.builtin:
            workflow = Workflow.browse(Workflow.from_template(self.key))
        else:
            Workflow._manager()
            if not self.available:
                raise UserError(_('Install the application of this template first.'))
            workflow = self.workflow_id._clone({'name': self.name, 'description': self.description})
        return workflow.action_open_builder()

    def action_edit_template(self):
        self.ensure_one()
        self._manager()
        if self.builtin:
            raise UserError(_('Built-in templates cannot be changed. Start a workflow from it instead.'))
        return self.workflow_id.action_open_builder()


class WorkflowTemplateSave(models.TransientModel):
    _name = 'workflow.template.save'
    _description = 'Save a workflow as a template'

    workflow_id = fields.Many2one('workflow.definition', required=True, readonly=True)
    name = fields.Char(required=True, string='Template name')
    description = fields.Text(help='Shown on the template card: what the workflow does and when to use it.')
    category = fields.Selection(CATEGORIES, required=True, default='other')

    def action_save(self):
        self.ensure_one()
        workflow = self.workflow_id
        workflow._manager()
        workflow._not_template()
        copy = workflow._clone({'name': self.name, 'description': self.description}, is_template=True)
        model = self.env['ir.model']._get(workflow.model_name)
        app = self.env['ir.module.module'].sudo().search(
            [('name', 'in', (model.modules or '').replace(' ', '').split(',')), ('application', '=', True)], limit=1)
        template = self.env['workflow.template'].with_context(workflow_template_save=True).create({
            'name': self.name, 'description': self.description, 'category': self.category,
            'model_name': workflow.model_name, 'trigger': TRIGGERS.get(workflow.trigger, workflow.trigger),
            'app_id': app.id,
        })
        template.with_context(workflow_template_sync=True).write({'workflow_id': copy.id})
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'type': 'success', 'title': _('Template saved'),
            'message': _('“%s” is now in Templates under My templates.', self.name),
            'next': {'type': 'ir.actions.act_window_close'},
        }}
