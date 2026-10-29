from odoo import api, fields, models

AUTOMATION_STATUSES = [
    ('active', 'Active'),
    ('paused', 'Paused'),
    ('draft', 'Draft'),
    ('failed', 'Needs attention'),
]


class AiHomeItem(models.Model):
    _name = 'ai.home.item'
    _description = 'AI Home Item'
    _order = 'section, sequence, id'

    name = fields.Char(required=True, translate=True)
    section = fields.Selection(
        selection=[
            ('attention', 'Needs Your Attention'),
            ('automation', 'Automations'),
            ('recent', 'Recent'),
        ],
        required=True,
        index=True,
    )
    subtitle = fields.Char(translate=True)
    occurred_label = fields.Char(translate=True)
    icon_text = fields.Char(help='Short text displayed when the item has no image.')
    tone = fields.Selection(
        selection=[
            ('primary', 'Primary'),
            ('success', 'Success'),
            ('warning', 'Warning'),
            ('danger', 'Danger'),
            ('neutral', 'Neutral'),
            ('info', 'Info'),
        ],
        default='neutral',
        required=True,
    )
    automation_status = fields.Selection(
        AUTOMATION_STATUSES,
        string='Automation status',
        default='active',
        help='Status used by the Automations filter on Home.',
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        ondelete='cascade',
    )
    group_ids = fields.Many2many(
        'res.groups',
        string='Visible to Groups',
        help='Leave empty to show the item to every internal user who can access its company.',
    )
    seen_user_ids = fields.Many2many(
        'res.users',
        'ai_home_item_seen_user_rel',
        'item_id',
        'user_id',
        string='Seen by Users',
        copy=False,
        groups='base.group_system',
    )

    # ------------------------------------------------------------------
    # Static items (configured records)
    # ------------------------------------------------------------------

    @api.model
    def get_dashboard_items(self):
        """Return only dashboard items visible to the current internal user."""
        items = self.search([('active', '=', True)])
        user_groups = self.env.user.all_group_ids
        items = items.filtered(
            lambda item: not item.group_ids or bool(item.group_ids & user_groups)
        )
        items = items.filtered(
            lambda item: item.section != 'recent'
            or self.env.user not in item.sudo().seen_user_ids
        )
        return [
            {
                'id': item.id,
                'key': f'item-{item.id}',
                'name': item.name,
                'section': item.section,
                'subtitle': item.subtitle or '',
                'occurredLabel': item.occurred_label or '',
                'iconText': item.icon_text or item.name[:1].upper(),
                'tone': item.tone,
                'status': item.automation_status or 'active',
                'action': False,
            }
            for item in items
        ]

    @api.model
    def mark_recent_seen(self, item_id):
        """Mark an accessible Recent card as seen for the current user."""
        item = self.search([
            ('id', '=', item_id),
            ('section', '=', 'recent'),
            ('active', '=', True),
        ], limit=1)
        if not item:
            return False
        item.sudo().write({'seen_user_ids': [fields.Command.link(self.env.uid)]})
        return True
