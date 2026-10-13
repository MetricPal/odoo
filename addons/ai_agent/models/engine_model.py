from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .common import manager, trusted


class EngineModel(models.Model):
    _name = 'ai.agent.engine.model'
    _description = 'Enabled Hermes model'
    _order = 'provider, model'

    engine_id = fields.Many2one('ai.agent.engine', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='engine_id.company_id', store=True)
    provider = fields.Char(required=True, readonly=True)
    model = fields.Char(required=True, readonly=True)
    name = fields.Char(compute='_compute_name', store=True)
    enabled = fields.Boolean(default=True)
    _pair_unique = models.UniqueIndex('(engine_id, provider, model)', 'This model is already registered for this engine.')

    @api.depends('provider', 'model')
    def _compute_name(self):
        for record in self:
            record.name = '%s / %s' % (record.provider, record.model)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            engine = self.env['ai.agent.engine'].browse(vals.get('engine_id')).exists()
            if not engine:
                raise UserError(_('Choose a saved Hermes connection.'))
            manager(engine)
            if not trusted(self):
                engine._validate_catalog_model(vals.get('provider'), vals.get('model'))
            if {'company_id', 'name'} & vals.keys():
                raise AccessError(_('Model ownership and labels are derived from the connection.'))
        return super().create(vals_list)

    def write(self, vals):
        for record in self:
            manager(record.engine_id)
            if {'engine_id', 'provider', 'model', 'company_id', 'name'} & vals.keys():
                raise AccessError(_('Model identity cannot be reassigned. Enable another model instead.'))
            if vals.get('enabled') and not trusted(self):
                record.engine_id._validate_catalog_model(record.provider, record.model)
        return super().write(vals)

    def action_disable(self):
        self.ensure_one()
        self.write({'enabled': False})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def unlink(self):
        for record in self:
            manager(record.engine_id)
        return super().unlink()
