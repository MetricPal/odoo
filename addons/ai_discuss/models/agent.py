"""Each agent's own chat partner (ADR 0013, phase 1).

The partner is the agent's identity in Discuss and the chatter: its name and avatar, with an AI label. Like
OdooBot's partner it is archived, so it stays out of Contacts, pickers and @ suggestions, and nobody can log in
as it. It is never a user and never reads data: answers run as the agent's AI assistant user and the person who
asked (ADR 0012).
"""

from odoo import api, fields, models

from odoo.addons.ai_agent.models.common import internal


class Agent(models.Model):
    _inherit = 'ai.agent'

    partner_id = fields.Many2one('res.partner', string='Chat partner', readonly=True, copy=False,
                                 ondelete='set null', index='btree_not_null',
                                 help='How this assistant appears in Discuss and the chatter.')

    @api.model_create_multi
    def create(self, vals_list):
        agents = super().create(vals_list)
        agents._ensure_partner()
        return agents

    def write(self, vals):
        result = super().write(vals)
        if 'name' in vals or 'company_id' in vals:
            self._sync_partner()
        return result

    def unlink(self):
        partners = self.sudo().with_context(active_test=False).partner_id
        result = super().unlink()
        # An agent can only be deleted when it was never used (ai_agent); its partner then has no messages either.
        unused = partners.filtered(lambda p: not self.env['mail.message'].sudo().search_count(
            [('author_id', '=', p.id)], limit=1))
        unused.sudo().unlink()
        return result

    def _partner_values(self):
        return {'name': self.name, 'company_id': self.company_id.id, 'active': False, 'type': 'contact',
                'ai_agent_partner': True}

    def _ensure_partner(self):
        """A chat partner for every agent that has none (agents are created in several ways: kept idempotent)."""
        for agent in self.sudo().with_context(active_test=False).filtered(lambda a: not a.partner_id):
            partner = self.env['res.partner'].sudo().with_context(mail_create_nolog=True).create(
                agent._partner_values())
            internal(agent).write({'partner_id': partner.id})

    def _sync_partner(self):
        for agent in self.sudo().with_context(active_test=False):
            partner = agent.partner_id
            if partner and (partner.name != agent.name or partner.company_id != agent.company_id):
                partner.write({'name': agent.name, 'company_id': agent.company_id.id})
