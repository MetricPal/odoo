"""Ask agent: a workflow step that asks an AI agent about the record (ADR 0012, phase 5).

The question is sent as the agent's AI assistant user, so the agent sees only what that assistant may see, never what
the workflow's execution user may see. The workflow waits for the answer like a Wait step, then writes it to a field,
posts it as a note, or follows the Yes or No path. A failed or unanswered run follows the step's error setting.
"""

import hashlib
import json
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import plaintext2html

from odoo.addons.workflow_center.models.workflow import internal

RUNNING = ('queued', 'submitting', 'running', 'stop_requested', 'uncertain')
ANSWER_USES = [('field', 'Write it to a field'), ('note', 'Post it as a note'),
               ('branch', 'Choose the Yes or No path')]
ANSWER_FIELD_TYPES = ('char', 'text', 'html')
PLACEHOLDER = re.compile(r'\{(\w+)\}')
VERDICT = re.compile(r'^\W*(yes|no)\b', re.I)
# A finished agent run wakes the workflow at once; this is only the fallback check of a run still going.
CHECK_AGAIN = timedelta(hours=1)


def verdict(answer):
    """True for an answer starting with yes, False for no, None otherwise."""
    match = VERDICT.match(answer or '')
    return None if not match else match.group(1).lower() == 'yes'


class WorkflowStep(models.Model):
    _inherit = 'workflow.step'

    kind = fields.Selection(selection_add=[('agent', 'Ask agent')], ondelete={'agent': 'cascade'})
    ai_agent_id = fields.Many2one('ai.agent', string='Agent', ondelete='restrict',
                                  domain="[('state', '=', 'active'), ('company_id', '=', company_id)]")
    ai_question = fields.Text(string='Question', help='Fields in braces, such as {name}, are filled from the record.')
    ai_answer_use = fields.Selection(ANSWER_USES, string='Use the answer to', default='note', required=True)
    ai_answer_field_id = fields.Many2one(
        'ir.model.fields', string='Answer field', ondelete='cascade',
        domain="[('model_id', '=', model_id), ('ttype', 'in', ['char', 'text', 'html']), ('readonly', '=', False)]")
    ai_runs_as = fields.Char(compute='_compute_ai_runs_as', string='Runs as')

    @api.depends('ai_agent_id')
    def _compute_ai_runs_as(self):
        for step in self:
            assistant = step.ai_agent_id._assistant_user() if step.ai_agent_id else False
            step.ai_runs_as = assistant.name if assistant else False

    @api.depends('kind', 'ai_answer_use')
    def _compute_splits(self):
        return super()._compute_splits()

    def _splits(self):
        return super()._splits() or (self.kind == 'agent' and self.ai_answer_use == 'branch')

    def _follows_error_rule(self):
        return super()._follows_error_rule() or self.kind == 'agent'

    def _card(self):
        card = super()._card()
        if self.kind == 'agent':
            uses = {'field': _('answer goes to %s', self.ai_answer_field_id.field_description or _('a field')),
                    'note': _('answer posted as a note'), 'branch': _('answer chooses the path')}
            agent = self.ai_agent_id.sudo().name or _('Choose an agent')
            card.update(card_label=_('ASK AGENT'), card_hint=f'{agent} · {uses[self.ai_answer_use]}')
        return card

    def _issues(self):
        problems = super()._issues()
        if self.kind != 'agent':
            return problems
        agent = self.ai_agent_id.sudo()
        if not agent:
            problems.append(_('%s: choose the agent to ask.', self.name))
        else:
            if agent.state != 'active' or not agent.active:
                problems.append(_('%s: the agent %s is not active.', self.name, agent.name))
            if agent.company_id != self.company_id:
                problems.append(_('%s: choose an agent of this company.', self.name))
            assistant = agent._assistant_user()
            if not assistant or not assistant.active:
                problems.append(_('%s: %s has no AI assistant user. An AI Agent manager creates it on the department.',
                                  self.name, agent.name))
        if not (self.ai_question or '').strip():
            problems.append(_('%s: write the question to ask.', self.name))
        elif len(self.ai_question) > 4000:
            problems.append(_('%s: keep the question under 4,000 characters.', self.name))
        else:
            model = self.env[self.model_name]
            unknown = sorted({name for name in PLACEHOLDER.findall(self.ai_question) if name not in model._fields})
            if unknown:
                problems.append(_('%s: these fields do not exist on the record: %s', self.name, ', '.join(unknown)))
        if self.ai_answer_use == 'field':
            field = self.ai_answer_field_id
            if not field or field.model != self.model_name or field.ttype not in ANSWER_FIELD_TYPES:
                problems.append(_('%s: choose a text field of this document for the answer.', self.name))
        return problems

    def _ai_fingerprint(self):
        self.ensure_one()
        return [self.id, self.ai_agent_id.id, self.ai_question, self.ai_answer_use, self.ai_answer_field_id.name]


class WorkflowDefinition(models.Model):
    _inherit = 'workflow.definition'

    def _fingerprint(self):
        # Changing the agent, the question or what the answer does needs a new review, like any other step setting.
        digest = super()._fingerprint()
        steps = [step._ai_fingerprint() for step in self.step_ids.sorted('sequence') if step.kind == 'agent']
        if not steps:
            return digest
        return hashlib.sha256(json.dumps([digest, steps], default=str).encode()).hexdigest()


