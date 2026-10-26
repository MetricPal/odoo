"""Odoo Activities for what a person must do in marketing.

The next step that needs the owner (prepare the drafts, fix a channel, send for review, update after a refusal)
is kept as one To-Do activity on the record, assigned to the owner: it appears in the Activities menu of the top
bar, on the record and in "Your action needed" on the control panel, and is marked done by itself when the step
is done. Approvals already come as activities from Approval Center; proofs, requests and workflows add theirs.
"""

from odoo import _, api, fields, models


class OwnerActivity(models.AbstractModel):
    _name = 'mi.owner.activity.mixin'
    _description = 'Marketing next step as an activity'

    mi_activity_id = fields.Many2one('mail.activity', readonly=True, copy=False, ondelete='set null',
                                     string='Next-step activity')

    def _owner_step(self):
        """(summary, user) of what the owner must do now, or (False, False)."""
        return False, False

    def _sync_owner_activity(self):
        for record in self.sudo():
            summary, user = record._owner_step()
            activity = record.mi_activity_id.exists()
            if summary and user:
                summary = summary[:250]
                if activity and activity.user_id == user:
                    if activity.summary != summary:
                        activity.summary = summary
                    continue
                if activity:
                    activity.unlink()
                activity = record.activity_schedule('mail.mail_activity_data_todo', user_id=user.id, summary=summary)
                record.mi_activity_id = activity
            elif activity:
                activity.action_feedback(feedback=_('Done'))
                record.mi_activity_id = False


class Plan(models.Model):
    _name = 'mi.plan'
    _inherit = ['mi.plan', 'mi.owner.activity.mixin']

    def _owner_step(self):
        self.ensure_one()
        if self.is_template or self.state not in ('brief', 'content', 'review', 'scheduled', 'live'):
            return False, False
        step, owner_must_act = self._next_step()
        return (step, self.user_id) if owner_must_act else (False, False)

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        plans._sync_owner_activity()
        # the next step was read from computed channel statuses: let later steps (e.g. the AI start) recompute them
        plans.item_ids.invalidate_recordset()
        plans.invalidate_recordset()
        return plans

    def write(self, vals):
        result = super().write(vals)
        if {'state', 'user_id', 'worker', 'is_template', 'item_ids', 'channel_ids'} & set(vals):
            self._sync_owner_activity()
        return result

    def _sync_state(self):
        result = super()._sync_state()
        self._sync_owner_activity()
        return result
