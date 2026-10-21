from odoo import api, fields, models
from odoo.tools import SQL
from .templates import catalog



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
    """Read-only recipe metadata for native search/filter/group controls."""
    _name = 'workflow.template'
    _description = 'Workflow template'
    _auto = False
    _log_access = False
    _order = 'id'

    key = fields.Char(readonly=True)
    name = fields.Char(readonly=True)
    description = fields.Text(readonly=True)
    app = fields.Selection(
        selection=lambda self: [(app, app) for app in sorted({item['app'] for item in catalog()})],
        string='Application', readonly=True,
    )
    category = fields.Char(readonly=True)
    model_name = fields.Char(string='Document model', readonly=True)
    trigger = fields.Char(string='Starts when', readonly=True)

    available = fields.Boolean(string='Application installed', compute='_compute_recipe_details',
                               search='_search_available')
    blocks = fields.Char(string='Steps', compute='_compute_recipe_details')

    @api.depends('key', 'model_name')
    def _compute_recipe_details(self):
        recipes = {item['key']: item for item in catalog()}
        for record in self:
            record.available = record.model_name in self.env
            record.blocks = ' · '.join(recipes.get(record.key, {}).get('blocks', [])[:4])

    def _search_available(self, operator, value):
        values = boolean_search_values(operator, value)
        if values is None:
            return NotImplemented
        if values == {True, False}:
            return []
        installed = [record.id for record in self.sudo().search([]) if record.model_name in self.env]
        if not values:
            return [('id', 'in', [])]
        return [('id', 'in' if True in values else 'not in', installed)]

    def action_start(self):
        self.ensure_one()
        self.check_access('read')
        workflow_id = self.env['workflow.definition'].from_template(self.key)
        return self.env['workflow.definition'].browse(workflow_id).action_open_builder()

    def init(self):
        rows = SQL(', ').join(
            SQL('(%s, %s, %s, %s, %s, %s, %s, %s)',
                index, item['key'], item['name'], item['description'], item['app'],
                item['category'], item['model'], item['trigger'])
            for index, item in enumerate(catalog(), 1)
        )
        self.env.cr.execute(SQL(
            'CREATE OR REPLACE VIEW %s AS SELECT * FROM (VALUES %s) '
            'AS recipe(id, key, name, description, app, category, model_name, trigger)',
            SQL.identifier(self._table), rows,
        ))
