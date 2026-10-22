"""Social profiles and chat channels of a contact.

Two sources: chats linked to the contact in Omnichannel (kept in sync,
read-only here) and profiles added by hand. The contact shows the platforms
of its active channels as tags; who can see the handles follows access rules
(chat identifiers only for members of that Omnichannel team).
"""

import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

# Platform code → (icon, tag colour index)
LOOK = {
    'whatsapp': ('oi_whatsapp', 10), 'telegram': ('oi_telegram', 4), 'messenger': ('oi_facebook-messenger', 8),
    'discord': ('oi_discord', 11), 'slack': ('oi_slack', 5), 'teams': ('forum', 8),
    'instagram': ('oi_instagram', 9), 'facebook': ('oi_facebook', 8), 'linkedin': ('oi_linkedin', 8),
    'x': ('oi_x', 6), 'threads': ('oi_threads', 6), 'tiktok': ('oi_tiktok', 1), 'youtube': ('oi_youtube-play', 1),
    'pinterest': ('oi_pinterest', 1),
}
# Profile address for a handle (``{h}`` = handle without a leading @).
PROFILE_URLS = {
    'instagram': 'https://www.instagram.com/{h}', 'facebook': 'https://www.facebook.com/{h}',
    'linkedin': 'https://www.linkedin.com/in/{h}', 'x': 'https://x.com/{h}',
    'threads': 'https://www.threads.net/@{h}', 'tiktok': 'https://www.tiktok.com/@{h}',
    'youtube': 'https://www.youtube.com/@{h}', 'pinterest': 'https://www.pinterest.com/{h}',
    'telegram': 'https://t.me/{h}', 'messenger': 'https://m.me/{h}',
}
CHANNEL_CODES = ('whatsapp', 'telegram', 'messenger', 'discord', 'slack', 'teams', 'instagram', 'facebook',
                 'linkedin', 'x', 'threads', 'tiktok', 'youtube', 'pinterest')


class ChannelType(models.Model):
    _inherit = 'omni.channel.type'

    icon = fields.Char(compute='_compute_look')
    color = fields.Integer(compute='_compute_look')

    @api.depends('code')
    def _compute_look(self):
        for row in self:
            row.icon, row.color = LOOK.get(row.code, ('forum', 6))


class PartnerChannel(models.Model):
    _name = 'omni.partner.channel'
    _description = 'Contact social or chat channel'
    _order = 'category desc, sequence, id'
    _rec_name = 'handle'

    partner_id = fields.Many2one('res.partner', required=True, ondelete='cascade', index=True, string='Contact')
    channel_type_id = fields.Many2one('omni.channel.type', required=True, ondelete='restrict', string='Platform',
                                      domain=[('code', 'in', CHANNEL_CODES)])
    category = fields.Selection(related='channel_type_id.category', store=True)
    icon = fields.Char(related='channel_type_id.icon')
    color = fields.Integer(related='channel_type_id.color')
    handle = fields.Char(required=True, string='Account',
                         help='Number, @username, ID or profile link on that platform.')
    url = fields.Char(compute='_compute_url', string='Profile')
    source = fields.Selection([('manual', 'Added by hand'), ('conversation', 'Omnichannel chat')],
                              required=True, default='manual', readonly=True)
    identity_id = fields.Many2one('omni.identity', readonly=True, ondelete='cascade', index='btree_not_null')
    channel_id = fields.Many2one(related='identity_id.channel_id', string='Chat channel')
    last_message_at = fields.Datetime(compute='_compute_last_message', string='Last message')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _identity_unique = models.UniqueIndex('(identity_id) WHERE identity_id IS NOT NULL',
                                          'This chat is already shown on a contact.')

    @api.depends('handle', 'channel_type_id.code')
    def _compute_url(self):
        for row in self:
            handle = (row.handle or '').strip()
            code = row.channel_type_id.code
            if re.match(r'^https?://', handle):
                row.url = handle
            elif code == 'whatsapp' and re.sub(r'\D', '', handle):
                row.url = 'https://wa.me/' + re.sub(r'\D', '', handle)
            elif code in PROFILE_URLS and handle and not (code == 'telegram' and handle.lstrip('-').isdigit()):
                row.url = PROFILE_URLS[code].format(h=handle.lstrip('@'))
            else:
                row.url = False

    def _compute_last_message(self):
        Message = self.env['omni.message'].sudo()
        for row in self:
            last = Message.search([('conversation_id.identity_id', '=', row.identity_id.id)],
                                  order='occurred_at desc', limit=1) if row.identity_id else Message
            row.last_message_at = last.occurred_at or False

    # ------------------------------------------------------------------ guards

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(vals.get('source', 'manual') != 'manual' or vals.get('identity_id')
                                   for vals in vals_list):
            raise AccessError(_('Chats appear here when they are linked to the contact in Omnichannel.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and (self.filtered(lambda r: r.source != 'manual') or {'source', 'identity_id'} & vals.keys()):
            raise AccessError(_('Chats linked in Omnichannel are managed there.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and self.filtered(lambda r: r.source != 'manual'):
            raise AccessError(_('Unlink the chat from the contact in Omnichannel instead.'))
        return super().unlink()

    # ------------------------------------------------------------------ sync

    @api.model
    def _sync_identities(self, identities):
        """One row per Omnichannel identity linked to a contact; removed when unlinked."""
        Channel = self.sudo().with_context(active_test=False)
        for identity in identities.sudo():
            row = Channel.search([('identity_id', '=', identity.id)], limit=1)
            partner = identity.partner_id
            if not partner:
                row.unlink()
                continue
            values = {'partner_id': partner.id, 'channel_type_id': identity.channel_id.channel_type_id.id,
                      'handle': identity.external_key, 'active': bool(identity.channel_id.active)}
            if row:
                row.write(values)
            else:
                Channel.create(dict(values, source='conversation', identity_id=identity.id))


class Identity(models.Model):
    _inherit = 'omni.identity'

    @api.model_create_multi
    def create(self, vals_list):
        identities = super().create(vals_list)
        self.env['omni.partner.channel']._sync_identities(identities.filtered('partner_id'))
        return identities

    def write(self, vals):
        result = super().write(vals)
        if 'partner_id' in vals:
            self.env['omni.partner.channel']._sync_identities(self)
        return result


class OmniChannel(models.Model):
    _inherit = 'omni.channel'

    def write(self, vals):
        result = super().write(vals)
        if 'active' in vals:
            rows = self.env['omni.partner.channel'].sudo().with_context(active_test=False).search(
                [('identity_id.channel_id', 'in', self.ids)])
            rows.write({'active': bool(vals['active'])})
        return result


class Partner(models.Model):
    _inherit = 'res.partner'

    channel_ids = fields.One2many('omni.partner.channel', 'partner_id', string='Social & chat')
    active_channel_ids = fields.One2many('omni.partner.channel', compute='_compute_active_channels',
                                         string='Active social & chat')
    channel_type_ids = fields.Many2many(
        'omni.channel.type', compute='_compute_channel_types', store=True, string='Channels',
        help='Platforms where this contact has an active social profile or Omnichannel chat.')

    @api.depends('channel_ids.active')
    def _compute_active_channels(self):
        for partner in self:
            partner.active_channel_ids = partner.channel_ids.filtered('active')

    @api.depends('channel_ids.active', 'channel_ids.channel_type_id')
    def _compute_channel_types(self):
        for partner in self:
            partner.channel_type_ids = partner.sudo().channel_ids.filtered('active').channel_type_id
