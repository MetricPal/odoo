from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools import BinaryBytes, html_escape

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
        """An agent's avatar is the AI Agent app icon with the agent's initial in place of "AI" (owner, 2026-11-09)."""
        if not self.ai_agent_partner:
            return super()._avatar_generate_svg()
        initial = html_escape((self.name or '?')[0].upper())
        return BinaryBytes((
            '<?xml version="1.0" encoding="UTF-8" ?>'
            '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180" viewBox="26 16 102 102">'
            '<rect x="26" y="16" width="102" height="102" fill="#ffffff"/>'
            '<path d="M68 35H44a11 11 0 0 0-11 11v55a11 11 0 0 0 11 11h55a11 11 0 0 0 11-11V67" fill="none" '
            'stroke="#004692" stroke-width="6" stroke-linecap="butt"/>'
            f'<text x="66" y="93" fill="#00bdf6" font-family="sans-serif" font-weight="700" font-size="46" '
            f'text-anchor="middle">{initial}</text>'
            '<path d="m92 20 4.7 10.3L107 35l-10.3 4.7L92 50l-4.7-10.3L77 35l10.3-4.7L92 20ZM113 40l3.3 7.7L124 '
            '51l-7.7 3.3L113 62l-3.3-7.7L102 51l7.7-3.3L113 40ZM117 24l1.9 4.1L123 30l-4.1 1.9L117 36l-1.9-4.1L111 '
            '30l4.1-1.9L117 24Z" fill="#ffb855"/>'
            '</svg>'
        ).encode(), filename=f'avatar_{initial}.svg')

    def _store_avatar_fields(self, res: Store.FieldList):
        super()._store_avatar_fields(res)
        # The AI label next to an assistant's name (approved mocks 2026-11-08, boards 10 to 12).
        res.attr('ai_agent_partner', predicate=lambda partner: partner.ai_agent_partner)
