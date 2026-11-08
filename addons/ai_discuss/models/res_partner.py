from odoo import api, fields, models
from odoo.fields import Domain

from odoo.addons.mail.tools.discuss import Store


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ai_agent_partner = fields.Boolean(string='AI assistant chat partner', readonly=True, copy=False,
                                      help='The identity of an AI agent in Discuss and the chatter (ADR 0013).')

    @api.model
    def _get_mention_suggestions_domain(self, search):
        """AI assistant users are identities agents act as, not people to mention: they would never answer. Agents'
        own chat partners are archived, so the standard active filter already leaves them out."""
        return super()._get_mention_suggestions_domain(search) & Domain(
            'user_ids', 'not any', Domain('ai_assistant', '=', True))

    def _store_avatar_fields(self, res: Store.FieldList):
        super()._store_avatar_fields(res)
        # The AI label next to an assistant's name (approved mocks 2026-11-08, boards 10 to 12).
        res.attr('ai_agent_partner', predicate=lambda partner: partner.ai_agent_partner)
