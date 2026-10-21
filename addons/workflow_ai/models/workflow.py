import json
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

RUNNING = ('queued', 'submitting', 'running', 'stop_requested', 'uncertain')
STEP_LIMIT = 12


def _json_object(text):
    """The first JSON object in an answer, or None."""
    match = re.search(r'\{.*\}', text or '', re.S)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


class WorkflowDefinition(models.Model):
    _inherit = 'workflow.definition'

    ai_run_id = fields.Many2one('ai.agent.run', readonly=True, copy=False, string='AI draft request')
    ai_suggestion = fields.Text(readonly=True, copy=False, string='AI suggestion')

    @api.model
    def home_data(self):
        data = super().home_data()
        data['agents'] = self.env['ai.agent']._chat_options()
        data['ai_drafting'] = True
        return data

    @api.model
    def ai_draft(self, description, model_id, agent_id):
        """Create a draft workflow and ask an agent to propose its name, trigger and steps.

        The agent only proposes text; the administrator builds and activates the workflow.
        """
        self._manager()
        if not isinstance(description, str) or not description.strip() or len(description) > 2000:
            raise UserError(_('Describe the workflow in at most 2,000 characters.'))
        model = self.env['ir.model'].browse(int(model_id)).exists()
        agent = self.env['ai.agent'].browse(int(agent_id)).exists()
        if not model or not agent:
            raise UserError(_('Choose a document and an agent.'))
        workflow = self.create({
            'name': description.strip()[:60],
            'description': description.strip(),
            'model_id': model.id,
        })
        triggers = dict(self._fields['trigger']._description_selection(self.env))
        prompt = '\n'.join([
            'Propose an automated workflow for Odoo.',
            f'Document it watches: {model.name} ({model.model}).',
            f'What the administrator wants: {description.strip()}',
            'Reply with one JSON object only, no other text:',
            '{"name": "short workflow name", "trigger": "<one key below>", '
            '"steps": ["one short step per line, in order"]}',
            'Trigger keys: ' + '; '.join(f'{key} = {label}' for key, label in triggers.items()),
            f'At most {STEP_LIMIT} steps. Do not claim anything was created or run.',
        ])
        run = self.env['ai.agent.run']._queue(agent, prompt, origin=workflow)
        workflow.ai_run_id = run.sudo().id
        workflow.message_post(body=_('Asked %s to draft this workflow.', agent.name))
        return workflow.action_open_builder()

    def _ai_agent_finished(self, run):
        """Apply an agent's proposal to a draft. Runs as the requester."""
        self.ensure_one()
        if run.id != self.ai_run_id.id:
            return
        if run.state != 'completed':
            self.message_post(body=_('The AI draft request ended without an answer (%s). Start blank instead.', run.state))
            self.ai_suggestion = _('No suggestion: the request ended without an answer.')
            return
        proposal = _json_object(run.answer) or {}
        values = {}
        name = proposal.get('name')
        if isinstance(name, str) and name.strip():
            values['name'] = name.strip()[:80]
        trigger = proposal.get('trigger')
        if self.state == 'draft' and trigger in dict(self._fields['trigger'].selection):
            values['trigger'] = trigger
        steps = proposal.get('steps')
        if isinstance(steps, list) and steps:
            lines = [str(step).strip()[:200] for step in steps[:STEP_LIMIT] if str(step).strip()]
            values['ai_suggestion'] = '\n'.join(f'{index}. {line}' for index, line in enumerate(lines, 1))
        else:
            values['ai_suggestion'] = (run.answer or '').strip()[:4000] or _('The agent returned no steps.')
        self.write(values)
        self.message_post(body=_('AI draft ready. Review the trigger and add the suggested steps before activating.'))

    def _builder_ai_info(self):
        if not self.ai_run_id:
            return False
        run = self.ai_run_id.sudo()
        return {'done': bool(self.ai_suggestion) or run.state not in RUNNING,
                'suggestion': self.ai_suggestion or ''}
