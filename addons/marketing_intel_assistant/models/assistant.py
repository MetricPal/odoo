"""Marketing assistant: instructions in plain words become a proposed action the person confirms.

1. The person writes an instruction. Simple ones are understood directly (``_parse``); anything else is sent to
   the person's AI agent, which answers with one JSON action (``AI_SCHEMA``). The agent has no tools: it only
   describes the action.
2. The action is validated and shown as a proposal in plain words. Nothing has changed yet.
3. **Do it** carries it out with the person's own rights. Campaigns and workflows keep their reviews: a created
   or changed campaign is still sent for review and approved as usual, a workflow still needs its approval.
"""

import json
import re
from datetime import date, timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, RedirectWarning, UserError, ValidationError
from odoo.tools import format_date

from odoo.addons.marketing_intel_ai.models.schema import InvalidAnswer, extract_json

ACTIONS = {
    'create_campaign': 'Create a campaign',
    'change_campaign': 'Change a campaign',
    'duplicate_campaign': 'Duplicate a campaign',
    'submit_campaign': 'Send a campaign for review',
    'pause_campaign': 'Take a campaign out of review',
    'cancel_campaign': 'Cancel a campaign',
    'report': 'Report',
    'pause_flow': 'Pause a workflow',
    'resume_flow': 'Resume a workflow',
    'submit_flow': 'Ask approval for a workflow',
}
CHANNEL_WORDS = {
    'email': 'email', 'e-mail': 'email', 'newsletter': 'email', 'sms': 'sms', 'text message': 'sms',
    'social': 'social', 'instagram': 'social', 'facebook': 'social', 'linkedin': 'social', 'post': 'social',
    'whatsapp': 'messaging', 'telegram': 'messaging', 'messaging': 'messaging',
    'webinar': 'event_virtual', 'online event': 'event_virtual', 'event': 'event_physical',
    'blog': 'content', 'seo': 'content', 'ads': 'ads', 'advert': 'ads', 'partner': 'partnership',
}
MONTHS = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov',
                                      'dec'], 1)}
AI_SCHEMA = (
    'Answer with ONE JSON object and nothing else: {"action": one of %(actions)s, "campaign": name of an existing '
    'campaign or null, "workflow": name of an existing workflow or null, "brand": brand name or null, "name": new '
    'campaign name or null, "start": "YYYY-MM-DD" or null, "end": "YYYY-MM-DD" or null, "channels": list of %(channels)s '
    'or [], "budget": number or null, "message": text or null, "audience": text or null, "ai_writes": true/false}. '
    'Use only names from the lists below. If the instruction is unclear, use {"action": "unclear", "question": "..."}.'
)


def _date(text, today):
    """'2026-11-20', '20 Nov', 'Nov 20', '20/11' (day first)."""
    text = (text or '').strip().lower().rstrip('.,')
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    match = re.match(r'^(\d{1,2})\s*([a-z]{3})[a-z]*\.?(?:\s+(\d{4}))?$', text) or None
    if match:
        day, month, year = int(match.group(1)), MONTHS.get(match.group(2)), match.group(3)
    else:
        match = re.match(r'^([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?$', text)
        if match:
            day, month, year = int(match.group(2)), MONTHS.get(match.group(1)), match.group(3)
        else:
            match = re.match(r'^(\d{1,2})/(\d{1,2})(?:/(\d{4}))?$', text)
            if not match:
                return None
            day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
    if not month:
        return None
    try:
        value = date(int(year) if year else today.year, month, day)
    except ValueError:
        return None
    if not year and value < today - timedelta(days=31):
        value = value.replace(year=value.year + 1)
    return value


