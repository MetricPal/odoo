"""Research in the Marketing assistant's chat (option 2a, approved boards 12.4 to 12.6, 2026-11-13).

In the person's chat with a Marketing assistant, Research in the composer (or the /research command) makes the
message a research question: it is saved in Insights › Research and answered in the chat. Other messages are
normal chat questions, as before.
"""

from markupsafe import Markup

from odoo import _, models

from odoo.addons.mail.tools.discuss import Store

COMMAND = '/research'


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _mi_research_chat(self):
        """The current person's chat with a Marketing assistant, and the person works in Marketing."""
        self.ensure_one()
        agent = self.sudo().ai_agent_id
        if self.channel_type != 'chat' or not agent or not self.env.user.has_group('marketing_intel.group_mi_user'):
            return False
        return agent in self.env['mi.panel']._mi_assistant_agents()

    def _ai_ask(self, message):
        if self.env.context.get('mi_research_question'):
            return None  # a research question: mi.research asks it and answers in the chat
        return super()._ai_ask(message)

    def _store_channel_fields(self, res: Store.FieldList):
        super()._store_channel_fields(res)
        res.attr('mi_research', lambda c: c._mi_research_chat(), predicate=lambda c: bool(c.sudo().ai_agent_id))

    def execute_command_research(self, body='', **kwargs):
        """/research <question>: the question as research, with the first brand and where web search allows."""
        self.ensure_one()
        if not self._mi_research_chat():
            text = _('Research is asked in your chat with the Marketing assistant.')
            self.env.user._bus_send_transient_message(self, Markup('<p>%s</p>') % text)
            return
        question = (body or '').strip()
        if question[:len(COMMAND)].lower() == COMMAND:
            question = question[len(COMMAND):].strip()
        if not question:
            text = _('Write your question after /research, or switch on Research above the message box. The answer '
                     'comes here and stays in Insights › Research.')
            self.env.user._bus_send_transient_message(self, Markup('<p>%s</p>') % text)
            return
        Research = self.env['mi.research']
        desk = Research.get_desk()
        brand_id = desk['brands'][0]['id'] if desk['brands'] else False
        Research.ask_in_chat(self.id, question, brand_id, desk['web'], True)
