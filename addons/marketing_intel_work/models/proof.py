"""Proofs: versions of a creative or a text, compared side by side, approved or sent back with changes.

An approved proof is the text the channel uses: it fills the channel's draft (or its saved text when the draft
does not exist yet). While a proof is open (in review or with changes requested) the campaign is not sent for
review, so the one campaign review only sees approved content.
"""

import difflib
import re

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

OPEN = ('draft', 'review', 'changes')


def _words(text):
    return re.findall(r'\w+|[^\w\s]+|\s+', text or '')


def diff_html(old, new):
    """Inline word diff: removed words struck through in red, added words in green."""
    old_words, new_words = _words(old), _words(new)
    out = []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, old_words, new_words, autojunk=False).get_opcodes():
        if op == 'equal':
            out.append(escape(''.join(old_words[a1:a2])))
            continue
        if a2 > a1:
            out.append(Markup('<del class="text-danger">%s</del>') % ''.join(old_words[a1:a2]))
        if b2 > b1:
            out.append(Markup('<ins class="text-success fw-bold">%s</ins>') % ''.join(new_words[b1:b2]))
    return Markup('<div style="white-space: pre-wrap">%s</div>') % Markup('').join(out)


class Proof(models.Model):
    _name = 'mi.proof'
    _description = 'Marketing proof'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'plan_id, name, version desc'

    name = fields.Char(string='Proof', required=True, tracking=True, help='What is proofed, e.g. "Launch email".')
    plan_id = fields.Many2one('mi.plan', string='Campaign', required=True, ondelete='cascade', index=True)
    item_id = fields.Many2one('mi.plan.item', string='Channel', domain="[('plan_id', '=', plan_id)]",
                              ondelete='set null', help='The approved version fills this channel\'s draft.')
    brand_id = fields.Many2one(related='plan_id.brand_id', store=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True)
    version = fields.Integer(default=1, readonly=True, copy=False)
    version_label = fields.Char(compute='_compute_version_label', string='Version')
    previous_id = fields.Many2one('mi.proof', string='Previous version', readonly=True, copy=False)
    subject = fields.Char(string='Subject / title')
    body = fields.Text(string='Text')
    image = fields.Image(string='Creative', max_width=1920, max_height=1920)
    author_id = fields.Many2one('res.users', string='Made by', default=lambda self: self.env.user, readonly=True,
                                copy=False)
    reviewer_id = fields.Many2one('res.users', string='Reviewer', tracking=True,
                                  help='Who approves this proof (someone other than its maker).')
    state = fields.Selection([('draft', 'Draft'), ('review', 'Waiting for review'), ('changes', 'Changes requested'),
                              ('approved', 'Approved'), ('old', 'Older version')], default='draft', required=True,
                             readonly=True, tracking=True, copy=False, group_expand=True)
    feedback = fields.Text(string='Feedback', copy=False, help='What to change (required to request changes).')
    decided_by = fields.Many2one('res.users', readonly=True, copy=False)
    decided_at = fields.Datetime(readonly=True, copy=False)
    compare_html = fields.Html(compute='_compute_compare', sanitize=False, string='What changed')
    previous_subject = fields.Char(related='previous_id.subject', string='Previous subject')
    previous_body = fields.Text(related='previous_id.body', string='Previous text')
    previous_image = fields.Image(related='previous_id.image', string='Previous creative')
    previous_feedback = fields.Text(related='previous_id.feedback', string='Feedback on the previous version')
    can_decide = fields.Boolean(compute='_compute_can_decide')

    @api.depends('version')
    def _compute_version_label(self):
        for proof in self:
            proof.version_label = 'v%s' % proof.version

    @api.depends('body', 'subject', 'previous_id.body', 'previous_id.subject')
    def _compute_compare(self):
        for proof in self:
            if not proof.previous_id:
                proof.compare_html = False
                continue
            parts = []
            if (proof.subject or '') != (proof.previous_id.subject or ''):
                parts.append(Markup('<p><b>%s</b> %s</p>') % (_('Subject:'), diff_html(proof.previous_id.subject,
                                                                                         proof.subject)))
            parts.append(diff_html(proof.previous_id.body, proof.body))
            proof.compare_html = Markup('').join(parts)

    @api.depends_context('uid')
    @api.depends('state', 'reviewer_id', 'author_id')
    def _compute_can_decide(self):
        manager = self.env.user.has_group('marketing_intel.group_mi_manager')
        for proof in self:
            proof.can_decide = proof.state == 'review' and (
                proof.reviewer_id == self.env.user or (manager and proof.author_id != self.env.user)
                or (not proof.reviewer_id and proof.author_id != self.env.user))

    @api.onchange('plan_id')
    def _onchange_plan_id(self):
        if self.plan_id and not self.reviewer_id and self.plan_id.user_id != self.env.user:
            self.reviewer_id = self.plan_id.user_id

    def action_send(self):
        for proof in self:
            if proof.state not in ('draft', 'changes'):
                raise UserError(_('Only a draft can be sent for review.'))
            if not (proof.body or proof.image or proof.subject):
                raise UserError(_('Add the text or the creative first.'))
            if proof.reviewer_id == self.env.user:
                raise UserError(_('Choose a reviewer other than yourself.'))
            proof.state = 'review'
            if proof.reviewer_id:
                proof.activity_schedule('mail.mail_activity_data_todo', user_id=proof.reviewer_id.id,
                                        summary=_('Review the proof %(name)s %(v)s', name=proof.name,
                                                  v=proof.version_label))
        return True

    def _decide(self):
        for proof in self:
            if proof.state != 'review':
                raise UserError(_('This proof is not waiting for review.'))
            if not proof.can_decide:
                raise UserError(_('Only the reviewer (or a marketing manager other than its maker) can decide.'))

    def action_approve(self):
        self._decide()
        for proof in self:
            proof.write({'state': 'approved', 'decided_by': self.env.uid, 'decided_at': fields.Datetime.now()})
            proof.activity_feedback(['mail.mail_activity_data_todo'], feedback=_('Approved'))
            proof._apply_to_channel()
        return True

    def action_request_changes(self):
        self._decide()
        for proof in self:
            if not (proof.feedback or '').strip():
                raise UserError(_('Write what to change in “Feedback” first.'))
            proof.write({'state': 'changes', 'decided_by': self.env.uid, 'decided_at': fields.Datetime.now()})
            proof.activity_feedback(['mail.mail_activity_data_todo'], feedback=proof.feedback)
            proof.activity_schedule('mail.mail_activity_data_todo', user_id=proof.author_id.id,
                                    summary=_('Changes requested on %s', proof.name), note=proof.feedback)
        return True

    def action_new_version(self):
        """A new version to edit; this one is kept for comparison."""
        self.ensure_one()
        if self.state == 'old':
            raise UserError(_('Make the new version from the latest one.'))
        if self.state == 'review':
            raise UserError(_('Wait for the decision on this version (or ask the reviewer).'))
        new = self.copy({'name': self.name, 'version': self.version + 1, 'previous_id': self.id, 'reviewer_id': self.reviewer_id.id,
                         'author_id': self.env.uid})
        self.activity_unlink(['mail.mail_activity_data_todo'])
        self.state = 'old'
        new.message_post(body=_('New version of %s.', self.version_label))
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.proof', 'res_id': new.id, 'view_mode': 'form',
                'views': [(False, 'form')], 'target': 'current'}

    def _apply_to_channel(self):
        """The approved text becomes the channel's text: its draft if it exists, its saved text otherwise."""
        self.ensure_one()
        item = self.item_id
        if not item or not (self.subject or self.body):
            return
        item.sudo().write({'content_subject': self.subject or item.content_subject,
                           'content_text': self.body or item.content_text})
        error = item._fill(self.subject, self.body)
        self.message_post(body=_('Not copied into the draft: %s', error) if error else
                          _('Approved text copied into the %s channel.', item.channel))


