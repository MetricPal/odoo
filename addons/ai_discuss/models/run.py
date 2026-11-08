from odoo import models


class Run(models.Model):
    _inherit = 'ai.agent.run'

    def _poll(self):
        result = super()._poll()
        # Keep "is typing…" on while an assistant chat waits for its answer (Discuss drops it after about a minute).
        if self.origin_model == 'discuss.channel' and self.state in ('queued', 'submitting', 'running'):
            self.env['discuss.channel'].sudo().browse(self.origin_res_id).exists()._ai_typing(True)
        return result
