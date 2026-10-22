"""UTM campaign, source and medium for Social posts, and tracked short links.

Links are shortened when a post is submitted, before its content is frozen for
review: the approver sees the exact text and, next to it, where each short
link leads. The list of links is part of the reviewed document, so a tracker
changed after approval stops the post from being published.
"""

import ipaddress
import re
from urllib.parse import urlsplit

from odoo import _, api, fields, models
from odoo.tools.mail import TEXT_URL_REGEX

from odoo.addons.omni_social.providers.registry import capabilities

SOURCES = {
    'facebook': 'utm.utm_source_facebook',
    'x': 'utm.utm_source_twitter',
    'linkedin': 'utm.utm_source_linkedin',
    'instagram': 'utm.utm_source_instagram',
    'youtube': 'utm.utm_source_youtube',
}


def public_base(url):
    """True when short links on this address can be opened from the internet."""
    parts = urlsplit(url or '')
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or not host or host == 'localhost' or host.endswith('.local'):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return '.' in host


class Campaign(models.Model):
    _inherit = 'omni.social.campaign'

    utm_campaign_id = fields.Many2one(
        'utm.campaign', string='Tracking campaign', ondelete='set null', copy=False,
        help='The campaign Link Tracker, CRM, Sales and Email Marketing report on. Created with the same name '
             'when left empty.',
    )
    link_clicks = fields.Integer(compute='_compute_link_clicks', string='Link clicks')

    @api.model_create_multi
    def create(self, vals_list):
        rows = super().create(vals_list)
        for row in rows.filtered(lambda r: not r.utm_campaign_id):
            row.utm_campaign_id = self.env['utm.campaign'].create({'title': row.name})
        return rows

    def _compute_link_clicks(self):
        Click = self.env['link.tracker.click'].sudo()
        for row in self:
            row.link_clicks = Click.search_count([('campaign_id', '=', row.utm_campaign_id.id)]) \
                if row.utm_campaign_id else 0

    def action_create_versions(self):
        result = super().action_create_versions()
        for row in self:
            drafts = row.publication_ids.filtered(lambda p: p.state == 'draft' and not p.utm_campaign_id)
            if row.utm_campaign_id and drafts:
                drafts.write({'utm_campaign_id': row.utm_campaign_id.id})
        return result

    def action_link_clicks(self):
        self.ensure_one()
        return _clicks_action(self.env, [('campaign_id', '=', self.utm_campaign_id.id)], self.name)


def _clicks_action(env, domain, name):
    return {
        'type': 'ir.actions.act_window',
        'name': _('Clicks: %s', name),
        'res_model': 'link.tracker.click',
        'view_mode': 'list,graph',
        'domain': domain,
        'context': {'create': False},
    }


class Publication(models.Model):
    _inherit = 'omni.social.publication'

    utm_campaign_id = fields.Many2one(
        'utm.campaign', string='Tracking campaign', ondelete='set null',
        help='Clicks, leads and sales from this post are reported under this campaign.',
    )
    track_links = fields.Boolean(
        default=True, string='Track links',
        help='When you submit, links in the text become short links that count clicks. The approver sees '
             'where each one leads.',
    )
    link_note = fields.Char(compute='_compute_link_note')
    link_clicks = fields.Integer(compute='_compute_link_clicks', string='Link clicks')

    @api.model_create_multi
    def create(self, vals_list):
        Campaign = self.env['omni.social.campaign']
        for vals in vals_list:
            if vals.get('campaign_id') and not vals.get('utm_campaign_id'):
                vals['utm_campaign_id'] = Campaign.browse(vals['campaign_id']).utm_campaign_id.id
        return super().create(vals_list)

    # ---------------------------------------------------------------- utm

    def _utm_source(self):
        caps = capabilities(self.provider)
        caps_label = caps.label if caps else (self.provider or 'Social')
        xmlid = SOURCES.get(self.provider)
        source = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else None
        if source:
            return source
        return self.env['utm.mixin']._find_or_create_record('utm.source', caps_label)

    def _utm_values(self):
        medium = self.env.ref('utm.utm_medium_social_media', raise_if_not_found=False)
        return {
            'campaign_id': self.utm_campaign_id.id,
            'source_id': self._utm_source().id,
            'medium_id': medium.id if medium else False,
            'utm_reference': '%s,%s' % (self._name, self.id),
            'title': self.name,
        }

    def _tracking_base(self):
        return self.env['ir.config_parameter'].sudo().get_str('web.base.url') or ''

    def _links_in(self, text):
        base = self._tracking_base().rstrip('/') + '/r/'
        return [url for url in dict.fromkeys(re.findall(TEXT_URL_REGEX, text or '')) if not url.startswith(base)]

    @api.depends('body', 'track_links', 'operation')
    def _compute_link_note(self):
        base = self._tracking_base()
        for row in self:
            count = len(row._links_in(row.body)) if row.track_links else 0
            if not count or row.state != 'draft':
                row.link_note = ''
            elif public_base(base):
                row.link_note = _('%(count)s link(s) will become tracked short links on %(host)s when you submit.',
                                  count=count, host=urlsplit(base).hostname)
            else:
                row.link_note = _('Links stay as written: tracked links need Odoo’s public HTTPS address '
                                  '(currently %(base)s).', base=base or _('not set'))

    def _trackers(self):
        self.ensure_one()
        if not self.id:
            return self.env['link.tracker']
        return self.env['link.tracker'].sudo().search(
            [('utm_reference', '=', '%s,%s' % (self._name, self.id))], order='id')

    def _compute_link_clicks(self):
        for row in self:
            row.link_clicks = sum(row._trackers().mapped('count')) if row.id else 0

    def action_link_clicks(self):
        self.ensure_one()
        return _clicks_action(self.env, [('link_id', 'in', self._trackers().ids)], self.name)

    def _shorten_links(self):
        """Replace the links in a draft by tracked short links (sudo: users only read trackers)."""
        self.ensure_one()
        if not self.track_links or self.operation == 'message' or not public_base(self._tracking_base()):
            return
        if not self._links_in(self.body):
            return
        body = self.env['mail.render.mixin'].sudo()._shorten_links_text(self.body, self._utm_values())
        if body != self.body:
            self.write({'body': body})

    def action_submit(self):
        for row in self:
            if row.state == 'draft' and row.requester_id == self.env.user:
                row.check_access('write')
                row._shorten_links()
        return super().action_submit()

    def _document(self, media_token):
        doc = super()._document(media_token)
        # Reviewed with the text: where each short link in it leads.
        links = []
        for tracker in self._trackers():
            if tracker.short_url and tracker.short_url in doc.get('body', ''):
                links.append({'short': tracker.short_url, 'url': tracker.url})
        if links:
            doc['links'] = links
        return doc


class Request(models.Model):
    _inherit = 'approval.center.request'

    social_links = fields.Text(compute='_compute_social_links', string='Link destinations')

    def _compute_social_links(self):
        for row in self:
            payload = row.sudo().social_publication_id.payload or {}
            row.social_links = '\n'.join('%s → %s' % (l['short'], l['url']) for l in payload.get('links') or [])
