from odoo import api, models


class MailMessage(models.Model):
    _inherit = 'mail.message'

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        Digest = self.env['metric.mention.digest']
        for message in messages.filtered(lambda m: m.message_type == 'sms' and m.body and '@' in str(m.body)):
            users = Digest._mentioned_users(message.body, exclude=message.author_id.user_ids)
            record = self.env[message.model].browse(message.res_id) if message.model in self.env and message.res_id \
                else None
            Digest._count_mention(users, 'sms', message.body, record)
        return messages


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    def _notify_note_mentions(self):
        """A user mentioned in an activity's note is told once per activity (the assignee is already told)."""
        Digest = self.env['metric.mention.digest']
        for activity in self.filtered(lambda a: a.note and '@' in str(a.note)):
            users = Digest._mentioned_users(activity.note, exclude=activity.user_id | self.env.user)
            for user in users:
                key = f'activity-{activity.id}'
                if not Digest.sudo().search_count([('user_id', '=', user.id), ('template_key', '=', key)]):
                    document = self.env[activity.res_model].browse(activity.res_id) \
                        if activity.res_model in self.env else None
                    Digest._count_mention(user, 'activity', activity.note, document, key=key)

    @api.model_create_multi
    def create(self, vals_list):
        activities = super().create(vals_list)
        activities._notify_note_mentions()
        return activities

    def write(self, vals):
        result = super().write(vals)
        if 'note' in vals:
            self._notify_note_mentions()
        return result
