from odoo import fields, models, _


class Ask(models.TransientModel):
    _name = 'ai.agent.ask'
    _description = 'Ask AI'

    agent_id = fields.Many2one('ai.agent', required=True, domain="[('state', '=', 'active')]")
    conversation_id = fields.Many2one('ai.agent.conversation')
    prompt = fields.Text(required=True, string='Your question')
    attachment_ids = fields.Many2many('ir.attachment', string='Files',
                                      help='Readable PDF or UTF-8 text, Markdown or CSV files, up to 5 MB each.')

    def action_send(self):
        self.ensure_one()
        run = self.env['ai.agent.run']._queue(self.agent_id, self.prompt, self.conversation_id,
                                              attachments=self.attachment_ids)
        return {'type': 'ir.actions.act_window', 'res_model': 'ai.agent.conversation', 'res_id': run.conversation_id.id,
                'view_mode': 'form', 'target': 'current', 'name': _('Conversation')}
