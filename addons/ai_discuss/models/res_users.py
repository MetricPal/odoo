from odoo import models


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _on_webclient_bootstrap(self):
        super()._on_webclient_bootstrap()
        if self._is_internal() and self.has_group('ai_agent.group_user'):
            self.env['discuss.channel'].with_user(self)._ai_ensure_assistant_chats()
