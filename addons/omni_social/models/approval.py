"""Social approval evidence cannot be forged through CRUD or RPC contexts."""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from .social import internal, trusted, guarded

class Request(models.Model):
    _inherit='approval.center.request'
    social_publication_id=fields.Many2one('omni.social.publication',readonly=True,ondelete='restrict',copy=False)
    social_purpose_id=fields.Many2one(related='social_publication_id.purpose_id',store=True)
    social_body=fields.Text(related='social_publication_id.body',string='Exact content')
    social_image=fields.Binary(related='social_publication_id.image',string='Approved photo')
    social_account=fields.Char(related='social_publication_id.connection_id.profile_name',string='Publishing account')
    social_operation=fields.Selection(related='social_publication_id.operation',string='Action')
    social_target=fields.Text(compute='_compute_social_target',string='Reply to')
    @api.depends('social_publication_id.payload')
    def _compute_social_target(self):
        for row in self: row.social_target=(row.social_publication_id.payload or {}).get('target_content','')
    @api.model_create_multi
    def create(self,values):
        guarded(self,{'social_publication_id','social_purpose_id'},values)
        return super().create(values)
    def write(self,values):
        guarded(self,{'social_publication_id','social_purpose_id'},[values])
        if not trusted(self) and self.sudo().social_publication_id: raise AccessError(_('Social approval evidence is frozen.'))
        return super().write(values)
    def unlink(self):
        if self.sudo().social_publication_id: raise AccessError(_('Social approvals are retained.'))
        return super().unlink()
    def _decision(self,approved):
        self.ensure_one(); self.check_access('read')
        pub=self.social_publication_id; pub.check_access('read'); pub._lock(); self.invalidate_recordset(); pub._frozen()
        if self.state!='submitted' or pub.state!='pending' or pub.requester_id==self.env.user or not self.env.user.has_group('approval_center.group_approval_center_approver'):
            raise AccessError(_('An assigned approver must review this request.'))
        lines=self.sudo().approver_ids.sorted(lambda l:(l.sequence,l.id))
        line=lines.filtered(lambda l:l.user_id==self.env.user)
        if len(line)!=1 or line.status!='submitted': raise AccessError(_('You are not a pending approver.'))
        policy=pub._policy()
        if policy['sequence'] and any(l.status!='approved' for l in lines[:list(lines).index(line)]):
            raise UserError(_('Earlier approvers must review first.'))
        internal(line).write({'status':'approved' if approved else 'refused'})
        if not approved:
            internal(self.sudo()).write({'state':'refused'}); internal(pub.sudo()).write({'state':'cancelled'})
        elif len(lines.filtered(lambda l:l.status=='approved'))>=policy['minimum'] and all(l.status=='approved' for l in lines.filtered('required')):
            internal(self.sudo()).write({'state':'approved','approved_at':fields.Datetime.now(),'approver_id':self.env.uid})
            internal(pub.sudo()).write({'state':'approved'})
        self._audit('approved' if approved else 'refused',_('Assigned social approver recorded a decision.'))
        pub._audit('social.approved' if approved else 'social.refused',_('Assigned approver recorded a decision.'))
    def action_approve(self):
        for row in self:
            if row.social_publication_id: row._decision(True)
            else: super(Request,row).action_approve()
        return True
    def action_refuse(self):
        for row in self:
            if row.social_publication_id: row._decision(False)
            else: super(Request,row).action_refuse()
        return True
    def action_execute(self):
        if len(self)==1 and self.social_publication_id: return self._execute_approved_action()
        return super().action_execute()
    def _execute_approved_action(self):
        if self.social_publication_id:
            # Approval Center execution opens the approved action; it never POSTs in its transaction.
            self.check_access('read')
            return {'type':'ir.actions.act_window','res_model':'omni.social.publication','res_id':self.social_publication_id.id,'view_mode':'form'}
        return super()._execute_approved_action()

class Approver(models.Model):
    _inherit='approval.center.approver'
    @api.model_create_multi
    def create(self,values):
        if not trusted(self):
            for vals in values:
                req=self.env['approval.center.request'].sudo().browse(vals.get('request_id') or self.env.context.get('default_request_id')).exists()
                if req.social_publication_id: raise AccessError(_('Social approvers are frozen.'))
        return super().create(values)
    def write(self,values):
        incoming=self.env['approval.center.request'].sudo().browse(values.get('request_id')).exists()
        if not trusted(self) and (self.sudo().request_id.social_publication_id or incoming.social_publication_id):
            raise AccessError(_('Social review evidence is frozen.'))
        return super().write(values)
    def unlink(self):
        if self.sudo().request_id.social_publication_id: raise AccessError(_('Social review evidence is retained.'))
        return super().unlink()
