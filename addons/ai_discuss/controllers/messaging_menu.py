from odoo.fields import Domain

from odoo.addons.mail.controllers.discuss.messaging_menu import (
    DiscussMessagingMenuController,
)


class AiDiscussMessagingMenuController(DiscussMessagingMenuController):
    def _get_menu_tab_filter_domain(self, tab_id, filter_id):
        # The Assistants filter of Chats (approved mock 2026-11-08, boards 10 and 12).
        if (tab_id, filter_id) == ('chat', 'chat_assistant'):
            return Domain('ai_agent_id', '!=', False)
        return super()._get_menu_tab_filter_domain(tab_id, filter_id)