class WorkflowRun(models.Model):
    _inherit = 'workflow.run'

    ai_run_id = fields.Many2one('ai.agent.run', string='Agent request', readonly=True, ondelete='restrict')

    # -- asking --------------------------------------------------------------------------------------------------
    def _start_step(self, step, record):
        if step.kind != 'agent':
            return super()._start_step(step, record)
        agent = step.ai_agent_id.sudo()
        if not agent:
            raise UserError(_('%s: choose the agent to ask.', step.name))
        assistant = agent._assistant_user()
        if not assistant or not assistant.active:
            raise UserError(_('%s has no AI assistant user. An AI Agent manager creates it on the department.',
                              agent.name))
        prompt = self._ai_prompt(step, record.with_user(assistant))
        run = self.env['ai.agent.run']._ask(agent, prompt, caller='workflow', origin=self, as_assistant=True)
        self._set(state='waiting', ai_run_id=run.id, wake_at=fields.Datetime.now() + CHECK_AGAIN)
        self._log(_('Asked %(agent)s, as %(assistant)s. Waiting for the answer.', agent=agent.name,
                    assistant=assistant.name), 'waiting')
        return True

    def _ai_prompt(self, step, record):
        """The step's question with record fields filled in, read as the AI assistant."""
        try:
            record.check_access('read')
        except AccessError:
            raise UserError(_('%(assistant)s may not read %(record)s. Give the AI assistant access to this document.',
                              assistant=record.env.user.name, record=record.display_name)) from None

        def value(match):
            name = match.group(1)
            field = record._fields.get(name)
            if not field:
                raise UserError(_('%(step)s: the record has no field %(field)s.', step=step.name, field=name))
            if not record._has_field_access(field, 'read'):
                raise UserError(_('%(assistant)s may not read %(field)s.', assistant=record.env.user.name,
                                  field=field.string))
            current = record[name]
            if field.type == 'many2one':
                return current.display_name or ''
            if field.type in ('one2many', 'many2many'):
                return ', '.join(current[:20].mapped('display_name'))
            if field.type == 'selection':
                return dict(field._description_selection(record.env)).get(current, '') if current else ''
            if field.type == 'boolean':
                return _('yes') if current else _('no')
            return '' if current is False else str(current)

        question = PLACEHOLDER.sub(value, step.ai_question or '').strip()
        lines = [question, '',
                 _('This question comes from the workflow "%(workflow)s", about %(record)s (%(model)s #%(id)s).',
                   workflow=self.workflow_id.name, record=record.display_name, model=record._name, id=record.id)]
        if step.ai_answer_use == 'branch':
            lines.append(_('Start your answer with Yes or No.'))
        return '\n'.join(lines)

    # -- the answer ----------------------------------------------------------------------------------------------
    def _resume_step(self, step, record):
        if step.kind != 'agent':
            return super()._resume_step(step, record)
        run = self.ai_run_id.sudo()
        if not run:
            return step  # Ask again (a retry after asking failed).
        if run.state in RUNNING:
            self._set(wake_at=fields.Datetime.now() + CHECK_AGAIN)
            return None
        self._set(ai_run_id=False)
        answer = (run.answer or '').strip()
        if run.state != 'completed' or not answer:
            return self._ai_failed(step, _('The agent did not answer (%s).', dict(
                run._fields['state']._description_selection(run.env)).get(run.state, run.state)))
        if step.ai_answer_use == 'branch':
            yes = verdict(answer)
            if yes is None:
                return self._ai_failed(step, _('The answer did not start with Yes or No: %s', answer[:200]))
            self._log(_('The agent answered %(verdict)s: %(answer)s', verdict=_('Yes') if yes else _('No'),
                        answer=answer[:500]))
            return step._next() if yes else step.false_id
        with self.env.cr.savepoint():
            if step.ai_answer_use == 'field':
                field = step.ai_answer_field_id
                text = plaintext2html(answer) if field.ttype == 'html' else answer
                record.write({field.name: text[:256] if field.ttype == 'char' else text})
                self._log(_('Answer written to %(field)s: %(answer)s', field=field.field_description,
                            answer=answer[:500]))
            else:
                # Posted with the execution user's rights, signed by the assistant that answered.
                record.message_post(body=plaintext2html(answer), message_type='comment', subtype_xmlid='mail.mt_note',
                                    author_id=run.user_id.partner_id.id)
                self._log(_('Answer posted as a note: %s', answer[:500]))
        return step._next()

    def _ai_failed(self, step, reason):
        """Apply the step's error setting to an agent that did not give a usable answer."""
        if step.on_error == 'continue':
            self._log(_('%s Configured failure rule: skipped this step.', reason), 'skipped')
            return step._next()
        if step.on_error == 'retry' and self.attempts < step.max_attempts:
            self._log(_('%s Asking again.', reason), 'retry')
            return step
        raise UserError(reason)

    def _ai_agent_finished(self, run):
        """The agent run this workflow waits for finished: continue the workflow now."""
        workflow_run = self.sudo()
        if workflow_run.ai_run_id.id != run.id or workflow_run.state != 'waiting':
            return
        internal(workflow_run).write({'wake_at': fields.Datetime.now()})
        workflow_run._advance()
