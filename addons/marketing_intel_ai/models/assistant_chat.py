"""Ask the assistant (owner, 2026-11-09): the Marketing control panel opens the person's chat with the marketing
agent, the same chat window as in Discuss. The button shows only while such an agent is active for the person."""

from odoo import _, api, models
from odoo.exceptions import AccessError, UserError
from odoo.orm.domains import Domain


class Panel(models.AbstractModel):
    _inherit = 'mi.panel'

    @api.model
    def _mi_assistant_agent_domain(self):
        """Which agents are the marketing assistant: the agents set on the brands (marketing_intel_team adds the
        marketing department's)."""
        # sudo: mi.brand - only the brands' agent ids are read, to know which agents work for marketing.
        return Domain('id', 'in', self.env['mi.brand'].sudo().search([]).ai_agent_id.ids)

    @api.model
    def _mi_assistant_agents(self):
        """Active marketing agents the current person can chat with now, the one to open first."""
        Agent = self.env['ai.agent']
        if self.env.user.share or not self.env.user.has_group('ai_agent.group_user'):
            return Agent
        agents = Agent
        for agent in Agent.search(Domain('state', '=', 'active') & Domain('can_chat', '=', True)
                                  & self._mi_assistant_agent_domain()):
            try:
                agent._usable()
            except (AccessError, UserError):
                continue
            agents |= agent
        return agents

    @api.model
    def get_panel(self, brand_id=False):
        data = super().get_panel(brand_id=brand_id)
        data['assistant'] = bool(self._mi_assistant_agents())
        return data

    @api.model
    def open_assistant_chat(self):
        """The person's chat with the marketing agent (its id), made if needed."""
        agent = self._mi_assistant_agents()[:1]
        if not agent:
            raise UserError(_('No marketing assistant is active for you. Ask an AI Agent manager to activate the '
                              'marketing department\'s agent.'))
        return self.env['discuss.channel']._ai_chat_for(agent).id
