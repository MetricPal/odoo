from odoo import fields, models


class Run(models.Model):
    _inherit = 'ai.agent.run'

    ai_asking_message_ids = fields.Json(readonly=True, help='Status lines "<agent> is asking…" posted in the chat.')

    def _poll(self):
        result = super()._poll()
        # Keep "is typing…" on while an assistant chat waits for its answer (Discuss drops it after about a minute).
        if self.origin_model == 'discuss.channel' and self.state in ('queued', 'submitting', 'running'):
            self.env['discuss.channel'].sudo().browse(self.origin_res_id).exists()._ai_typing(True)
        return result

    def _route_deliver(self, agent, why):
        """Discuss (ADR 0015, board 20): the question goes to the person's chat with the chosen agent, under a
        "Chosen for you" note, and is asked there like any message the person writes."""
        if self.caller != 'chat':
            return super()._route_deliver(agent, why)
        user = self.user_id
        chat = self.env['discuss.channel'].with_user(user).with_context(
            allowed_company_ids=[self.company_id.id])._ai_chat_for(agent)
        chat._ai_chosen_note(agent, why, self)
        return chat._ai_post_question(self.prompt)
