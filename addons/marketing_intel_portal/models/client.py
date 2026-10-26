"""What a client contact may see and decide, set on the brand."""

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

CLIENT_STATES = [('none', 'Not asked'), ('waiting', 'Waiting for the client'), ('approved', 'Client approved'),
                 ('changes', 'Client asked for changes')]


class Brand(models.Model):
    _inherit = 'mi.brand'

    portal_partner_ids = fields.Many2many('res.partner', 'mi_brand_portal_partner_rel', 'brand_id', 'partner_id',
                                          string='Client contacts',
                                          help='People who see this brand in their portal (give them portal access '
                                               'from the contact: Action › Grant portal access).')
    client_signoff = fields.Boolean(string='Client signs off campaigns',
                                    help='A campaign goes to the internal review only after a client contact '
                                         'approved it in the portal.')
    client_proofs = fields.Boolean(string='Client reviews proofs', help='New proofs are reviewed by the client.')

    @api.model
    def _portal_brands(self, partner=None):
        partner = partner or self.env.user.partner_id
        return self.sudo().search([('portal_partner_ids', 'in', partner.ids)])


class Plan(models.Model):
    _inherit = 'mi.plan'

    client_state = fields.Selection(CLIENT_STATES, string='Client sign-off', default='none', copy=False,
                                    readonly=True, tracking=True)
    client_feedback = fields.Text(string='Client feedback', readonly=True, copy=False)
    client_decided_by = fields.Many2one('res.partner', readonly=True, copy=False)
    client_signoff = fields.Boolean(related='brand_id.client_signoff')

    def _portal_url(self):
        return '%s/my/marketing/campaign/%s' % (self.get_base_url(), self.id)

    def action_ask_client(self):
        for plan in self:
            plan.check_access('write')
            if not plan.brand_id.client_signoff:
                raise UserError(_('This brand does not ask clients to sign off campaigns.'))
            partners = plan.brand_id.portal_partner_ids
            if not partners:
                raise UserError(_('Add client contacts on the brand (Brand › Client portal) first.'))
            if plan.state not in ('brief', 'content'):
                raise UserError(_('Ask the client before the campaign goes to review.'))
            plan.sudo().write({'client_state': 'waiting', 'client_feedback': False, 'client_decided_by': False})
            plan.message_post(
                body=Markup(_('Sent to the client for sign-off: <a href="%(url)s">open in the portal</a>.')) % {
                    'url': plan._portal_url()}, partner_ids=partners.ids, subtype_xmlid='mail.mt_comment')
        return True

    def _client_decide(self, partner, approve, feedback=''):
        """A client contact's decision from the portal (called with sudo after the portal access check)."""
        self.ensure_one()
        if partner not in self.brand_id.portal_partner_ids:
            raise AccessError(_('You are not a contact of this brand.'))
        if self.client_state != 'waiting':
            raise UserError(_('This campaign is not waiting for your sign-off.'))
        if not approve and not (feedback or '').strip():
            raise UserError(_('Write what should change.'))
        self.write({'client_state': 'approved' if approve else 'changes', 'client_feedback': feedback or False,
                    'client_decided_by': partner.id})
        body = _('%(who)s approved the campaign.', who=partner.name) if approve else \
            _('%(who)s asked for changes: %(text)s', who=partner.name, text=feedback)
        self.message_post(body=body + (_(' Comment: %s', feedback) if approve and feedback else ''),
                          author_id=partner.id, message_type='comment', subtype_xmlid='mail.mt_comment',
                          partner_ids=self.user_id.partner_id.ids)
        self._sync_owner_activity()

    def _review_blockers(self):
        blockers = super()._review_blockers()
        for plan in self.filtered(lambda p: p.brand_id.client_signoff and p.client_state != 'approved'):
            blockers.append({
                'none': _('The client has not signed off yet: click “Ask the client”.'),
                'waiting': _('Waiting for the client\'s sign-off in the portal.'),
                'changes': _('The client asked for changes: %s. Update it and ask the client again.',
                             plan.client_feedback or '-'),
            }[plan.client_state])
        return blockers

    def _back_to_content(self, note):
        signed = self.filtered(lambda p: p.state == 'review' and p.client_state == 'approved')
        result = super()._back_to_content(note)
        signed.sudo().client_state = 'none'
        return result

    def _next_step(self):
        step = super()._next_step()
        if self.sudo().brand_id.client_signoff and self.state == 'content' and self.client_state != 'approved' \
                and not self.is_template and not self._ai_busy() \
                and not any(stage in ('blocked', 'failed') for stage in self.item_ids.mapped('stage')):
            return {'none': (_('Finish the drafts, then ask the client to sign off (“Ask the client”)'), True),
                    'waiting': (_('Waiting for the client to sign off in the portal'), False),
                    'changes': (_('The client asked for changes: update the drafts and ask the client again'), True),
                    }[self.client_state]
        return step


class Proof(models.Model):
    _inherit = 'mi.proof'

    client_review = fields.Boolean(string='Client reviews', default=lambda self: self._default_client_review(),
                                   help='The client approves or asks for changes in the portal.')
    client_decided_by = fields.Many2one('res.partner', readonly=True, copy=False)

    @api.model
    def _default_client_review(self):
        plan = self.env['mi.plan'].browse(self.env.context.get('default_plan_id')).exists()
        return bool(plan.brand_id.client_proofs)

    @api.onchange('plan_id')
    def _onchange_plan_client(self):
        if self.plan_id and not self.previous_id:
            self.client_review = self.plan_id.brand_id.client_proofs

    def action_send(self):
        for proof in self.filtered('client_review'):
            if not proof.brand_id.portal_partner_ids:
                raise UserError(_('Add client contacts on the brand first, or untick “Client reviews”.'))
        result = super().action_send()
        for proof in self.filtered('client_review'):
            proof.message_post(
                body=Markup(_('Sent to the client: <a href="%(url)s">open in the portal</a>.')) % {
                    'url': '%s/my/marketing/proof/%s' % (proof.get_base_url(), proof.id)},
                partner_ids=proof.brand_id.portal_partner_ids.ids, subtype_xmlid='mail.mt_comment')
        return result

    def _client_decide(self, partner, approve, feedback=''):
        self.ensure_one()
        if not self.client_review or partner not in self.brand_id.portal_partner_ids:
            raise AccessError(_('You cannot decide on this proof.'))
        if self.state != 'review':
            raise UserError(_('This proof is not waiting for review.'))
        if not approve and not (feedback or '').strip():
            raise UserError(_('Write what should change.'))
        self.write({'state': 'approved' if approve else 'changes', 'feedback': feedback or False,
                    'client_decided_by': partner.id, 'decided_at': fields.Datetime.now()})
        self.message_post(body=_('%(who)s approved it.', who=partner.name) if approve else
                          _('%(who)s asked for changes: %(text)s', who=partner.name, text=feedback),
                          author_id=partner.id, message_type='comment', subtype_xmlid='mail.mt_comment',
                          partner_ids=self.author_id.partner_id.ids)
        if approve:
            self._apply_to_channel()
        else:
            self.activity_schedule('mail.mail_activity_data_todo', user_id=self.author_id.id,
                                   summary=_('Client asked for changes on %s', self.name), note=feedback)


class Request(models.Model):
    _inherit = 'mi.request'

    from_portal = fields.Boolean(readonly=True, string='Filed in the portal')
