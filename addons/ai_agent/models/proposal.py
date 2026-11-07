"""Agent proposals (ADR 0012, phase 4): an agent prepares a note, an activity or a field change; a person approves it
through Approval Center; only then is it applied.

The proposal is the target record of an "AI agent proposal" approval request. When the request is fully approved, its
``action_apply`` runs once, as the person who asked: it checks again that this person may change the record, then the
agent's AI assistant user makes the change (or the person, when the agent has no assistant).
"""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html2plaintext, plaintext2html

from odoo.addons.approval_center.models.common import approval_internal

from .common import internal, trusted

KINDS = [('note', 'Note'), ('activity', 'Activity'), ('change', 'Field change')]


class AgentProposal(models.Model):
    _name = 'ai.agent.proposal'
    _description = 'AI agent proposal'
    _order = 'id desc'

    name = fields.Char(required=True, readonly=True)
    kind = fields.Selection(KINDS, required=True, readonly=True)
    run_id = fields.Many2one('ai.agent.run', required=True, readonly=True, ondelete='restrict', index=True)
    agent_id = fields.Many2one(related='run_id.agent_id', store=True)
    company_id = fields.Many2one(related='run_id.company_id', store=True)
    requester_id = fields.Many2one('res.users', string='Asked by', readonly=True)
    assistant_user_id = fields.Many2one('res.users', string='Acts as', readonly=True)
    target_model = fields.Char(required=True, readonly=True)
    target_res_id = fields.Integer(required=True, readonly=True)
    target_name = fields.Char(string='Record', readonly=True)
    values = fields.Json(readonly=True, help='The proposed values (field change, activity).')
    text = fields.Text(readonly=True, help='The proposed note or activity text.')
    request_id = fields.Many2one('approval.center.request', string='Approval request', readonly=True,
                                 ondelete='restrict')
    state = fields.Selection([('waiting', 'Waiting for approval'), ('applied', 'Applied'), ('refused', 'Refused'),
                              ('failed', 'Failed'), ('cancelled', 'Cancelled')], compute='_compute_state')
    applied_at = fields.Datetime(readonly=True)

    @api.depends('request_id.state', 'request_id.executed_at', 'request_id.failure_reason', 'applied_at')
    def _compute_state(self):
        for proposal in self:
            request = proposal.sudo().request_id
            if proposal.applied_at:
                proposal.state = 'applied'
            elif request.state == 'refused':
                proposal.state = 'refused'
            elif request.state == 'cancel':
                proposal.state = 'cancelled'
            elif request.failure_reason:
                proposal.state = 'failed'
            else:
                proposal.state = 'waiting'

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self):
            raise AccessError(_('Agents create proposals through their tools.'))
        return super().create(vals_list)

    def write(self, vals):
        if not trusted(self):
            raise AccessError(_('Proposals are decided through their approval request.'))
        return super().write(vals)

    def unlink(self):
        raise UserError(_('Proposals are kept as evidence.'))

    # -- creating ---------------------------------------------------------------------------------------------
    @api.model
    def _propose(self, run, kind, record, summary, text=None, values=None):
        """Create the proposal and submit its approval request for the person who asked (or the assistant)."""
        users = self.env['ai.agent.tools']._acting_users(run)
        requester = run.user_id or users[0]
        assistant = users[0] if users[0] != run.user_id else self.env['res.users']
        proposal = internal(self.sudo()).create({
            'name': summary[:200], 'kind': kind, 'run_id': run.id, 'requester_id': requester.id,
            'assistant_user_id': assistant.id, 'target_model': record._name, 'target_res_id': record.id,
            'target_name': record.display_name, 'values': values or {}, 'text': text or False})
        policy = self.env.ref('ai_agent.approval_type_agent_proposal').sudo()
        description = proposal._describe()
        # The request belongs to the person who asked: created and submitted as them (privileged, governed).
        Request = approval_internal(self.env['approval.center.request'].with_user(requester).sudo())
        request = Request.create({
            'name': _('%(agent)s: %(summary)s', agent=run.agent_id.sudo().name, summary=summary)[:200],
            'policy_id': policy.id, 'requester_id': requester.id, 'company_id': run.company_id.id,
            'target_model': proposal._name, 'target_res_id': proposal.id, 'reason': description})
        with self.env.cr.savepoint():
            request.action_submit()
        internal(proposal).write({'request_id': request.id})
        return proposal, request

    def _describe(self):
        self.ensure_one()
        lines = [_('The agent "%(agent)s" proposes, on %(record)s (%(model)s #%(id)s):',
                   agent=self.agent_id.sudo().name, record=self.target_name, model=self.target_model,
                   id=self.target_res_id)]
        if self.kind == 'note':
            lines += [_('A note:'), self.text or '']
        elif self.kind == 'activity':
            values = self.values or {}
            lines += [_('An activity "%(summary)s" due %(due)s.', summary=values.get('summary'), due=values.get('due')),
                      self.text or '']
        else:
            lines += [_('These changes:')] + [f'- {name}: {value!r}' for name, value in (self.values or {}).items()]
        lines.append(_('Asked by %s.', self.requester_id.name))
        return '\n'.join(line for line in lines if line is not None)

    # -- applying ---------------------------------------------------------------------------------------------
    def action_apply(self):
        """Run by Approval Center once the request is approved. Applies the proposal once."""
        self.ensure_one()
        request = self.sudo().request_id
        if self.applied_at or not request or request.state != 'approved':
            raise UserError(_('This proposal is not approved, or was already applied.'))
        record = self.env[self.target_model].sudo().browse(self.target_res_id).exists()
        if not record:
            raise UserError(_('The record no longer exists.'))
        actor = self.sudo().assistant_user_id or self.sudo().requester_id
        if self.kind == 'change':
            self._check_person_may_change(record)
            record.with_user(actor).write(dict(self.values or {}))
        elif self.kind == 'note':
            self._check_person_may_change(record, fields_to_check=())
            record.with_user(actor).message_post(
                body=plaintext2html(self.text or ''), message_type='comment', subtype_xmlid='mail.mt_note')
        else:
            self._check_person_may_change(record, fields_to_check=())
            values = self.values or {}
            record.with_user(actor).activity_schedule(
                'mail.mail_activity_data_todo', date_deadline=values.get('due'), summary=values.get('summary'),
                note=plaintext2html(self.text or ''), user_id=values.get('user_id') or self.sudo().requester_id.id)
        internal(self.sudo()).write({'applied_at': fields.Datetime.now()})
        self.sudo().run_id._event('proposal', _('%(kind)s applied on %(record)s after approval.',
                                              kind=dict(KINDS)[self.kind], record=self.target_name))
        return True

    def _check_person_may_change(self, record, fields_to_check=None):
        """The person who asked must still be allowed to change the record (and the fields of a change)."""
        person = self.sudo().requester_id
        target = record.with_user(person)
        if not target._filtered_access('write'):
            raise AccessError(_('%s may no longer change this record.', person.name))
        names = (self.values or {}).keys() if fields_to_check is None else fields_to_check
        for name in names:
            field = target._fields.get(name)
            if not field or not target._has_field_access(field, 'write'):
                raise AccessError(_('%(person)s may not change %(field)s.', person=person.name, field=name))


class ApprovalRequest(models.Model):
    _inherit = 'approval.center.request'

    def action_approve(self):
        result = super().action_approve()
        # An approved agent proposal is applied at once, as the person who asked.
        for request in self.sudo().filtered(lambda r: r.target_model == 'ai.agent.proposal' and r.state == 'approved'
                                            and not r.executed_at):
            # As the person who asked (Approval Center's execution rule), privileged for the request's own audit
            # writes; action_apply checks the person's rights explicitly and changes the record as the assistant.
            request.with_user(request.requester_id).sudo()._execute_approved_action()
        return result
