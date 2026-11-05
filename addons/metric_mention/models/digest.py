"""Mention digests: a user mentioned in messages that are not chatter (activity notes, SMS, Omnichannel, social) gets
one Inbox notification per channel, template and day. Mentioned in 100 SMS sent from the same text on one day = one
notification, its count kept up to date, with one sample.

A "template" is the message text itself (normalised), so 100 copies of one SMS or one mass message group together;
a message typed by hand differs from the others and notifies on its own.
"""

import hashlib
import re

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.tools import html2plaintext

CHANNELS = [('activity', 'Activity'), ('sms', 'SMS'), ('omnichannel', 'Omnichannel'), ('social', 'Social media')]
# (model, text field, channel) read by the scheduled scan; skipped while the app is not installed.
SCANNED = [('omni.message', 'body', 'omnichannel'), ('omni.social.activity', 'body', 'social')]
LINK_RE = re.compile(r'data-oe-model="res\.(partner|users)"[^>]*data-oe-id="(\d+)"')


class MetricMentionDigest(models.Model):
    _name = 'metric.mention.digest'
    _description = 'Mention digest'
    _order = 'day desc, id desc'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    channel = fields.Selection(CHANNELS, required=True)
    template_key = fields.Char(required=True, index=True)
    day = fields.Date(required=True, index=True)
    count = fields.Integer(default=1)
    sample = fields.Text()
    res_model = fields.Char('Document model')
    res_id = fields.Many2oneReference('Document', model_field='res_model')
    message_id = fields.Many2one('mail.message', 'Notification', ondelete='set null')

    _unique_digest = models.Constraint('unique(user_id, channel, template_key, day)',
                                       'One digest per user, channel, template and day.')

    # ------------------------------------------------------------------
    # Finding mentions
    # ------------------------------------------------------------------

    @api.model
    def _mentioned_users(self, content, exclude=None):
        """Internal users mentioned in the text or HTML: mention links, or "@" followed by a user's full name."""
        content = content or ''
        users = self.env['res.users']
        for kind, record_id in LINK_RE.findall(str(content)):
            if kind == 'users':
                users |= self.env['res.users'].sudo().browse(int(record_id)).exists()
            else:
                users |= self.env['res.partner'].sudo().browse(int(record_id)).exists().user_ids
        text = html2plaintext(str(content)) if '<' in str(content) else str(content)
        if '@' in text:
            lowered = text.lower()
            candidates = self.env['res.users'].sudo().search([('share', '=', False)], limit=2000)
            for user in sorted(candidates, key=lambda u: -len(u.name or '')):
                if user.name and len(user.name) >= 3 and f'@{user.name.lower()}' in lowered:
                    users |= user
        users = users.filtered(lambda user: not user.share and user.active)
        return users - exclude if exclude else users

    @api.model
    def _template_key(self, text):
        normal = ' '.join(html2plaintext(text or '').lower().split())
        return hashlib.sha1(normal.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Recording and notifying
    # ------------------------------------------------------------------

    @api.model
    def _count_mention(self, users, channel, text, record=None, key=None):
        """Count a mention for each user; the first one of the day for that template sends the notification."""
        if not users:
            return self.browse()
        key = key or self._template_key(text)
        today = fields.Date.context_today(self)
        sample = ' '.join(html2plaintext(text or '').split())[:280]
        digests = self.browse()
        Digest = self.sudo()
        for user in users:
            digest = Digest.search([('user_id', '=', user.id), ('channel', '=', channel),
                                    ('template_key', '=', key), ('day', '=', today)], limit=1)
            if digest:
                digest.count += 1
                digest._refresh_notification()
            else:
                digest = Digest.create({
                    'user_id': user.id, 'channel': channel, 'template_key': key, 'day': today, 'sample': sample,
                    'res_model': record._name if record else False, 'res_id': record.id if record else False,
                })
                digest._notify()
            digests |= digest
        return digests

    def _body(self):
        self.ensure_one()
        label = dict(CHANNELS)[self.channel]
        if self.count == 1:
            intro = _('You were mentioned in %(channel)s:', channel=label.lower() if self.channel != 'sms' else 'an SMS')
        else:
            intro = _('You were mentioned in %(count)s %(channel)s messages today, all with the same text. Example:',
                      count=self.count, channel=label)
        return Markup('<p>%s</p><blockquote>%s</blockquote>') % (intro, self.sample or '')

    def _target(self):
        """Where the notification lives: the document when it has a chatter, else the user's own contact."""
        self.ensure_one()
        if self.res_model and self.res_model in self.env and self.res_id:
            record = self.env[self.res_model].sudo().browse(self.res_id).exists()
            if record and hasattr(record, 'message_notify'):
                return record
        return self.user_id.partner_id.sudo()

    def _notify(self):
        for digest in self:
            message = digest._target().message_notify(
                partner_ids=digest.user_id.partner_id.ids, body=digest._body(),
                subject=_('You were mentioned'), author_id=self.env.ref('base.partner_root').id)
            digest.message_id = message

    def _refresh_notification(self):
        for digest in self:
            if digest.message_id:
                digest.message_id.sudo().write({'body': digest._body()})
            else:
                digest._notify()

    # ------------------------------------------------------------------
    # Scheduled scan of Omnichannel and social messages
    # ------------------------------------------------------------------

    @api.model
    def _scan_model(self, model, field, channel):
        """Read records created since the last scan and count the mentions in their text."""
        if model not in self.env or field not in self.env[model]._fields:
            return 0
        Param = self.env['ir.config_parameter'].sudo()
        mark = f'metric_mention.last_scan.{model}'
        since = Param.get_str(mark)
        now = fields.Datetime.now()
        domain = [(field, 'ilike', '@')]
        if since:
            domain.append(('create_date', '>', since))
        found = 0
        for record in self.env[model].sudo().search(domain, order='id', limit=5000):
            users = self._mentioned_users(record[field])
            if users:
                self._count_mention(users, channel, record[field], record)
                found += 1
        Param.set_str(mark, fields.Datetime.to_string(now))
        return found

    @api.model
    def _cron_scan(self):
        for model, field, channel in SCANNED:
            self._scan_model(model, field, channel)