class PlanItem(models.Model):
    _inherit = 'mi.plan.item'

    @api.depends('channel', 'plan_id')
    def _compute_display_name(self):
        labels = dict(self._fields['channel']._description_selection(self.env))
        for item in self:
            item.display_name = labels.get(item.channel) or item.plan_id.name or ''


class Plan(models.Model):
    _inherit = 'mi.plan'

    proof_ids = fields.One2many('mi.proof', 'plan_id', string='Proofs')
    design_proof_ids = fields.One2many('mi.proof', 'plan_id', string='Creatives', domain=[('state', '!=', 'old')])
    proof_open_count = fields.Integer(compute='_compute_proof_counts', string='Open proofs')
    proof_count = fields.Integer(compute='_compute_proof_counts', string='Proofs')

    def _compute_proof_counts(self):
        for plan in self:
            current = plan.proof_ids.filtered(lambda p: p.state != 'old')
            plan.proof_count = len(current)
            plan.proof_open_count = len(current.filtered(lambda p: p.state in OPEN))

    def _review_blockers(self):
        blockers = super()._review_blockers()
        for proof in self.proof_ids.filtered(lambda p: p.state in OPEN):
            state = dict(proof._fields['state']._description_selection(self.env))[proof.state]
            blockers.append(_('Proof “%(name)s” %(v)s: %(state)s (approve it or delete it).', name=proof.name,
                              v=proof.version_label, state=state.lower()))
        return blockers

    def action_open_proofs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Proofs · %s', self.name), 'res_model': 'mi.proof',
                'view_mode': 'kanban,list,form', 'views': [(False, 'kanban'), (False, 'list'), (False, 'form')],
                'domain': [('plan_id', '=', self.id), ('state', '!=', 'old')],
                'context': {'default_plan_id': self.id}}
