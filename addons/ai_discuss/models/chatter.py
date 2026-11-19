"""Ask an assistant from a record's chatter (ADR 0013, phase 3; approved board 11, 2026-11-08).

The Assistants button sits after Log note. The person picks an assistant whose data access covers the record's model
and asks about the record. The question is an internal note by the person ("Asked <assistant>"); the answer is an
internal note by the assistant's chat partner, "on behalf of" the person. Nothing is emailed, and nothing changes
without approval: proposals are listed with a link to their approval request, as in Discuss.

``ai.chatter.question`` remembers which record asked, so the answer finds its way back when the run finishes.
"""

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import plaintext2html

from .discuss_channel import answer_body

QUESTION_MAX = 4000


class ChatterQuestion(models.Model):
    _name = 'ai.chatter.question'
    _description = 'Question to an assistant from a chatter'
    _order = 'id desc'

    res_model = fields.Char(required=True, readonly=True)
    res_id = fields.Many2oneReference(model_field='res_model', required=True, readonly=True)
    agent_id = fields.Many2one('ai.agent', required=True, readonly=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', required=True, readonly=True, default=lambda self: self.env.user,
                              ondelete='cascade', index=True)
    question = fields.Text(required=True, readonly=True)
    run_id = fields.Many2one('ai.agent.run', readonly=True, ondelete='set null')

    # ------------------------------------------------------------------ what the chatter offers

    @api.model
    def _agents_for(self, res_model):
        """Assistants the person may ask about records of ``res_model``: answering, in their audience, and with
        that model in their data access."""
        if res_model not in self.env or not self.env.user._is_internal():
            return self.env['ai.agent']
        agents = self.env['ai.agent'].search([('state', '=', 'active'), ('can_chat', '=', True)])
        # sudo: ai.agent.access - which models an agent reads is set by AI Agent managers; only the model is used.
        return agents.filtered(lambda agent: res_model in agent.sudo().access_ids.mapped('model_name'))

    @api.model
    def chatter_assistants(self, res_model):
        """For the chatter: the assistants to offer on this kind of record, and how to name such a record."""
        agents = self._agents_for(res_model)
        if not agents:
            return {'agents': [], 'record_label': ''}
        return {
            'record_label': (self.env['ir.model']._get(res_model).name or '').lower(),
            # sudo: ai.agent - what the picker shows of an assistant: its department and description.
            'agents': [{'id': agent.id, 'name': agent.sudo().name,
                        'department': agent.sudo().department_id.name or _('Company'),
                        'description': agent.sudo().description or ''} for agent in agents],
        }

    # ------------------------------------------------------------------ asking

    @api.model
    def chatter_ask(self, res_model, res_id, agent_id, question):
        """Post the person's question as a note on the record and ask the assistant about the record."""
        question = (question or '').strip()
        if not question:
            raise UserError(_('Write your question.'))
        if len(question) > QUESTION_MAX:
            raise UserError(_('Ask in at most %s characters.', QUESTION_MAX))
        agent = self._agents_for(res_model).filtered(lambda a: a.id == agent_id)
        if not agent:
            raise AccessError(_('You cannot ask this assistant about this record.'))
        record = self.env[res_model].browse(int(res_id)).exists()
        if not record or not hasattr(record, 'message_post'):
            raise UserError(_('This record has no conversation to answer in.'))
        record.check_access('read')
        asked = self.create({'res_model': res_model, 'res_id': record.id, 'agent_id': agent.id,
                             'question': question})
        prompt = _('About this %(kind)s, “%(name)s” (%(model)s, id %(id)s): %(question)s',
                   kind=self.env['ir.model']._get(res_model).name, name=record.display_name, model=res_model,
                   id=record.id, question=question)
        run = self.env['ai.agent.run']._ask(agent, prompt, caller='chat', origin=asked)
        asked.sudo().run_id = run.id
        # The question, as an internal note of the person (never emailed).
        record.message_post(
            body=Markup('<p class="o_ai_chatter_asked text-muted small mb-1">%s</p>') % _(
                'Asked %s', agent.sudo().name) + plaintext2html(question),
            message_type='comment', subtype_xmlid='mail.mt_note')
        return True

    def _record(self):
        """The record that asked, with the asking person's rights."""
        self.ensure_one()
        if self.res_model not in self.env:
            return None
        return self.env[self.res_model].browse(self.res_id).exists()

    def _ai_agent_finished(self, run):
        """The run ended: the assistant answers in the record's chatter, as an internal note."""
        self.ensure_one()
        record = self._record()
        if not record:
            return
        record.check_access('read')
        run = run.sudo()
        partner = self.agent_id.sudo().partner_id
        on_behalf = Markup('<p class="o_ai_chatter_behalf text-muted small mb-1">%s</p>') % _(
            'On behalf of %s', self.user_id.name)
        # sudo: mail.thread - the assistant's chat partner writes the note; it is not a user.
        record.sudo().message_post(author_id=partner.id, body=on_behalf + answer_body(self.env, run),
                                   message_type='comment', subtype_xmlid='mail.mt_note')
