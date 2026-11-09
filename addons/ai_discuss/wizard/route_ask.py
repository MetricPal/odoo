"""Ask an assistant from Discuss without choosing one (ADR 0015, board 20), and Change the chosen one."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class RouteAsk(models.TransientModel):
    _name = 'ai.agent.route.ask'
    _description = 'Ask an assistant'

    prompt = fields.Text(string='Your question', required=True)
    router_run_id = fields.Many2one('ai.agent.run', readonly=True)
    agent_id = fields.Many2one('ai.agent', string='Assistant')
    allowed_agent_ids = fields.Many2many('ai.agent', compute='_compute_allowed_agent_ids')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        context = self.env.context
        if context.get('active_model') == 'ai.agent.run' and context.get('active_id'):
            run = self.env['ai.agent.run'].browse(context['active_id']).exists()
            if run and run.user_id == self.env.user:
                values.update(prompt=run.prompt, router_run_id=run.id)
        return values

    @api.depends('router_run_id')
    def _compute_allowed_agent_ids(self):
        ids = [option['id'] for option in self.env['ai.agent']._chat_options()]
        for wizard in self:
            chosen = wizard.router_run_id.sudo().routed_run_id.agent_id
            wizard.allowed_agent_ids = [fields.Command.set([i for i in ids if i != chosen.id])]

    def action_send(self):
        self.ensure_one()
        agent = self.agent_id
        if agent and agent not in self.allowed_agent_ids:
            raise UserError(_('Choose one of your assistants.'))
        if not agent:
            options = self.env['ai.agent']._chat_options()
            if len(options) == 1:
                agent = self.env['ai.agent'].browse(options[0]['id'])
            else:
                self.env['ai.agent.run']._route(self.prompt, caller='chat')
                return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                    'type': 'info', 'title': _('Choosing the right assistant…'),
                    'message': _('The answer appears in your chat with the assistant chosen for you.'),
                    'next': {'type': 'ir.actions.act_window_close'}}}
        chat = self.env['discuss.channel']._ai_chat_for(agent)
        chat._ai_post_question(self.prompt)
        return {'type': 'ir.actions.act_url', 'url': '/odoo/action-mail.action_discuss?active_id=%s' % chat.id,
                'target': 'self'}
