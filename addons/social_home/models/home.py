"""Social items in Home's "Needs your attention" list, read with the user's own access."""

from odoo import _, models

from odoo.addons.ai_home.models.home_data import LIMIT


class AiHomeItem(models.Model):
    _inherit = 'ai.home.item'

    def _attention_collectors(self):
        return super()._attention_collectors() + [self._attention_social]

    def _attention_social(self):
        if not self._can_read('omni.social.activity'):
            return []
        user = self.env.user
        Activity = self.env['omni.social.activity']
        to_answer = [
            ('inbox_state', '=', 'new'), ('kind', '!=', 'post'),
            '|', ('assignee_id', '=', False), ('assignee_id', '=', user.id),
        ]
        items = []
        groups = Activity._read_group(to_answer, ['connection_id'], ['__count', 'occurred_at:max'], limit=LIMIT)
        for account, count, latest in groups:
            items.append(self._item(
                'conversation', account, _('%(count)s to answer on %(account)s', count=count, account=account.name),
                _('Social Marketing · comments and messages'), {'label': _('Open'), 'open': True},
                occurred=latest,
                open_action={
                    'type': 'ir.actions.act_window', 'name': _('To answer'), 'res_model': 'omni.social.activity',
                    'views': [[False, 'list'], [False, 'form']], 'target': 'current',
                    'domain': [('connection_id', '=', account.id)] + to_answer,
                }))
        if self._can_read('omni.social.publication'):
            for post in self.env['omni.social.publication'].search(
                [('requester_id', '=', user.id), ('stage', '=', 'attention')], order='write_date desc', limit=LIMIT,
            ):
                items.append(self._item(
                    'conversation', post, post.name,
                    _('Social Marketing · not published: %(account)s', account=post.connection_id.name),
                    {'label': _('Open'), 'open': True}, tag=_('Not published'), occurred=post.write_date))
        return items
