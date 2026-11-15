from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools import BinaryBytes

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

    def _avatar_generate_svg(self):
        """An agent's avatar is Odoo's usual one (its initial on its colour) with the stars of the AI Agent app icon
        at the top right (owner, 2026-11-15; before, the AI Agent icon's frame with the initial)."""
        avatar = super()._avatar_generate_svg()
        if not self.ai_agent_partner:
            return avatar
        # The stars keep the app icon's shape and colour; the white edge keeps them clear on any avatar colour.
        stars = (
            '<path transform="translate(26.4 -13) scale(1.15)" fill="#ffb855" stroke="#ffffff" stroke-width="2.6" '
            'stroke-linejoin="round" paint-order="stroke" '
            'd="m92 20 4.7 10.3L107 35l-10.3 4.7L92 50l-4.7-10.3L77 35l10.3-4.7L92 20ZM113 40l3.3 7.7L124 '
            '51l-7.7 3.3L113 62l-3.3-7.7L102 51l7.7-3.3L113 40ZM117 24l1.9 4.1L123 30l-4.1 1.9L117 36l-1.9-4.1L111 '
            '30l4.1-1.9L117 24Z"/>'
        )
        return BinaryBytes(avatar.content.replace(b'</svg>', stars.encode() + b'</svg>'), filename=avatar.filename)

    def _store_avatar_fields(self, res: Store.FieldList):
        super()._store_avatar_fields(res)
        # The AI label next to an assistant's name (approved mocks 2026-11-08, boards 10 to 12).
        res.attr('ai_agent_partner', predicate=lambda partner: partner.ai_agent_partner)
