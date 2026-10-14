from odoo import fields, models, _
from odoo.exceptions import UserError

from ..models.common import manager


class ModelPicker(models.TransientModel):
    _name = 'ai.agent.model.picker'
    _description = 'Choose Hermes provider and model'

    name = fields.Char(default='Providers and models', readonly=True)
    engine_id = fields.Many2one('ai.agent.engine', required=True)
    agent_id = fields.Many2one('ai.agent')
    catalog = fields.Json(readonly=True)
    provider = fields.Char()
    model = fields.Char()
    use_default = fields.Boolean(default=False, string='Use engine default')

    def _engine(self):
        self.ensure_one()
        manager(self.engine_id)
        if self.agent_id:
            manager(self.agent_id)
            if self.agent_id.engine_id != self.engine_id:
                raise UserError(_('The agent connection changed. Close this window and reopen the model picker.'))
        return self.engine_id

    def action_refresh(self):
        engine = self._engine()
        self.write({'catalog': engine._model_catalog()})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new', 'name': _('Providers and models')}

    def action_setup(self):
        engine = self._engine()
        return engine.action_provider_setup()

    def action_apply(self):
        engine = self._engine()
        if not self.agent_id:
            raise UserError(_('Change the engine default through provider setup in Hermes.'))
        if self.use_default:
            self.agent_id.write({'provider': False, 'model': False})
        else:
            catalog = engine._model_catalog()
            provider = next((p for p in catalog['providers'] if p['slug'] == self.provider), None)
            if not provider or provider['authenticated'] is not True:
                raise UserError(_('Authenticate this provider in Hermes, then refresh the catalog.'))
            if self.model not in provider['models']:
                raise UserError(_('Select a model returned by this provider in the current Hermes catalog.'))
            self.agent_id.write({'provider': self.provider, 'model': self.model})
        return {'type': 'ir.actions.act_window_close'}
