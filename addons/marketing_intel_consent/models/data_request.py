"""Requests for a copy or erasure of a person's marketing data, executed only after approval.

* Copy: a JSON file with the person's consent history, Messaging contacts and their consents, email/SMS
  mailing contacts and list subscriptions, workflow runs and campaign leads.
* Erasure: the person is anonymized everywhere marketing keeps them; their addresses stay suppressed
  (blacklisted, opted out) so they are not contacted again; the consent history is kept, anonymized, as proof.
"""

import base64
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .consent import CHANNELS, anonymous_hash


class DataRequest(models.Model):
    _name = 'mi.data.request'
    _description = 'Marketing data request'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    subject_id = fields.Many2one('mi.consent.subject', required=True, string='Person', tracking=True)
    company_id = fields.Many2one(related='subject_id.company_id', store=True)
    kind = fields.Selection([('export', 'A copy of their data'), ('erase', 'Erase their marketing data')],
                            required=True, default='export', string='They ask for', tracking=True)
    note = fields.Text(string='How they asked', help='e.g. email of 3 March, identity checked by phone')
    state = fields.Selection([('new', 'New'), ('pending', 'Waiting for approval'), ('done', 'Done'),
                              ('refused', 'Refused')], default='new', readonly=True, tracking=True)
    approval_request_id = fields.Many2one('approval.center.request', readonly=True, copy=False)
    attachment_id = fields.Many2one('ir.attachment', readonly=True, copy=False, string='Data file')
    done_at = fields.Datetime(readonly=True)

    def action_submit(self):
        for request in self:
            if request.state not in ('new', 'refused'):
                raise UserError(_('This request was already sent for approval.'))
            if not (request.note or '').strip():
                raise UserError(_('Note how the person asked and how their identity was checked.'))
            policy = self.env.ref('marketing_intel_consent.policy_data_request').sudo()
            approval = self.env['approval.center.request'].sudo().create({
                'name': _('Data request: %(kind)s for %(name)s', kind=dict(request._fields['kind']._description_selection(
                    self.env))[request.kind], name=request.subject_id.name),
                'policy_id': policy.id, 'company_id': request.company_id.id, 'requester_id': self.env.uid,
                'target_model': request._name, 'target_res_id': request.id, 'reason': request.note,
            })
            try:
                approval.with_user(self.env.user).sudo().action_submit()
            except UserError as error:
                raise UserError(_('%s Approvers are set on the approval type “Marketing data request”.', error)) from None
            request.write({'approval_request_id': approval.id, 'state': 'pending'})
        return True

    def action_execute(self):
        """Runs from the approval (as the requester); refuses without an approved request."""
        for request in self:
            approval = request.sudo().approval_request_id
            if not approval or approval.state != 'approved' or request.state != 'pending':
                raise AccessError(_('This data request has no valid approval.'))
            if request.kind == 'export':
                request._export()
            else:
                request._erase()
            request.write({'state': 'done', 'done_at': fields.Datetime.now()})
        return True

    def _collect(self):
        subject = self.subject_id.sudo()
        data = {'person': {'name': subject.name, 'email': subject.email, 'phone': subject.phone},
                'consent': [{'channel': r.channel, 'topic': r.topic_id.name or None, 'action': r.action,
                             'source': r.source, 'evidence': r.evidence, 'at': fields.Datetime.to_string(r.recorded_at)}
                            for r in subject.record_ids.sorted('recorded_at')]}
        contacts = subject._mm_contacts()
        data['messaging'] = [{'name': c.name, 'whatsapp': c.whatsapp, 'lists': c.list_ids.mapped('name'),
                              'consents': [{'channel': k.channel, 'action': k.action, 'evidence': k.evidence}
                                           for k in c.consent_ids]} for c in contacts]
        if subject.email:
            mailing = self.env['mailing.contact'].sudo().search([('email', '=ilike', subject.email)])
            data['email_contacts'] = [{'name': m.name, 'email': m.email, 'lists': m.list_ids.mapped('name')}
                                      for m in mailing]
        if 'mi.flow.run' in self.env and subject.partner_id:
            runs = self.env['mi.flow.run'].sudo().search([('partner_id', '=', subject.partner_id.id)])
            data['workflow_runs'] = [{'workflow': r.flow_id.name, 'at': fields.Datetime.to_string(r.create_date),
                                      'result': r.state} for r in runs]
        return data

    def _export(self):
        content = json.dumps(self._collect(), indent=2, ensure_ascii=False).encode()
        attachment = self.env['ir.attachment'].sudo().create({
            'name': 'marketing-data-%s.json' % self.id, 'datas': base64.b64encode(content),
            'res_model': self._name, 'res_id': self.id, 'mimetype': 'application/json'})
        self.attachment_id = attachment
        self.message_post(body=_('Data file prepared: send it to the person.'), attachment_ids=attachment.ids)

    def _erase(self):
        subject = self.subject_id.sudo()
        evidence = _('Erasure request #%s', self.id)
        for channel, _label in CHANNELS:
            if subject[f'{channel}_status'] != 'opted_out':
                subject._record(channel, 'opt_out', 'data_request', evidence)
        for contact in subject._mm_contacts():
            contact.write({'name': _('Erased person'), 'active': False})
        if subject.email:
            self.env['mailing.contact'].sudo().search([('email', '=ilike', subject.email)]).write(
                {'name': _('Erased person'), 'active': False})
        subject.write({'name': _('Erased person %s', anonymous_hash(subject.email or subject.phone)),
                       'partner_id': False, 'erased': True})
        self.message_post(body=_('Erased: Messaging and email contacts anonymized and archived; addresses kept on '
                                 'the blacklists so the person is not contacted again.'))


class Request(models.Model):
    _inherit = 'approval.center.request'

    def action_approve(self):
        result = super().action_approve()
        for request in self.sudo().filtered(lambda r: r.target_model == 'mi.data.request' and r.state == 'approved'
                                            and not r.executed_at):
            request.with_user(request.requester_id).sudo().action_execute()
        return result

    def action_refuse(self):
        result = super().action_refuse()
        for request in self.sudo().filtered(lambda r: r.target_model == 'mi.data.request' and r.state == 'refused'):
            data_request = self.env['mi.data.request'].sudo().browse(request.target_res_id).exists()
            data_request.filtered(lambda d: d.state == 'pending').write({'state': 'refused'})
        return result