class AssistantRequest(models.Model):
    _name = 'mi.assistant.request'
    _description = 'Marketing assistant request'
    _order = 'id desc'
    _rec_name = 'instruction'

    instruction = fields.Text(required=True, string='What should I do?')
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user, required=True, readonly=True,
                              index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, readonly=True)
    state = fields.Selection([('new', 'New'), ('thinking', 'The AI is reading it'), ('proposed', 'Waiting for you'),
                              ('done', 'Done'), ('failed', 'Could not do it'), ('cancelled', 'Cancelled')],
                             default='new', required=True, readonly=True)
    action = fields.Selection(list(ACTIONS.items()), readonly=True)
    intent = fields.Json(readonly=True, copy=False)
    proposal = fields.Html(readonly=True, sanitize=True, string='I will')
    result = fields.Html(readonly=True, sanitize=True, string='Answer')
    understood_by = fields.Selection([('rules', 'Understood directly'), ('ai', 'Read by the AI agent')], readonly=True)
    run_id = fields.Many2one('ai.agent.run', readonly=True, copy=False, string='AI request')
    res_model = fields.Char(readonly=True)
    res_id = fields.Many2oneReference(model_field='res_model', readonly=True)

    # ------------------------------------------------------------------ entry point
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['user_id'] = self.env.uid
        records = super().create(vals_list)
        for record in records:
            record._understand()
        return records

    def action_ask_again(self):
        """A new request with the same words (e.g. after the campaign changed)."""
        self.ensure_one()
        return self.create({'instruction': self.instruction})._open()

    def _open(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'views': [(False, 'form')], 'target': 'current'}

    def _understand(self):
        self.ensure_one()
        intent = self._parse(self.instruction)
        if intent:
            self.understood_by = 'rules'
            self._propose(intent)
            return
        agent = self._agent()
        if not agent:
            self._fail(_('I did not understand that, and no AI agent is available to read it. Try for example: '
                         '“report Open day”, “create campaign Black Friday with email and social from 20 Nov to '
                         '30 Nov”, “pause workflow Comment INFO”.'))
            return
        run = self.env['ai.agent.run']._queue(agent, self._ai_prompt(), origin=self)
        self.write({'state': 'thinking', 'run_id': run.id, 'understood_by': 'ai'})

    def _agent(self):
        try:
            options = self.env['ai.agent']._chat_options()
        except AccessError:
            return False
        brands = self.env['mi.brand'].search([])
        if 'ai_agent_id' in brands._fields and brands.ai_agent_id:
            ids = {o['id'] for o in options}
            agent = brands.ai_agent_id.filtered(lambda a: a.id in ids)[:1]
            if agent:
                return agent
        return self.env['ai.agent'].browse(options[0]['id']) if options else False

    def _ai_prompt(self):
        plans = self.env['mi.plan'].search([('is_template', '=', False), ('state', '!=', 'cancelled')], limit=60,
                                           order='date_start desc')
        flows = self.env['mi.flow'].search([], limit=40)
        return '\n'.join([
            'You turn a marketer\'s instruction into one action for the marketing app.',
            AI_SCHEMA % {'actions': json.dumps(list(ACTIONS)),
                         'channels': json.dumps(sorted(set(CHANNEL_WORDS.values())))},
            'Today: %s' % fields.Date.context_today(self),
            'Brands: %s' % json.dumps(self.env['mi.brand'].search([]).mapped('name')),
            'Campaigns: %s' % json.dumps(plans.mapped('name')),
            'Workflows: %s' % json.dumps(flows.mapped('name')),
            'Instruction: %s' % self.instruction,
        ])

    def _ai_agent_finished(self, run):
        """Runs as the requester when the AI answer arrives."""
        self.ensure_one()
        if run.id != self.run_id.id or self.state != 'thinking':
            return
        if run.state != 'completed':
            self._fail(_('The AI request ended without an answer. Ask again.'))
            return
        self._apply_answer(run.answer)

    def _apply_answer(self, answer):
        try:
            data = extract_json(answer)
        except InvalidAnswer as error:
            self._fail(_('The AI answer could not be used: %s', str(error)))
            return
        if data.get('action') == 'unclear':
            self._fail(_('The assistant needs more detail: %s', str(data.get('question') or '')[:300]))
            return
        self._propose(data)

    # ------------------------------------------------------------------ understanding without AI
    @api.model
    def _parse(self, text):
        """The common instructions, understood without AI. Returns an intent dict or None."""
        raw = ' '.join((text or '').split())
        low = raw.lower()
        quoted = re.findall(r'[“"]([^”"]+)[”"]', raw)

        def rest(match, group):
            return quoted[0] if quoted else match.group(group).strip(' .?!')

        match = re.match(r'^(?:pause|stop)\s+(?:the\s+)?workflow\s+(.+)$', low) or \
            re.match(r'^(?:pause|stop)\s+(?:the\s+)?(.+?)\s+workflow$', low)
        if match:
            return {'action': 'pause_flow', 'workflow': rest(match, 1)}
        match = re.match(r'^(?:resume|restart|start)\s+(?:the\s+)?workflow\s+(.+)$', low) or \
            re.match(r'^(?:resume|restart)\s+(?:the\s+)?(.+?)\s+workflow$', low)
        if match:
            return {'action': 'resume_flow', 'workflow': rest(match, 1)}
        match = re.match(r'^(?:ask|request)\s+approval\s+for\s+(?:the\s+)?workflow\s+(.+)$', low)
        if match:
            return {'action': 'submit_flow', 'workflow': rest(match, 1)}
        match = re.match(r'^(?:report(?:\s+on)?|results?(?:\s+of|\s+for)?|how\s+is|how\s+are)\s+(?:the\s+)?'
                         r'(?:campaign\s+)?(.+?)(?:\s+campaign)?(?:\s+doing)?\??$', low)
        if match:
            target = rest(match, 1)
            if target in ('all', 'everything', 'my campaigns', 'campaigns', 'things', 'we doing', 'it going'):
                return {'action': 'report'}
            return {'action': 'report', 'campaign': target}
        match = re.match(r'^(?:duplicate|copy|repeat)\s+(?:the\s+)?(?:campaign\s+)?(.+?)'
                         r'(?:\s+(?:starting|from|on)\s+(.+))?$', low)
        if match:
            intent = {'action': 'duplicate_campaign', 'campaign': rest(match, 1)}
            if match.group(2):
                intent['start'] = match.group(2)
            return intent
        match = re.match(r'^(?:send|submit)\s+(?:the\s+)?(?:campaign\s+)?(.+?)\s+(?:for|to)\s+review$', low)
        if match:
            return {'action': 'submit_campaign', 'campaign': rest(match, 1)}
        match = re.match(r'^(?:pause|hold|withdraw)\s+(?:the\s+)?(?:campaign\s+)?(.+)$', low)
        if match:
            return {'action': 'pause_campaign', 'campaign': rest(match, 1)}
        match = re.match(r'^cancel\s+(?:the\s+)?(?:campaign\s+)?(.+)$', low)
        if match:
            return {'action': 'cancel_campaign', 'campaign': rest(match, 1)}
        match = re.match(r'^(?:create|new|start|plan|make)\s+(?:a\s+|an\s+)?(?:new\s+)?campaign\s+(.+)$', raw, re.I)
        if match:
            body = match.group(1)
            intent = {'action': 'create_campaign', 'channels': [], 'ai_writes': bool(re.search(
                r'\b(ai|assistant)\s+(writes?|write it)|let (the )?ai\b', body, re.I))}
            dates = re.search(r'\bfrom\s+(.+?)\s+(?:to|until|till|-)\s+(.+?)(?=\s+(?:with|for|budget|about|and)\b|[,.]|$)',
                              body, re.I)
            if dates:
                intent['start'], intent['end'] = dates.group(1), dates.group(2)
            budget = re.search(r'\bbudget\s+(?:of\s+)?[^\d]{0,4}([\d,.]+)', body, re.I)
            if budget:
                intent['budget'] = float(budget.group(1).replace(',', ''))
            brand = re.search(r'\bfor\s+(?:brand\s+)?([\w.&\- ]+?)(?=\s+(?:with|from|budget|about)\b|[,.]|$)', body,
                              re.I)
            if brand:
                intent['brand'] = brand.group(1).strip()
            about = re.search(r'\babout\s+(.+?)(?=\s+(?:with|from|budget)\b|$)', body, re.I)
            if about:
                intent['message'] = about.group(1).strip(' .')
            low_body = body.lower()
            for word, code in CHANNEL_WORDS.items():
                if re.search(r'\b%s\b' % re.escape(word), low_body) and code not in intent['channels']:
                    if code == 'event_physical' and 'event_virtual' in intent['channels']:
                        continue
                    intent['channels'].append(code)
            name = quoted[0] if quoted else re.split(r'\s+(?:for|with|from|budget|about|on)\b|[,.]', body, maxsplit=1, flags=re.I)[0]
            intent['name'] = name.strip(' "“”')
            return intent
        return None

    # ------------------------------------------------------------------ validation
    def _find(self, model, name, domain=None, label=''):
        name = (name or '').strip()
        if not name:
            raise UserError(_('Which %s?', label))
        Model = self.env[model]
        domain = list(domain or [])
        exact = Model.search(domain + [('name', '=ilike', name)], limit=2)
        found = exact if len(exact) == 1 else Model.search(domain + [('name', 'ilike', name)], limit=6)
        if not found:
            raise UserError(_('I found no %(label)s called “%(name)s”.', label=label, name=name))
        if len(found) > 1:
            raise UserError(_('Several %(label)ss match “%(name)s”: %(names)s. Say which one.', label=label, name=name,
                              names=', '.join(found.mapped('name'))))
        return found

    def _clean_intent(self, data):
        """Check the action against what exists and what the person may do; returns the stored intent."""
        action = data.get('action')
        if action not in ACTIONS:
            raise UserError(_('I cannot do “%s” from here.', action or '-'))
        today = fields.Date.context_today(self)
        intent = {'action': action}
        if action in ('change_campaign', 'duplicate_campaign', 'submit_campaign', 'pause_campaign', 'cancel_campaign') \
                or (action == 'report' and data.get('campaign')):
            plan = self._find('mi.plan', data.get('campaign'), [('is_template', '=', False)], _('campaign'))
            intent['campaign_id'] = plan.id
        if action in ('pause_flow', 'resume_flow', 'submit_flow'):
            intent['flow_id'] = self._find('mi.flow', data.get('workflow'), label=_('workflow')).id
        if action == 'report' and data.get('brand') and not data.get('campaign'):
            intent['brand_id'] = self._find('mi.brand', data.get('brand'), label=_('brand')).id
        if action in ('create_campaign', 'change_campaign', 'duplicate_campaign'):
            for key in ('start', 'end'):
                if data.get(key):
                    value = data[key] if isinstance(data[key], date) else _date(str(data[key]), today)
                    if not value:
                        raise UserError(_('I could not read the date “%s” (write e.g. 20 Nov or 2026-11-20).', data[key]))
                    intent[key] = value.isoformat()
            if intent.get('start') and intent.get('end') and intent['end'] < intent['start']:
                raise UserError(_('The end date is before the start date.'))
        if action in ('create_campaign', 'change_campaign'):
            channels = [c for c in (data.get('channels') or []) if c in set(CHANNEL_WORDS.values())]
            if channels:
                intent['channels'] = sorted(set(channels))
            if data.get('budget') not in (None, ''):
                try:
                    budget = float(data['budget'])
                except (TypeError, ValueError):
                    raise UserError(_('The budget must be a number.')) from None
                if budget < 0:
                    raise UserError(_('The budget cannot be negative.'))
                intent['budget'] = budget
            for key in ('message', 'audience'):
                if data.get(key):
                    intent[key] = str(data[key])[:2000]
        if action == 'create_campaign':
            intent['name'] = str(data.get('name') or '').strip()[:120]
            if not intent['name']:
                raise UserError(_('What should the campaign be called?'))
            brands = self.env['mi.brand'].search([])
            if data.get('brand'):
                brand = self._find('mi.brand', data.get('brand'), label=_('brand'))
            elif len(brands) == 1:
                brand = brands
            else:
                raise UserError(_('For which brand? (%s)', ', '.join(brands.mapped('name')[:10])))
            intent['brand_id'] = brand.id
            intent['ai_writes'] = bool(data.get('ai_writes'))
            if not intent.get('channels'):
                raise UserError(_('Which channels? (email, SMS, social, WhatsApp/Telegram, webinar, event…)'))
        return intent

    # ------------------------------------------------------------------ proposal
    def _propose(self, data):
        try:
            intent = self._clean_intent(data)
        except RedirectWarning as error:
            self._fail(error.args[0])
            return
        except (UserError, ValidationError, AccessError) as error:
            self._fail(str(error))
            return
        if intent['action'] == 'report':  # reading changes nothing: answer straight away
            self.write({'intent': intent, 'action': 'report', 'proposal': False})
            self._do()
            return
        self.write({'intent': intent, 'action': intent['action'], 'state': 'proposed',
                    'proposal': self._describe(intent)})

    def _channel_names(self, codes):
        labels = dict(self.env['mi.channel']._fields['code']._description_selection(self.env))
        return ', '.join(labels.get(c, c) for c in codes)

    def _describe(self, intent):
        Plan, Flow = self.env['mi.plan'], self.env['mi.flow']
        plan = Plan.browse(intent.get('campaign_id'))
        flow = Flow.browse(intent.get('flow_id'))
        lines = []
        action = intent['action']
        if action == 'create_campaign':
            start = fields.Date.to_date(intent.get('start')) or fields.Date.context_today(self)
            end = fields.Date.to_date(intent.get('end')) or start + timedelta(days=29)
            lines.append(_('Create the campaign “%(name)s” for %(brand)s, %(start)s → %(end)s, with %(channels)s.',
                           name=intent['name'], brand=self.env['mi.brand'].browse(intent['brand_id']).name,
                           start=format_date(self.env, start), end=format_date(self.env, end),
                           channels=self._channel_names(intent['channels'])))
            if intent.get('budget') is not None:
                lines.append(_('Budget: %s.', ('%g' % intent['budget'])))
            if intent.get('message'):
                lines.append(_('Key message: %s', intent['message']))
            lines.append(_('The AI assistant writes every channel and sends it for review.') if intent['ai_writes'] else
                         _('You prepare the drafts; then send it for review as usual.'))
        elif action == 'change_campaign':
            changes = []
            for key, label in (('start', _('start')), ('end', _('end'))):
                if intent.get(key):
                    changes.append('%s %s' % (label, format_date(self.env, fields.Date.to_date(intent[key]))))
            if intent.get('channels'):
                changes.append(_('channels: %s', self._channel_names(intent['channels'])))
            if intent.get('budget') is not None:
                changes.append(_('budget %s', ('%g' % intent['budget'])))
            for key in ('message', 'audience'):
                if intent.get(key):
                    changes.append('%s: %s' % (self.env['mi.plan']._fields[key].string.lower(), intent[key][:120]))
            if not changes:
                return Markup('<p>%s</p>') % _('Nothing to change was given.')
            lines.append(_('Change “%(name)s”: %(changes)s.', name=plan.name, changes='; '.join(changes)))
            lines.append(_('Only possible before the review; it then goes through the review again.'))
        elif action == 'duplicate_campaign':
            start = fields.Date.to_date(intent.get('start')) if intent.get('start') else fields.Date.context_today(self)
            lines.append(_('Make a copy of “%(name)s” starting %(start)s, with the same channels, texts and tasks. '
                           'The copy needs its own review.', name=plan.name, start=format_date(self.env, start)))
        elif action == 'submit_campaign':
            lines.append(_('Send “%s” for review (the usual approvers decide).', plan.name))
        elif action == 'pause_campaign':
            lines.append(_('Take “%s” out of review and back to Content (the review request is withdrawn).', plan.name))
        elif action == 'cancel_campaign':
            lines.append(_('Cancel “%s”. Anything already sent stays sent.', plan.name))
        elif action == 'pause_flow':
            lines.append(_('Pause the workflow “%s”: it stops reacting until resumed.', flow.name))
        elif action == 'resume_flow':
            lines.append(_('Resume the workflow “%s” (only if it is unchanged since it was approved).', flow.name))
        elif action == 'submit_flow':
            lines.append(_('Ask approval for the workflow “%s”.', flow.name))
        return Markup('').join(Markup('<p>%s</p>') % line for line in lines)

    def _fail(self, message):
        self.write({'state': 'failed', 'result': Markup('<p>%s</p>') % message})

    # ------------------------------------------------------------------ doing it
    def action_do(self):
        for request in self:
            if request.user_id != self.env.user:
                raise AccessError(_('Only the person who asked can confirm.'))
            if request.state != 'proposed':
                raise UserError(_('There is nothing waiting to be done.'))
            request._do()
        if len(self) == 1 and self.res_model and self.res_id and self.state == 'done':
            return {'type': 'ir.actions.act_window', 'res_model': self.res_model, 'res_id': self.res_id,
                    'view_mode': 'form', 'views': [(False, 'form')], 'target': 'current'}
        return True

    def action_cancel(self):
        self.filtered(lambda r: r.state in ('proposed', 'thinking', 'new')).write({'state': 'cancelled'})
        return True

    def _do(self):
        self.ensure_one()
        intent = self.intent or {}
        try:
            with self.env.cr.savepoint():
                message, record = getattr(self, '_do_%s' % intent['action'])(intent)
        except RedirectWarning as error:
            self._fail(error.args[0])
            return
        except (UserError, ValidationError, AccessError) as error:
            self._fail(str(error))
            return
        values = {'state': 'done', 'result': message}
        if record:
            values.update({'res_model': record._name, 'res_id': record.id})
        self.write(values)

    def _plan(self, intent):
        plan = self.env['mi.plan'].browse(intent['campaign_id']).exists()
        if not plan:
            raise UserError(_('The campaign no longer exists.'))
        plan.check_access('read')
        return plan

    def _flow(self, intent):
        flow = self.env['mi.flow'].browse(intent['flow_id']).exists()
        if not flow:
            raise UserError(_('The workflow no longer exists.'))
        flow.check_access('write')
        return flow

    def _p(self, text):
        return Markup('<p>%s</p>') % text

    def _do_create_campaign(self, intent):
        channels = self.env['mi.channel'].search([('code', 'in', intent['channels'])])
        start = fields.Date.to_date(intent.get('start')) or fields.Date.context_today(self)
        values = {'name': intent['name'], 'brand_id': intent['brand_id'], 'date_start': start,
                  'date_end': fields.Date.to_date(intent.get('end')) or start + timedelta(days=29),
                  'channel_ids': [(6, 0, channels.ids)], 'worker': 'ai' if intent.get('ai_writes') else 'me'}
        for key in ('budget', 'message', 'audience'):
            if intent.get(key) is not None:
                values[key] = intent[key]
        plan = self.env['mi.plan'].create(values)
        plan.message_post(body=_('Created by the marketing assistant at the request of %s: “%s”',
                                 self.env.user.name, self.instruction))
        return self._p(_('Created “%(name)s”. Next step: %(step)s', name=plan.name, step=plan.next_step)), plan

    def _do_change_campaign(self, intent):
        plan = self._plan(intent)
        if plan.state not in ('brief', 'content'):
            raise UserError(_('“%s” is already in review or approved: duplicate it to change it, or take it out of '
                              'review first.', plan.name))
        values = {}
        for key in ('start', 'end'):
            if intent.get(key):
                values['date_%s' % key] = fields.Date.to_date(intent[key])
        if intent.get('channels'):
            values['channel_ids'] = [(6, 0, self.env['mi.channel'].search([('code', 'in', intent['channels'])]).ids)]
        for key in ('budget', 'message', 'audience'):
            if intent.get(key) is not None:
                values[key] = intent[key]
        if not values:
            raise UserError(_('Nothing to change was given.'))
        plan.write(values)
        plan.message_post(body=_('Changed by the marketing assistant at the request of %s: “%s”',
                                 self.env.user.name, self.instruction))
        return self._p(_('Changed “%(name)s”. Next step: %(step)s', name=plan.name, step=plan.next_step)), plan

    def _do_duplicate_campaign(self, intent):
        plan = self._plan(intent)
        start = fields.Date.to_date(intent.get('start')) if intent.get('start') else None
        copy = plan.create(plan._copy_values(name=_('%s (copy)', plan.name), worker='me', date_start=start))
        copy.message_post(body=_('Copied from “%s” by the marketing assistant.', plan.name))
        return self._p(_('Copied to “%s”. It needs its own review.', copy.name)), copy

    def _do_submit_campaign(self, intent):
        plan = self._plan(intent)
        result = plan.action_submit_review()
        if isinstance(result, dict) and result.get('tag') == 'display_notification':
            raise UserError('%s\n%s' % (result['params']['title'], result['params']['message']))
        return self._p(_('“%(name)s” is in review. %(step)s', name=plan.name, step=plan.next_step)), plan

    def _do_pause_campaign(self, intent):
        plan = self._plan(intent)
        plan.check_access('write')
        if plan.state != 'review':
            raise UserError(_('“%(name)s” is not in review (status: %(state)s). Released campaigns are paused in each '
                              'channel\'s app, or cancelled.', name=plan.name, state=plan.status))
        request = plan.sudo().review_request_id
        if request.state == 'submitted':
            request.with_user(request.requester_id).sudo().action_cancel()
        plan.sudo().state = 'content'
        plan.message_post(body=_('Taken out of review by %s (marketing assistant).', self.env.user.name))
        return self._p(_('“%s” is back in Content; send it for review again when ready.', plan.name)), plan

    def _do_cancel_campaign(self, intent):
        plan = self._plan(intent)
        plan.check_access('write')
        plan.action_cancel()
        return self._p(_('“%s” is cancelled.', plan.name)), plan

    def _do_pause_flow(self, intent):
        flow = self._flow(intent)
        if flow.state != 'active':
            raise UserError(_('The workflow “%s” is not running.', flow.name))
        flow.action_pause()
        return self._p(_('The workflow “%s” is paused.', flow.name)), flow

    def _do_resume_flow(self, intent):
        flow = self._flow(intent)
        flow.action_resume()
        if flow.state != 'active':
            raise UserError(_('The workflow “%s” is not paused.', flow.name))
        return self._p(_('The workflow “%s” runs again.', flow.name)), flow

    def _do_submit_flow(self, intent):
        flow = self._flow(intent)
        flow.action_request_approval()
        return self._p(_('Approval asked for the workflow “%s”.', flow.name)), flow

    def _do_report(self, intent):
        if intent.get('campaign_id'):
            plan = self._plan(intent)
            return self._campaign_report(plan), plan
        brands = self.env['mi.brand'].browse(intent['brand_id']) if intent.get('brand_id') else self.env['mi.brand'].search([])
        plans = self.env['mi.plan'].search([('brand_id', 'in', brands.ids), ('is_template', '=', False),
                                            ('state', 'in', ('brief', 'content', 'review', 'scheduled', 'live'))],
                                           order='date_start')
        if not plans:
            return self._p(_('No campaign is active.')), False
        rows = Markup('').join(
            Markup('<li><b>%s</b> (%s) · %s · %s/%s channels out · %s sent · %s clicks · %s</li>') % (
                p.name, p.brand_id.name, dict(p._fields['status']._description_selection(self.env))[p.status],
                p.channels_out, p.channel_count, sum(p.item_ids.mapped('result_sent')),
                sum(p.item_ids.mapped('result_clicks')), p.next_step or '') for p in plans)
        needs = plans.filtered('needs_me')
        head = _('%(n)s active campaign(s); %(m)s need your action.', n=len(plans), m=len(needs))
        return Markup('<p>%s</p><ul>%s</ul>') % (head, rows), False

    def _campaign_report(self, plan):
        stages = dict(plan.item_ids._fields['stage']._description_selection(self.env))
        channels = dict(plan.item_ids._fields['channel']._description_selection(self.env))
        rows = []
        for item in plan.item_ids:
            figures = ', '.join('%s %s' % (item[f], label) for f, label in (
                ('result_sent', _('sent')), ('result_opened', _('opened')), ('result_clicks', _('clicks')),
                ('result_replied', _('replies')), ('result_registrations', _('registrations'))) if item[f])
            rows.append(Markup('<li><b>%s</b>: %s%s</li>') % (channels.get(item.channel), stages.get(item.stage),
                                                              (' · ' + figures) if figures else ''))
        status = dict(plan._fields['status']._description_selection(self.env))[plan.status]
        return Markup('<p><b>%s</b> (%s): %s, %s → %s, %s of %s channels out.</p><ul>%s</ul><p>%s %s</p>') % (
            plan.name, plan.brand_id.name, status, format_date(self.env, plan.date_start),
            format_date(self.env, plan.date_end), plan.channels_out, plan.channel_count, Markup('').join(rows),
            _('Next step:'), plan.next_step or '-')


class Panel(models.AbstractModel):
    _inherit = 'mi.panel'

    @api.model
    def get_panel(self, brand_id=False):
        data = super().get_panel(brand_id=brand_id)
        data['assistant'] = True
        return data
