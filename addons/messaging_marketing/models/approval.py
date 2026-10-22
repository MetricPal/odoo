"""Mailing reviews in Approval Center: frozen evidence, assigned approvers only."""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .mailing import guarded, internal, render, trusted


class Request(models.Model):
    _inherit = 'approval.center.request'

    mm_mailing_id = fields.Many2one('mm.mailing', readonly=True, ondelete='restrict', copy=False,
                                    string='Mailing')
    mm_channel = fields.Selection(related='mm_mailing_id.channel', string='Channel')
    mm_channel_id = fields.Many2one(related='mm_mailing_id.channel_id', string='Sent from')
    mm_body = fields.Text(compute='_compute_mm_review', string='Exact message')
    mm_preview = fields.Text(compute='_compute_mm_review', string='As one recipient sees it')
    mm_audience_count = fields.Integer(compute='_compute_mm_review', string='Recipients')
    mm_lists = fields.Char(compute='_compute_mm_review', string='Lists')
    mm_excluded = fields.Text(compute='_compute_mm_review', string='Not included')
    mm_scheduled_at = fields.Datetime(compute='_compute_mm_review', string='Sends at')
    mm_cost = fields.Char(compute='_compute_mm_review', string='Estimated cost')

    def _approval_trusted(self):
        return trusted(self) or super()._approval_trusted()

    @api.depends('mm_mailing_id.payload')
    def _compute_mm_review(self):
        for row in self:
            payload = row.sudo().mm_mailing_id.payload or {}
            recipients = payload.get('recipients') or []
            audience = payload.get('audience') or {}
            row.mm_body = payload.get('body') or ''
            first = row.env['mm.contact'].sudo().browse(recipients[0][0]).exists() if recipients else False
            row.mm_preview = render(row.mm_body, first) if first else row.mm_body
            row.mm_audience_count = len(recipients)
            row.mm_lists = ', '.join(row.env['mm.list'].sudo().browse(payload.get('lists') or []).exists()
                                     .mapped('name'))
            labels = [
                (audience.get('no_answer'), _('no opt-in yet')), (audience.get('opted_out'), _('opted out')),
                (audience.get('blacklisted'), _('blacklisted')), (audience.get('no_address'), _('no address')),
                (audience.get('no_chat'), _('no bot conversation')),
            ]
            row.mm_excluded = ', '.join(f'{count} {label}' for count, label in labels if count) or False
            row.mm_scheduled_at = payload.get('scheduled_at') or False
            cost = payload.get('cost') or {}
            row.mm_cost = (f"{cost.get('price', 0) * len(recipients):.2f} {cost.get('currency', '')}"
                           if cost.get('price') else False)

    @api.model_create_multi
    def create(self, vals_list):
        guarded(self, {'mm_mailing_id'}, vals_list)
        return super().create(vals_list)

    def write(self, vals):
        guarded(self, {'mm_mailing_id'}, [vals])
        if not trusted(self) and self.sudo().mm_mailing_id:
            raise AccessError(_('Mailing review evidence is frozen.'))
        return super().write(vals)

    def unlink(self):
        if self.sudo().mm_mailing_id:
            raise AccessError(_('Mailing reviews are kept with the mailing.'))
        return super().unlink()

    def _mm_decision(self, approved):
        self.ensure_one()
        self.check_access('read')
        mailing = self.sudo().mm_mailing_id
        mailing._lock()
        self.invalidate_recordset()
        if (self.state != 'submitted' or mailing.state != 'pending' or mailing.requester_id == self.env.user
                or not self.env.user.has_group('approval_center.group_approval_center_approver')):
            raise AccessError(_('An assigned approver must review this mailing.'))
        lines = self.sudo().approver_ids.sorted(lambda line: (line.sequence, line.id))
        line = lines.filtered(lambda item: item.user_id == self.env.user)
        if len(line) != 1 or line.status != 'submitted':
            raise AccessError(_('You are not a pending approver of this mailing.'))
        mailing._frozen()
        policy = mailing._policy()
        if policy['sequence'] and any(item.status != 'approved' for item in lines[:list(lines).index(line)]):
            raise UserError(_('Earlier approvers must review first.'))
        internal(line).write({'status': 'approved' if approved else 'refused'})
        start_now = False
        if not approved:
            internal(self.sudo()).write({'state': 'refused'})
            internal(mailing).write({'state': 'refused'})
        elif (len(lines.filtered(lambda item: item.status == 'approved')) >= policy['minimum']
              and all(item.status == 'approved' for item in lines.filtered('required'))):
            internal(self.sudo()).write({'state': 'approved', 'approved_at': fields.Datetime.now(),
                                         'approver_id': self.env.uid})
            internal(mailing).write({'state': 'approved'})
            start_now = mailing.schedule == 'now'
        self._audit('approved' if approved else 'refused', _('Assigned mailing approver recorded a decision.'))
        mailing._audit('mm.approved' if approved else 'mm.refused', _('Assigned approver recorded a decision.'))
        if start_now:
            # Queue only; the Omnichannel worker sends. A channel problem leaves the mailing approved.
            try:
                with self.env.cr.savepoint():
                    mailing._start_sending()
            except (UserError, AccessError) as error:
                mailing.message_post(body=_('Approved, but sending could not start yet: %s', error))

    def action_approve(self):
        for row in self:
            if row.sudo().mm_mailing_id:
                row._mm_decision(True)
            else:
                super(Request, row).action_approve()
        return True

    def action_refuse(self):
        for row in self:
            if row.sudo().mm_mailing_id:
                row._mm_decision(False)
            else:
                super(Request, row).action_refuse()
        return True

    def action_execute(self):
        if len(self) == 1 and self.sudo().mm_mailing_id:
            return self._execute_approved_action()
        return super().action_execute()

    def _execute_approved_action(self):
        if self.sudo().mm_mailing_id:
            # Approval Center opens the mailing; sending happens there (or at its scheduled time).
            self.check_access('read')
            return {'type': 'ir.actions.act_window', 'res_model': 'mm.mailing',
                    'res_id': self.mm_mailing_id.id, 'view_mode': 'form', 'target': 'current'}
        return super()._execute_approved_action()


class Approver(models.Model):
    _inherit = 'approval.center.approver'

    def _mm_frozen(self, request_ids=()):
        requests = self.sudo().request_id | self.env['approval.center.request'].sudo().browse(
            [rid for rid in request_ids if rid]).exists()
        return bool(requests.mm_mailing_id)

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self) and self._mm_frozen([
                vals.get('request_id') or self.env.context.get('default_request_id') for vals in vals_list]):
            raise AccessError(_('Mailing approvers come from the channel approval type.'))
        return super().create(vals_list)

    def write(self, vals):
        if not trusted(self) and self._mm_frozen([vals.get('request_id')]):
            raise AccessError(_('Mailing review evidence is frozen.'))
        return super().write(vals)

    def unlink(self):
        if self._mm_frozen():
            raise AccessError(_('Mailing review evidence is kept.'))
        return super().unlink()
