"""Guard only requests created by Workflows; preserve other Approval Center flows."""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from .workflow import internal, trusted


class WorkflowApproval(models.Model):
    _inherit = 'approval.center.request'

    workflow_run_id = fields.Many2one('workflow.run', readonly=True, ondelete='restrict', copy=False)
    workflow_minimum = fields.Integer(readonly=True, copy=False)
    workflow_sequential = fields.Boolean(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self) and any(v.get('workflow_run_id') or v.get('workflow_minimum')
                                     or v.get('workflow_sequential') for v in vals_list):
            raise AccessError(_('Workflow requests are created by the workflow engine.'))
        return super().create(vals_list)

    def write(self, vals):
        protected = {'state', 'policy_id', 'target_model', 'target_res_id', 'requester_id',
                     'approver_ids', 'approver_id', 'company_id', 'approved_at', 'executed_at',
                     'workflow_run_id', 'workflow_minimum', 'workflow_sequential'}
        if not trusted(self) and protected & vals.keys() and (
            'workflow_run_id' in vals or self.sudo().filtered('workflow_run_id')
        ):
            raise AccessError(_('Use Approve or Refuse. Workflow approval decisions cannot be edited directly.'))
        return super().write(vals)

    def unlink(self):
        if self.sudo().filtered('workflow_run_id'):
            raise AccessError(_('Keep workflow approval requests as part of the run history.'))
        return super().unlink()

    def _check_can_review(self):
        self.ensure_one()
        if self.sudo().workflow_run_id:
            self.check_access('write')
            if self.company_id not in self.env.companies:
                raise AccessError(_('Switch to the request company before reviewing it.'))
            if self.requester_id == self.env.user:
                raise AccessError(_('You cannot approve or refuse your own workflow request.'))
            reviewer = self._get_current_user_approver()
            if not reviewer or reviewer.status != 'submitted':
                raise AccessError(_('Only a designated approver with a pending decision can review this request.'))
            if self.workflow_sequential and self.approver_ids.filtered(
                lambda a: a.sequence < reviewer.sequence and a.status != 'approved'
            ):
                raise UserError(_('An earlier approver must decide first.'))
            return True
        return super()._check_can_review()

    def action_approve(self):
        for request in self:
            if not request.sudo().workflow_run_id:
                super(WorkflowApproval, request).action_approve()
                continue
            request._check_can_review()
            super(WorkflowApproval, internal(request)).action_approve()
            complete = (
                len(request.approver_ids.filtered(lambda a: a.status == 'approved')) >= request.workflow_minimum
                and not request.approver_ids.filtered(lambda a: a.required and a.status != 'approved')
            )
            internal(request).write({
                'state': 'approved' if complete else 'submitted',
                'approved_at': fields.Datetime.now() if complete else False,
            })
        return True

    def action_refuse(self):
        for request in self:
            if request.sudo().workflow_run_id:
                request._check_can_review()
                super(WorkflowApproval, internal(request)).action_refuse()
            else:
                super(WorkflowApproval, request).action_refuse()
        return True


class WorkflowApprover(models.Model):
    _inherit = 'approval.center.approver'

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self):
            requests = self.env['approval.center.request'].sudo().browse(
                [v['request_id'] for v in vals_list if v.get('request_id')])
            if requests.filtered('workflow_run_id'):
                raise AccessError(_('Workflow approvers are fixed when the request starts.'))
        return super().create(vals_list)

    def write(self, vals):
        requests = self.sudo().request_id
        if vals.get('request_id'):
            requests |= self.env['approval.center.request'].sudo().browse(vals['request_id'])
        if not trusted(self) and requests.filtered('workflow_run_id'):
            raise AccessError(_('Use the request decision buttons. Workflow approvers cannot be edited.'))
        return super().write(vals)

    def unlink(self):
        if self.sudo().request_id.filtered('workflow_run_id'):
            raise AccessError(_('Workflow approvers are retained for the audit trail.'))
        return super().unlink()
