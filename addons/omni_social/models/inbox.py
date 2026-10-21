"""Inbox handling for imported activity, and the weekly report.

Imported activity stays read-only platform data; only its handling state and
assignee change, through these actions, for members of the account's team.
A comment or message becomes "Replied" when a reply to it is published.
"""

from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError
from .social import internal

INBOX_STATES = [('new', 'New'), ('replied', 'Replied'), ('ignored', 'No reply needed')]


class Activity(models.Model):
    _inherit = 'omni.social.activity'

    inbox_state = fields.Selection(INBOX_STATES, default='new', required=True, index=True, string='Handling')
    assignee_id = fields.Many2one('res.users', string='Assigned to', index=True)
    def _auto_init(self):
        result = super()._auto_init()
        # Imported posts are our own content, never something to answer (idempotent).
        self.env.cr.execute("UPDATE omni_social_activity SET inbox_state = 'ignored' "
                            "WHERE kind = 'post' AND inbox_state = 'new'")
        return result

    @api.model_create_multi
    def create(self, values):
        for vals in values:
            if vals.get('kind') == 'post':
                vals.setdefault('inbox_state', 'ignored')
        return super().create(values)

    def _handle(self, values):
        for row in self:
            row.check_access('read')
            row.connection_id.check_access('read')
        # Members may only read imported activity; the handling fields change through these actions.
        internal(self.sudo()).write(values)
        return True

    def action_assign_me(self):
        return self._handle({'assignee_id': self.env.uid})

    def action_mark_ignored(self):
        return self._handle({'inbox_state': 'ignored'})

    def action_mark_new(self):
        return self._handle({'inbox_state': 'new'})


class Publication(models.Model):
    _inherit = 'omni.social.publication'

    def _social_sent(self):
        """Called after the platform accepted this publication."""
        target = self.sudo().target_id
        if target and self.operation in ('reply', 'message'):
            internal(target).write({'inbox_state': 'replied'})


class Report(models.Model):
    """Posts, likes and comments per account and week (read-only SQL view)."""

    _name = 'omni.social.report'
    _description = 'Social Weekly Report'
    _auto = False
    _order = 'week desc'

    week = fields.Date(readonly=True)
    connection_id = fields.Many2one('omni.social.connection', string='Account', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    purpose_id = fields.Many2one('omni.purpose', string='Communication team', readonly=True)
    published = fields.Integer(string='Posts published', readonly=True)
    likes = fields.Integer(string='Likes', readonly=True)
    comments = fields.Integer(string='Comments', readonly=True)
    received = fields.Integer(string='Comments and messages received', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS (
                SELECT row_number() OVER () AS id, week, connection_id, company_id, purpose_id,
                       SUM(published) AS published, SUM(likes) AS likes, SUM(comments) AS comments,
                       SUM(received) AS received
                  FROM (
                    SELECT date_trunc('week', p.published_at)::date AS week, p.connection_id,
                           p.company_id, p.purpose_id, 1 AS published, 0 AS likes, 0 AS comments, 0 AS received
                      FROM omni_social_publication p
                     WHERE p.state = 'sent' AND p.operation = 'post' AND p.published_at IS NOT NULL
                    UNION ALL
                    SELECT date_trunc('week', a.occurred_at)::date, a.connection_id, a.company_id, a.purpose_id,
                           0, CASE WHEN a.kind = 'post' THEN COALESCE(a.likes, 0) ELSE 0 END,
                           CASE WHEN a.kind = 'post' THEN COALESCE(a.comments, 0) ELSE 0 END,
                           CASE WHEN a.kind IN ('comment', 'message') THEN 1 ELSE 0 END
                      FROM omni_social_activity a
                     WHERE a.occurred_at IS NOT NULL
                  ) rows
                 GROUP BY week, connection_id, company_id, purpose_id
            )
        """)

    def write(self, values):
        raise UserError(_('The report is read-only.'))
