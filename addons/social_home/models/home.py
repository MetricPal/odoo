"""Social items in Home's "needs attention" list, read with the user's own access."""

from odoo import _, api, models

from odoo.addons.ai_home.models.ai_home_item import LIVE_LIMIT, _iso


class AiHomeItem(models.Model):
    _inherit = 'ai.home.item'

    @api.model
    def _live_attention(self):
        items = super()._live_attention()
        if not self._can_read('omni.social.activity'):
            return items
        user = self.env.user
        Activity = self.env['omni.social.activity']
        to_answer = [
            ('inbox_state', '=', 'new'), ('kind', '!=', 'post'),
            '|', ('assignee_id', '=', False), ('assignee_id', '=', user.id),
        ]
        groups = Activity._read_group(to_answer, ['connection_id'], ['__count', 'occurred_at:max'], limit=LIVE_LIMIT)
        for account, count, latest in groups:
            items.append({
                'key': f'social-inbox-{account.id}',
                'kind': 'social_inbox',
                'name': _('%(count)s to answer on %(account)s', count=count, account=account.name),
                'subtitle': _('Social · comments and messages'),
                'occurred': _iso(latest),
                'tone': 'warning',
                'iconText': 'SO',
                'action': {
                    'type': 'ir.actions.act_window',
                    'name': _('To answer'),
                    'res_model': 'omni.social.activity',
                    'views': [[False, 'list'], [False, 'form']],
                    'domain': [('connection_id', '=', account.id)] + to_answer,
                    'target': 'current',
                },
            })
        if self._can_read('omni.social.publication'):
            for post in self.env['omni.social.publication'].search(
                [('requester_id', '=', user.id), ('stage', '=', 'attention')], order='write_date desc', limit=LIVE_LIMIT,
            ):
                items.append({
                    'key': f'social-post-{post.id}',
                    'kind': 'social_post',
                    'name': post.name,
                    'subtitle': _('Social · not published: %(account)s', account=post.connection_id.name),
                    'occurred': _iso(post.write_date),
                    'tone': 'danger',
                    'iconText': 'SO',
                    'action': self._record_action(post._name, post.id),
                })
        return items
