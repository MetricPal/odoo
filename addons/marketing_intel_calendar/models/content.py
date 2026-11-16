"""Content calendar (plan M7, approved boards 14.1 and 14.2, 2026-11-15).

Everything that goes out to customers on one calendar: emails and SMS (``mailing.mailing``), messages
(``mm.mailing``) and social posts (``omni.social.publication``). ``mi.content`` is a read-only SQL view over the
three; a person sees only the items they may read in each app. An item opens in its own app. Dragging an item
changes its time through its own record, with the person's rights, and only where the app allows it: a message or a
post that was submitted carries its time in what the approver approved, so it does not move from here.
"""

from datetime import timedelta

from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, UserError
from odoo.orm.domains import Domain
from odoo.tools import html2plaintext

SOURCES = ('mailing.mailing', 'mm.mailing', 'omni.social.publication')
STATUSES = [('draft', 'Draft'), ('review', 'In review'), ('scheduled', 'Scheduled'), ('sent', 'Sent'),
            ('failed', 'Not sent')]
NEW_KINDS = ('email', 'sms', 'messaging', 'social')


class ContentChannel(models.Model):
    _name = 'mi.content.channel'
    _description = 'Content calendar channel'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    color = fields.Integer()
    sequence = fields.Integer(default=10)

    _code_unique = models.Constraint('UNIQUE(code)', 'A channel exists once.')


class Content(models.Model):
    _name = 'mi.content'
    _description = 'Content calendar item'
    _auto = False
    _order = 'date, id'
    _rec_name = 'name'

    name = fields.Char(string='Title', readonly=True)
    channel_id = fields.Many2one('mi.content.channel', string='Channel', readonly=True)
    date = fields.Datetime(string='When')
    status = fields.Selection(STATUSES, string='Stage', readonly=True)
    status_label = fields.Char(compute='_compute_details', string='Status')
    where = fields.Char(compute='_compute_details', string='Channel and account')
    text = fields.Char(compute='_compute_details', string='Text')
    no_time = fields.Char(compute='_compute_no_time', string=' ')
    res_model = fields.Char(readonly=True)
    res_id = fields.Many2oneReference(model_field='res_model', readonly=True)
    plan_id = fields.Many2one('mi.plan', string='Campaign', readonly=True)
    user_id = fields.Many2one('res.users', string='Owner', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    is_striked = fields.Boolean(readonly=True)
    is_hatched = fields.Boolean(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # ids: the source id times 10 plus 1 (mailing), 2 (message) or 3 (post), so they never meet.
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS (
                SELECT c.*, c.status = 'sent' AS is_striked, c.status = 'draft' AS is_hatched FROM (
                    SELECT m.id * 10 + 1 AS id,
                           m.subject AS name,
                           (SELECT id FROM mi_content_channel
                             WHERE code = CASE WHEN m.mailing_type = 'sms' THEN 'sms' ELSE 'email' END) AS channel_id,
                           CASE WHEN m.state = 'done' THEN COALESCE(m.sent_date, m.schedule_date)
                                WHEN m.schedule_type = 'scheduled' THEN m.schedule_date END AS date,
                           CASE m.state WHEN 'draft' THEN 'draft' WHEN 'done' THEN 'sent' ELSE 'scheduled' END AS status,
                           'mailing.mailing' AS res_model, m.id AS res_id,
                           (SELECT i.plan_id FROM mi_plan_item i
                             WHERE i.res_model = 'mailing.mailing' AND i.res_id = m.id LIMIT 1) AS plan_id,
                           m.user_id, NULL::integer AS company_id
                      FROM mailing_mailing m
                     WHERE m.active AND m.mailing_type IN ('mail', 'sms')
                    UNION ALL
                    SELECT g.id * 10 + 2, g.name,
                           (SELECT id FROM mi_content_channel WHERE code = 'messaging'),
                           COALESCE(g.sent_at, CASE WHEN g.schedule = 'later' THEN g.scheduled_at END),
                           CASE g.state WHEN 'draft' THEN 'draft' WHEN 'pending' THEN 'review'
                                        WHEN 'done' THEN 'sent' WHEN 'refused' THEN 'failed' ELSE 'scheduled' END,
                           'mm.mailing', g.id,
                           (SELECT i.plan_id FROM mi_plan_item i
                             WHERE i.res_model = 'mm.mailing' AND i.res_id = g.id LIMIT 1),
                           g.requester_id, g.company_id
                      FROM mm_mailing g
                     WHERE g.state != 'cancelled'
                    UNION ALL
                    SELECT p.id * 10 + 3, p.name,
                           (SELECT id FROM mi_content_channel WHERE code = 'social'),
                           COALESCE(p.published_at, p.scheduled_at),
                           CASE WHEN p.state = 'draft' THEN 'draft' WHEN p.state = 'pending' THEN 'review'
                                WHEN p.state = 'sent' THEN 'sent'
                                WHEN p.state IN ('failed', 'unknown') THEN 'failed' ELSE 'scheduled' END,
                           'omni.social.publication', p.id,
                           (SELECT i.plan_id FROM mi_plan_item i
                             WHERE i.res_model = 'omni.social.campaign' AND i.res_id = p.campaign_id LIMIT 1),
                           p.requester_id, p.company_id
                      FROM omni_social_publication p
                     WHERE p.operation = 'post' AND p.state != 'cancelled'
                ) c
            )
        """)

    # ------------------------------------------------------------------ only what the person may read in each app

    @api.model
    def _readable(self):
        """A domain keeping the items whose own record the person may read (each app's access and record rules)."""
        if self.env.su:
            return Domain.TRUE
        domain = Domain.FALSE
        for model in SOURCES:
            Source = self.env[model]
            if Source.has_access('read'):
                domain |= Domain('res_model', '=', model) & Domain('res_id', 'in', Source._search([]))
        return domain

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        domain = Domain(domain) & self._readable()
        return super()._search(domain, offset, limit, order, active_test=active_test, bypass_access=bypass_access)

    @api.model
    def _read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        domain = Domain(domain) & self._readable()
        return super()._read_group(domain, groupby, aggregates, having, offset, limit, order)

    def _source(self):
        """The item's own record, with the person's rights."""
        self.ensure_one()
        return self.env[self.res_model].browse(self.res_id)

    # ------------------------------------------------------------------ what an item shows (board 14.2 A)

    @api.depends('res_model', 'res_id')
    def _compute_details(self):
        for item in self:
            record = item._source().exists() if item.res_model in SOURCES else None
            if not record:
                item.status_label = item.where = item.text = False
                continue
            if item.res_model == 'mailing.mailing':
                label = dict(record._fields['state']._description_selection(self.env)).get(record.state)
                where = item.channel_id.name
                text = record.preview or record.body_plaintext or html2plaintext(record.body_html or '')
            elif item.res_model == 'mm.mailing':
                label = record.display_state
                channel = dict(record._fields['channel']._description_selection(self.env)).get(record.channel)
                where = ' · '.join(filter(None, [item.channel_id.name, channel, record.channel_id.display_name]))
                text = record.body
            else:
                label = dict(record._fields['stage']._description_selection(self.env)).get(record.stage)
                where = ' · '.join(filter(None, [item.channel_id.name, record.connection_id.display_name]))
                text = record.body
            text = ' '.join((text or '').split())
            item.status_label = label
            item.where = where
            item.text = text[:140] + '…' if len(text) > 140 else text

    @api.depends('name', 'channel_id')
    def _compute_display_name(self):
        for item in self:
            item.display_name = ' · '.join(filter(None, [item.channel_id.name, item.name]))

    @api.depends('date')
    def _compute_no_time(self):
        for item in self:
            item.no_time = False if item.date else _('No time yet')

    def action_open(self):
        """Open: the item in its own app, where it is edited, reviewed and sent."""
        self.ensure_one()
        record = self._source()
        action = {'type': 'ir.actions.act_window', 'res_model': record._name, 'res_id': record.id,
                  'view_mode': 'form', 'views': [(False, 'form')], 'target': 'current'}
        if record._name == 'mailing.mailing' and record.mailing_type == 'sms':
            action['views'] = [(self.env.ref('mass_mailing_sms.mailing_mailing_view_form_sms').id, 'form')]
            action['context'] = {'default_mailing_type': 'sms', 'mailing_sms': True}
        return action

    # ------------------------------------------------------------------ New (board 14.1)

    @api.model
    def new_options(self):
        """What New offers: only what the person may create."""
        options = []
        if self.env['mailing.mailing'].has_access('create'):
            options += [['email', _('Email')], ['sms', _('SMS')]]
        if self.env['mm.mailing'].has_access('create'):
            options.append(['messaging', _('Message')])
        if self.env['omni.social.publication'].has_access('create'):
            options.append(['social', _('Social post')])
        return options

    @api.model
    def action_new(self, kind, date=False):
        """The app's own form for a new item, with the day filled in when it is still to come."""
        if kind not in dict(self.new_options()):
            raise UserError(_('You cannot create this from the calendar.'))
        when = fields.Datetime.to_datetime(date) if date else False
        if when and when <= fields.Datetime.now():
            when = False
        when = fields.Datetime.to_string(when) if when else False
        action = {'type': 'ir.actions.act_window', 'view_mode': 'form', 'views': [(False, 'form')],
                  'target': 'current', 'context': {}}
        if kind in ('email', 'sms'):
            action['res_model'] = 'mailing.mailing'
            action['context'] = {'default_mailing_type': 'mail' if kind == 'email' else 'sms',
                                 'default_user_id': self.env.uid}
            if kind == 'sms':
                action['views'] = [(self.env.ref('mass_mailing_sms.mailing_mailing_view_form_sms').id, 'form')]
                action['context']['mailing_sms'] = True
            if when:
                action['context']['default_calendar_date'] = when
        elif kind == 'messaging':
            action['res_model'] = 'mm.mailing'
            if when:
                action['context'] = {'default_schedule': 'later', 'default_scheduled_at': when}
        else:
            action['res_model'] = 'omni.social.publication'
            if when:
                action['context'] = {'default_scheduled_at': when}
        return action

    # ------------------------------------------------------------------ dragging an item (board 14.2 B)

    def write(self, vals):
        if set(vals) != {'date'}:
            raise UserError(_('Open the item to change it; the calendar only moves it to another time.'))
        when = fields.Datetime.to_datetime(vals['date'])
        for item in self:
            item._move(when)
        self.env.flush_all()
        self.invalidate_model()
        return True

    def _move(self, when):
        self.ensure_one()
        record = self._source()
        if not record.exists():
            raise UserError(_('This item no longer exists.'))
        if self.status == 'sent':
            raise UserError(_('This went out already, so it does not move.'))
        if self.status == 'review':
            raise UserError(_('Waiting for review. Move it after the decision.'))
        if self.status == 'failed':
            raise UserError(_('This was not sent. Open it to see why.'))
        if not when or when <= fields.Datetime.now() + timedelta(seconds=30):
            raise UserError(_('Choose a time that is still to come.'))
        if not record.has_access('write'):
            raise UserError(_('You may only read this item, so it does not move.'))
        if record._name == 'mailing.mailing':
            # Email and SMS: a draft takes the planned time; a queued mailing goes out at the new time.
            record.write({'schedule_type': 'scheduled', 'schedule_date': when})
            return
        if self.status == 'scheduled':
            # The approver approved the time with the content (its hash); only a new submission changes it.
            raise UserError(_('The time of “%s” was approved with it, so it does not move here. To change it, '
                              'open it, cancel it and submit a copy with the new time.', self.name))
        try:
            if record._name == 'mm.mailing':
                record.write({'schedule': 'later', 'scheduled_at': when})
            else:
                record.write({'scheduled_at': when})
        except AccessError as error:
            # The app's own words, e.g. only the person who prepared a draft can change it.
            raise UserError(str(error.args[0] if error.args else error)) from None
